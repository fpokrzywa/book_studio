"""E2E-GOLDEN-01 (docs/TEST_PLAN.md section 5), backend driver.

Steps 08-10 and 14 (edit, restore, backup/restore) are covered by test_acceptance_phase02.py.
Steps that become executable in later phases are recorded as strict xfail with the phase
that owns them, so the scenario's progress is visible in every test run.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pbs_core.api.app import create_app
from pbs_core.context import build_context
from tests.conftest import BASE_URL, make_settings


def test_steps_01_to_03_and_11md_create_persist_restart_export(workspace: Path) -> None:
    ctx = build_context(make_settings(workspace))
    with TestClient(
        create_app(make_settings(workspace), ctx=ctx), base_url=BASE_URL, headers={"X-PBS-Token": ctx.token}
    ) as c:
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
    with TestClient(
        create_app(make_settings(workspace), ctx=ctx2), base_url=BASE_URL, headers={"X-PBS-Token": ctx2.token}
    ) as c:
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
    with TestClient(
        create_app(make_settings(workspace), ctx=ctx), base_url=BASE_URL, headers={"X-PBS-Token": ctx.token}
    ) as c:
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


PENDING = [
    ("05", "brief + outline generation with mock provider", "05"),
    ("11", "export EPUB, DOCX, PDF (Markdown and HTML exports are covered)", "07"),
    ("12", "validate exports (preflight)", "07"),
    ("13", "KDP handoff package", "07"),
]


@pytest.mark.parametrize(("step", "what", "phase"), PENDING, ids=[s for s, _, _ in PENDING])
@pytest.mark.xfail(strict=True, reason="not implemented yet; owned by a later phase")
def test_pending_golden_steps(step: str, what: str, phase: str) -> None:
    pytest.fail(f"E2E-GOLDEN-01 step {step} ({what}) arrives in Phase {phase}")


def test_step_04_ingest_knowledge_sources(client: TestClient) -> None:
    """04: a source is imported, indexed with provenance, searchable by exact passage and removable."""
    from tests.test_knowledge import HANDBOOK, upload

    p = client.post("/api/projects", json={"title": "The Quiet Engine", "project_type": "technical"}).json()
    src = upload(client, p["id"], "torque-handbook.md", HANDBOOK).json()["source"]
    hit = client.get(f"/api/projects/{p['id']}/knowledge/search", params={"q": "spiral pattern"}).json()["hits"][0]
    assert hit["citation_key"] == src["citation_key"] and hit["locator"].startswith("para")
    client.delete(f"/api/knowledge/sources/{src['id']}")
    assert client.get(f"/api/projects/{p['id']}/knowledge/search", params={"q": "spiral"}).json()["hits"] == []
