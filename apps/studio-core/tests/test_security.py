"""Local API guard (T-S1, T-S2), redaction (T-S5) and loopback-only configuration."""

from pathlib import Path

import pytest
import structlog
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pbs_core.api.app import create_app
from pbs_core.config import Settings
from pbs_core.context import AppContext
from pbs_core.security.redact import REDACTED, redact_text
from tests.conftest import BASE_URL, UI_ORIGIN, make_settings


@pytest.fixture
def raw_client(workspace: Path, ctx: AppContext) -> TestClient:
    """Client WITHOUT the session token header."""
    return TestClient(create_app(make_settings(workspace), ctx=ctx), base_url=BASE_URL)


def test_missing_token_is_rejected(raw_client: TestClient) -> None:
    resp = raw_client.get("/api/projects")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "missing_or_bad_token"


def test_wrong_token_is_rejected(raw_client: TestClient) -> None:
    assert raw_client.get("/api/projects", headers={"X-PBS-Token": "nope"}).status_code == 401


def test_healthz_needs_no_token(raw_client: TestClient) -> None:
    assert raw_client.get("/healthz").json() == {"status": "ok"}


def test_bad_host_is_rejected(raw_client: TestClient, ctx: AppContext) -> None:
    resp = raw_client.get("/api/projects", headers={"X-PBS-Token": ctx.token, "Host": "evil.example"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "bad_host"


def test_rebinding_host_with_right_port_is_rejected(raw_client: TestClient, ctx: AppContext) -> None:
    resp = raw_client.get("/healthz", headers={"Host": "attacker.example:8765"})
    assert resp.status_code == 400


def test_foreign_origin_is_rejected_even_with_token(raw_client: TestClient, ctx: AppContext) -> None:
    resp = raw_client.post(
        "/api/projects",
        json={"title": "x", "project_type": "fiction"},
        headers={"X-PBS-Token": ctx.token, "Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "bad_origin"


def test_cross_site_fetch_metadata_is_rejected(raw_client: TestClient, ctx: AppContext) -> None:
    resp = raw_client.get("/api/projects", headers={"X-PBS-Token": ctx.token, "Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 403


def test_allowed_origin_works_and_no_cors_headers(raw_client: TestClient, ctx: AppContext) -> None:
    resp = raw_client.get("/api/projects", headers={"X-PBS-Token": ctx.token, "Origin": UI_ORIGIN})
    assert resp.status_code == 200
    assert not any(h.lower().startswith("access-control-") for h in resp.headers)


def test_preflight_gets_no_cors_approval(raw_client: TestClient) -> None:
    resp = raw_client.options(
        "/api/projects",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code in (401, 403)
    assert "access-control-allow-origin" not in {h.lower() for h in resp.headers}


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com", "::"])  # noqa: S104
def test_non_loopback_host_setting_is_refused(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValidationError):
        Settings(workspace=tmp_path, host=host)


def test_token_file_written(ctx: AppContext) -> None:
    assert ctx.workspace.token_path.read_text(encoding="ascii") == ctx.token
    assert len(ctx.token) >= 43


def test_redact_text_patterns() -> None:
    samples = [
        "sk-test-CANARY0123456789abcdef",
        "sk-ant-api03-CANARYabcdefghijkl",
        "AIzaSyCANARY0123456789abcdefghij",
        "gsk_CANARY0123456789",
        "Authorization: Bearer abcdefghijklmnop",
        "x-api-key: CANARY-secret",
    ]
    for s in samples:
        assert "CANARY" not in redact_text(s) and REDACTED in redact_text(s), s


def test_logs_never_contain_secrets(ctx: AppContext) -> None:
    log = structlog.get_logger("test")
    canary = "sk-test-CANARYCANARY0123456789"
    log.info("provider_call", api_key=canary, note=f"using key {canary}")
    try:
        raise RuntimeError(f"upstream rejected key {canary}")
    except RuntimeError:
        log.exception("boom")
    import logging

    for h in logging.getLogger().handlers:
        h.flush()
    content = "".join(p.read_text(encoding="utf-8") for p in ctx.workspace.logs_dir.glob("core.jsonl*"))
    assert "provider_call" in content and "boom" in content
    assert "CANARY" not in content
