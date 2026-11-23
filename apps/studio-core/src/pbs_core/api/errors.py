"""RFC 9457 problem+json responses."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pbs_core.domain.errors import DomainError
from pbs_core.storage.paths import UnsafePathError

log = structlog.get_logger(__name__)


def problem(status: int, code: str, title: str, detail: str | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"type": f"urn:pbs:problem:{code}", "title": title, "status": status, "code": code}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(UnsafePathError)
    async def _unsafe(_: Request, exc: UnsafePathError) -> JSONResponse:
        log.warning("unsafe_path_rejected", reason=str(exc))
        return problem(400, "unsafe_path", "The request referred to an unsafe file path.")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo submitted input back (it may be manuscript text).
        errors = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return problem(422, "validation_failed", "Some fields are invalid.", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return problem(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return problem(
            500,
            "internal_error",
            "Something went wrong in Personal Book Studio Core.",
            "The error was logged locally. No data was sent anywhere.",
        )
