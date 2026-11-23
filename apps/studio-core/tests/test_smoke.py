from fastapi.testclient import TestClient

from tests.conftest import new_chapter, new_project, save


def test_vertical_slice_api(client: TestClient) -> None:
    p = new_project(client)
    c = new_chapter(client, p["id"])
    r = save(client, p["id"], c["id"], "Hello *world*.\n", 0)
    assert r.status_code == 200, r.text
    assert r.json()["content"]["revision_no"] == 1
    e = client.post(f"/api/projects/{p['id']}/exports", json={"format": "markdown"})
    assert e.status_code == 201, e.text
    f = client.get(e.json()["download_url"])
    assert f.status_code == 200
    assert "Hello *world*." in f.text
