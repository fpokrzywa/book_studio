"""Markdown export (T-P6): deterministic format, verbatim chapter text, sanitized file names."""

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from pbs_core.context import AppContext
from tests.conftest import new_chapter, new_project, save

TRICKY = "| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('hi')\t# tab  \n```\n\n$$E = mc^2$$\n"


def test_markdown_export_golden(client: TestClient, ctx: AppContext) -> None:
    p = new_project(client, title='Book: "One"/Two', subtitle="Sub", author_name="A. Writer", language="en-GB")
    c1 = new_chapter(client, p["id"], "Chapter One")
    new_chapter(client, p["id"], "Empty Chapter")
    c3 = new_chapter(client, p["id"], "Chapter Three")
    save(client, p["id"], c1["id"], "First chapter text.", 0)
    save(client, p["id"], c3["id"], TRICKY, 0)

    resp = client.post(f"/api/projects/{p['id']}/exports", json={"format": "markdown"})
    assert resp.status_code == 201, resp.text
    exp = resp.json()
    assert exp["status"] == "completed" and exp["chapter_count"] == 3
    assert exp["file_name"] == "Book- -One-Two.md"
    assert exp["warnings"] == ["Chapter “Empty Chapter” has no saved content; exported as a heading only."]

    f = client.get(exp["download_url"])
    assert f.status_code == 200
    assert "filename*=utf-8''Book-%20-One-Two.md" in f.headers["content-disposition"]
    expected = (
        "---\n"
        'title: "Book: \\"One\\"/Two"\n'
        'subtitle: "Sub"\n'
        'author: "A. Writer"\n'
        'lang: "en-GB"\n'
        "pbs_export:\n"
        '  schema: "pbs-md-export/1"\n'
        f'  project_id: "{p["id"]}"\n'
        f'  export_id: "{exp["id"]}"\n'
        "---\n"
        "\n"
        "# Chapter One {#ch-chapter-one}\n\nFirst chapter text.\n"
        "\n"
        "# Empty Chapter {#ch-empty-chapter}\n\n"
        "\n"
        "# Chapter Three {#ch-chapter-three}\n\n" + TRICKY
    )
    assert f.text == expected
    assert hashlib.sha256(f.content).hexdigest() == exp["sha256"]
    on_disk = ctx.workspace.project_dir(p["id"]) / "exports" / exp["id"] / exp["file_name"]
    assert Path(on_disk).read_bytes() == f.content

    listed = client.get(f"/api/projects/{p['id']}/exports").json()
    assert [e["id"] for e in listed] == [exp["id"]]


def test_export_of_empty_project_warns(client: TestClient) -> None:
    p = new_project(client, title="CON")
    exp = client.post(f"/api/projects/{p['id']}/exports", json={}).json()
    assert exp["file_name"] == "_CON.md"
    assert exp["warnings"] == ["The project has no chapters; the export contains metadata only."]


def test_export_missing_file_is_404(client: TestClient, ctx: AppContext) -> None:
    p = new_project(client)
    exp = client.post(f"/api/projects/{p['id']}/exports", json={}).json()
    (ctx.workspace.project_dir(p["id"]) / "exports" / exp["id"] / exp["file_name"]).unlink()
    assert client.get(exp["download_url"]).status_code == 404
