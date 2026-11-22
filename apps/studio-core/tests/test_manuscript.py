"""Manuscript workspace: tree, reorder, slugs, targets, drafts (autosave), history, compare, restore, tags."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import new_chapter, new_project, save


def chapters(client: TestClient, pid: str) -> list[dict[str, Any]]:
    resp = client.get(f"/api/projects/{pid}/chapters")
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def move(client: TestClient, pid: str, cid: str, parent: str | None, index: int) -> Any:
    return client.post(f"/api/projects/{pid}/chapters/{cid}/move", json={"parent_id": parent, "index": index})


def test_tree_with_sections_in_reading_order(client: TestClient) -> None:
    p = new_project(client)
    part = client.post(f"/api/projects/{p['id']}/chapters", json={"title": "Part One", "kind": "part"}).json()
    c1 = client.post(f"/api/projects/{p['id']}/chapters", json={"title": "Ch 1", "parent_id": part["id"]}).json()
    s1 = client.post(
        f"/api/projects/{p['id']}/chapters", json={"title": "Sec 1.1", "kind": "section", "parent_id": c1["id"]}
    ).json()
    c2 = client.post(f"/api/projects/{p['id']}/chapters", json={"title": "Ch 2", "parent_id": part["id"]}).json()
    epi = new_chapter(client, p["id"], "Epilogue")
    got = chapters(client, p["id"])
    assert [(c["title"], c["depth"]) for c in got] == [
        ("Part One", 0), ("Ch 1", 1), ("Sec 1.1", 2), ("Ch 2", 1), ("Epilogue", 0)
    ]  # fmt: skip
    assert s1["depth"] == 2 and c2["parent_id"] == part["id"] and epi["parent_id"] is None
    too_deep = client.post(f"/api/projects/{p['id']}/chapters", json={"title": "x", "parent_id": s1["id"]})
    assert too_deep.status_code == 422
    book = client.get(f"/api/projects/{p['id']}/book").json()
    assert [c["title"] for c in book["chapters"]] == [c["title"] for c in got]


def test_reorder_and_reparent(client: TestClient) -> None:
    p = new_project(client)
    a, b, c = (new_chapter(client, p["id"], t) for t in ("A", "B", "C"))
    order = move(client, p["id"], c["id"], None, 0).json()
    assert [x["title"] for x in order] == ["C", "A", "B"]
    order = move(client, p["id"], c["id"], None, 99).json()  # index clamps to the end
    assert [x["title"] for x in order] == ["A", "B", "C"]
    order = move(client, p["id"], b["id"], a["id"], 0).json()  # B becomes a section of A
    assert [(x["title"], x["depth"]) for x in order] == [("A", 0), ("B", 1), ("C", 0)]
    assert move(client, p["id"], a["id"], b["id"], 0).status_code == 422  # cycle
    assert move(client, p["id"], a["id"], a["id"], 0).status_code == 422  # self
    # Many reorders keep keys strictly ordered.
    for i in range(30):
        move(client, p["id"], c["id"], None, i % 2)
    titles = [x["title"] for x in chapters(client, p["id"])]
    assert sorted(titles) == ["A", "B", "C"] and len(titles) == 3


def test_reorder_does_not_orphan_references(client: TestClient) -> None:
    p = new_project(client)
    png = (
        __import__("pathlib").Path(__file__).resolve().parents[3] / "fixtures" / "images" / "engine.png"
    ).read_bytes()
    asset = client.post(f"/api/projects/{p['id']}/assets", files={"file": ("engine.png", png, "image/png")}).json()
    a = new_chapter(client, p["id"], "First")
    b = new_chapter(client, p["id"], "Second")
    text_a = f'See [@smith2020] and ![Engine]({asset["reference"]}){{#fig-e alt="An engine"}}\n'
    save(client, p["id"], a["id"], text_a, 0)
    save(client, p["id"], a["id"], text_a + "\nMore.\n", 1)
    save(client, p["id"], b["id"], "Second chapter.\n", 0)
    client.put(f"/api/projects/{p['id']}/chapters/{a['id']}/revisions/1/tag", json={"label": "first draft"})

    move(client, p["id"], a["id"], None, 1)
    after = chapters(client, p["id"])
    assert [x["title"] for x in after] == ["Second", "First"]
    moved = next(x for x in after if x["id"] == a["id"])
    assert moved["slug"] == a["slug"] and moved["head_revision_no"] == 2
    revs = client.get(f"/api/projects/{p['id']}/chapters/{a['id']}/revisions").json()
    assert [r["revision_no"] for r in revs] == [2, 1] and revs[1]["label"] == "first draft"
    html = client.post(f"/api/projects/{p['id']}/exports", json={"format": "html"}).json()
    page = client.get(html["download_url"]).text
    assert page.index("Second chapter.") < page.index("An engine")  # new order
    assert "data:image/png;base64," in page and 'data-keys="smith2020"' in page  # refs still resolve
    assert not any("missing" in w for w in html["warnings"])


def test_slug_title_status_and_target_edits(client: TestClient) -> None:
    p = new_project(client)
    a = new_chapter(client, p["id"], "Alpha")
    b = new_chapter(client, p["id"], "Beta")
    url = f"/api/projects/{p['id']}/chapters/{a['id']}"
    assert client.patch(url, json={"slug": "the-alpha"}).json()["slug"] == "the-alpha"
    clash = client.patch(f"/api/projects/{p['id']}/chapters/{b['id']}", json={"slug": "the-alpha"})
    assert clash.status_code == 409 and clash.json()["reason"] == "slug_taken"
    assert client.patch(url, json={"slug": "Bad Slug!"}).status_code == 422
    got = client.patch(url, json={"target_word_count": 2500, "status": "in_review", "title": "Alpha Prime"}).json()
    assert (got["target_word_count"], got["status"], got["title"], got["slug"]) == (
        2500,
        "in_review",
        "Alpha Prime",
        "the-alpha",
    )


def test_archive_chapter_archives_its_sections(client: TestClient) -> None:
    p = new_project(client)
    a = new_chapter(client, p["id"], "A")
    client.post(f"/api/projects/{p['id']}/chapters", json={"title": "A.1", "parent_id": a["id"]})
    new_chapter(client, p["id"], "B")
    client.post(f"/api/projects/{p['id']}/chapters/{a['id']}/archive")
    assert [c["title"] for c in chapters(client, p["id"])] == ["B"]


def test_draft_autosave_lifecycle(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    base = f"/api/projects/{p['id']}/chapters/{c['id']}"
    save(client, p["id"], c["id"], "Saved text.\n", 0)
    d = client.put(f"{base}/draft", json={"source_md": "Typing in progress", "base_revision_no": 1}).json()
    assert d["draft"]["source_md"] == "Typing in progress" and d["revision_no"] == 1
    # Survives a reload: the content endpoint returns the draft alongside the saved head.
    content = client.get(f"{base}/content").json()
    assert content["source_md"] == "Saved text.\n" and content["draft"]["source_md"] == "Typing in progress"
    # Autosave never creates revisions.
    assert len(client.get(f"{base}/revisions").json()) == 1
    # Typing back to the saved text clears the draft.
    assert (
        client.put(f"{base}/draft", json={"source_md": "Saved text.\n", "base_revision_no": 1}).json()["draft"] is None
    )
    client.put(f"{base}/draft", json={"source_md": "Second try", "base_revision_no": 1})
    # A save elsewhere makes the stale autosave conflict instead of overwriting.
    save(client, p["id"], c["id"], "Saved in another window.\n", 1)
    stale = client.put(f"{base}/draft", json={"source_md": "Old tab", "base_revision_no": 1})
    assert stale.status_code == 409 and stale.json()["current"]["revision_no"] == 2
    # Saving consumes the draft; discard removes it.
    client.put(f"{base}/draft", json={"source_md": "New draft", "base_revision_no": 2})
    assert client.delete(f"{base}/draft").json()["draft"] is None
    client.put(f"{base}/draft", json={"source_md": "Final words", "base_revision_no": 2})
    r = save(client, p["id"], c["id"], "Final words", 2).json()
    assert r["content"]["draft"] is None and client.get(f"{base}/content").json()["draft"] is None


def test_restore_creates_new_revision_and_keeps_history(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    base = f"/api/projects/{p['id']}/chapters/{c['id']}"
    save(client, p["id"], c["id"], "Version one.\n", 0)
    save(client, p["id"], c["id"], "Version two, longer.\n", 1)
    save(client, p["id"], c["id"], "Version three.\n", 2)
    stale = client.post(f"{base}/revisions/1/restore", json={"expected_head_no": 2})
    assert stale.status_code == 409
    r = client.post(f"{base}/revisions/1/restore", json={"expected_head_no": 3, "note": "Back to basics"}).json()
    assert r["content"]["revision_no"] == 4 and r["content"]["source_md"] == "Version one.\n"
    revs = client.get(f"{base}/revisions").json()
    assert [x["revision_no"] for x in revs] == [4, 3, 2, 1]  # newer revisions remain in history
    assert revs[0]["origin"] == "restored" and revs[0]["restored_from_revision_no"] == 1
    assert revs[0]["note"] == "Back to basics" and revs[0]["is_head"]
    assert client.get(f"{base}/revisions/3").json()["source_md"] == "Version three.\n"
    assert client.get(f"{base}/revisions/9").status_code == 404


def test_compare_side_by_side_with_word_highlights(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Line one.\nThe engine is cold.\nRemoved line.\n", 0)
    save(client, p["id"], c["id"], "Line one.\nThe engine is warm.\nAdded line.\nAnother.\n", 1)
    diff = client.get(f"/api/projects/{p['id']}/chapters/{c['id']}/compare", params={"from": 1, "to": 2}).json()
    kinds = [r["kind"] for r in diff["rows"]]
    assert kinds[0] == "equal" and "replace" in kinds
    changed = next(r for r in diff["rows"] if r["kind"] == "replace" and "engine" in r["left"][0]["text"])
    assert [s["text"] for s in changed["left"] if s["changed"]] == ["cold"]
    assert [s["text"] for s in changed["right"] if s["changed"]] == ["warm"]
    assert diff["changed_lines"] >= 1 and diff["added_lines"] >= 1


def test_labels_and_notes_on_saved_revisions(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    base = f"/api/projects/{p['id']}/chapters/{c['id']}"
    client.put(
        f"{base}/content",
        json={"source_md": "Text\n", "expected_head_no": 0, "label": "Outline done", "note": "first pass"},
    )
    revs = client.get(f"{base}/revisions").json()
    assert revs[0]["label"] == "Outline done" and revs[0]["note"] == "first pass"
    tagged = client.put(f"{base}/revisions/1/tag", json={"label": "Sent to editor", "note": "v1 to Sam"}).json()
    assert tagged["label"] == "Sent to editor" and tagged["note"] == "v1 to Sam"
    assert client.get(f"{base}/revisions/1").json()["source_md"] == "Text\n"  # content untouched


def test_preview_renders_and_warns(client: TestClient) -> None:
    p = new_project(client)
    out = client.post(
        f"/api/projects/{p['id']}/preview",
        json={
            "source_md": "# Hi\n\n| a |\n|---|\n| 1 |\n\n$x^2$ [@k]\n\n![No alt](asset:0123456789abcdef)\n\n<script>x</script>\n"
        },
    ).json()
    assert "<table>" in out["html"] and "<math" in out["html"] and "<script" not in out["html"]
    assert out["citation_keys"] == ["k"]
    codes = {w["code"] for w in out["warnings"]}
    assert {"missing_alt", "missing_asset"} <= codes


def test_currency_dollars_are_not_math(client: TestClient) -> None:
    p = new_project(client)
    out = client.post(f"/api/projects/{p['id']}/preview", json={"source_md": "It cost $5 and $6 later.\n"}).json()
    assert "<math" not in out["html"] and "$5 and $6" in out["html"]
