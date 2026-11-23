"""Ollama (local models) over its REST API with httpx2.

Facts used (docs.ollama.com/api, checked 2026-11-22):

* Default base ``http://localhost:11434``; no auth locally. PBS accepts only loopback Ollama
  servers: the egress gate has no allowlist entry for Ollama, so a remote URL is refused.
* ``GET /api/version`` -> ``{"version"}``; ``GET /api/tags`` -> ``{"models": [{"name", ...}]}``.
* ``POST /api/show {"model"}`` -> ``capabilities`` (string list, e.g. "completion", "thinking",
  "vision") and ``model_info`` with ``"<arch>.context_length"`` where arch is
  ``model_info["general.architecture"]``.
* ``POST /api/chat`` streams NDJSON (one JSON object per line). Text in ``message.content``; the
  last object has ``done: true``, ``done_reason``, ``prompt_eval_count`` (input tokens) and
  ``eval_count`` (output tokens). Options: ``num_predict`` (max output), ``temperature``.
* Errors mid-stream keep HTTP 200 and arrive as a line with an ``error`` key: every line is checked.
* Structured output: ``format`` = a JSON schema object (documented for local models).
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
    status_error,
)
from pbs_core.providers.egress import EgressBlockedError, EgressPermit, check, gated_client

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaAdapter:
    kind = "ollama"
    local = True

    def __init__(
        self, permit: EgressPermit, base_url: str = DEFAULT_BASE_URL, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self.permit = permit
        self.base_url = base_url.rstrip("/")
        check(self.base_url, permit)  # refuses non-loopback Ollama servers before anything is sent
        self._http = gated_client(permit, transport=transport, timeout=600.0)

    def _error(self, resp: httpx2.Response) -> ProviderError:
        try:
            msg = str(resp.json().get("error", ""))
        except Exception:
            msg = resp.text[:300]
        if resp.status_code == 404:
            return ProviderError(
                "not_found", f"Ollama does not have this model: {msg}. Pull it with `ollama pull`.", status=404
            )
        return status_error(resp.status_code, msg)

    def _call(self, fn: Any) -> Any:
        try:
            return fn()
        except (EgressBlockedError, ProviderError, Cancelled):
            raise
        except httpx2.TimeoutException as exc:
            raise ProviderError("timeout", "Ollama did not answer in time.") from exc
        except httpx2.HTTPError as exc:
            if isinstance(exc.__cause__, EgressBlockedError):
                raise exc.__cause__ from exc
            raise ProviderError(
                "connection", f"Could not reach Ollama at {self.base_url}. Is it running (`ollama serve`)?"
            ) from exc

    def health(self) -> Health:
        start = time.monotonic()

        def go() -> Health:
            resp = self._http.get(f"{self.base_url}/api/version", timeout=5.0)
            if resp.status_code != 200:
                raise self._error(resp)
            version = str(resp.json().get("version", "unknown"))
            return Health(
                True,
                f"Ollama {version} is running locally.",
                version=version,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        result: Health = self._call(go)
        return result

    def list_models(self) -> list[ModelDesc]:
        def go() -> list[ModelDesc]:
            resp = self._http.get(f"{self.base_url}/api/tags", timeout=10.0)
            if resp.status_code != 200:
                raise self._error(resp)
            out = []
            for m in resp.json().get("models", []):
                name = str(m.get("model") or m.get("name"))
                out.append(self._describe(name, m.get("details") or {}))
            return sorted(out, key=lambda d: d.name)

        result: list[ModelDesc] = self._call(go)
        return result

    def _describe(self, name: str, details: dict[str, Any]) -> ModelDesc:
        caps: dict[str, str] = {
            "chat": "unknown",
            "structured_output": "documented:true",
            "temperature": "documented:true",
        }
        ctx_tokens: int | None = None
        try:
            resp = self._http.post(f"{self.base_url}/api/show", json={"model": name}, timeout=10.0)
            if resp.status_code == 200:
                info = resp.json()
                reported = info.get("capabilities")
                if isinstance(reported, list):
                    caps["chat"] = "reported:true" if "completion" in reported else "reported:false"
                    for extra in ("thinking", "vision", "tools"):
                        caps[extra] = "reported:true" if extra in reported else "reported:false"
                mi = info.get("model_info") or {}
                arch = mi.get("general.architecture")
                if arch and isinstance(mi.get(f"{arch}.context_length"), int):
                    ctx_tokens = int(mi[f"{arch}.context_length"])
        except httpx2.HTTPError:
            pass
        label = " ".join(str(x) for x in (details.get("parameter_size"), details.get("quantization_level")) if x)
        return ModelDesc(
            name=name,
            display_name=f"{name} ({label})" if label else None,
            context_tokens=ctx_tokens,
            max_output_tokens=None,
            capabilities=caps,
        )

    def stream_chat(self, req: GenRequest, on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult:
        options: dict[str, Any] = {"num_predict": req.max_output_tokens}
        if req.temperature is not None:
            options["temperature"] = req.temperature
        body: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": "system", "content": req.system}]
            + [{"role": m.role, "content": m.content} for m in req.messages],
            "stream": True,
            "options": options,
        }
        if req.json_schema is not None:
            body["format"] = req.json_schema

        def go() -> GenResult:
            parts: list[str] = []
            final: dict[str, Any] = {}
            with self._http.stream("POST", f"{self.base_url}/api/chat", json=body, timeout=req.timeout_s) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise self._error(resp)
                for line in resp.iter_lines():
                    if should_cancel():
                        raise Cancelled()
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if "error" in obj:
                        raise ProviderError("server_error", f"Ollama reported an error: {str(obj['error'])[:300]}")
                    text = (obj.get("message") or {}).get("content")
                    if text:
                        parts.append(text)
                        on_delta(text)
                    if obj.get("done"):
                        final = obj
                        break
            if not final:
                raise ProviderError("connection", "Ollama closed the stream before finishing.")
            pin, pout = final.get("prompt_eval_count"), final.get("eval_count")
            return GenResult(
                "".join(parts),
                Usage(pin, pout, reported=pin is not None or pout is not None),
                final.get("done_reason"),
                final.get("model"),
            )

        result: GenResult = self._call(go)
        return result
