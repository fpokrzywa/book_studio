"""Project library CRUD, search/filter/sort, archive and duplicate (T-P5)."""

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import new_chapter, new_project, save


def _titles(client: TestClient, **params: Any) -> list[str]:
    resp = client.get("/api/projects", params=params)
    assert resp.status_code == 200, resp.text
    return [p["title"] for p in resp.json()["items"]]


def test_create_and_read_back(client: TestClient) -> None:
    p = new_project(
        client,
        subtitle="Notes for builders",
        author_name="A. Writer",
        language="en-GB",
        audience="Hobbyist engineers",
        target_word_count=30000,
        publication_formats=["paperback", "ebook"],
    )
    got = client.get(f"/api/projects/{p['id']}").json()
    assert got["title"] == "The Quiet Engine"
    assert got["publication_formats"] == ["ebook", "paperback"]  # canonical order
    assert got["status"] == "active" and got["chapter_count"] == 0
    assert got["language"] == "en-GB"


def test_validation(client: TestClient) -> None:
    bad = [
        {"title": "", "project_type": "fiction"},
        {"title": "x", "project_type": "poetry"},
        {"title": "x", "project_type": "fiction", "language": "english language"},
        {"title": "x", "project_type": "fiction", "target_word_count": -5},
        {"title": "line\nbreak", "project_type": "fiction"},
        {"title": "x", "project_type": "fiction", "publication_formats": ["ebook", "ebook"]},
        {"title": "x", "project_type": "fiction", "unexpected": 1},
    ]
    for body in bad:
        resp = client.post("/api/projects", json=body)
        assert resp.status_code == 422, body
        assert resp.json()["code"] == "validation_failed"
        assert all(set(e) == {"loc", "msg", "type"} for e in resp.json()["errors"])  # input never echoed
    leaked = client.post("/api/projects", json={"title": "SECRET\nMANUSCRIPT", "project_type": "fiction"})
    assert "SECRET" not in leaked.text


def test_rename_and_edit(client: TestClient) -> None:
    p = new_project(client)
    resp = client.patch(f"/api/projects/{p['id']}", json={"title": "Renamed", "audience": "Everyone"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed" and resp.json()["audience"] == "Everyone"
    kinds = [a["kind"] for a in client.get("/api/activity").json()]
    assert "project_updated" in kinds and "project_created" in kinds


def test_search_filter_sort(client: TestClient) -> None:
    new_project(
        client,
        title="Zebra Tales",
        project_type="fiction",
        language="en",
        target_word_count=80000,
        audience="Teens",
        publication_formats=["ebook"],
    )
    new_project(
        client,
        title="alpha Manual",
        project_type="technical",
        language="de",
        target_word_count=20000,
        publication_formats=["paperback"],
    )
    new_project(
        client,
        title="Émile's Memoir",
        project_type="memoir",
        language="fr",
        audience="Adults",
        publication_formats=["ebook", "hardcover"],
    )

    assert _titles(client, sort="title", order="asc") == ["alpha Manual", "Zebra Tales", "Émile's Memoir"]
    assert _titles(client, q="MANUAL") == ["alpha Manual"]
    assert _titles(client, q="émile") == ["Émile's Memoir"]  # Unicode case folding
    assert _titles(client, q="teens") == ["Zebra Tales"]  # audience is searchable
    assert _titles(client, q="100%_") == []  # LIKE wildcards are escaped
    assert _titles(client, project_type="memoir") == ["Émile's Memoir"]
    assert _titles(client, language="DE") == ["alpha Manual"]
    assert sorted(_titles(client, publication_format="ebook")) == ["Zebra Tales", "Émile's Memoir"]
    # numeric sort with NULLs last in both directions
    assert _titles(client, sort="target_word_count", order="asc") == ["alpha Manual", "Zebra Tales", "Émile's Memoir"]
    assert _titles(client, sort="target_word_count", order="desc") == ["Zebra Tales", "alpha Manual", "Émile's Memoir"]
    assert _titles(client, sort="audience", order="asc")[-1] == "alpha Manual"
    assert _titles(client, sort="project_type", order="asc") == ["Zebra Tales", "Émile's Memoir", "alpha Manual"]
    assert client.get("/api/projects", params={"sort": "nonsense"}).status_code == 422


def test_archive_is_read_only_and_reversible(client: TestClient) -> None:
    p = new_project(client)
    ch = new_chapter(client, p["id"])
    assert save(client, p["id"], ch["id"], "Before archive.\n", 0).status_code == 200
    archived = client.post(f"/api/projects/{p['id']}/archive").json()
    assert archived["status"] == "archived" and archived["archived_at"]

    assert _titles(client) == []
    assert _titles(client, status="archived") == ["The Quiet Engine"]
    assert _titles(client, status="all") == ["The Quiet Engine"]

    # read-only while archived; reads still work
    assert client.patch(f"/api/projects/{p['id']}", json={"title": "X"}).status_code == 409
    resp = save(client, p["id"], ch["id"], "During archive.\n", 1)
    assert resp.status_code == 409 and resp.json()["code"] == "project_archived"
    assert client.post(f"/api/projects/{p['id']}/chapters", json={"title": "New"}).status_code == 409
    assert client.get(f"/api/projects/{p['id']}/chapters/{ch['id']}/content").json()["source_md"] == "Before archive.\n"

    restored = client.post(f"/api/projects/{p['id']}/unarchive").json()
    assert restored["status"] == "active" and restored["archived_at"] is None
    assert save(client, p["id"], ch["id"], "After archive.\n", 1).status_code == 200


def test_duplicate_copies_heads_not_history(client: TestClient) -> None:
    p = new_project(client, audience="Makers", publication_formats=["ebook", "paperback"])
    ch = new_chapter(client, p["id"])
    save(client, p["id"], ch["id"], "v1\n", 0)
    save(client, p["id"], ch["id"], "v2 final\n", 1)
    dup = client.post(f"/api/projects/{p['id']}/duplicate").json()
    assert dup["id"] != p["id"]
    assert dup["title"] == "The Quiet Engine (copy)"
    assert dup["duplicated_from_id"] == p["id"]
    assert dup["publication_formats"] == ["ebook", "paperback"] and dup["chapter_count"] == 1
    dup_ch = client.get(f"/api/projects/{dup['id']}/chapters").json()[0]
    assert dup_ch["id"] != ch["id"]
    content = client.get(f"/api/projects/{dup['id']}/chapters/{dup_ch['id']}/content").json()
    assert content["source_md"] == "v2 final\n" and content["revision_no"] == 1
    revs = client.get(f"/api/projects/{dup['id']}/chapters/{dup_ch['id']}/revisions").json()
    assert [r["origin"] for r in revs] == ["imported"]
    # editing the copy leaves the original untouched
    save(client, dup["id"], dup_ch["id"], "changed copy\n", 1)
    assert client.get(f"/api/projects/{p['id']}/chapters/{ch['id']}/content").json()["source_md"] == "v2 final\n"


def test_unknown_project_ids(client: TestClient) -> None:
    for pid in ["01ARZ3NDEKTSV4RRFFQ69G5FAV", "not-a-ulid", "..%2F..%2Fetc"]:
        assert client.get(f"/api/projects/{pid}").status_code == 404


def test_project_counts(client: TestClient) -> None:
    p = new_project(client)
    a = new_chapter(client, p["id"], "A")
    b = new_chapter(client, p["id"], "B")
    save(client, p["id"], a["id"], "one two three\n", 0)
    save(client, p["id"], b["id"], "four five\n", 0)
    got = client.get(f"/api/projects/{p['id']}").json()
    assert got["chapter_count"] == 2 and got["word_count"] == 5
    client.post(f"/api/projects/{p['id']}/chapters/{b['id']}/archive")
    got = client.get(f"/api/projects/{p['id']}").json()
    assert got["chapter_count"] == 1 and got["word_count"] == 3
