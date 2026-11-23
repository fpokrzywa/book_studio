"""Provider-neutral types. Adapters translate these to each provider's documented API."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

Capability = str  # "reported:true" | "reported:false" | "declared:true" | "declared:false" | "unknown"


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class GenRequest:
    model: str
    system: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_output_tokens: int = 2048
    json_schema: dict[str, Any] | None = None  # native structured output when supported
    timeout_s: float = 180.0


@dataclass
class Usage:
    input_tokens: int | None
    output_tokens: int | None
    reported: bool  # True when the provider returned the counts


@dataclass
class GenResult:
    text: str
    usage: Usage
    finish_reason: str | None = None
    model: str | None = None


@dataclass
class ModelDesc:
    name: str
    display_name: str | None = None
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    capabilities: dict[str, Capability] = field(default_factory=dict)


@dataclass
class Health:
    ok: bool
    message: str
    version: str | None = None
    latency_ms: int | None = None


class ProviderError(Exception):
    """A provider call failed. `code` drives retry decisions and the message shown to the author."""

    RETRYABLE = frozenset({"rate_limited", "overloaded", "timeout", "connection", "server_error", "invalid_output"})

    def __init__(self, code: str, message: str, *, retry_after: float | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.code in self.RETRYABLE


class Cancelled(Exception):
    """The author cancelled the job while it was running."""


DeltaFn = Callable[[str], None]
CancelFn = Callable[[], bool]


class ProviderAdapter(Protocol):
    kind: str
    local: bool

    def health(self) -> Health: ...
    def list_models(self) -> list[ModelDesc]: ...
    def stream_chat(self, req: GenRequest, on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult: ...


def status_error(status: int, message: str, retry_after: float | None = None) -> ProviderError:
    """Map an HTTP status to a provider error code with an actionable message."""
    if status in (401, 403):
        return ProviderError("auth", "The provider rejected the API key. Check it in AI settings.", status=status)
    if status == 404:
        return ProviderError("not_found", "The model or endpoint was not found. Refresh the model list.", status=status)
    if status == 429:
        return ProviderError(
            "rate_limited", "The provider is rate-limiting requests.", retry_after=retry_after, status=status
        )
    if status in (408,):
        return ProviderError("timeout", "The provider timed out.", status=status)
    if status == 529 or status == 503:
        return ProviderError("overloaded", "The provider is overloaded.", retry_after=retry_after, status=status)
    if status >= 500:
        return ProviderError("server_error", f"The provider had an internal error ({status}).", status=status)
    return ProviderError("bad_request", f"The provider rejected the request ({status}): {message[:300]}", status=status)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating a ```json fence around it."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return json.loads(t)
