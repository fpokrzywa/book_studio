"""Imports: preview, chapters, fidelity, warnings, duplicates, originals preserved, safety, size limits."""

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pbs_core.api.app import create_app
from pbs_core.context import AppContext, build_context
from tests.conftest import BASE_URL, make_settings, new_chapter, new_project, save

FIX = Path(__file__).resolve().parents[3] / "fixtures"


def upload(client: TestClient, rel: str, target: str | None = None, name: str | None = None) -> dict[str, Any]:
    data = (FIX / rel).read_bytes()
    form = {"target_project_id": target} if target else {}
    resp = client.post("/api/imports", files={"file": (name or Path(rel).name, data)}, data=form)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def commit(client: TestClient, imp: dict[str, Any], **body: Any) -> dict[str, Any]:
    body.setdefault("mode", "new_project")
    resp = client.post(f"/api/imports/{imp['id']}/commit", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def content(client: TestClient, pid: str, cid: str) -> str:
    return client.get(f"/api/projects/{pid}/chapters/{cid}/content").json()["source_md"]  # type: ignore[no-any-return]


def codes(imp: dict[str, Any]) -> set[str]:
    return {w["code"] for w in imp["warnings"]}


def test_markdown_import_is_lossless_and_split_by_headings(client: TestClient) -> None:
    imp = upload(client, "import/multi-chapter.md")
    assert imp["status"] == "preview_ready" and imp["importer"] == "markdown" and not imp["lossy"]
    assert [c["title"] for c in imp["chapters"]] == ["Chapter One", "Chapter Two", "Chapter Three"]
    assert "unresolved_image" in codes(imp)
    done = commit(client, imp, project_title="From Markdown")
    pid = done["project_id"]
    texts = [content(client, pid, cid) for cid in done["chapter_ids"]]
    source = (FIX / "import/multi-chapter.md").read_text(encoding="utf-8")
    assert texts[1] == '| A | B |\n|---|---|\n| 1 | 2 |\n\n```bash\necho "kept exactly"\n```\n'
    for t in texts:  # every chapter body appears verbatim in the original
        assert t.strip() in source
    revs = client.get(f"/api/projects/{pid}/chapters/{done['chapter_ids'][0]}/revisions").json()
    assert revs[0]["origin"] == "imported"


def test_html_import_preserves_structures_and_strips_scripts(client: TestClient) -> None:
    imp = upload(client, "import/multi-chapter.html")
    assert [c["title"] for c in imp["chapters"]] == [
        "Chapter One: Waking the Engine", "Chapter Two: Torque", "Chapter Three: Running"
    ]  # fmt: skip
    assert imp["chapters"][0]["image_count"] == 1
    assert {"unsafe_link", "removed_elements"} <= codes(imp) and imp["lossy"]
    done = commit(client, imp)
    pid = done["project_id"]
    ch1, ch2, ch3 = (content(client, pid, c) for c in done["chapter_ids"])
    assert "[@smith2020]" in ch1 and "$E = mc^2$" in ch1 and "[^1]" in ch1 and "[^1]: Cold engines need a choke." in ch1
    assert (
        'alt="Line drawing of a small two-stroke engine"' in ch1
        and "![The engine at rest, seen from the *left*](asset:" in ch1
    )
    assert "javascript" not in ch1 and "steal" not in ch1 and "alert" not in ch1
    assert "| Bolt | 12 Nm |" in ch2 and ": Fastener torque values" in ch2 and "```python\ndef start(engine):" in ch2
    assert "**firmly**" in ch3 and "> Patience starts" in ch3
    assets = client.get(f"/api/projects/{pid}/assets").json()
    assert len(assets) == 1 and assets[0]["mime"] == "image/png"
    assert client.get(assets[0]["url"]).status_code == 200


def test_docx_import(client: TestClient) -> None:
    imp = upload(client, "import/sample.docx")
    assert imp["importer"] == "docx" and imp["lossy"]
    assert [c["title"] for c in imp["chapters"]] == ["Chapter One: Setup", "Chapter Two: Numbers"]
    assert {"docx_equations", "missing_alt"} <= codes(imp)
    done = commit(client, imp)
    ch1, ch2 = (content(client, done["project_id"], c) for c in done["chapter_ids"])
    assert "**bold**" in ch1 and "*italic*" in ch1 and "![Wiring diagram of the starter circuit](asset:" in ch1
    assert "| Bolt | 12 Nm |" in ch2 and "```\nprint('hello')\n```" in ch2 and "- Bullet one" in ch2


def test_text_pdf_import_is_marked_lossy(client: TestClient) -> None:
    imp = upload(client, "import/text.pdf")
    assert imp["importer"] == "pdf" and imp["lossy"] and "pdf_text_only" in codes(imp)
    assert [c["title"] for c in imp["chapters"]] == ["Chapter 1: The Workshop", "Chapter 2: The Engine"]
    assert "smelled of oil" in imp["chapters"][0]["preview_source"]


@pytest.mark.parametrize(
    ("rel", "needle"),
    [
        ("import/scanned.pdf", "scanned"),
        ("import/encrypted.pdf", "password"),
        ("malicious/legacy.doc", "old Word"),
        ("malicious/zipbomb.docx", "zip bomb"),
        ("malicious/traversal.docx", "unsafe path"),
        ("malicious/xxe.docx", "DTD"),
    ],
)
def test_unreadable_or_hostile_files_fail_safely_but_original_is_kept(
    client: TestClient, ctx: AppContext, rel: str, needle: str
) -> None:
    imp = upload(client, rel)
    assert imp["status"] == "failed" and imp["chapters"] == []
    assert needle.lower() in imp["warnings"][0]["message"].lower()
    original = ctx.workspace.root / "originals"
    stored = list(original.rglob("*"))
    data = (FIX / rel).read_bytes()
    assert any(p.is_file() and p.read_bytes() == data for p in stored)  # preserved byte-for-byte
    assert client.post(f"/api/imports/{imp['id']}/commit", json={"mode": "new_project"}).status_code == 409
    assert not (ctx.workspace.root.parent / "evil.txt").exists()


def test_injection_html_is_neutralised(client: TestClient) -> None:
    imp = upload(client, "malicious/injection.html")
    done = commit(client, imp)
    text = content(client, done["project_id"], done["chapter_ids"][0])
    for bad in ("<script", "onclick", "onerror", "javascript:", "data:text/html", "evil.example", "<object", "<form"):
        assert bad not in text, bad
    preview = client.post(f"/api/projects/{done['project_id']}/preview", json={"source_md": text}).json()
    assert "<script" not in preview["html"] and "onerror" not in preview["html"]


def test_original_is_immutable_and_downloadable(client: TestClient, ctx: AppContext) -> None:
    imp = upload(client, "import/multi-chapter.md")
    original = client.get(f"/api/imports/{imp['id']}/original")
    assert original.status_code == 200 and original.content == (FIX / "import/multi-chapter.md").read_bytes()
    assert hashlib.sha256(original.content).hexdigest() == imp["sha256"]
    conn = sqlite3.connect(ctx.workspace.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE original_file SET byte_size = 0")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM original_file")
    finally:
        conn.close()


def test_duplicates_are_reported(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"], "Chapter Three")
    save(client, p["id"], c["id"], "Final words.[^1]\n\n[^1]: A note.\n", 0)
    upload(client, "import/multi-chapter.md")
    again = upload(client, "import/multi-chapter.md", target=p["id"])
    assert again["previously_imported_at"] is not None and "duplicate_file" in codes(again)
    dup = again["chapters"][2]
    assert dup["duplicate_of_chapter_id"] == c["id"] and dup["duplicate_reason"] == "same text as an existing chapter"
    done = commit(client, again, mode="existing_project", include=[0, 1])
    titles = [x["title"] for x in client.get(f"/api/projects/{p['id']}/chapters").json()]
    assert titles == ["Chapter Three", "Chapter One", "Chapter Two"] and len(done["chapter_ids"]) == 2


def test_cancel_and_double_commit(client: TestClient) -> None:
    imp = upload(client, "import/multi-chapter.md")
    assert client.post(f"/api/imports/{imp['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/imports/{imp['id']}/commit", json={"mode": "new_project"}).status_code == 409
    imp2 = upload(client, "import/multi-chapter.md")
    commit(client, imp2)
    assert client.post(f"/api/imports/{imp2['id']}/commit", json={"mode": "new_project"}).status_code == 409


def test_unsupported_type_and_empty_upload(client: TestClient) -> None:
    exe = client.post("/api/imports", files={"file": ("tool.exe", b"MZ\x90\x00")})
    assert exe.status_code == 201 and exe.json()["status"] == "failed"
    assert "Unsupported file type" in exe.json()["warnings"][0]["message"]
    empty = client.post("/api/imports", files={"file": ("e.md", b"")})
    assert empty.status_code == 422


def test_upload_size_limit(workspace: Path) -> None:
    settings = make_settings(workspace, max_upload_mb=1)
    ctx = build_context(settings)
    try:
        with TestClient(create_app(settings, ctx=ctx), base_url=BASE_URL, headers={"X-PBS-Token": ctx.token}) as c:
            resp = c.post("/api/imports", files={"file": ("big.txt", b"a" * (1024 * 1024 + 10))})
            assert resp.status_code == 413 and resp.json()["code"] == "payload_too_large"
            p = new_project(c)
            img = c.post(f"/api/projects/{p['id']}/assets", files={"file": ("x.svg", b"<svg onload=alert(1)/>")})
            assert img.status_code == 422  # only raster images are accepted
    finally:
        ctx.close()
