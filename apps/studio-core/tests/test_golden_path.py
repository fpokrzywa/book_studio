"""E2E-GOLDEN-01 (docs/TEST_PLAN.md section 5), backend driver.

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


PENDING = [
    ("04", "ingest sources: import DOCX manuscript + knowledge sources", "02/04"),
    ("05", "brief + outline generation with mock provider", "05"),
    ("06", "generate chapter draft into a proposal", "03/06"),
    ("07", "accept proposal -> ai_generated revision", "03"),
    ("08", "human edit with table/equation/figure -> block IDs preserved", "02"),
    ("09", "restore revision 2 as a new revision", "02"),
    ("10", "restore revision 3 again", "02"),
    ("11", "export EPUB, DOCX, PDF (+HTML)", "02/07"),
    ("12", "validate exports (preflight)", "07"),
    ("13", "KDP handoff package", "07"),
    ("14", "backup -> restore as new project", "02"),
    ("15", "zero non-loopback egress across the whole run with AI enabled", "03"),
]


@pytest.mark.parametrize(("step", "what", "phase"), PENDING, ids=[s for s, _, _ in PENDING])
@pytest.mark.xfail(strict=True, reason="not implemented yet; owned by a later phase")
def test_pending_golden_steps(step: str, what: str, phase: str) -> None:
    pytest.fail(f"E2E-GOLDEN-01 step {step} ({what}) arrives in Phase {phase}")
