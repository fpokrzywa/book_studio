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


def test_ai_job_survives_hard_kill_without_double_apply(tmp_path: Path) -> None:
    """Kill Core while a job streams; after restart it re-runs once and yields exactly one suggestion."""
    os.environ["PBS_SECRET_BACKEND"] = "memory"  # noqa: S105 - backend name
    try:
        core = CoreProcess(tmp_path / "ws", _free_port())
        core.start()
        with core.client() as c:
            prov = c.post("/api/ai/providers", json={"kind": "mock"}).json()
            p = c.post("/api/projects", json={"title": "Restart", "project_type": "fiction"}).json()
            ch = c.post(f"/api/projects/{p['id']}/chapters", json={"title": "One"}).json()
            c.put(
                f"/api/projects/{p['id']}/chapters/{ch['id']}/content",
                json={"source_md": "Start.\n", "expected_head_no": 0},
            )
            job = c.post(
                f"/api/projects/{p['id']}/ai/jobs",
                json={
                    "chapter_id": ch["id"],
                    "task": "draft",
                    "instruction": "[[mock:slow]] go",
                    "base_revision_no": 1,
                    "provider_id": prov["id"],
                    "model_name": "mock-writer",
                    "client_request_id": "restart-test-0001",
                },
            ).json()
            deadline = time.monotonic() + 15
            while c.get(f"/api/ai/jobs/{job['id']}").json()["stage"] != "receiving" and time.monotonic() < deadline:
                time.sleep(0.1)
            assert c.get(f"/api/ai/jobs/{job['id']}").json()["stage"] == "receiving"
        core.kill()
        core.start()
        with core.client() as c:
            deadline = time.monotonic() + 30
            j = c.get(f"/api/ai/jobs/{job['id']}").json()
            while j["status"] != "succeeded" and time.monotonic() < deadline:
                time.sleep(0.25)
                j = c.get(f"/api/ai/jobs/{job['id']}").json()
            assert j["status"] == "succeeded" and j["attempt"] == 2
            logs = [x["message"] for x in c.get(f"/api/ai/jobs/{job['id']}/logs").json()]
            assert any("Core restarted" in m for m in logs)
            props = c.get(f"/api/projects/{p['id']}/proposals").json()
            assert len(props) == 1
            content = c.get(f"/api/projects/{p['id']}/chapters/{ch['id']}/content").json()
            assert content["revision_no"] == 1 and content["source_md"] == "Start.\n"
            a1 = c.post(f"/api/projects/{p['id']}/proposals/{props[0]['id']}/accept", json={"expected_head_no": 1})
            a2 = c.post(f"/api/projects/{p['id']}/proposals/{props[0]['id']}/accept", json={"expected_head_no": 1})
            assert a1.status_code == 200 and a2.status_code == 409
        core.kill()
    finally:
        os.environ.pop("PBS_SECRET_BACKEND", None)
