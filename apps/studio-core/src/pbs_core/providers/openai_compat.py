"""OpenAI, Groq and xAI (Grok) through the official `openai` Python SDK (Chat Completions).

Facts used (official docs, checked 2026-11-22; see docs/ADR/0004-ai-providers.md):

* OpenAI: base ``https://api.openai.com/v1``. Chat Completions "remains supported" (Responses is
  recommended for new projects). ``max_completion_tokens`` replaces the deprecated ``max_tokens``.
  Streaming usage needs ``stream_options={"include_usage": true}`` (a final chunk with empty
  ``choices``). Structured output: ``response_format={"type": "json_schema", "json_schema":
  {"name", "schema", "strict"}}``. ``GET /v1/models`` returns no capability information.
  429 with ``insufficient_quota`` is a billing problem and must not be retried.
* Groq: OpenAI-compatible at ``https://api.groq.com/openai/v1``. Structured outputs are NOT
  supported together with streaming, so structured requests are sent without streaming.
  ``stream_options.include_usage`` could not be verified, so it is not sent; usage is read only if
  the provider returns it. Models list includes ``context_window``.
* xAI: OpenAI-compatible at ``https://api.x.ai/v1`` (Chat Completions is offered as a legacy
  endpoint; Responses is recommended). Streaming usage via ``stream_options.include_usage``.
  Models list includes ``context_length``.

PBS uses Chat Completions for all three because it is the one interface they share; the switch to
the Responses API is tracked in the ADR. SDK retries are disabled: the job runner owns retries.
"""

from __future__ import annotations

import time
from typing import Any

import httpx2
import openai
from openai import DefaultHttpxClient

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

PROFILES: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "stream_usage": True,
        "stream_with_schema": True,
        "context_field": None,
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "stream_usage": False,
        "stream_with_schema": False,
        "context_field": "context_window",
    },
    "xai": {
        "label": "xAI",
        "base_url": "https://api.x.ai/v1",
        "stream_usage": True,
        "stream_with_schema": True,
        "context_field": "context_length",
    },
}
BILLING_CODES = frozenset({"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached"})


class OpenAICompatAdapter:
    local = False

    def __init__(
        self,
        kind: str,
        api_key: str | None,
        permit: EgressPermit,
        base_url: str | None = None,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        if kind not in PROFILES:
            raise ValueError(kind)
        if not api_key:
            raise ProviderError("auth", "No API key is stored for this provider. Add one in AI settings.")
        self.kind = kind
        self.profile = PROFILES[kind]
        self.permit = permit
        self.base_url = base_url or self.profile["base_url"]
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            max_retries=0,
            http_client=gated_client(permit, transport=transport, factory=DefaultHttpxClient),
        )

    @property
    def label(self) -> str:
        return str(self.profile["label"])

    def _guard(self) -> None:
        check(self.base_url, self.permit)

    def _map(self, exc: Exception) -> Exception:
        if isinstance(exc, EgressBlockedError):
            return exc
        cause = exc.__cause__ or exc.__context__
        if isinstance(cause, EgressBlockedError):
            return cause
        if isinstance(exc, openai.APITimeoutError):
            return ProviderError("timeout", f"The request to {self.label} timed out.")
        if isinstance(exc, openai.APIConnectionError):
            return ProviderError("connection", f"Could not connect to {self.label}.")
        if isinstance(exc, openai.APIStatusError):
            code = getattr(exc, "code", None)
            if exc.status_code == 429 and code in BILLING_CODES:
                return ProviderError(
                    "quota", f"{self.label} reports a billing or quota limit ({code}). Check your account.", status=429
                )
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
            return status_error(exc.status_code, str(exc.message), retry_after)
        return exc

    def health(self) -> Health:
        self._guard()
        start = time.monotonic()
        try:
            page = self._client.models.list()
            count = len(page.data)
        except Exception as exc:
            raise self._map(exc) from exc
        return Health(
            ok=True,
            message=f"Connected to {self.label}: {count} models available to this key.",
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    def list_models(self) -> list[ModelDesc]:
        self._guard()
        field = self.profile["context_field"]
        try:
            out = []
            for m in self._client.models.list():
                extra = m.model_extra or {}
                if extra.get("active") is False:
                    continue
                ctx_tokens = extra.get(field) if field else None
                out.append(
                    ModelDesc(
                        name=m.id,
                        display_name=None,
                        context_tokens=int(ctx_tokens) if isinstance(ctx_tokens, int) else None,
                        max_output_tokens=None,
                        # The models list does not report capabilities: they stay unknown until
                        # the author declares them in AI settings.
                        capabilities={"chat": "unknown", "structured_output": "unknown", "temperature": "unknown"},
                    )
                )
            return sorted(out, key=lambda d: d.name)
        except Exception as exc:
            raise self._map(exc) from exc

    def _params(self, req: GenRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = [{"role": "system", "content": req.system}]
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        params: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "max_completion_tokens": req.max_output_tokens,
            "timeout": req.timeout_s,
        }
        if req.temperature is not None:
            params["temperature"] = req.temperature
        if req.json_schema is not None:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "pbs_result", "schema": req.json_schema, "strict": self.kind != "groq"},
            }
        return params

    def stream_chat(self, req: GenRequest, on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult:
        self._guard()
        params = self._params(req)
        if req.json_schema is not None and not self.profile["stream_with_schema"]:
            return self._complete(params, on_delta, should_cancel)
        if self.profile["stream_usage"]:
            params["stream_options"] = {"include_usage": True}
        parts: list[str] = []
        usage: Any = None
        finish: str | None = None
        model: str | None = None
        try:
            stream = self._client.chat.completions.create(stream=True, **params)
            try:
                for chunk in stream:
                    if should_cancel():
                        raise Cancelled()
                    model = chunk.model or model
                    if getattr(chunk, "usage", None):
                        usage = chunk.usage
                    for choice in chunk.choices:
                        if choice.finish_reason:
                            finish = choice.finish_reason
                        delta = choice.delta
                        if getattr(delta, "refusal", None):
                            raise ProviderError(
                                "refused", "The model declined this request. Rephrase it or try another model."
                            )
                        if delta.content:
                            parts.append(delta.content)
                            on_delta(delta.content)
            finally:
                stream.close()
        except (Cancelled, EgressBlockedError, ProviderError):
            raise
        except Exception as exc:
            raise self._map(exc) from exc
        return GenResult("".join(parts), _usage(usage), finish, model)

    def _complete(self, params: dict[str, Any], on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult:
        if should_cancel():
            raise Cancelled()
        try:
            resp = self._client.chat.completions.create(**params)
        except Exception as exc:
            raise self._map(exc) from exc
        if should_cancel():
            raise Cancelled()
        choice = resp.choices[0] if resp.choices else None
        if choice is not None and getattr(choice.message, "refusal", None):
            raise ProviderError("refused", "The model declined this request. Rephrase it or try another model.")
        text = (choice.message.content or "") if choice else ""
        if text:
            on_delta(text)
        return GenResult(text, _usage(resp.usage), choice.finish_reason if choice else None, resp.model)


def _usage(u: Any) -> Usage:
    if u is None:
        return Usage(None, None, reported=False)
    return Usage(getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None), reported=True)
