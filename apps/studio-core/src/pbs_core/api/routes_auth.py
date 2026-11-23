"""Sign-in, sign-out, password change and background task status (Phase 09).

The web guard (security/guard.py) has already checked Host, Origin, the session cookie and the
CSRF header before any of these run.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from pbs_core.api.routes import ERRORS, Ctx
from pbs_core.contracts_auth import AuthStateOut, LoginIn, PasswordChangeIn, SessionsOut, SetupIn, TaskOut
from pbs_core.domain.errors import UnauthorizedError
from pbs_core.services import auth, tasks

router = APIRouter(prefix="/api", responses=ERRORS)


def _principal(request: Request) -> auth.Principal | None:
    p: Any = getattr(request.state, "principal", None)
    return p if isinstance(p, auth.Principal) else None


def require_principal(request: Request) -> auth.Principal:
    p = _principal(request)
    if p is None:
        raise UnauthorizedError("Sign in to continue.")
    return p


Me = Annotated[auth.Principal, Depends(require_principal)]


def _set_cookie(ctx: Ctx, response: Response, token: str) -> None:
    response.set_cookie(
        auth.cookie_name(ctx),
        token,
        max_age=ctx.settings.session_max_days * 86400,
        path="/",
        secure=ctx.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/auth/state", tags=["auth"])
def auth_state(ctx: Ctx, request: Request, response: Response) -> AuthStateOut:
    response.headers["Cache-Control"] = "no-store"
    return auth.state(ctx, _principal(request))


@router.post("/auth/setup", tags=["auth"])
def setup(ctx: Ctx, body: SetupIn, request: Request, response: Response) -> AuthStateOut:
    token, principal = auth.setup(
        ctx,
        body.username,
        body.password.get_secret_value(),
        body.setup_code.get_secret_value(),
        request.headers.get("user-agent", ""),
    )
    _set_cookie(ctx, response, token)
    return auth.state(ctx, principal)


@router.post("/auth/login", tags=["auth"])
def login(ctx: Ctx, body: LoginIn, request: Request, response: Response) -> AuthStateOut:
    token, principal = auth.login(
        ctx, body.username, body.password.get_secret_value(), _client(request), request.headers.get("user-agent", "")
    )
    _set_cookie(ctx, response, token)
    return auth.state(ctx, principal)


@router.post("/auth/logout", tags=["auth"])
def logout(ctx: Ctx, me: Me, response: Response) -> AuthStateOut:
    auth.logout(ctx, me)
    response.delete_cookie(auth.cookie_name(ctx), path="/", secure=ctx.settings.cookie_secure, httponly=True,
                           samesite="strict")  # fmt: skip
    return auth.state(ctx, None)


@router.post("/auth/password", tags=["auth"])
def change_password(ctx: Ctx, me: Me, body: PasswordChangeIn) -> SessionsOut:
    n = auth.change_password(ctx, me, body.current_password.get_secret_value(), body.new_password.get_secret_value())
    return SessionsOut(signed_out=n)


@router.post("/auth/sign-out-others", tags=["auth"])
def sign_out_others(ctx: Ctx, me: Me) -> SessionsOut:
    return SessionsOut(signed_out=auth.sign_out_others(ctx, me))


@router.get("/tasks/{task_id}", tags=["tasks"])
def get_task(ctx: Ctx, task_id: str) -> TaskOut:
    return tasks.get(ctx, task_id)
