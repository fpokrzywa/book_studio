"""Anthropic (Claude) via the official `anthropic` Python SDK.

Facts used (Claude API reference, checked 2026-11-22):
* Messages API, `client.messages.stream(...)`; text deltas via `stream.text_stream`; final usage on
  `get_final_message().usage.input_tokens / output_tokens`.
* Structured output: `output_config={"format": {"type": "json_schema", "schema": ...}}`
  (the old `output_format` parameter is deprecated).
* Models API: `client.models.list()` with `max_input_tokens`, `max_tokens`, and a `capabilities`
  tree (`capabilities["structured_outputs"]["supported"]`).
* Sampling parameters (`temperature`) are rejected by current API versions, so PBS never sends them.
* `stop_reason == "refusal"` means the model declined; it is reported, not retried.
* The SDK is built on httpx2; PBS passes its own gated `DefaultHttpxClient` and disables SDK
  retries (the job runner owns retries so cancellation and accounting stay consistent).
"""

from __future__ import annotations

import time
from typing import Any

import anthropic
import httpx2
from anthropic import DefaultHttpxClient

from pbs_core.providers.base import (
    CancelFn,
    Cancelled,
    DeltaFn,
    GenRequest,
    GenResult,
    Health,
    ModelDesc,
    ProviderError,
    Usage,
    parse_retry_after,
    status_error,
)
from pbs_core.providers.egress import EgressBlockedError, EgressPermit, check, gated_client

DEFAULT_BASE_URL = "https://api.anthropic.com"


def _leaf(caps: Any, *path: str) -> str:
    node = caps
    try:
        for p in path:
            node = node[p]
        return "reported:true" if bool(node["supported"]) else "reported:false"
    except (KeyError, TypeError):
        return "unknown"


class AnthropicAdapter:
    kind = "anthropic"
    local = False

    def __init__(
        self,
        api_key: str | None,
        permit: EgressPermit,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("auth", "No API key is stored for this provider. Add one in AI settings.")
        self.permit = permit
        self.base_url = base_url
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            http_client=gated_client(permit, transport=transport, factory=DefaultHttpxClient),
        )

    def _guard(self) -> None:
        check(self.base_url, self.permit)

    def _map(self, exc: Exception) -> Exception:
        if isinstance(exc, EgressBlockedError):
            return exc
        cause = exc.__cause__ or exc.__context__
        if isinstance(cause, EgressBlockedError):
            return cause
        if isinstance(exc, anthropic.APITimeoutError):
            return ProviderError("timeout", "The request to Anthropic timed out.")
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError("connection", "Could not connect to Anthropic.")
        if isinstance(exc, anthropic.APIStatusError):
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
            return status_error(exc.status_code, str(exc.message), retry_after)
        return exc

    def health(self) -> Health:
        self._guard()
        start = time.monotonic()
        try:
            page = self._client.models.list(limit=1)
            count = len(page.data)
        except Exception as exc:
            raise self._map(exc) from exc
        return Health(
            ok=True,
            message=f"Connected to Anthropic ({count} model listed in a 1-item probe).",
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    def list_models(self) -> list[ModelDesc]:
        self._guard()
        try:
            out = []
            for m in self._client.models.list():
                caps = getattr(m, "capabilities", None) or {}
                out.append(
                    ModelDesc(
                        name=m.id,
                        display_name=getattr(m, "display_name", None),
                        context_tokens=getattr(m, "max_input_tokens", None),
                        max_output_tokens=getattr(m, "max_tokens", None),
                        capabilities={
                            "chat": "reported:true",
                            "structured_output": _leaf(caps, "structured_outputs"),
                            "temperature": "reported:false",
                        },
                    )
                )
            return out
        except Exception as exc:
            raise self._map(exc) from exc

    def stream_chat(self, req: GenRequest, on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult:
        self._guard()
        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_output_tokens,
            "system": req.system,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        }
        if req.json_schema is not None:
            params["output_config"] = {"format": {"type": "json_schema", "schema": req.json_schema}}
        try:
            with self._client.with_options(timeout=req.timeout_s).messages.stream(**params) as stream:
                parts: list[str] = []
                for delta in stream.text_stream:
                    if should_cancel():
                        raise Cancelled()
                    parts.append(delta)
                    on_delta(delta)
                final = stream.get_final_message()
        except (Cancelled, EgressBlockedError):
            raise
        except Exception as exc:
            raise self._map(exc) from exc
        if final.stop_reason == "refusal":
            raise ProviderError("refused", "The model declined this request. Rephrase it or try another model.")
        usage = getattr(final, "usage", None)
        return GenResult(
            text="".join(parts),
            usage=Usage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                reported=usage is not None,
            ),
            finish_reason=str(final.stop_reason),
            model=final.model,
        )
