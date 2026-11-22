"""Google Gemini API (API key, generativelanguage.googleapis.com) over REST with httpx2.

Facts used (ai.google.dev / aistudio.google.com docs, checked 2026-11-22):

* Base ``https://generativelanguage.googleapis.com/v1beta``, header ``x-goog-api-key``.
* ``generateContent`` is documented as legacy but "fully supported" (the Interactions API is the
  new recommended surface; PBS uses generateContent because its streaming and usage fields are
  documented in detail). Streaming: ``POST /models/{m}:streamGenerateContent?alt=sse``; each SSE
  ``data:`` chunk is a GenerateContentResponse; text at ``candidates[0].content.parts[].text``.
  No end marker: the stream ends when the connection closes. Usage in ``usageMetadata``
  (``promptTokenCount``, ``candidatesTokenCount``): PBS keeps the last one seen.
* ``GET /models`` returns ``inputTokenLimit``, ``outputTokenLimit`` and
  ``supportedGenerationMethods``; it does not report structured-output support, so that stays
  ``unknown`` unless the author declares it.
* Gemini 4 and Gemini 3.6+ ignore a custom ``temperature`` and may reject it in future: PBS sends
  it only when the author explicitly sets one.
* Errors: ``{"error": {"code", "message", "status"}}``; 429 ``RESOURCE_EXHAUSTED``; 402 is a
  spend limit and is not retried. ``Retry-After`` is not documented, so it is read only if sent.
* Native structured output (``responseMimeType`` + ``responseJsonSchema``, as the official SDKs
  name them) is used only when the author declared the capability for the model.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx2

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

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAdapter:
    kind = "gemini"
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
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._http = gated_client(permit, transport=transport)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._key, "content-type": "application/json"}

    def _error(self, resp: httpx2.Response) -> ProviderError:
        try:
            body = resp.json().get("error", {})
            msg = str(body.get("message", ""))
        except Exception:
            msg = resp.text[:300]
        if resp.status_code == 402:
            return ProviderError(
                "quota", "Google reports a spend limit for this project. Check your account.", status=402
            )
        return status_error(resp.status_code, msg, parse_retry_after(resp.headers.get("retry-after")))

    def _call(self, fn: Any) -> Any:
        try:
            return fn()
        except (EgressBlockedError, ProviderError, Cancelled):
            raise
        except httpx2.TimeoutException as exc:
            raise ProviderError("timeout", "The request to Google Gemini timed out.") from exc
        except httpx2.HTTPError as exc:
            if isinstance(exc.__cause__, EgressBlockedError):
                raise exc.__cause__ from exc
            raise ProviderError("connection", "Could not connect to Google Gemini.") from exc

    def health(self) -> Health:
        check(self.base_url, self.permit)
        start = time.monotonic()

        def go() -> Health:
            resp = self._http.get(f"{self.base_url}/models", headers=self._headers(), params={"pageSize": 1})
            if resp.status_code != 200:
                raise self._error(resp)
            return Health(True, "Connected to Google Gemini.", latency_ms=int((time.monotonic() - start) * 1000))

        result: Health = self._call(go)
        return result

    def list_models(self) -> list[ModelDesc]:
        check(self.base_url, self.permit)

        def go() -> list[ModelDesc]:
            out: list[ModelDesc] = []
            token: str | None = None
            for _ in range(20):  # pagination guard
                params: dict[str, Any] = {"pageSize": 100}
                if token:
                    params["pageToken"] = token
                resp = self._http.get(f"{self.base_url}/models", headers=self._headers(), params=params)
                if resp.status_code != 200:
                    raise self._error(resp)
                data = resp.json()
                for m in data.get("models", []):
                    methods = m.get("supportedGenerationMethods") or []
                    if "generateContent" not in methods:
                        continue
                    out.append(
                        ModelDesc(
                            name=str(m.get("name", "")).removeprefix("models/"),
                            display_name=m.get("displayName"),
                            context_tokens=m.get("inputTokenLimit"),
                            max_output_tokens=m.get("outputTokenLimit"),
                            capabilities={
                                "chat": "reported:true",
                                "structured_output": "unknown",
                                "temperature": "unknown",
                            },
                        )
                    )
                token = data.get("nextPageToken")
                if not token:
                    break
            return sorted(out, key=lambda d: d.name)

        result: list[ModelDesc] = self._call(go)
        return result

    def stream_chat(self, req: GenRequest, on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult:
        check(self.base_url, self.permit)
        gen_config: dict[str, Any] = {"maxOutputTokens": req.max_output_tokens}
        if req.temperature is not None:
            gen_config["temperature"] = req.temperature
        if req.json_schema is not None:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseJsonSchema"] = req.json_schema
        body = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in req.messages
            ],
            "system_instruction": {"parts": [{"text": req.system}]},
            "generationConfig": gen_config,
        }
        url = f"{self.base_url}/models/{req.model}:streamGenerateContent"

        def go() -> GenResult:
            parts: list[str] = []
            usage: dict[str, Any] | None = None
            finish: str | None = None
            model: str | None = None
            with self._http.stream(
                "POST", url, headers=self._headers(), params={"alt": "sse"}, json=body, timeout=req.timeout_s
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise self._error(resp)
                for line in resp.iter_lines():
                    if should_cancel():
                        raise Cancelled()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    chunk = json.loads(payload)
                    if "error" in chunk:
                        err = chunk["error"]
                        raise status_error(int(err.get("code") or 500), str(err.get("message", "")))
                    usage = chunk.get("usageMetadata") or usage
                    model = chunk.get("modelVersion") or model
                    feedback = chunk.get("promptFeedback") or {}
                    if feedback.get("blockReason"):
                        raise ProviderError("refused", f"Gemini blocked the request ({feedback['blockReason']}).")
                    for cand in chunk.get("candidates") or []:
                        finish = cand.get("finishReason") or finish
                        for part in (cand.get("content") or {}).get("parts") or []:
                            if part.get("thought"):
                                continue
                            text = part.get("text")
                            if text:
                                parts.append(text)
                                on_delta(text)
            if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII") and not parts:
                raise ProviderError("refused", f"Gemini stopped for safety reasons ({finish}).")
            return GenResult(
                "".join(parts),
                Usage(
                    usage.get("promptTokenCount") if usage else None,
                    usage.get("candidatesTokenCount") if usage else None,
                    reported=usage is not None,
                ),
                finish,
                model,
            )

        result: GenResult = self._call(go)
        return result
