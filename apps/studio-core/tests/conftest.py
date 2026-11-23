"""Shared fixtures: hermetic workspace, network guard, API client."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from pbs_core.api.app import create_app
from pbs_core.config import Settings
from pbs_core.context import AppContext, build_context

if TYPE_CHECKING:
    from pbs_core.jobs.runner import JobRunner

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
UI_ORIGIN = "http://127.0.0.1:5173"
OWNER = "author"
PASSWORD = "correct horse battery 42"  # test-only account password, never a real credential  # noqa: S105


def _is_loopback(address: Any) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
    else:
        return True  # AF_UNIX paths etc.
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True, scope="session")
def network_guard() -> Iterator[list[Any]]:
    """Fail any attempt to open a non-loopback connection (TEST_PLAN section 2.2)."""
    attempts: list[Any] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not _is_loopback(address):
            attempts.append(address)
            raise OSError(f"network guard: blocked non-loopback connection to {address!r}")
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        if not _is_loopback(address):
            attempts.append(address)
            raise OSError(f"network guard: blocked non-loopback connection to {address!r}")
        return real_connect_ex(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    yield attempts
    socket.socket.connect = real_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
    assert attempts == [], f"non-loopback network attempts during tests: {attempts}"


def make_settings(workspace: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "workspace": workspace,
        "port": PORT,
        "ui_origins": [UI_ORIGIN],
        "log_console": False,
        "secret_backend": "memory",  # never touch the real OS credential store in tests
        "ai_runner": False,  # tests drive the job runner explicitly
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """scrypt at n=2**10 in tests (production uses 2**17); stored hashes carry their own cost."""
    from pbs_core.security import passwords

    monkeypatch.setattr(passwords, "LOG2_N", 10)


def sign_in(c: TestClient, ctx: AppContext) -> TestClient:
    """Create the studio account on first use (with the setup code), else sign in; set the CSRF header."""
    from pbs_core.services import auth

    if auth.account_count(ctx) == 0:
        auth.ensure_setup_code(ctx)
        code = (ctx.workspace.runtime_dir / auth.SETUP_CODE_FILE).read_text(encoding="ascii")
        resp = c.post(
            "/api/auth/setup",
            json={"username": OWNER, "password": PASSWORD, "setup_code": code},
            headers={"X-PBS-CSRF": "1"},
        )
    else:
        resp = c.post("/api/auth/login", json={"username": OWNER, "password": PASSWORD}, headers={"X-PBS-CSRF": "1"})
    assert resp.status_code == 200, resp.text
    c.headers["X-PBS-CSRF"] = resp.json()["csrf_token"]
    return c


@contextmanager
def signed_client(ctx: AppContext, settings: Settings | None = None, **kwargs: Any) -> Iterator[TestClient]:
    """Enter the client first, then sign in: requests made outside the TestClient context each start a
    new event loop (and, on Windows, a socket pair), which exhausts socket buffers over a full run."""
    settings = settings or ctx.settings
    with TestClient(create_app(settings, ctx=ctx), base_url=BASE_URL, **kwargs) as c:
        yield sign_in(c, ctx)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def ctx(workspace: Path) -> Iterator[AppContext]:
    context = build_context(make_settings(workspace))
    yield context
    context.close()


@pytest.fixture
def client(workspace: Path, ctx: AppContext) -> Iterator[TestClient]:
    with signed_client(ctx, make_settings(workspace)) as c:
        yield c


def new_project(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"title": "The Quiet Engine", "project_type": "technical"}
    body.update(overrides)
    resp = client.post("/api/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def new_chapter(client: TestClient, project_id: str, title: str = "Chapter One") -> dict[str, Any]:
    resp = client.post(f"/api/projects/{project_id}/chapters", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def save(client: TestClient, project_id: str, chapter_id: str, text: str, expected: int) -> Any:
    return client.put(
        f"/api/projects/{project_id}/chapters/{chapter_id}/content",
        json={"source_md": text, "expected_head_no": expected},
    )


@pytest.fixture
def runner(ctx: AppContext) -> JobRunner:
    from pbs_core.jobs.runner import JobRunner

    r = JobRunner(ctx, workers=1)
    ctx.jobs = r
    return r


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from pbs_core.providers.base import GenRequest
    from pbs_core.providers.mock import MockAdapter

    """Every request the test model receives, so tests can inspect exactly what was sent."""
    seen: list[GenRequest] = []
    original = MockAdapter.stream_chat

    def spy(self: MockAdapter, req: GenRequest, on_delta: Any, should_cancel: Any) -> Any:
        seen.append(req)
        return original(self, req, on_delta, should_cancel)

    monkeypatch.setattr(MockAdapter, "stream_chat", spy)
    return seen
