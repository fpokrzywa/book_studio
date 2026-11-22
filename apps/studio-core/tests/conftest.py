"""Shared fixtures: hermetic workspace, network guard, API client."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pbs_core.api.app import create_app
from pbs_core.config import Settings
from pbs_core.context import AppContext, build_context

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
UI_ORIGIN = "http://127.0.0.1:5173"


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
    }
    values.update(overrides)
    return Settings(**values)


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
    app = create_app(make_settings(workspace), ctx=ctx)
    with TestClient(app, base_url=BASE_URL, headers={"X-PBS-Token": ctx.token}) as c:
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
