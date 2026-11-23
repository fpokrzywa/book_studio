"""Provider adapters against recorded wire formats (httpx2.MockTransport), the egress gate, and secrets."""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from pbs_core.context import AppContext
from pbs_core.jobs.runner import JobRunner
from pbs_core.providers import egress
from pbs_core.providers.anthropic_adapter import AnthropicAdapter
from pbs_core.providers.base import ChatMessage, GenRequest, ProviderError
from pbs_core.providers.egress import EgressBlockedError, EgressPermit, check
from pbs_core.providers.gemini import GeminiAdapter
from pbs_core.providers.ollama import OllamaAdapter
from pbs_core.providers.openai_compat import OpenAICompatAdapter
from tests.conftest import new_chapter, new_project, save

CLOUD = EgressPermit("openai", cloud_allowed=True)
CANARY = "sk-canary-7f3a9b2c4d5e6f708192"


def req(schema: dict[str, Any] | None = None) -> GenRequest:
    return GenRequest(
        model="m", system="sys", messages=[ChatMessage("user", "hi")], max_output_tokens=50, json_schema=schema
    )


def no_cancel() -> bool:
    return False


def sse(events: list[tuple[str | None, dict[str, Any] | str]]) -> bytes:
    out = []
    for name, data in events:
        if name:
            out.append(f"event: {name}")
        out.append("data: " + (data if isinstance(data, str) else json.dumps(data)))
        out.append("")
    return ("\n".join(out) + "\n").encode()


# ---------- egress gate ----------


@pytest.mark.parametrize(
    ("url", "permit", "ok"),
    [
        ("http://127.0.0.1:11434/api/chat", EgressPermit("ollama", False), True),
        ("http://localhost:11434", EgressPermit("ollama", False), True),
        ("http://[::1]:1/x", EgressPermit("ollama", False), True),
        ("https://api.openai.com/v1/models", EgressPermit("openai", False), False),
        ("https://api.openai.com/v1/models", EgressPermit("openai", True), True),
        ("https://evil.example.com/v1", EgressPermit("openai", True), False),
        ("https://api.anthropic.com/v1", EgressPermit("openai", True), False),  # wrong provider's host
        ("http://api.openai.com/v1", EgressPermit("openai", True), False),  # plain http to cloud
        ("file:///etc/passwd", EgressPermit("openai", True), False),
        ("http://10.0.0.5:11434", EgressPermit("ollama", True), False),  # LAN Ollama is not local
    ],
)
def test_egress_gate(url: str, permit: EgressPermit, ok: bool) -> None:
    if ok:
        check(url, permit)
    else:
        with pytest.raises(EgressBlockedError):
            check(url, permit)


def test_gated_client_blocks_before_sending() -> None:
    sent: list[httpx2.Request] = []
    client = egress.gated_client(
        EgressPermit("openai", False), transport=httpx2.MockTransport(lambda r: sent.append(r) or httpx2.Response(200))
    )
    with pytest.raises(EgressBlockedError):
        client.get("https://api.openai.com/v1/models")
    assert sent == []


# ---------- OpenAI-compatible (OpenAI, Groq, xAI) ----------


def _chat_stream(body: dict[str, Any]) -> bytes:
    chunks = [
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-x",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hel"}, "finish_reason": None}],
        },
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-x",
            "choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}],
        },
    ]
    if body.get("stream_options", {}).get("include_usage"):
        chunks.append(
            {
                "id": "c",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-x",
                "choices": [],
                "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
            }
        )
    return sse([(None, c) for c in chunks] + [(None, "[DONE]")])


def test_openai_stream_request_shape_and_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(r: httpx2.Request) -> httpx2.Response:
        seen["url"], seen["auth"], seen["body"] = str(r.url), r.headers["authorization"], json.loads(r.content)
        return httpx2.Response(200, content=_chat_stream(seen["body"]), headers={"content-type": "text/event-stream"})

    a = OpenAICompatAdapter("openai", CANARY, CLOUD, transport=httpx2.MockTransport(handler))
    deltas: list[str] = []
    out = a.stream_chat(req(), deltas.append, no_cancel)
    assert out.text == "Hello" and deltas == ["Hel", "lo"]
    assert out.usage.input_tokens == 11 and out.usage.output_tokens == 2 and out.usage.reported
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == f"Bearer {CANARY}"
    body = seen["body"]
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body and "temperature" not in body
    assert body["messages"][0] == {"role": "system", "content": "sys"} and body["stream_options"] == {
        "include_usage": True
    }


def test_openai_structured_output_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(r: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(r.content)
        return httpx2.Response(200, content=_chat_stream(seen["body"]), headers={"content-type": "text/event-stream"})

    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    OpenAICompatAdapter("openai", CANARY, CLOUD, transport=httpx2.MockTransport(handler)).stream_chat(
        req(schema), lambda _: None, no_cancel
    )
    rf = seen["body"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"] == schema and rf["json_schema"]["strict"] is True


def test_groq_structured_output_does_not_stream() -> None:
    seen: dict[str, Any] = {}

    def handler(r: httpx2.Request) -> httpx2.Response:
        seen["url"], seen["body"] = str(r.url), json.loads(r.content)
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "llama",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": '{"ideas": []}'}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )

    a = OpenAICompatAdapter("groq", CANARY, EgressPermit("groq", True), transport=httpx2.MockTransport(handler))
    out = a.stream_chat(req({"type": "object"}), lambda _: None, no_cancel)
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert "stream" not in seen["body"] or seen["body"]["stream"] is False
    assert out.usage.output_tokens == 3


def test_openai_errors_map_to_actionable_codes() -> None:
    def quota(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            json={
                "error": {
                    "message": "You exceeded your quota",
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                }
            },
        )

    def limited(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            headers={"retry-after": "2"},
            json={"error": {"message": "slow down", "type": "rate_limit_error", "code": None}},
        )

    def bad_key(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401, json={"error": {"message": "bad key", "type": "invalid_request_error", "code": "invalid_api_key"}}
        )

    for handler, code, retryable in (
        (quota, "quota", False),
        (limited, "rate_limited", True),
        (bad_key, "auth", False),
    ):
        a = OpenAICompatAdapter("openai", CANARY, CLOUD, transport=httpx2.MockTransport(handler))
        with pytest.raises(ProviderError) as ei:
            a.stream_chat(req(), lambda _: None, no_cancel)
        assert ei.value.code == code and ei.value.retryable is retryable
        assert CANARY not in str(ei.value)
    with pytest.raises(ProviderError) as ei:
        OpenAICompatAdapter("openai", CANARY, CLOUD, transport=httpx2.MockTransport(limited)).stream_chat(
            req(), lambda _: None, no_cancel
        )
    assert ei.value.retry_after == 2.0


def test_xai_models_report_context_length() -> None:
    def handler(r: httpx2.Request) -> httpx2.Response:
        assert str(r.url) == "https://api.x.ai/v1/models"
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "grok-4.7", "object": "model", "created": 1, "owned_by": "xai", "context_length": 256000}
                ],
            },
        )

    models = OpenAICompatAdapter(
        "xai", CANARY, EgressPermit("xai", True), transport=httpx2.MockTransport(handler)
    ).list_models()
    assert models[0].name == "grok-4.7" and models[0].context_tokens == 256000
    assert models[0].capabilities["structured_output"] == "unknown"  # not reported: never assumed


def test_cloud_adapter_in_local_mode_sends_nothing() -> None:
    sent: list[Any] = []
    a = OpenAICompatAdapter(
        "openai",
        CANARY,
        EgressPermit("openai", False),
        transport=httpx2.MockTransport(lambda r: sent.append(r) or httpx2.Response(500)),
    )
    with pytest.raises(EgressBlockedError):
        a.stream_chat(req(), lambda _: None, no_cancel)
    assert sent == []


# ---------- Anthropic ----------


def test_anthropic_stream_and_no_temperature() -> None:
    seen: dict[str, Any] = {}
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "claude-opus-5-5",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 25, "output_tokens": 1},
                },
            },
        ),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Quiet "}},
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "night."}},
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 7},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]

    def handler(r: httpx2.Request) -> httpx2.Response:
        # The SDK chooses the auth header (x-api-key or Bearer, depending on its version).
        key = r.headers.get("x-api-key") or r.headers.get("authorization", "").removeprefix("Bearer ")
        seen["url"], seen["key"], seen["body"] = str(r.url), key, json.loads(r.content)
        return httpx2.Response(200, content=sse(events), headers={"content-type": "text/event-stream"})

    a = AnthropicAdapter(CANARY, EgressPermit("anthropic", True), transport=httpx2.MockTransport(handler))
    r = req({"type": "object"})
    r.temperature = 0.7
    out = a.stream_chat(r, lambda _: None, no_cancel)
    assert out.text == "Quiet night." and out.usage.input_tokens == 25 and out.usage.output_tokens == 7
    assert seen["url"] == "https://api.anthropic.com/v1/messages" and seen["key"] == CANARY
    assert "temperature" not in seen["body"] and seen["body"]["system"] == "sys"
    assert seen["body"]["output_config"]["format"]["type"] == "json_schema"


def test_anthropic_refusal_is_reported() -> None:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "m",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "c",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 0},
                },
            },
        ),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "refusal", "stop_sequence": None},
                "usage": {"output_tokens": 0},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    a = AnthropicAdapter(
        CANARY,
        EgressPermit("anthropic", True),
        transport=httpx2.MockTransport(
            lambda r: httpx2.Response(200, content=sse(events), headers={"content-type": "text/event-stream"})
        ),
    )
    with pytest.raises(ProviderError) as ei:
        a.stream_chat(req(), lambda _: None, no_cancel)
    assert ei.value.code == "refused" and not ei.value.retryable


# ---------- Gemini ----------


def test_gemini_stream_shape_and_usage() -> None:
    seen: dict[str, Any] = {}
    chunks = [
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hi "}]}}], "responseId": "r"},
        {
            "candidates": [{"content": {"role": "model", "parts": [{"text": "there"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2, "totalTokenCount": 11},
            "modelVersion": "gemini-x",
        },
    ]

    def handler(r: httpx2.Request) -> httpx2.Response:
        seen["url"], seen["key"], seen["body"] = str(r.url), r.headers.get("x-goog-api-key"), json.loads(r.content)
        return httpx2.Response(
            200, content=sse([(None, c) for c in chunks]), headers={"content-type": "text/event-stream"}
        )

    a = GeminiAdapter(CANARY, EgressPermit("gemini", True), transport=httpx2.MockTransport(handler))
    out = a.stream_chat(req(), lambda _: None, no_cancel)
    assert out.text == "Hi there" and out.usage.input_tokens == 9 and out.usage.output_tokens == 2
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/m:streamGenerateContent?alt=sse"
    assert seen["key"] == CANARY and CANARY not in seen["url"]  # key in a header, never in the URL
    assert seen["body"]["system_instruction"] == {"parts": [{"text": "sys"}]}
    assert seen["body"]["generationConfig"] == {"maxOutputTokens": 50}  # no temperature unless set


def test_gemini_models_strip_prefix_and_filter_methods() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-x",
                        "displayName": "Gemini X",
                        "inputTokenLimit": 1000,
                        "outputTokenLimit": 100,
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]},
                ]
            },
        )

    models = GeminiAdapter(CANARY, EgressPermit("gemini", True), transport=httpx2.MockTransport(handler)).list_models()
    assert [m.name for m in models] == ["gemini-x"] and models[0].context_tokens == 1000


# ---------- Ollama ----------


def _ollama(r: httpx2.Request) -> httpx2.Response:
    path = r.url.path
    if path == "/api/version":
        return httpx2.Response(200, json={"version": "0.12.6"})
    if path == "/api/tags":
        return httpx2.Response(
            200,
            json={
                "models": [
                    {
                        "name": "gemma4:4b",
                        "model": "gemma4:4b",
                        "details": {"parameter_size": "4B", "quantization_level": "Q4_K_M"},
                    }
                ]
            },
        )
    if path == "/api/show":
        return httpx2.Response(
            200,
            json={
                "capabilities": ["completion", "vision"],
                "model_info": {"general.architecture": "gemma4", "gemma4.context_length": 131072},
            },
        )
    if path == "/api/chat":
        body = json.loads(r.content)
        if body["model"] == "broken":
            lines = [{"message": {"content": "par"}, "done": False}, {"error": "model crashed"}]
        else:
            lines = [
                {"message": {"role": "assistant", "content": "Lo"}, "done": False},
                {"message": {"role": "assistant", "content": "cal"}, "done": False},
                {
                    "model": body["model"],
                    "message": {"content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 12,
                    "eval_count": 4,
                },
            ]
        return httpx2.Response(
            200,
            content="\n".join(json.dumps(x) for x in lines).encode(),
            headers={"content-type": "application/x-ndjson"},
        )
    return httpx2.Response(404, json={"error": "nope"})


def test_ollama_health_models_and_stream() -> None:
    a = OllamaAdapter(EgressPermit("ollama", False), transport=httpx2.MockTransport(_ollama))
    assert a.health().version == "0.12.6"
    m = a.list_models()[0]
    assert m.name == "gemma4:4b" and m.context_tokens == 131072 and m.capabilities["chat"] == "reported:true"
    out = a.stream_chat(req(), lambda _: None, no_cancel)
    assert out.text == "Local" and out.usage.input_tokens == 12 and out.usage.output_tokens == 4


def test_ollama_mid_stream_error_is_caught() -> None:
    a = OllamaAdapter(EgressPermit("ollama", False), transport=httpx2.MockTransport(_ollama))
    r = req()
    r.model = "broken"
    with pytest.raises(ProviderError) as ei:
        a.stream_chat(r, lambda _: None, no_cancel)
    assert "model crashed" in ei.value.message


def test_ollama_remote_server_refused() -> None:
    with pytest.raises(EgressBlockedError):
        OllamaAdapter(EgressPermit("ollama", True), base_url="http://192.168.1.20:11434")


def test_ollama_remote_url_rejected_in_settings(client: TestClient) -> None:
    r = client.post("/api/ai/providers", json={"kind": "ollama", "base_url": "http://192.168.1.20:11434"})
    assert r.status_code == 422


# ---------- privacy mode, consent and the full cloud path (mocked wire) ----------


def _cloud_setup(client: TestClient) -> tuple[str, str, str]:
    prov = client.post("/api/ai/providers", json={"kind": "openai"}).json()
    assert client.put(f"/api/ai/providers/{prov['id']}/key", json={"api_key": CANARY}).status_code == 200
    p = new_project(client)
    c = new_chapter(client, p["id"])
    save(client, p["id"], c["id"], "Text.\n", 0)
    return prov["id"], p["id"], c["id"]


def _ask(client: TestClient, pid: str, cid: str, prov: str) -> Any:
    return client.post(
        f"/api/projects/{pid}/ai/jobs",
        json={
            "chapter_id": cid,
            "task": "draft",
            "base_revision_no": 1,
            "provider_id": prov,
            "model_name": "gpt-x",
            "client_request_id": uuid.uuid4().hex,
        },
    )


def test_local_only_mode_makes_zero_external_calls(
    client: TestClient, ctx: AppContext, network_guard: list[Any]
) -> None:
    sent: list[Any] = []
    ctx.http_transport = httpx2.MockTransport(lambda r: sent.append(r) or httpx2.Response(500))
    prov, pid, cid = _cloud_setup(client)
    before = egress.external_requests()

    health = client.post(f"/api/ai/providers/{prov}/test").json()
    assert health["ok"] is False and health["code"] == "egress_blocked"
    assert client.post(f"/api/ai/providers/{prov}/models/refresh").status_code == 409
    r = _ask(client, pid, cid, prov)
    assert r.status_code == 409 and r.json()["code"] == "cloud_blocked"
    est = client.post(
        f"/api/projects/{pid}/ai/estimate",
        json={
            "chapter_id": cid,
            "task": "draft",
            "base_revision_no": 1,
            "provider_id": prov,
            "model_name": "gpt-x",
            "client_request_id": uuid.uuid4().hex,
        },
    ).json()
    assert "Local-only" in est["blocked_reason"]

    assert sent == [] and egress.external_requests() == before and network_guard == []


def test_cloud_needs_confirmation_and_project_consent(client: TestClient, ctx: AppContext) -> None:
    calls: list[str] = []

    def handler(r: httpx2.Request) -> httpx2.Response:
        calls.append(str(r.url))
        return httpx2.Response(
            200, content=_chat_stream(json.loads(r.content)), headers={"content-type": "text/event-stream"}
        )

    ctx.http_transport = httpx2.MockTransport(handler)
    prov, pid, cid = _cloud_setup(client)
    assert client.put("/api/ai/privacy", json={"mode": "cloud_allowed"}).status_code == 422  # needs confirm
    assert client.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True}).status_code == 200

    r = _ask(client, pid, cid, prov)
    assert r.status_code == 409 and "not been allowed" in r.json()["title"]
    assert client.put(f"/api/projects/{pid}/ai/consent/{prov}").status_code == 200
    j = _ask(client, pid, cid, prov)
    assert j.status_code == 202
    runner = JobRunner(ctx)
    runner.run_until_idle()
    job = client.get(f"/api/ai/jobs/{j.json()['id']}").json()
    assert job["status"] == "succeeded" and calls == ["https://api.openai.com/v1/chat/completions"]

    usage = client.get("/api/ai/usage").json()
    assert usage["rows"][0]["input_tokens"] == 11 and usage["rows"][0]["reported_by_provider"] is True
    assert (
        usage["rows"][0]["cost_amount"] is None and "no price" in usage["rows"][0]["price_basis"]
    )  # unknown stays unknown

    price = client.put(
        f"/api/ai/providers/{prov}/prices",
        json={
            "model_name": "gpt-x",
            "input_per_mtok": "2",
            "output_per_mtok": "8",
            "currency": "usd",
            "source_url": "https://example.com/pricing",
            "as_of": "2026-11-22",
        },
    )
    assert price.status_code == 200, price.text
    _ask(client, pid, cid, prov)
    runner.run_until_idle()
    row = client.get("/api/ai/usage").json()["rows"][0]
    assert row["cost_amount"] == "0.000038" and row["currency"] == "USD"  # 11*2/1e6 + 2*8/1e6

    # Revoking consent stops the next job before anything is sent, even if it was queued earlier.
    queued = _ask(client, pid, cid, prov).json()
    client.delete(f"/api/projects/{pid}/ai/consent/{prov}")
    n = len(calls)
    runner.run_until_idle()
    blocked = client.get(f"/api/ai/jobs/{queued['id']}").json()
    assert blocked["status"] == "failed" and blocked["error_code"] == "egress_blocked" and len(calls) == n


def test_api_key_never_leaves_the_credential_store(client: TestClient, ctx: AppContext, workspace: Path) -> None:
    ctx.http_transport = httpx2.MockTransport(
        lambda r: httpx2.Response(
            200, content=_chat_stream(json.loads(r.content)), headers={"content-type": "text/event-stream"}
        )
    )
    prov, pid, cid = _cloud_setup(client)
    out = client.get(f"/api/ai/providers/{prov}").json()
    assert out["key_status"] == "stored" and CANARY not in json.dumps(out)
    client.put("/api/ai/privacy", json={"mode": "cloud_allowed", "confirm": True})
    client.put(f"/api/projects/{pid}/ai/consent/{prov}")
    _ask(client, pid, cid, prov)
    JobRunner(ctx).run_until_idle()
    bad = client.put(f"/api/ai/providers/{prov}/key", json={"api_key": CANARY + " with spaces"})
    assert bad.status_code == 422 and CANARY not in bad.text

    backup = client.post(f"/api/projects/{pid}/backups").json()
    export = client.post(f"/api/projects/{pid}/exports", json={"format": "markdown"})
    ctx.db.dispose()  # flush WAL so the file bytes are complete
    blobs: list[tuple[str, bytes]] = []
    for path in workspace.rglob("*"):
        if path.is_file() and "runtime" not in path.parts:
            blobs.append((str(path), path.read_bytes()))
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as z:
                    blobs += [(f"{path}!{n}", z.read(n)) for n in z.namelist()]
    assert blobs and backup and export.status_code in (200, 201)
    leaks = [name for name, data in blobs if CANARY.encode() in data]
    assert leaks == [], f"API key found in: {leaks}"
    assert ctx.secrets.get(f"provider:{prov}") == CANARY
