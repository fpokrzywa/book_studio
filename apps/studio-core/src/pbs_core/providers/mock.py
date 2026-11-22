"""Deterministic offline adapter for tests, demos and CI. It is not AI and says so in its output.

Control markers in the author's instruction (mock only) make failure paths testable:
``[[mock:rate_limit]]`` (retryable, then succeeds), ``[[mock:auth]]``, ``[[mock:slow]]`` (streams
slowly so cancel can be exercised), ``[[mock:bad_json]]``.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time

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
)
from pbs_core.providers.mock_knowledge import with_knowledge

MODELS = [
    ModelDesc(
        name="mock-writer",
        display_name="Built-in test model (not AI)",
        context_tokens=32_000,
        max_output_tokens=4_000,
        capabilities={"chat": "reported:true", "structured_output": "reported:true", "temperature": "reported:true"},
    )
]
_attempts: dict[str, int] = {}
_lock = threading.Lock()


class MockAdapter:
    kind = "mock"
    local = True

    def health(self) -> Health:
        return Health(ok=True, message="Built-in test model is available (offline, deterministic).", version="1")

    def list_models(self) -> list[ModelDesc]:
        return list(MODELS)

    def stream_chat(self, req: GenRequest, on_delta: DeltaFn, should_cancel: CancelFn) -> GenResult:
        prompt = req.system + "\n".join(m.content for m in req.messages)
        # The prompt envelope tag is random per request; drop it so output is deterministic.
        stable = re.sub(r"pbs-data-[0-9a-f]+", "pbs-data", prompt)
        key = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]
        if "[[mock:auth]]" in prompt:
            raise ProviderError("auth", "The provider rejected the API key. Check it in AI settings.", status=401)
        if "[[mock:rate_limit]]" in prompt:
            with _lock:
                _attempts[key] = _attempts.get(key, 0) + 1
                first = _attempts[key] == 1
            if first:
                raise ProviderError(
                    "rate_limited", "The provider is rate-limiting requests.", retry_after=0.05, status=429
                )
        if req.json_schema is not None:
            text = (
                "not json"
                if "[[mock:bad_json]]" in prompt
                else json.dumps(
                    {"ideas": [{"title": f"Idea {i}", "description": f"Test idea {i} ({key})."} for i in (1, 2, 3)]}
                )
            )
        else:
            instruction = _last_instruction(req)
            text = (
                f"[Test model output, not AI] This paragraph was produced by the built-in test model for: "
                f"{instruction[:120].rstrip('.')}. Reference {key}."
            )
            text = with_knowledge(text, prompt)
        delay = 0.1 if "[[mock:slow]]" in prompt else 0.0
        out: list[str] = []
        for word in re.split(r"(\s+)", text):
            if should_cancel():
                raise Cancelled()
            if delay:
                time.sleep(delay)
            out.append(word)
            on_delta(word)
        result = "".join(out)
        return GenResult(
            text=result,
            usage=Usage(input_tokens=len(prompt) // 4 + 1, output_tokens=len(result) // 4 + 1, reported=True),
            finish_reason="stop",
            model=req.model,
        )


def _last_instruction(req: GenRequest) -> str:
    text = req.messages[-1].content if req.messages else ""
    m = re.search(r"Instruction from the author:\s*(.+)", text)
    return (m.group(1) if m else text).strip().splitlines()[0] if (m or text) else ""
