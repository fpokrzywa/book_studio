"""Real Core process: loopback-only bind (T-S3) and persistence across a hard kill + restart (T-P1)."""

import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.slow


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class CoreProcess:
    def __init__(self, workspace: Path, port: int) -> None:
        self.workspace, self.port = workspace, port
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = {
            **os.environ,
            "PBS_ENV": "test",
            "PBS_WORKSPACE": str(self.workspace),
            "PBS_PORT": str(self.port),
            "PBS_LOG_CONSOLE": "false",
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "pbs_core"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"core exited early: {self.proc.stderr.read().decode() if self.proc.stderr else ''}")
            try:
                if httpx.get(f"{self.base}/healthz", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("core did not become healthy")

    def kill(self) -> None:
        """Hard kill (TerminateProcess / SIGKILL) to simulate a crash."""
        assert self.proc is not None
        self.proc.kill()
        self.proc.wait(timeout=15)

    def client(self) -> httpx.Client:
        token = (self.workspace / "runtime" / "session.token").read_text(encoding="ascii")
        return httpx.Client(base_url=self.base, headers={"X-PBS-Token": token}, timeout=10)


@pytest.fixture
def core(tmp_path: Path) -> Iterator[CoreProcess]:
    c = CoreProcess(tmp_path / "ws", _free_port())
    c.start()
    yield c
    if c.proc and c.proc.poll() is None:
        c.kill()


def _listen_addresses(port: int) -> list[str]:
    out = subprocess.run(["netstat", "-an"], capture_output=True, text=True, timeout=30, check=False).stdout
    addrs = []
    for line in out.splitlines():
        if "LISTEN" not in line.upper():
            continue
        for token in line.split():
            if re.search(rf"[:.]{port}$", token):
                addrs.append(token)
                break
    return addrs


def test_core_listens_on_loopback_only(core: CoreProcess) -> None:
    addrs = _listen_addresses(core.port)
    assert addrs, "netstat did not report the listening socket"
    assert all(a.startswith(("127.0.0.1", "[::1]", "::1")) for a in addrs), addrs


def test_content_survives_hard_kill_and_restart(core: CoreProcess) -> None:
    text = "Line one.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\t kept  \n```\n"
    with core.client() as c:
        p = c.post("/api/projects", json={"title": "Durable", "project_type": "fiction"}).json()
        ch = c.post(f"/api/projects/{p['id']}/chapters", json={"title": "One"}).json()
        saved = c.put(
            f"/api/projects/{p['id']}/chapters/{ch['id']}/content", json={"source_md": text, "expected_head_no": 0}
        )
        assert saved.status_code == 200
        old_token = c.headers["X-PBS-Token"]

    core.kill()
    core.start()

    with core.client() as c:
        assert c.headers["X-PBS-Token"] != old_token  # fresh token per launch
        got = c.get(f"/api/projects/{p['id']}/chapters/{ch['id']}/content").json()
        assert got["source_md"] == text and got["revision_no"] == 1
        titles = [x["title"] for x in c.get("/api/projects").json()["items"]]
        assert titles == ["Durable"]
    with httpx.Client(base_url=core.base) as anon:
        assert anon.get("/api/projects", headers={"X-PBS-Token": old_token}).status_code == 401
