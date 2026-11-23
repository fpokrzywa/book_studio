"""ASGI middleware in front of every request (docs/SECURITY.md section 2).

1. Host header must be one Core answers to: its loopback address, or PBS_PUBLIC_ORIGIN on a
   server (defeats DNS rebinding and Host-header tricks).
2. A present Origin header must be the studio's own origin; cross-site fetch metadata is refused.
   No CORS headers are ever emitted, so other sites cannot read responses.
3. Deny by default: every /api request needs a valid sign-in session cookie, except the three
   sign-in endpoints in PUBLIC_API. Routes cannot forget to require it.
4. CSRF: every POST, PUT, PATCH and DELETE must carry X-PBS-CSRF equal to the session's token
   (sign-in endpoints: any value, which a cross-site form cannot add).
5. Request bodies larger than the upload limit are refused before they are read.
6. Security headers (CSP, nosniff, frame denial, referrer, HSTS on https) on every response.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

Scope = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[dict[str, Any]], Any]
ASGIApp = Callable[[Scope, Receive, Send], Any]

PUBLIC_API = frozenset({"/api/auth/state", "/api/auth/login", "/api/auth/setup"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


class BodyTooLargeError(HTTPException):
    """Raised from `receive` once a body passes the limit; FastAPI passes HTTPExceptions through."""

    def __init__(self) -> None:
        super().__init__(413, "The request is too large.")


class WebGuard:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: frozenset[str],
        allowed_origins: frozenset[str],
        cookie_name: str,
        authenticate: Callable[[str | None], Any],
        body_limit: Callable[[str], int],
        hsts: bool,
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins
        self.cookie_name = cookie_name
        self.authenticate = authenticate
        self.body_limit = body_limit
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = {"value": False}
        send = self._with_headers(send, started)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if headers.get("host", "").lower() not in self.allowed_hosts:
            await _problem(send, 400, "bad_host", "Request host is not allowed.")
            return
        origin = headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            await _problem(send, 403, "bad_origin", "Cross-origin requests are not allowed.")
            return
        if headers.get("sec-fetch-site") == "cross-site":
            await _problem(send, 403, "cross_site", "Cross-site requests are not allowed.")
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()
        limit = self.body_limit(path)
        length = headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            await _problem(send, 413, "too_large", "The request is too large.")
            return

        principal = None
        token = _cookie(headers.get("cookie", ""), self.cookie_name)
        if token is not None:
            principal = await run_in_threadpool(self.authenticate, token)
        scope.setdefault("state", {})["principal"] = principal

        if path.startswith("/api/") or path == "/api":
            csrf = headers.get("x-pbs-csrf")
            if path in PUBLIC_API:
                if method in UNSAFE_METHODS and not csrf:
                    await _problem(send, 403, "csrf", "This request is missing its anti-forgery header.")
                    return
            elif principal is None:
                await _problem(send, 401, "not_signed_in", "Sign in to continue.")
                return
            elif method in UNSAFE_METHODS and not (
                csrf and hmac.compare_digest(csrf.encode("utf-8", "ignore"), principal.csrf_token.encode())
            ):
                await _problem(send, 403, "csrf", "This request is missing its anti-forgery token. Reload the page.")
                return

        try:
            await self.app(scope, self._limited(receive, limit), send)
        except BodyTooLargeError:
            if not started["value"]:
                await _problem(send, 413, "too_large", "The request is too large.")

    def _limited(self, receive: Receive, limit: int) -> Receive:
        seen = 0

        async def wrapped() -> Any:
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLargeError
            return message

        return wrapped

    def _with_headers(self, send: Send, started: dict[str, bool]) -> Send:
        async def wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                started["value"] = True
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
                    (b"content-security-policy", CSP.encode()),
                ]
                if self.hsts:
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [(k, v) for k, v in extra if k not in present]
            await send(message)

        return wrapped


def _cookie(header: str, name: str) -> str | None:
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name and v:
            return v
    return None


async def _problem(send: Send, status: int, code: str, title: str) -> None:
    body = json.dumps({"type": f"urn:pbs:problem:{code}", "title": title, "status": status, "code": code}).encode(
        "utf-8"
    )
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
