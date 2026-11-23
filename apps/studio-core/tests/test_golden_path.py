"""E2E-GOLDEN-01 (docs/TEST_PLAN.md section 5), backend driver.

Steps 08-10 and 14 (edit, restore, backup/restore) are covered by test_acceptance_phase02.py.
Steps that become executable in later phases are recorded as strict xfail with the phase
that owns them, so the scenario's progress is visible in every test run.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from pbs_core.context import build_context
from tests.conftest import make_settings, signed_client


def test_steps_01_to_03_and_11md_create_persist_restart_export(workspace: Path) -> None:
    ctx = build_context(make_settings(workspace))
    with signed_client(ctx, make_settings(workspace)) as c:
        # 1. Empty library, local-only.
        assert c.get("/api/projects").json()["total"] == 0
        assert c.get("/api/system/info").json()["privacy_mode"] == "local_only"
        # 2. Create the project with full metadata.
        p = c.post(
            "/api/projects",
            json={
                "title": "The Quiet Engine",
                "project_type": "technical",
                "language": "en",
                "audience": "hobbyist engineers",
                "target_word_count": 30000,
                "publication_formats": ["ebook", "paperback"],
            },
        ).json()
        ch = c.post(f"/api/projects/{p['id']}/chapters", json={"title": "Chapter One"}).json()
        c.put(
            f"/api/projects/{p['id']}/chapters/{ch['id']}/content",
            json={"source_md": "Body text.\n", "expected_head_no": 0},
        )
    ctx.close()

    # 3. Restart (new context on the same workspace): everything is still there.
    ctx2 = build_context(make_settings(workspace))
    with signed_client(ctx2, make_settings(workspace)) as c:
        got = c.get(f"/api/projects/{p['id']}").json()
        assert got["audience"] == "hobbyist engineers" and got["publication_formats"] == ["ebook", "paperback"]
        # 11 (Markdown part). Export.
        exp = c.post(f"/api/projects/{p['id']}/exports", json={"format": "markdown"}).json()
        assert "Body text." in c.get(exp["download_url"]).text
    ctx2.close()


def test_steps_06_07_15_draft_review_accept_with_zero_egress(workspace: Path, network_guard: list[object]) -> None:
    """06 draft into a proposal, 07 accept -> ai_generated revision, 15 zero non-loopback egress."""
    import uuid

    from pbs_core.jobs.runner import JobRunner
    from pbs_core.providers.egress import external_requests

    ctx = build_context(make_settings(workspace))
    runner = JobRunner(ctx)
    ctx.jobs = runner
    before = external_requests()
    with signed_client(ctx, make_settings(workspace)) as c:
        prov = c.post("/api/ai/providers", json={"kind": "mock"}).json()
        c.put("/api/ai/routes/draft", json={"provider_id": prov["id"], "model_name": "mock-writer"})
        p = c.post("/api/projects", json={"title": "The Quiet Engine", "project_type": "technical"}).json()
        ch = c.post(f"/api/projects/{p['id']}/chapters", json={"title": "Chapter One"}).json()
        c.put(
            f"/api/projects/{p['id']}/chapters/{ch['id']}/content", json={"source_md": "Body.\n", "expected_head_no": 0}
        )
        body = {
            "chapter_id": ch["id"],
            "task": "draft",
            "instruction": "One paragraph.",
            "base_revision_no": 1,
            "client_request_id": uuid.uuid4().hex,
        }
        assert c.post(f"/api/projects/{p['id']}/ai/jobs", json=body).status_code == 202
        runner.run_until_idle()
        prop = c.get(f"/api/projects/{p['id']}/proposals").json()[0]  # 06
        acc = c.post(f"/api/projects/{p['id']}/proposals/{prop['id']}/accept", json={"expected_head_no": 1})
        assert acc.status_code == 200  # 07
        revs = c.get(f"/api/projects/{p['id']}/chapters/{ch['id']}/revisions").json()
        assert revs[0]["origin"] == "ai_generated"
        assert c.get("/api/ai/status").json()["external_requests"] == before
    ctx.close()
    assert external_requests() == before and network_guard == []  # 15


def test_steps_11_12_13_exports_preflight_and_kdp_package(client: TestClient) -> None:
    """11: EPUB, DOCX and PDF (with Markdown and HTML); 12: preflight with each export; 13: the KDP package."""
    from tests.test_publishing import fixture_book

    f = fixture_book(client)
    pkg = client.post(f"/api/projects/{f['pid']}/publishing/package")
    assert pkg.status_code == 201, pkg.text
    out = pkg.json()
    kinds = {p["kind"] for p in client.get(f"/api/projects/{f['pid']}/publishing/publications").json()}
    assert {"markdown", "html", "epub", "docx", "pdf", "cover_print", "cover_ebook", "package"} <= kinds  # 11
    assert out["report_summary"].get("pass", 0) > 0  # 12
    names = {x["name"] for x in out["files"]}
    assert {"KDP-UPLOAD-STEPS.md", "metadata.json", "preflight-report.html"} <= names  # 13


def test_step_04_ingest_knowledge_sources(client: TestClient) -> None:
    """04: a source is imported, indexed with provenance, searchable by exact passage and removable."""
    from tests.test_knowledge import HANDBOOK, upload

    p = client.post("/api/projects", json={"title": "The Quiet Engine", "project_type": "technical"}).json()
    src = upload(client, p["id"], "torque-handbook.md", HANDBOOK).json()["source"]
    hit = client.get(f"/api/projects/{p['id']}/knowledge/search", params={"q": "spiral pattern"}).json()["hits"][0]
    assert hit["citation_key"] == src["citation_key"] and hit["locator"].startswith("para")
    client.delete(f"/api/knowledge/sources/{src['id']}")
    assert client.get(f"/api/projects/{p['id']}/knowledge/search", params={"q": "spiral"}).json()["hits"] == []


def test_step_05_brief_and_outline_with_test_model(client: TestClient, runner: Any) -> None:
    """05: from an idea, a brief and an approved, applied outline using the deterministic test model."""
    from tests.test_planning import approve_and_apply, mock_provider, new_book, outline_from_ai

    pid = new_book(client)["project"]["id"]
    proposal = outline_from_ai(client, runner, pid, mock_provider(client))
    report = approve_and_apply(client, pid, proposal["id"])
    assert len(report["created"]) == 4 and len(client.get(f"/api/projects/{pid}/chapters").json()) == 4
