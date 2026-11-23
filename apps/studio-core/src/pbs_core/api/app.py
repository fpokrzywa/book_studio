"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response

from pbs_core import __version__
from pbs_core.api import errors
from pbs_core.api.routes import api, health
from pbs_core.api.routes_advanced import router as advanced_router
from pbs_core.api.routes_ai import router as ai_router
from pbs_core.api.routes_auth import router as auth_router
from pbs_core.api.routes_knowledge import router as knowledge_router
from pbs_core.api.routes_planning import router as planning_router
from pbs_core.api.routes_publishing import router as publishing_router
from pbs_core.api.routes_series import router as series_router
from pbs_core.api.routes_writing import router as writing_router
from pbs_core.config import Settings
from pbs_core.context import AppContext, build_context
from pbs_core.security.guard import WebGuard
from pbs_core.storage.locks import ProcessLock
from pbs_core.storage.paths import UnsafePathError, safe_join

WORKER_LOCK = "worker.lock"
MB = 1024 * 1024


def start_runner(ctx: AppContext) -> tuple[object, ProcessLock]:
    """Take the worker lock and start the job and task runner (role "all" or "worker")."""
    from pbs_core.jobs.runner import JobRunner

    lock = ProcessLock(ctx.workspace.runtime_dir / WORKER_LOCK)
    lock.acquire()
    runner = JobRunner(ctx, workers=ctx.settings.ai_workers)
    ctx.jobs = runner
    runner.start()  # recovers jobs and tasks a previous process left running
    return runner, lock


def create_app(
    settings: Settings | None = None,
    *,
    ctx: AppContext | None = None,
    initialize: bool = True,
) -> FastAPI:
    """Build the app. `initialize=False` builds routes only (used to export the OpenAPI schema)."""
    settings = settings or Settings()
    if initialize and ctx is None:
        ctx = build_context(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        runner = lock = None
        if ctx is not None:
            from pbs_core.services import auth

            auth.ensure_setup_code(ctx)
        if ctx is not None and settings.runs_jobs and ctx.jobs is None:
            runner, lock = start_runner(ctx)
        try:
            yield
        finally:
            if runner is not None:
                runner.stop()  # type: ignore[attr-defined]
                ctx.jobs = None  # type: ignore[union-attr]
            if lock is not None:
                lock.release()
            if ctx is not None:
                ctx.close()

    app = FastAPI(
        title="Personal Book Studio Core",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.env != "prod" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.ctx = ctx
    errors.install(app)
    app.include_router(health)
    app.include_router(auth_router)
    app.include_router(api)
    app.include_router(ai_router)
    app.include_router(knowledge_router)
    app.include_router(planning_router)
    app.include_router(writing_router)
    app.include_router(publishing_router)
    app.include_router(series_router)
    app.include_router(advanced_router)
    if settings.ui_dist is not None:
        _serve_ui(app, settings.ui_dist)
    if ctx is not None:
        from pbs_core.services import auth

        context = ctx

        def body_limit(path: str) -> int:
            mb = settings.max_backup_mb if "/backups" in path else settings.max_upload_mb
            return (mb + 1) * MB  # multipart framing

        app.add_middleware(
            WebGuard,
            allowed_hosts=settings.allowed_hosts(),
            allowed_origins=settings.allowed_origins(),
            cookie_name=auth.cookie_name(context),
            authenticate=lambda token: auth.authenticate(context, token),
            body_limit=body_limit,
            hsts=settings.cookie_secure,
        )
    return app


def _serve_ui(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page UI from Core: one origin, no separate web server needed."""
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            return errors.problem(404, "not_found", "Not Found")
        if path:
            try:
                file = safe_join(root, *[p for p in path.split("/") if p])
            except UnsafePathError:
                return errors.problem(400, "unsafe_path", "The request referred to an unsafe file path.")
            if file.is_file():
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
                return FileResponse(file, headers={"Cache-Control": cache})
        if not index.is_file():
            return errors.problem(404, "not_found", "The studio's web interface has not been built.")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
