"""The egress gate: the only way any code in Personal Book Studio reaches the network.

Rules (docs/SECURITY.md section 4):
1. Loopback addresses (127.0.0.0/8, ::1, localhost) are always allowed: local models.
2. Anything else needs privacy mode "cloud_allowed" AND, for the project being worked on,
   the author's consent for that provider AND a host on that provider's allowlist.
3. Violations raise EgressBlocked BEFORE a connection is opened. Nothing falls back.

Every HTTP client used by an adapter is created here with a request hook that re-checks each
request (including redirects, which are disabled anyway).
"""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx2

CLOUD_HOSTS: dict[str, frozenset[str]] = {
    "openai": frozenset({"api.openai.com"}),
    "anthropic": frozenset({"api.anthropic.com"}),
    "gemini": frozenset({"generativelanguage.googleapis.com"}),
    "groq": frozenset({"api.groq.com"}),
    "xai": frozenset({"api.x.ai"}),
}
LOCAL_KINDS = frozenset({"mock", "ollama"})


class EgressBlockedError(RuntimeError):
    """Raised instead of opening a connection the privacy rules do not allow."""


def is_loopback_host(host: str) -> bool:
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class EgressPermit:
    """What a single job (or settings action) may contact."""

    provider_kind: str
    cloud_allowed: bool  # privacy mode is cloud_allowed AND (for jobs) the project consented
    reason_if_blocked: str = ""


def check(url: httpx2.URL | str, permit: EgressPermit, *, record: bool = False) -> None:
    """Raise unless `url` may be contacted. `record=True` (the per-request hook) counts it."""
    parsed = httpx2.URL(str(url))
    if parsed.scheme not in ("http", "https"):
        raise EgressBlockedError(f"Only http(s) addresses are allowed (got {parsed.scheme}).")
    host = parsed.host or ""
    if is_loopback_host(host):
        return
    if not permit.cloud_allowed:
        raise EgressBlockedError(
            permit.reason_if_blocked
            or "Local-only mode is on, so nothing may be sent to the internet. Nothing was sent."
        )
    allowed = CLOUD_HOSTS.get(permit.provider_kind, frozenset())
    if host not in allowed:
        raise EgressBlockedError(f"{host} is not an approved address for {permit.provider_kind}. Nothing was sent.")
    if parsed.scheme != "https":
        raise EgressBlockedError("Cloud providers must be contacted over https.")
    if record:
        _count_external(host)


def normalize_loopback_url(url: str) -> str:
    """Return a clean http(s) URL on this computer, or raise ValueError (used for Ollama's address)."""
    try:
        parsed = httpx2.URL(url)
    except Exception as exc:
        raise ValueError("not a URL") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError("not an http(s) URL")
    if not is_loopback_host(parsed.host):
        raise ValueError("not on this computer")
    return str(parsed).rstrip("/")


def provider_is_local(kind: str, base_url: str) -> bool:
    if kind == "mock":
        return True
    try:
        return is_loopback_host(httpx2.URL(base_url).host or "")
    except Exception:
        return False


# --- audit counter: every request that passed the gate to a non-loopback host ---
_external_lock = threading.Lock()
_external: dict[str, int] = {}


def _count_external(host: str) -> None:
    with _external_lock:
        _external[host] = _external.get(host, 0) + 1


def external_requests() -> dict[str, int]:
    """Requests sent to the internet since Core started, by host. Empty in local-only mode."""
    with _external_lock:
        return dict(_external)


# --- live indicator of outbound cloud traffic (shown in the privacy badge) ---
_active_lock = threading.Lock()
_active: dict[str, int] = {}


@contextmanager
def cloud_activity(kind: str, local: bool) -> Iterator[None]:
    if local:
        yield
        return
    with _active_lock:
        _active[kind] = _active.get(kind, 0) + 1
    try:
        yield
    finally:
        with _active_lock:
            _active[kind] -= 1
            if _active[kind] <= 0:
                del _active[kind]


def active_cloud_calls() -> dict[str, int]:
    with _active_lock:
        return dict(_active)


def gated_client(
    permit: EgressPermit,
    *,
    timeout: float = 120.0,
    transport: httpx2.BaseTransport | None = None,
    factory: Callable[..., httpx2.Client] | None = None,
) -> httpx2.Client:
    """An httpx2 client whose every request is checked by the gate."""

    def hook(request: httpx2.Request) -> None:
        check(request.url, permit, record=True)

    kwargs: dict[str, Any] = {
        "event_hooks": {"request": [hook]},
        "timeout": httpx2.Timeout(timeout, connect=10.0),
        "follow_redirects": False,
        "trust_env": False,  # never route through a proxy from the environment
    }
    if transport is not None:
        kwargs["transport"] = transport
    return (factory or httpx2.Client)(**kwargs)
