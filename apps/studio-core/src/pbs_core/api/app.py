"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pbs_core import __version__
from pbs_core.api import errors
from pbs_core.api.routes import api, health
from pbs_core.api.routes_ai import router as ai_router
from pbs_core.api.routes_knowledge import router as knowledge_router
from pbs_core.config import Settings
from pbs_core.context import AppContext, build_context
from pbs_core.security.guard import LocalGuard


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
        runner = None
        if ctx is not None and settings.ai_runner and ctx.jobs is None:
            from pbs_core.jobs.runner import JobRunner

            runner = JobRunner(ctx, workers=settings.ai_workers)
            ctx.jobs = runner
            runner.start()  # recovers jobs a previous process left running
        try:
            yield
        finally:
            if runner is not None:
                runner.stop()
                ctx.jobs = None  # type: ignore[union-attr]
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
    app.include_router(api)
    app.include_router(ai_router)
    app.include_router(knowledge_router)
    if ctx is not None:
        token = ctx.token
        app.add_middleware(
            LocalGuard,
            allowed_hosts=settings.allowed_hosts(),
            allowed_origins=frozenset(settings.ui_origins),
            token=lambda: token,
        )
    return app
