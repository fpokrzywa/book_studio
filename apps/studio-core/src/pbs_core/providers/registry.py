"""Build provider adapters from stored configuration, and decide what each call may contact.

Nothing here falls back: if the chosen provider is blocked or misconfigured, the call fails with
an explanation. A local job never silently becomes a cloud job.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from pbs_core.providers.base import ProviderAdapter, ProviderError
from pbs_core.providers.egress import EgressPermit, provider_is_local
from pbs_core.security.secrets import credential_ref, env_key
from pbs_core.storage.ai_models import CloudConsent, ProviderConfig

if TYPE_CHECKING:
    from pbs_core.context import AppContext

DEFAULT_URLS: dict[str, str] = {
    "mock": "builtin:mock",
    "ollama": "http://127.0.0.1:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "groq": "https://api.groq.com/openai/v1",
    "xai": "https://api.x.ai/v1",
}
KIND_LABELS: dict[str, str] = {
    "mock": "Built-in test model (not AI)",
    "ollama": "Ollama (local)",
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "gemini": "Google Gemini",
    "groq": "Groq",
    "xai": "xAI (Grok)",
}
NEEDS_KEY = frozenset({"openai", "anthropic", "gemini", "groq", "xai"})
NATIVE_SCHEMA_VALUES = frozenset({"reported:true", "declared:true", "documented:true"})


def is_local(provider: ProviderConfig) -> bool:
    return provider_is_local(provider.kind, provider.base_url)


def privacy_mode(ctx: AppContext) -> str:
    """The effective mode. PBS_ALLOW_CLOUD=false (the server operator's switch) always means local-only."""
    if not ctx.settings.allow_cloud:
        return "local_only"
    return str(ctx.setting("privacy_mode") or "local_only")


def has_consent(ctx: AppContext, project_id: str, provider_id: str) -> bool:
    with ctx.db.tx() as s:
        return s.get(CloudConsent, (project_id, provider_id)) is not None


def permit_for(ctx: AppContext, provider: ProviderConfig, *, project_id: str | None = None) -> EgressPermit:
    """Cloud access needs privacy mode `cloud_allowed` and, for project work, that project's consent."""
    if is_local(provider):
        return EgressPermit(
            provider.kind,
            cloud_allowed=False,
            reason_if_blocked="Local providers may only use this machine or an operator-named private model host.",
        )
    if not ctx.settings.allow_cloud:
        return EgressPermit(
            provider.kind,
            cloud_allowed=False,
            reason_if_blocked=f"Cloud AI is turned off on this server (PBS_ALLOW_CLOUD=false), so {provider.label} "
            "cannot be contacted. Nothing was sent.",
        )
    if privacy_mode(ctx) != "cloud_allowed":
        return EgressPermit(
            provider.kind,
            cloud_allowed=False,
            reason_if_blocked=f"Local-only mode is on, so {provider.label} cannot be contacted. Nothing was sent.",
        )
    if project_id is not None and not has_consent(ctx, project_id, provider.id):
        return EgressPermit(
            provider.kind,
            cloud_allowed=False,
            reason_if_blocked=(
                f"This project has not been allowed to send text to {provider.label}. "
                "Allow it in the AI panel first. Nothing was sent."
            ),
        )
    return EgressPermit(provider.kind, cloud_allowed=True)


def api_key(ctx: AppContext, provider: ProviderConfig) -> tuple[str | None, str]:
    """(key, source) where source is 'store', 'env' or 'none'. The key is never logged."""
    if provider.credential_ref:
        stored = ctx.secrets.get(provider.credential_ref)
        if stored:
            return stored, "store"
    from_env = env_key(provider.kind)
    if from_env:
        return from_env, "env"
    return None, "none"


def build(ctx: AppContext, provider: ProviderConfig, permit: EgressPermit) -> ProviderAdapter:
    transport = ctx.http_transport
    kind = provider.kind
    if kind == "mock":
        from pbs_core.providers.mock import MockAdapter

        return MockAdapter()
    if kind == "ollama":
        from pbs_core.providers.ollama import OllamaAdapter

        return OllamaAdapter(permit, provider.base_url, transport=transport)
    key, _ = api_key(ctx, provider)
    if kind == "anthropic":
        from pbs_core.providers.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(key, permit, provider.base_url, transport=transport)
    if kind == "gemini":
        from pbs_core.providers.gemini import GeminiAdapter

        return GeminiAdapter(key, permit, provider.base_url, transport=transport)
    if kind in ("openai", "groq", "xai"):
        from pbs_core.providers.openai_compat import OpenAICompatAdapter

        return OpenAICompatAdapter(kind, key, permit, provider.base_url, transport=transport)
    raise ProviderError("bad_request", f"Unknown provider kind {kind!r}.")


def store_key(ctx: AppContext, provider: ProviderConfig, value: str) -> str:
    ref = credential_ref(provider.id)
    ctx.secrets.set(ref, value)
    return ref


def native_schema_ok(capabilities_json: str | None) -> bool:
    try:
        caps = json.loads(capabilities_json or "{}")
    except ValueError:
        return False
    return caps.get("structured_output") in NATIVE_SCHEMA_VALUES


def model_capabilities(ctx: AppContext, provider_id: str, model: str) -> str | None:
    from pbs_core.storage.ai_models import ModelInfo

    with ctx.db.tx() as s:
        row = s.scalars(
            select(ModelInfo).where(ModelInfo.provider_config_id == provider_id, ModelInfo.name == model)
        ).one_or_none()
        return row.capabilities_json if row else None
