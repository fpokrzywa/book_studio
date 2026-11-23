"""Phase 09: sign-in, sessions, CSRF, authorization on every route, file safety, server settings,
encrypted key store, private model hosts and durable background tasks."""

from __future__ import annotations

import base64
import re
import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pbs_core.api.app import create_app
from pbs_core.config import Settings
from pbs_core.context import AppContext, build_context
from pbs_core.domain.clock import Clock
from pbs_core.security.guard import PUBLIC_API, UNSAFE_METHODS
from pbs_core.services import auth, tasks
from tests.conftest import BASE_URL, OWNER, PASSWORD, make_settings, new_chapter, new_project, save, signed_client

ULID = "01HZZZZZZZZZZZZZZZZZZZZZZZ"


def _api_routes(app: Any) -> list[tuple[str, str]]:
    """Every documented /api operation (the OpenAPI schema lists each route the app serves)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api"):
            for m in sorted(ops):
                out.append((m.upper(), re.sub(r"\{[^}]+\}", ULID, path)))
    return out


@pytest.fixture
def anon(workspace: Path, ctx: AppContext) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(workspace), ctx=ctx), base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def stack() -> Iterator[ExitStack]:
    with ExitStack() as s:
        yield s


def _setup_code(ctx: AppContext) -> str:
    auth.ensure_setup_code(ctx)
    return (ctx.workspace.runtime_dir / auth.SETUP_CODE_FILE).read_text(encoding="ascii")


# ---------- authorization on every endpoint ----------


def test_every_api_route_requires_sign_in(anon: TestClient) -> None:
    routes = _api_routes(anon.app)
    assert len(routes) > 150  # the whole API, not a sample
    for method, path in routes:
        resp = anon.request(method, path, headers={"X-PBS-CSRF": "1"})
        if path in PUBLIC_API:
            continue
        assert resp.status_code == 401, (method, path, resp.status_code)
        assert resp.json()["code"] == "not_signed_in"


def test_every_state_changing_route_requires_the_session_csrf_token(client: TestClient) -> None:
    good = client.headers.pop("X-PBS-CSRF")
    for method, path in _api_routes(client.app):
        if method not in UNSAFE_METHODS or path in PUBLIC_API:
            continue
        for headers in ({}, {"X-PBS-CSRF": "wrong"}):
            resp = client.request(method, path, headers=headers)
            assert resp.status_code == 403 and resp.json()["code"] == "csrf", (method, path, resp.status_code)
    client.headers["X-PBS-CSRF"] = good
    assert client.post("/api/projects", json={"title": "Fine", "project_type": "fiction"}).status_code == 201


def test_sign_in_endpoints_need_the_anti_forgery_header(anon: TestClient) -> None:
    resp = anon.post("/api/auth/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 403 and resp.json()["code"] == "csrf"


# ---------- setup ----------


def test_setup_needs_the_code_and_happens_once(anon: TestClient, ctx: AppContext) -> None:
    state = anon.get("/api/auth/state").json()
    assert state["setup_required"] and not state["signed_in"] and state["csrf_token"] is None
    code = _setup_code(ctx)
    bad = anon.post("/api/auth/setup", json={"username": OWNER, "password": PASSWORD, "setup_code": "guess"},
                    headers={"X-PBS-CSRF": "1"})  # fmt: skip
    assert bad.status_code == 401 and bad.json()["reason"] == "bad_setup_code"
    weak = anon.post("/api/auth/setup", json={"username": OWNER, "password": "short", "setup_code": code},
                     headers={"X-PBS-CSRF": "1"})  # fmt: skip
    assert weak.status_code == 422
    ok = anon.post("/api/auth/setup", json={"username": OWNER, "password": PASSWORD, "setup_code": code},
                   headers={"X-PBS-CSRF": "1"})  # fmt: skip
    assert ok.status_code == 200 and ok.json()["signed_in"] and ok.json()["username"] == OWNER
    assert not (ctx.workspace.runtime_dir / auth.SETUP_CODE_FILE).exists()
    again = anon.post("/api/auth/setup", json={"username": "second", "password": PASSWORD, "setup_code": code},
                      headers={"X-PBS-CSRF": "1"})  # fmt: skip
    assert again.status_code == 409 and again.json()["reason"] == "account_exists"
    assert auth.account_count(ctx) == 1


def test_secrets_never_reach_logs_or_the_database(client: TestClient, ctx: AppContext) -> None:
    token = client.cookies.get("pbs_session")
    assert token
    db = ctx.workspace.db_path.read_bytes()
    assert PASSWORD.encode() not in db and token.encode() not in db
    with sqlite3.connect(ctx.workspace.db_path) as con:
        (hashed,) = con.execute("select password_hash from user_account").fetchone()
    assert hashed.startswith("scrypt$")
    logs = "".join(p.read_text(encoding="utf-8") for p in ctx.workspace.logs_dir.glob("core.jsonl*"))
    assert "account_created" in logs and PASSWORD not in logs and token not in logs


# ---------- sign in, cookies, sessions ----------


def test_cookie_is_httponly_strict_and_host_only(anon: TestClient, ctx: AppContext) -> None:
    resp = anon.post("/api/auth/setup", json={"username": OWNER, "password": PASSWORD, "setup_code": _setup_code(ctx)},
                     headers={"X-PBS-CSRF": "1"})  # fmt: skip
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie and "domain=" not in cookie


def test_wrong_password_and_unknown_user_look_the_same_then_throttle(anon: TestClient, ctx: AppContext) -> None:
    auth.create_account(ctx, OWNER, PASSWORD)
    h = {"X-PBS-CSRF": "1"}
    a = anon.post("/api/auth/login", json={"username": OWNER, "password": "wrong password 1"}, headers=h)
    b = anon.post("/api/auth/login", json={"username": "nobody", "password": "wrong password 1"}, headers=h)
    assert a.status_code == b.status_code == 401 and a.json()["title"] == b.json()["title"]
    for _ in range(4):
        anon.post("/api/auth/login", json={"username": OWNER, "password": "wrong password 1"}, headers=h)
    locked = anon.post("/api/auth/login", json={"username": OWNER, "password": PASSWORD}, headers=h)
    assert locked.status_code == 429 and locked.json()["retry_after"] > 0  # even the right password waits


def test_logout_and_password_change_end_sessions(
    client: TestClient, workspace: Path, ctx: AppContext, stack: ExitStack
) -> None:
    other = stack.enter_context(signed_client(ctx, make_settings(workspace)))
    assert other.get("/api/projects").status_code == 200
    weak = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "tiny"})
    assert weak.status_code == 422
    wrong = client.post("/api/auth/password", json={"current_password": "not it at all", "new_password": "x" * 20})
    assert wrong.status_code == 401
    resp = client.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "a much newer password"}
    )
    assert resp.status_code == 200 and resp.json()["signed_out"] == 1
    assert other.get("/api/projects").status_code == 401  # the other browser is signed out
    assert client.get("/api/projects").status_code == 200  # this one stays signed in
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/projects").status_code == 401


def test_cli_password_reset_signs_everyone_out(client: TestClient, ctx: AppContext) -> None:
    auth.reset_password(ctx, OWNER, "reset from the server")
    assert client.get("/api/projects").status_code == 401
    with pytest.raises(Exception, match="no account"):
        auth.reset_password(ctx, "ghost", "reset from the server")


@pytest.fixture
def clocked(workspace: Path) -> Iterator[tuple[AppContext, list[datetime]]]:
    now = [datetime(2026, 11, 23, 9, 0, tzinfo=UTC)]
    ctx = build_context(make_settings(workspace, session_idle_minutes=30, session_max_days=1),
                        clock=Clock(lambda: now[0]))  # fmt: skip
    yield ctx, now
    ctx.close()


def test_sessions_expire_when_idle_and_after_the_absolute_limit(
    clocked: tuple[AppContext, list[datetime]], stack: ExitStack
) -> None:
    ctx, now = clocked
    c = stack.enter_context(signed_client(ctx))
    now[0] += timedelta(minutes=29)
    assert c.get("/api/projects").status_code == 200
    now[0] += timedelta(minutes=31)
    assert c.get("/api/projects").status_code == 401  # idle too long
    c = stack.enter_context(signed_client(ctx))
    for _ in range(50):  # stays active, but the absolute limit still ends it
        now[0] += timedelta(minutes=29)
        if c.get("/api/projects").status_code == 401:
            break
    assert now[0] - datetime(2026, 11, 23, 10, 0, tzinfo=UTC) <= timedelta(days=1, minutes=30)
    assert c.get("/api/projects").status_code == 401


# ---------- headers, limits, server settings ----------


def test_security_headers_on_every_response(client: TestClient, anon: TestClient) -> None:
    for resp in (client.get("/api/projects"), anon.get("/api/projects"), anon.get("/healthz")):
        h = resp.headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in h["content-security-policy"] and h["referrer-policy"] == "no-referrer"
        assert "strict-transport-security" not in h  # plain http on loopback: no HSTS


def test_oversized_request_is_refused_before_it_is_read(client: TestClient) -> None:
    resp = client.post("/api/imports", content=b"x", headers={"Content-Length": str(500 * 1024 * 1024)})
    assert resp.status_code == 413 and resp.json()["code"] == "too_large"


def test_streamed_body_over_the_limit_is_cut_off(workspace: Path, stack: ExitStack) -> None:
    ctx = build_context(make_settings(workspace, max_upload_mb=1))
    try:
        c = stack.enter_context(signed_client(ctx))

        def chunks() -> Iterator[bytes]:
            for _ in range(5):
                yield b"a" * (1024 * 1024)

        resp = c.post("/api/projects", content=chunks(), headers={"Content-Type": "application/json"})
        assert resp.status_code == 413 and resp.json()["code"] == "too_large"
    finally:
        ctx.close()


def test_server_deployment_settings(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(workspace=tmp_path, deployment="server", host="0.0.0.0")  # noqa: S104 - needs a public origin
    with pytest.raises(ValidationError):
        Settings(workspace=tmp_path, deployment="server", host="0.0.0.0", public_origin="http://books.example.lan")  # noqa: S104
    with pytest.raises(ValidationError):
        Settings(workspace=tmp_path, deployment="server", public_origin="https://books.example.lan/studio")
    with pytest.raises(ValidationError):
        Settings(workspace=tmp_path, local_ai_hosts=["http://ollama:11434"])
    s = Settings(workspace=tmp_path, deployment="server", host="0.0.0.0", public_origin="https://Books.example.lan")  # noqa: S104
    assert s.cookie_secure and s.allowed_origins() == frozenset({"https://books.example.lan"})
    assert {"books.example.lan", "books.example.lan:443", "127.0.0.1:8765"} <= s.allowed_hosts()
    assert "http://127.0.0.1:5173" not in s.allowed_origins()


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[AppContext, TestClient]]:
    settings = make_settings(tmp_path / "ws", deployment="server", host="0.0.0.0",  # noqa: S104
                             public_origin="https://books.example.test")  # fmt: skip
    ctx = build_context(settings)
    with TestClient(create_app(settings, ctx=ctx), base_url="https://books.example.test") as c:
        yield ctx, c
    ctx.close()


def test_server_mode_uses_host_prefixed_secure_cookie_and_hsts(server: tuple[AppContext, TestClient]) -> None:
    ctx, c = server
    resp = c.post("/api/auth/setup", json={"username": OWNER, "password": PASSWORD, "setup_code": _setup_code(ctx)},
                  headers={"X-PBS-CSRF": "1", "Origin": "https://books.example.test"})  # fmt: skip
    assert resp.status_code == 200, resp.text
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-pbs_session=") and "Secure" in cookie
    assert resp.headers["strict-transport-security"].startswith("max-age=")
    c.headers["X-PBS-CSRF"] = resp.json()["csrf_token"]
    assert c.get("/api/projects").status_code == 200
    dev_origin = c.post("/api/projects", json={"title": "x", "project_type": "fiction"},
                        headers={"Origin": "http://127.0.0.1:5173"})  # fmt: skip
    assert dev_origin.status_code == 403
    assert c.get("/api/projects", headers={"Host": "other.example.test"}).status_code == 400


# ---------- serving the built UI ----------


def test_built_ui_is_served_without_exposing_other_files(
    workspace: Path, ctx: AppContext, tmp_path: Path, stack: ExitStack
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    c = stack.enter_context(TestClient(create_app(make_settings(workspace, ui_dist=dist), ctx=ctx), base_url=BASE_URL))
    assert c.get("/").text.startswith("<!doctype html>")
    assert c.get("/projects/123/write").text.startswith("<!doctype html>")  # client-side route
    js = c.get("/assets/app.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    for evil in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt", "/..%5csecret.txt"):
        resp = c.get(evil)
        assert "outside" not in resp.text, evil
    assert c.get("/api/nothing-here").status_code == 401  # API paths never fall through to the UI


# ---------- file endpoints ----------


def test_file_endpoints_refuse_path_tricks(client: TestClient) -> None:
    p = new_project(client)
    pid = p["id"]
    probes = [
        f"/api/projects/{pid}/narration/exports/..%2F..%2Fstudio.db",
        f"/api/projects/{pid}/narration/exports/....zip",
        f"/api/projects/{pid}/assets/..%2F..%2Fstudio.db",
        "/api/projects/..%2F..%2Fruntime/chapters",
        f"/api/projects/{pid}/publishing/publications/{ULID}/file",
    ]
    for path in probes:
        resp = client.get(path)
        assert resp.status_code in (400, 404, 422), (path, resp.status_code)
        assert b"SQLite format" not in resp.content


def test_uploads_check_type_by_content_not_name(client: TestClient) -> None:
    pid = new_project(client)["id"]
    fake = client.post(
        f"/api/projects/{pid}/recordings",
        files={"file": ("interview.mp3", b"<html><script>alert(1)</script></html>", "audio/mpeg")},
        data={"rights_confirmed": "true"},
    )
    assert fake.status_code == 422


def test_existing_content_survives_and_phase08_routes_work_when_signed_in(client: TestClient) -> None:
    p = new_project(client, title="Kept")
    ch = new_chapter(client, p["id"])
    assert save(client, p["id"], ch["id"], "Mara has grey eyes.\n", 0).status_code == 200
    assert client.post("/api/series", json={"title": "Tides"}).status_code == 201
    assert client.get(f"/api/projects/{p['id']}/editions").status_code == 200
    assert client.get("/api/media/status").status_code == 200


# ---------- secrets on a server ----------


def test_encrypted_key_store_keeps_no_plaintext_and_fails_closed(tmp_path: Path) -> None:
    from pbs_core.security.secrets import EncryptedFileStore, SecretStoreError, build_store

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    key = tmp_path / "master.key"
    key.write_text(base64.b64encode(b"k" * 32).decode(), encoding="ascii")
    store = build_store("auto", runtime, key)
    assert isinstance(store, EncryptedFileStore) and store.secure
    store.set("provider:x", "sk-test-CANARY0123456789")
    raw = (runtime / "secrets.enc.json").read_text(encoding="utf-8")
    assert "CANARY" not in raw and "sk-test" not in raw
    assert build_store("encrypted-file", runtime, key).get("provider:x") == "sk-test-CANARY0123456789"
    key.write_text(base64.b64encode(b"z" * 32).decode(), encoding="ascii")
    with pytest.raises(SecretStoreError, match="does not match"):
        build_store("encrypted-file", runtime, key)
    key.write_text("too short", encoding="ascii")
    with pytest.raises(SecretStoreError, match="32 random bytes"):
        build_store("encrypted-file", runtime, key)


def test_server_without_key_file_never_falls_back_to_a_desktop_keyring(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path / "ws", deployment="server", host="0.0.0.0",  # noqa: S104
                        public_origin="https://b.example.test", log_console=False, env="test")  # fmt: skip
    ctx = build_context(settings)
    try:
        assert ctx.secrets.name == "none" and not ctx.secrets.writable
    finally:
        ctx.close()


# ---------- private model hosts ----------


def test_configured_private_model_host_is_local_and_nothing_else_is(workspace: Path) -> None:
    from pbs_core.providers import egress

    permit = egress.EgressPermit("ollama", cloud_allowed=False)
    with pytest.raises(egress.EgressBlockedError):
        egress.check("http://ollama:11434/api/tags", permit)
    ctx = build_context(make_settings(workspace, local_ai_hosts=["ollama"]))
    try:
        egress.check("http://ollama:11434/api/tags", permit)  # allowed, and not counted as internet
        assert egress.provider_is_local("ollama", "http://ollama:11434")
        for other in ("http://10.0.0.5:11434", "http://ollama.evil.example:11434", "http://api.openai.com"):
            with pytest.raises(egress.EgressBlockedError):
                egress.check(other, permit)
    finally:
        egress.configure_local_hosts([])
        ctx.close()


# ---------- background tasks and the worker ----------


def test_publishing_build_runs_as_a_durable_task(client: TestClient, ctx: AppContext) -> None:
    from pbs_core.jobs.runner import JobRunner

    p = new_project(client, title="Queued")
    ch = new_chapter(client, p["id"])
    save(client, p["id"], ch["id"], "# One\n\nText.\n", 0)
    queued = client.post(f"/api/projects/{p['id']}/publishing/build-task", json={"formats": ["html"]})
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    tid = queued.json()["id"]
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "queued"
    runner = JobRunner(ctx, workers=1)
    assert runner.run_tasks_until_idle() == 1
    done = client.get(f"/api/tasks/{tid}").json()
    assert done["status"] == "succeeded" and done["result"]["publications"][0]["kind"] == "html"
    assert client.get(f"/api/projects/{p['id']}/publishing/publications").json()
    missing = client.post(f"/api/projects/{ULID}/publishing/build-task", json={"formats": ["html"]})
    assert missing.status_code == 404


def test_task_left_running_by_a_crash_is_retried_then_interrupted(ctx: AppContext) -> None:
    pid = ""
    with ctx.db.tx() as s:
        from pbs_core.storage.models import Project

        pid = s.scalars(__import__("sqlalchemy").select(Project.id)).first() or ""
    t = tasks.enqueue(ctx, "publishing.build", None, {"formats": ["html"]})
    assert tasks.claim(ctx, "crashed-worker") == t.id
    assert tasks.recover(ctx) == 1 and tasks.get(ctx, t.id).status == "queued"
    tasks.claim(ctx, "crashed-again")
    tasks.recover(ctx)
    final = tasks.get(ctx, t.id)
    assert final.status == "interrupted" and final.error_code == "interrupted" and not pid


def test_failed_task_keeps_the_error_for_the_browser(ctx: AppContext) -> None:
    t = tasks.enqueue(ctx, "publishing.build", None, {"formats": ["html"]})
    assert tasks.run_once(ctx)
    out = tasks.get(ctx, t.id)
    assert out.status == "failed" and out.error_code and out.error_message


def test_only_one_worker_per_workspace(ctx: AppContext) -> None:
    from pbs_core.storage.locks import LockHeldError, ProcessLock

    a = ProcessLock(ctx.workspace.runtime_dir / "worker.lock")
    b = ProcessLock(ctx.workspace.runtime_dir / "worker.lock")
    a.acquire()
    try:
        with pytest.raises(LockHeldError):
            b.acquire()
    finally:
        a.release()
    b.acquire()
    b.release()
