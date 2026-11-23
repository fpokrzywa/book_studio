"""Chapters, revisions, optimistic concurrency, DB-level immutability and project isolation."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from pbs_core.context import AppContext
from tests.conftest import new_chapter, new_project, save


def _content(client: TestClient, pid: str, cid: str) -> dict:  # type: ignore[type-arg]
    resp = client.get(f"/api/projects/{pid}/chapters/{cid}/content")
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def test_chapters_append_in_order_with_unique_slugs(client: TestClient) -> None:
    p = new_project(client)
    titles = ["Intro", "Intro", "Getting Started!", "Intro"]
    for t in titles:
        new_chapter(client, p["id"], t)
    chapters = client.get(f"/api/projects/{p['id']}/chapters").json()
    assert [c["title"] for c in chapters] == titles
    assert [c["slug"] for c in chapters] == ["intro", "intro-2", "getting-started", "intro-3"]
    assert [c["position"] for c in chapters] == sorted(c["position"] for c in chapters)


def test_save_creates_sequential_revisions(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    assert _content(client, p["id"], c["id"])["revision_no"] == 0
    r1 = save(client, p["id"], c["id"], "First draft.\r\n", 0).json()
    assert r1["created"] is True and r1["content"]["revision_no"] == 1
    assert r1["content"]["source_md"] == "First draft.\n"  # line endings normalised
    r2 = save(client, p["id"], c["id"], "Second draft, longer now.\n", 1).json()
    assert r2["content"]["revision_no"] == 2 and r2["content"]["word_count"] == 4
    revs = client.get(f"/api/projects/{p['id']}/chapters/{c['id']}/revisions").json()
    assert [r["revision_no"] for r in revs] == [2, 1]
    assert {r["origin"] for r in revs} == {"human"}


def test_identical_save_is_a_no_op(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Same.\n", 0)
    again = save(client, p["id"], c["id"], "Same.\n", 1).json()
    assert again["created"] is False and again["content"]["revision_no"] == 1


def test_stale_save_conflicts_without_writing(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Tab A.\n", 0)
    resp = save(client, p["id"], c["id"], "Tab B (stale).\n", 0)
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "conflict" and body["current"]["source_md"] == "Tab A.\n"
    assert _content(client, p["id"], c["id"])["revision_no"] == 1


def test_approved_chapter_must_be_reopened(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Done.\n", 0)
    client.patch(f"/api/projects/{p['id']}/chapters/{c['id']}", json={"status": "approved"})
    resp = save(client, p["id"], c["id"], "Sneaky change.\n", 1)
    assert resp.status_code == 409 and resp.json()["reason"] == "chapter_approved"
    client.patch(f"/api/projects/{p['id']}/chapters/{c['id']}", json={"status": "in_review"})
    assert save(client, p["id"], c["id"], "Deliberate change.\n", 1).status_code == 200


def test_rename_and_archive_chapter(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    renamed = client.patch(f"/api/projects/{p['id']}/chapters/{c['id']}", json={"title": "Better Title"}).json()
    assert renamed["title"] == "Better Title" and renamed["slug"] == c["slug"]  # slugs are stable
    assert client.post(f"/api/projects/{p['id']}/chapters/{c['id']}/archive").status_code == 204
    assert client.get(f"/api/projects/{p['id']}/chapters").json() == []
    assert client.get(f"/api/projects/{p['id']}/chapters/{c['id']}/content").status_code == 404


def test_project_isolation_through_api(client: TestClient) -> None:
    a = new_project(client, title="Book A")
    b = new_project(client, title="Book B")
    ca = new_chapter(client, a["id"], "A1")
    cb = new_chapter(client, b["id"], "B1")
    save(client, a["id"], ca["id"], "Secret of A.\n", 0)
    save(client, b["id"], cb["id"], "Secret of B.\n", 0)

    assert [c["title"] for c in client.get(f"/api/projects/{a['id']}/chapters").json()] == ["A1"]
    assert [c["title"] for c in client.get(f"/api/projects/{b['id']}/chapters").json()] == ["B1"]
    # Chapter of B addressed through project A: 404 (not 403), and nothing is written.
    assert client.get(f"/api/projects/{a['id']}/chapters/{cb['id']}/content").status_code == 404
    assert save(client, a["id"], cb["id"], "Overwrite!\n", 1).status_code == 404
    assert client.patch(f"/api/projects/{a['id']}/chapters/{cb['id']}", json={"title": "x"}).status_code == 404
    assert client.post(f"/api/projects/{a['id']}/chapters/{cb['id']}/archive").status_code == 404
    assert _content(client, b["id"], cb["id"])["source_md"] == "Secret of B.\n"
    # Exports contain only their own project's text.
    exp = client.post(f"/api/projects/{a['id']}/exports", json={}).json()
    text_a = client.get(exp["download_url"]).text
    assert "Secret of A." in text_a and "Secret of B." not in text_a
    # Export IDs are project-scoped too.
    assert client.get(f"/api/projects/{b['id']}/exports/{exp['id']}/file").status_code == 404


def test_db_rejects_cross_project_references(client: TestClient, ctx: AppContext) -> None:
    a = new_project(client, title="Book A")
    b = new_project(client, title="Book B")
    cb = new_chapter(client, b["id"], "B1")
    save(client, b["id"], cb["id"], "B text\n", 0)
    head_b = client.get(f"/api/projects/{b['id']}/chapters").json()[0]["head_revision_id"]
    ca = new_chapter(client, a["id"], "A1")
    with pytest.raises(IntegrityError), ctx.db.tx() as s:
        # Point A's chapter head at B's revision: composite FK must refuse it.
        s.execute(text("UPDATE chapter SET head_revision_id = :r WHERE id = :c"), {"r": head_b, "c": ca["id"]})
    with pytest.raises(IntegrityError), ctx.db.tx() as s:
        s.execute(
            text(
                "INSERT INTO chapter_revision (id, project_id, chapter_id, revision_no, origin, source_md, bdm_json,"
                " parser_version, content_hash, word_count, created_at)"
                " VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FAV', :p, :c, 1, 'human', 'x', '{}', 'v', 'h', 1, 'now')"
            ),
            {"p": a["id"], "c": cb["id"]},
        )


def test_revisions_are_immutable_in_the_database(client: TestClient, ctx: AppContext) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Original words.\n", 0)
    conn = sqlite3.connect(ctx.workspace.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE chapter_revision SET source_md = 'tampered'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM chapter_revision")
        with pytest.raises(sqlite3.IntegrityError, match="accepted proposal"):
            conn.execute(
                "INSERT INTO chapter_revision (id, project_id, chapter_id, revision_no, origin, source_md, bdm_json,"
                " parser_version, content_hash, word_count, created_at)"
                " VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FAW', ?, ?, 2, 'ai_generated', 'x', '{}', 'v', 'h', 1, 'now')",
                (p["id"], c["id"]),
            )
        with pytest.raises(sqlite3.IntegrityError, match="sequential"):
            conn.execute(
                "INSERT INTO chapter_revision (id, project_id, chapter_id, revision_no, origin, source_md, bdm_json,"
                " parser_version, content_hash, word_count, created_at)"
                " VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FAX', ?, ?, 7, 'human', 'x', '{}', 'v', 'h', 1, 'now')",
                (p["id"], c["id"]),
            )
    finally:
        conn.close()
    assert _content(client, p["id"], c["id"])["source_md"] == "Original words.\n"
