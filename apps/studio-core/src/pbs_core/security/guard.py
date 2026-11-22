"""ASGI middleware protecting the loopback API from other websites and local processes.

1. Host header must be an allowed loopback host:port (defeats DNS rebinding).
2. A present Origin header must be an allowed UI origin; cross-site fetch metadata is refused.
3. Every /api request must carry X-PBS-Token equal to the per-launch session token.

No CORS headers are ever emitted, so browsers cannot read responses cross-origin.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pbs_core.security.token import tokens_equal

Scope = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[dict[str, Any]], Any]
ASGIApp = Callable[[Scope, Receive, Send], Any]

EXEMPT_PATHS = frozenset({"/healthz"})


class LocalGuard:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: frozenset[str],
        allowed_origins: frozenset[str],
        token: Callable[[], str],
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if host not in self.allowed_hosts:
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
        if path not in EXEMPT_PATHS and not tokens_equal(headers.get("x-pbs-token"), self.token()):
            await _problem(send, 401, "missing_or_bad_token", "A valid session token is required.")
            return
        await self.app(scope, receive, send)


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
