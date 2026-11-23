"""Phase 10: operations commands, backup archive verification, the operator's cloud switch and
remote (private) Ollama hosts."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pbs_core.__main__ import main
from pbs_core.context import AppContext, build_context
from pbs_core.ops import ArchiveError, check, status, verify_archive
from pbs_core.providers import egress
from tests.conftest import make_settings, new_chapter, new_project, save, signed_client


def _archive_of(ws: Path, dest: Path) -> Path:
    with tarfile.open(dest, "w:gz") as tar:
        for p in sorted(ws.rglob("*")):
            if p.is_file() and "runtime" not in p.parts:
                tar.add(p, arcname=f"./{p.relative_to(ws).as_posix()}")
    return dest


def test_status_and_check_report_content_and_worker(client: TestClient, ctx: AppContext) -> None:
    p = new_project(client)
    ch = new_chapter(client, p["id"])
    save(client, p["id"], ch["id"], "Some text.\n", 0)
    st = status(ctx)
    assert st["schema"] == st["schema_head"] == "0010"
    assert st["content"]["books"] == 1 and st["content"]["revisions"] == 1 and st["content"]["accounts"] == 1
    assert st["worker_heartbeat_age_s"] is None  # no worker in this test
    problems, warnings = check(ctx)
    assert problems == []
    assert any("background worker" in w for w in warnings)


def test_cli_status_json_and_check(
    workspace: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PBS_WORKSPACE", str(workspace))
    monkeypatch.setenv("PBS_ENV", "test")
    monkeypatch.setenv("PBS_SECRET_BACKEND", "memory")
    main(["migrate"])
    assert "-> 0010" in capsys.readouterr().out
    main(["status", "--json"])
    assert json.loads(capsys.readouterr().out)["schema"] == "0010"
    main(["check"])
    assert "OK: database" in capsys.readouterr().out


def test_verify_archive_accepts_a_real_backup(client: TestClient, ctx: AppContext, tmp_path: Path) -> None:
    p = new_project(client, title="Backed Up")
    ch = new_chapter(client, p["id"])
    save(client, p["id"], ch["id"], "Kept.\n", 0)
    out = verify_archive(_archive_of(ctx.workspace.root, tmp_path / "b.tgz"))
    assert out["integrity"] == "ok" and out["schema"] == "0010" and out["restorable_by_this_version"]
    assert out["content"]["project"] == 1 and out["content"]["chapter_revision"] == 1


def _tar_with(dest: Path, members: dict[str, bytes], link: str | None = None) -> Path:
    with tarfile.open(dest, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo(link)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
    return dest


@pytest.mark.parametrize(
    ("members", "link", "message"),
    [
        ({"../evil": b"x", "studio.db": b""}, None, "unsafe path"),
        ({"/abs": b"x"}, None, "unsafe path"),
        ({"projects/a.txt": b"x"}, None, "no studio.db"),
        ({"studio.db": b"not a database"}, None, ""),
        ({"studio.db": b""}, "projects/link", "links"),
    ],
)
def test_verify_archive_rejects_unsafe_or_broken_archives(
    tmp_path: Path, members: dict[str, bytes], link: str | None, message: str
) -> None:
    bad = _tar_with(tmp_path / "bad.tgz", members, link)
    with pytest.raises((ArchiveError, ValueError, OSError), match=message):
        verify_archive(bad)


def test_cli_verify_backup_exits_nonzero_on_a_bad_archive(tmp_path: Path) -> None:
    bad = _tar_with(tmp_path / "bad.tgz", {"projects/a.txt": b"x"})
    with pytest.raises(SystemExit, match="NOT usable"):
        main(["verify-backup", str(bad)])


def test_operator_cloud_switch_forces_local_only(tmp_path: Path) -> None:
    ctx = build_context(make_settings(tmp_path / "ws", allow_cloud=False))
    try:
        with signed_client(ctx) as c:
            resp = c.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True})
            assert resp.status_code == 409 and resp.json()["reason"] == "cloud_disabled_by_operator"
            st = c.get("/api/ai/status").json()
            assert st["privacy_mode"] == "local_only" and st["cloud_allowed_by_operator"] is False
            # Even a stored "cloud_allowed" setting (from before the switch) is overridden.
            from pbs_core.storage.models import AppSetting

            with ctx.db.tx() as s:
                row = s.get(AppSetting, "privacy_mode")
                assert row is not None
                row.value_json = json.dumps("cloud_allowed")
            assert c.get("/api/ai/status").json()["privacy_mode"] == "local_only"
            assert c.get("/api/system/info").json()["privacy_mode"] == "local_only"
            prov = c.post("/api/ai/providers", json={"kind": "openai"}).json()
            key = c.put(f"/api/ai/providers/{prov['id']}/key", json={"api_key": "sk-test-NOTREAL0123456789"})
            assert key.status_code == 200, key.text
            test = c.post(f"/api/ai/providers/{prov['id']}/test").json()
            assert test["ok"] is False and test["code"] == "egress_blocked" and "PBS_ALLOW_CLOUD" in test["message"]
    finally:
        ctx.close()


def test_remote_ollama_on_an_operator_named_lan_address(tmp_path: Path) -> None:
    permit = egress.EgressPermit("ollama", cloud_allowed=False)
    with pytest.raises(egress.EgressBlockedError):
        egress.check("http://192.168.1.50:11434/api/tags", permit)
    ctx = build_context(make_settings(tmp_path / "ws", local_ai_hosts=["192.168.1.50", "gpu-box.lan"]))
    try:
        egress.check("http://192.168.1.50:11434/api/tags", permit)
        egress.check("http://gpu-box.lan:11434/api/tags", permit)
        with pytest.raises(egress.EgressBlockedError):
            egress.check("http://192.168.1.51:11434/api/tags", permit)
        with signed_client(ctx) as c:
            ok = c.post("/api/ai/providers", json={"kind": "ollama", "base_url": "http://192.168.1.50:11434"})
            assert ok.status_code == 201, ok.text
            bad = c.post("/api/ai/providers", json={"kind": "ollama", "base_url": "http://203.0.113.9:11434"})
            assert bad.status_code == 422
            assert c.get("/api/ai/status").json()["private_model_hosts"] == ["192.168.1.50", "gpu-box.lan"]
    finally:
        egress.configure_local_hosts([])
        ctx.close()
