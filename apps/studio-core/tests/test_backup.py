"""Backup ZIP (manifest/1) and restore-as-new-project: equivalence, integrity checks, no overwrite."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import new_chapter, new_project, save

FIX = Path(__file__).resolve().parents[3] / "fixtures"


def snapshot(client: TestClient, pid: str) -> dict[str, Any]:
    """Everything that defines a manuscript, independent of database IDs."""
    proj = client.get(f"/api/projects/{pid}").json()
    chs = client.get(f"/api/projects/{pid}/chapters").json()
    by_id = {c["id"]: c for c in chs}
    out_chapters = []
    for c in chs:
        revs = client.get(f"/api/projects/{pid}/chapters/{c['id']}/revisions").json()
        full = [client.get(f"/api/projects/{pid}/chapters/{c['id']}/revisions/{r['revision_no']}").json() for r in revs]
        draft = client.get(f"/api/projects/{pid}/chapters/{c['id']}/content").json()["draft"]
        out_chapters.append(
            {
                "title": c["title"], "slug": c["slug"], "status": c["status"], "kind": c["kind"], "depth": c["depth"],
                "parent": by_id[c["parent_id"]]["slug"] if c["parent_id"] else None,
                "target": c["target_word_count"],
                "revisions": [(r["revision_no"], r["origin"], r["label"], r["note"], r["source_md"],
                               r["restored_from_revision_no"]) for r in full],
                "draft": draft["source_md"] if draft else None,
            }
        )  # fmt: skip
    meta = {k: proj[k] for k in ("subtitle", "author_name", "description", "project_type", "language", "audience",
                                 "target_word_count", "publication_formats", "word_count", "chapter_count")}  # fmt: skip
    assets = sorted(a["short_hash"] for a in client.get(f"/api/projects/{pid}/assets").json())
    return {"meta": meta, "chapters": out_chapters, "assets": assets}


def build_rich_project(client: TestClient) -> str:
    imp = client.post(
        "/api/imports", files={"file": ("book.html", (FIX / "import/multi-chapter.html").read_bytes())}
    ).json()
    pid = client.post(f"/api/imports/{imp['id']}/commit", json={"mode": "new_project", "project_title": "Rich"}).json()[
        "project_id"
    ]
    client.patch(f"/api/projects/{pid}", json={"subtitle": "Sub", "author_name": "A. Writer", "description": "About it",
                                               "audience": "Makers", "target_word_count": 5000})  # fmt: skip
    chs = client.get(f"/api/projects/{pid}/chapters").json()
    first = chs[0]
    sec = client.post(
        f"/api/projects/{pid}/chapters", json={"title": "A section", "parent_id": first["id"], "kind": "section"}
    ).json()
    save(client, pid, sec["id"], "Section text.\n", 0)
    text = client.get(f"/api/projects/{pid}/chapters/{first['id']}/content").json()["source_md"]
    save(client, pid, first["id"], text + "\nAn added paragraph.\n", 1)
    client.post(f"/api/projects/{pid}/chapters/{first['id']}/revisions/1/restore", json={"expected_head_no": 2})
    client.put(f"/api/projects/{pid}/chapters/{first['id']}/revisions/2/tag", json={"label": "edited", "note": "n"})
    client.patch(f"/api/projects/{pid}/chapters/{chs[1]['id']}", json={"status": "in_review", "target_word_count": 900})
    client.put(
        f"/api/projects/{pid}/chapters/{chs[2]['id']}/draft",
        json={"source_md": "Unsaved draft text", "base_revision_no": 1},
    )
    client.post(f"/api/projects/{pid}/chapters/{chs[2]['id']}/move", json={"parent_id": None, "index": 0})
    return pid  # type: ignore[no-any-return]


def make_backup(client: TestClient, pid: str) -> bytes:
    b = client.post(f"/api/projects/{pid}/backups")
    assert b.status_code == 201, b.text
    data = client.get(b.json()["download_url"]).content
    assert data[:2] == b"PK"
    return data


def restore(client: TestClient, data: bytes) -> Any:
    return client.post("/api/backups/restore", files={"file": ("b.pbsbak.zip", data, "application/zip")})


def test_backup_then_restore_is_equivalent_and_never_overwrites(client: TestClient) -> None:
    pid = build_rich_project(client)
    before = snapshot(client, pid)
    data = make_backup(client, pid)
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    assert manifest["schema"] == "manifest/1" and manifest["schema_revision"] == "0004"
    assert manifest["tables"]["chapter_revision"] >= 6 and any(
        f["path"].startswith("files/assets/") for f in manifest["files"]
    )
    assert any(f["path"].startswith("files/originals/") for f in manifest["files"])

    r = restore(client, data)
    assert r.status_code == 201, r.text
    out = r.json()
    new_pid = out["project"]["id"]
    assert new_pid != pid and out["project"]["title"] == "Rich (restored)" and out["warnings"] == []
    assert out["restored_from_project_id"] == pid
    after = snapshot(client, new_pid)
    assert after == before
    assert snapshot(client, pid) == before  # original untouched
    # Restored chapters are new rows: editing one never touches the original project.
    ch = next(c for c in client.get(f"/api/projects/{new_pid}/chapters").json() if c["title"] == "Chapter Two: Torque")
    orig_ch = next(c for c in client.get(f"/api/projects/{pid}/chapters").json() if c["title"] == "Chapter Two: Torque")
    assert ch["id"] != orig_ch["id"]
    head = client.get(f"/api/projects/{new_pid}/chapters/{ch['id']}/content").json()
    save(client, new_pid, ch["id"], "Changed after restore\n", head["revision_no"])
    assert snapshot(client, pid) == before
    # Images resolve in the restored project.
    html = client.post(f"/api/projects/{new_pid}/exports", json={"format": "html"}).json()
    assert "data:image/png;base64," in client.get(html["download_url"]).text
    # Restoring twice makes two independent copies.
    assert restore(client, data).json()["project"]["id"] not in (pid, new_pid)


def _rezip(data: bytes, mutate: Any) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    entries = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    mutate(entries)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for name, blob in entries.items():
            zout.writestr(name, blob)
    return buf.getvalue()


def test_tampered_backups_are_rejected(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Original words.\n", 0)
    data = make_backup(client, p["id"])

    def tamper(e: dict[str, bytes]) -> None:
        e["data/chapter_revision.jsonl"] = e["data/chapter_revision.jsonl"].replace(b"Original", b"Tampered")

    def extra(e: dict[str, bytes]) -> None:
        e["files/unlisted.txt"] = b"surprise"

    def no_manifest(e: dict[str, bytes]) -> None:
        del e["manifest.json"]

    def future(e: dict[str, bytes]) -> None:
        m = json.loads(e["manifest.json"])
        m["schema_revision"] = "9999_future"
        e["manifest.json"] = json.dumps(m).encode()

    def bad_schema(e: dict[str, bytes]) -> None:
        m = json.loads(e["manifest.json"])
        m["schema"] = "manifest/99"
        e["manifest.json"] = json.dumps(m).encode()

    cases = [(tamper, "Checksum mismatch"), (extra, "not listed"), (no_manifest, "manifest.json is missing"),
             (future, "newer version"), (bad_schema, "manifest is not valid")]  # fmt: skip
    projects_before = client.get("/api/projects", params={"status": "all"}).json()["total"]
    for mutate, message in cases:
        resp = restore(client, _rezip(data, mutate))
        assert resp.status_code == 422, (message, resp.text)
        assert message in resp.json()["title"], resp.json()["title"]
    assert client.get("/api/projects", params={"status": "all"}).json()["total"] == projects_before


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "data/../../x", "C:/win.txt"])
def test_backup_with_unsafe_paths_is_rejected(client: TestClient, name: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", b"{}")
        zf.writestr(name, b"x")
    resp = restore(client, buf.getvalue())
    assert resp.status_code == 422 and "rejected" in resp.json()["title"]


def test_not_a_zip(client: TestClient) -> None:
    resp = restore(client, b"this is not a zip")
    assert resp.status_code == 422
