"""AI settings, job requests and proposal review.

Rules enforced here (docs/SECURITY.md sections 4-5, docs/ARCHITECTURE.md "AI jobs"):
* No silent fallback: a request names one provider and model (explicitly or via the task route);
  if that provider is blocked or broken the request fails, nothing else is tried.
* Cloud needs privacy mode ``cloud_allowed`` plus this project's consent for that provider.
* Requests are scoped to one project and one chapter, built from an immutable revision, and
  clipped to the per-request content limit.
* AI output becomes a proposal. Only an explicit accept, against the head the author is looking
  at, creates a revision; a proposal can be applied at most once (unique index).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_ai import (
    AcceptIn,
    AcceptOut,
    AiRequestIn,
    AiStatusOut,
    ConsentOut,
    EstimateOut,
    HealthOut,
    JobLogOut,
    JobOut,
    ManualModelIn,
    ModelOut,
    PriceIn,
    PriceOut,
    PrivacyIn,
    ProposalOut,
    ProviderCreate,
    ProviderKindOut,
    ProviderOut,
    ProviderPatch,
    RouteIn,
    RouteOut,
    SecretStoreOut,
    UsageOut,
    UsageRowOut,
    UsageTotalOut,
)
from pbs_core.document import bookmd
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.jobs import prompts
from pbs_core.jobs.execute import retrieval_query
from pbs_core.jobs.runner import add_log
from pbs_core.knowledge import retrieval
from pbs_core.providers import registry
from pbs_core.providers.base import ProviderError
from pbs_core.providers.egress import (
    EgressBlockedError,
    active_cloud_calls,
    external_requests,
    normalize_loopback_url,
)
from pbs_core.security.secrets import SecretStoreError, credential_ref
from pbs_core.services import activity, chapters, costs, evidence
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.ai_models import (
    TASKS,
    CloudConsent,
    Job,
    JobLog,
    ModelInfo,
    ModelPrice,
    Proposal,
    ProviderConfig,
    TaskRoute,
    UsageRecord,
)
from pbs_core.storage.knowledge_models import AuthorProfile
from pbs_core.storage.models import AppSetting, Chapter, ChapterDraft, ChapterRevision, Project

log = structlog.get_logger(__name__)

KIND_NOTES: dict[str, str] = {
    "mock": "Deterministic test model for trying the workflow offline. Its output is not AI.",
    "ollama": "Runs models on this computer. Nothing leaves your machine.",
    "openai": "Cloud. Your text is sent to OpenAI.",
    "anthropic": "Cloud. Your text is sent to Anthropic.",
    "gemini": "Cloud. Your text is sent to Google.",
    "groq": "Cloud. Your text is sent to Groq.",
    "xai": "Cloud. Your text is sent to xAI (Grok).",
}


class CloudBlockedError(ConflictError):
    code = "cloud_blocked"


class NeedsChoiceError(ConflictError):
    code = "model_not_chosen"


# ---------- privacy and status ----------


def secret_store_out(ctx: AppContext) -> SecretStoreOut:
    store = ctx.secrets
    warning = None
    if store.name == "dev-file":
        warning = "Keys are kept in a development file protected only by file permissions. Use the OS credential store for real work."
    elif store.name == "memory":
        warning = "Keys are kept in memory only (test mode) and are lost when Core stops."
    elif not store.writable:
        warning = (
            "No OS credential store was found. Keys can only come from PBS_<PROVIDER>_API_KEY environment variables."
        )
    return SecretStoreOut(backend=store.name, secure=store.secure, writable=store.writable, warning=warning)


def status(ctx: AppContext) -> AiStatusOut:
    with ctx.db.tx() as s:
        counts = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        pending = s.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "pending")) or 0
    return AiStatusOut(
        privacy_mode=registry.privacy_mode(ctx),
        external_requests=external_requests(),
        active_cloud_calls=active_cloud_calls(),
        queued_jobs=int(counts.get("queued", 0)),
        running_jobs=int(counts.get("running", 0)),
        pending_proposals=int(pending),
        secret_store=secret_store_out(ctx),
    )


def set_privacy(ctx: AppContext, data: PrivacyIn) -> AiStatusOut:
    if data.mode == "cloud_allowed" and not data.confirm:
        raise ValidationFailedError("Confirm that you want to allow cloud AI providers.")
    with ctx.db.tx() as s:
        row = s.get(AppSetting, "privacy_mode")
        if row is None:
            s.add(AppSetting(key="privacy_mode", value_json=json.dumps(data.mode)))
        else:
            row.value_json = json.dumps(data.mode)
        label = (
            "Cloud AI allowed (per project consent still required)"
            if data.mode == "cloud_allowed"
            else "Local-only mode on"
        )
        activity.record(s, ctx, kind="privacy_mode_changed", summary=label)
    return status(ctx)


# ---------- providers ----------


def provider_kinds(ctx: AppContext) -> list[ProviderKindOut]:
    kinds = [k for k in registry.DEFAULT_URLS if k != "mock" or ctx.settings.env != "prod"]
    return [
        ProviderKindOut(
            kind=k,
            label=registry.KIND_LABELS[k],
            local=k in ("mock", "ollama"),
            needs_key=k in registry.NEEDS_KEY,
            default_url=registry.DEFAULT_URLS[k],
            url_editable=k == "ollama",
            note=KIND_NOTES[k],
        )
        for k in kinds
    ]


def _require_provider(s: Session, provider_id: str) -> ProviderConfig:
    p = s.get(ProviderConfig, provider_id) if is_ulid(provider_id) else None
    if p is None:
        raise NotFoundError("AI provider not found.")
    return p


def _health_out(raw: str) -> HealthOut | None:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return None
    return HealthOut(**data) if data else None


def _model_out(m: ModelInfo) -> ModelOut:
    return ModelOut(
        name=m.name,
        display_name=m.display_name,
        context_tokens=m.context_tokens,
        max_output_tokens=m.max_output_tokens,
        capabilities=json.loads(m.capabilities_json or "{}"),
        source=m.source,
        updated_at=m.updated_at,
    )


def _provider_out(ctx: AppContext, s: Session, p: ProviderConfig) -> ProviderOut:
    if p.kind not in registry.NEEDS_KEY:
        key_status = "not_needed"
    else:
        _, source = registry.api_key(ctx, p)
        key_status = {"store": "stored", "env": "env", "none": "missing"}[source]
    models = s.scalars(select(ModelInfo).where(ModelInfo.provider_config_id == p.id).order_by(ModelInfo.name)).all()
    return ProviderOut(
        id=p.id,
        kind=p.kind,
        label=p.label,
        base_url=p.base_url,
        local=registry.is_local(p),
        enabled=bool(p.enabled),
        key_status=key_status,
        health=_health_out(p.health_json),
        models=[_model_out(m) for m in models],
        created_at=p.created_at,
    )


def list_providers(ctx: AppContext) -> list[ProviderOut]:
    with ctx.db.tx() as s:
        rows = s.scalars(select(ProviderConfig).order_by(ProviderConfig.created_at)).all()
        return [_provider_out(ctx, s, p) for p in rows]


def get_provider(ctx: AppContext, provider_id: str) -> ProviderOut:
    with ctx.db.tx() as s:
        return _provider_out(ctx, s, _require_provider(s, provider_id))


def _check_ollama_url(url: str) -> str:
    try:
        return normalize_loopback_url(url)
    except ValueError as exc:
        raise ValidationFailedError(
            "Ollama must run on this computer, at an address such as http://127.0.0.1:11434. "
            "Remote servers are not allowed."
        ) from exc


def create_provider(ctx: AppContext, data: ProviderCreate) -> ProviderOut:
    if data.kind == "mock" and ctx.settings.env == "prod":
        raise ValidationFailedError("The built-in test model is only available in development.")
    base_url = registry.DEFAULT_URLS[data.kind]
    if data.kind == "ollama" and data.base_url:
        base_url = _check_ollama_url(data.base_url)
    elif data.base_url and data.base_url.rstrip("/") != base_url:
        raise ValidationFailedError("This provider's address is fixed to its official API.")
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        p = ProviderConfig(
            id=ctx.ids.new(),
            kind=data.kind,
            label=data.label or registry.KIND_LABELS[data.kind],
            base_url=base_url,
            credential_ref=None,
            enabled=1,
            health_json="{}",
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.flush()
        if data.kind == "mock":  # the test model's single model is known without a network call
            from pbs_core.providers.mock import MODELS

            _upsert_models(s, ctx, p, MODELS)
        activity.record(s, ctx, kind="ai_provider_added", summary=f"Added AI provider {p.label}")
        s.flush()
        return _provider_out(ctx, s, p)


def update_provider(ctx: AppContext, provider_id: str, data: ProviderPatch) -> ProviderOut:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        if data.label is not None:
            p.label = data.label
        if data.enabled is not None:
            p.enabled = 1 if data.enabled else 0
        if data.base_url is not None:
            if p.kind != "ollama":
                raise ValidationFailedError("This provider's address is fixed to its official API.")
            p.base_url = _check_ollama_url(data.base_url)
        p.updated_at = ctx.clock.iso()
        s.flush()
        return _provider_out(ctx, s, p)


def delete_provider(ctx: AppContext, provider_id: str) -> None:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        ctx.secrets.delete(credential_ref(p.id))
        s.execute(delete(TaskRoute).where(TaskRoute.provider_config_id == p.id))
        s.execute(delete(CloudConsent).where(CloudConsent.provider_config_id == p.id))
        used = s.scalar(select(func.count()).select_from(Job).where(Job.provider_config_id == p.id)) or 0
        if used:
            # Job history keeps pointing at it, so it is disabled and its key removed instead.
            p.enabled, p.credential_ref, p.updated_at = 0, None, ctx.clock.iso()
            activity.record(
                s, ctx, kind="ai_provider_removed", summary=f"Disabled AI provider {p.label} (kept for job history)"
            )
            return
        s.execute(delete(ModelPrice).where(ModelPrice.provider_config_id == p.id))
        s.execute(delete(ModelInfo).where(ModelInfo.provider_config_id == p.id))
        s.delete(p)
        activity.record(s, ctx, kind="ai_provider_removed", summary=f"Removed AI provider {p.label}")


def set_key(ctx: AppContext, provider_id: str, api_key: str) -> ProviderOut:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        if p.kind not in registry.NEEDS_KEY:
            raise ValidationFailedError("This provider does not use an API key.")
        try:
            p.credential_ref = registry.store_key(ctx, p, api_key)
        except SecretStoreError as exc:
            raise ConflictError(str(exc), extra={"reason": "no_secret_store"}) from exc
        p.health_json = "{}"
        p.updated_at = ctx.clock.iso()
        activity.record(s, ctx, kind="ai_key_stored", summary=f"Stored an API key for {p.label} in {ctx.secrets.name}")
        s.flush()
        return _provider_out(ctx, s, p)


def delete_key(ctx: AppContext, provider_id: str) -> ProviderOut:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        ctx.secrets.delete(credential_ref(p.id))
        p.credential_ref = None
        p.health_json = "{}"
        p.updated_at = ctx.clock.iso()
        activity.record(s, ctx, kind="ai_key_removed", summary=f"Removed the API key for {p.label}")
        s.flush()
        return _provider_out(ctx, s, p)


def _snapshot(ctx: AppContext, provider_id: str) -> ProviderConfig:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        s.expunge(p)
        return p


def _save_health(ctx: AppContext, provider_id: str, health: HealthOut) -> None:
    with ctx.db.tx() as s:
        p = s.get(ProviderConfig, provider_id)
        if p is not None:
            p.health_json = health.model_dump_json()


def test_provider(ctx: AppContext, provider_id: str) -> HealthOut:
    """Check the connection. Cloud providers are contacted only when cloud AI is allowed."""
    p = _snapshot(ctx, provider_id)
    now = ctx.clock.iso()
    try:
        adapter = registry.build(ctx, p, registry.permit_for(ctx, p))
        h = adapter.health()
        out = HealthOut(ok=h.ok, message=h.message, version=h.version, latency_ms=h.latency_ms, checked_at=now)
    except EgressBlockedError as exc:
        out = HealthOut(ok=False, code="egress_blocked", message=str(exc), checked_at=now)
    except ProviderError as exc:
        out = HealthOut(ok=False, code=exc.code, message=exc.message, checked_at=now)
    _save_health(ctx, provider_id, out)
    return out


def _upsert_models(s: Session, ctx: AppContext, p: ProviderConfig, found: list[Any]) -> None:
    now = ctx.clock.iso()
    existing = {m.name: m for m in s.scalars(select(ModelInfo).where(ModelInfo.provider_config_id == p.id))}
    for d in found:
        row = existing.get(d.name)
        caps = dict(d.capabilities)
        if row is not None:
            # Keep what the author declared where the provider reports nothing.
            for k, v in json.loads(row.capabilities_json or "{}").items():
                if str(v).startswith("declared:") and caps.get(k, "unknown") == "unknown":
                    caps[k] = v
            row.display_name, row.context_tokens = d.display_name, d.context_tokens or row.context_tokens
            row.max_output_tokens = d.max_output_tokens or row.max_output_tokens
            row.capabilities_json, row.updated_at = json.dumps(caps), now
            if row.source == "manual":
                row.source = "discovered"
        else:
            s.add(
                ModelInfo(
                    id=ctx.ids.new(),
                    provider_config_id=p.id,
                    name=d.name,
                    display_name=d.display_name,
                    context_tokens=d.context_tokens,
                    max_output_tokens=d.max_output_tokens,
                    capabilities_json=json.dumps(caps),
                    source="discovered",
                    updated_at=now,
                )
            )


def refresh_models(ctx: AppContext, provider_id: str) -> ProviderOut:
    p = _snapshot(ctx, provider_id)
    try:
        found = registry.build(ctx, p, registry.permit_for(ctx, p)).list_models()
    except EgressBlockedError as exc:
        raise CloudBlockedError(str(exc)) from exc
    except ProviderError as exc:
        raise ConflictError(exc.message, extra={"reason": exc.code}) from exc
    with ctx.db.tx() as s:
        live = _require_provider(s, provider_id)
        _upsert_models(s, ctx, live, found)
        s.flush()
        return _provider_out(ctx, s, live)


def put_manual_model(ctx: AppContext, provider_id: str, data: ManualModelIn) -> ProviderOut:
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        row = s.scalars(
            select(ModelInfo).where(ModelInfo.provider_config_id == p.id, ModelInfo.name == data.name)
        ).one_or_none()
        if row is None:
            caps = {"chat": "unknown", "structured_output": data.structured_output, "temperature": "unknown"}
            s.add(
                ModelInfo(
                    id=ctx.ids.new(),
                    provider_config_id=p.id,
                    name=data.name,
                    display_name=None,
                    context_tokens=data.context_tokens,
                    max_output_tokens=data.max_output_tokens,
                    capabilities_json=json.dumps(caps),
                    source="manual",
                    updated_at=now,
                )
            )
        else:
            caps = json.loads(row.capabilities_json or "{}")
            current = caps.get("structured_output", "unknown")
            if not (str(current).startswith(("reported:", "documented:")) and data.structured_output == "unknown"):
                caps["structured_output"] = data.structured_output
            row.capabilities_json = json.dumps(caps)
            row.context_tokens = data.context_tokens or row.context_tokens
            row.max_output_tokens = data.max_output_tokens or row.max_output_tokens
            row.updated_at = now
        s.flush()
        return _provider_out(ctx, s, p)


def delete_model(ctx: AppContext, provider_id: str, name: str) -> ProviderOut:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        s.execute(delete(ModelInfo).where(ModelInfo.provider_config_id == p.id, ModelInfo.name == name))
        s.flush()
        return _provider_out(ctx, s, p)


# ---------- routes and prices ----------


def _route_out(r: TaskRoute, p: ProviderConfig) -> RouteOut:
    return RouteOut(
        task=r.task,
        provider_id=p.id,
        provider_label=p.label,
        provider_local=registry.is_local(p),
        model_name=r.model_name,
        temperature=float(r.temperature) if r.temperature not in (None, "") else None,
        max_output_tokens=r.max_output_tokens,
        updated_at=r.updated_at,
    )


def list_routes(ctx: AppContext) -> list[RouteOut]:
    with ctx.db.tx() as s:
        rows = s.execute(select(TaskRoute, ProviderConfig).join(ProviderConfig)).all()
        by_task = {r.task: _route_out(r, p) for r, p in rows}
        return [by_task[t] for t in TASKS if t in by_task]


def put_route(ctx: AppContext, task: str, data: RouteIn) -> RouteOut:
    if task not in TASKS:
        raise NotFoundError("Unknown task.")
    with ctx.db.tx() as s:
        p = _require_provider(s, data.provider_id)
        r = s.get(TaskRoute, task)
        temp = None if data.temperature is None else str(data.temperature)
        if r is None:
            r = TaskRoute(
                task=task,
                provider_config_id=p.id,
                model_name=data.model_name,
                temperature=temp,
                max_output_tokens=data.max_output_tokens,
                updated_at=ctx.clock.iso(),
            )
            s.add(r)
        else:
            r.provider_config_id, r.model_name, r.temperature = p.id, data.model_name, temp
            r.max_output_tokens, r.updated_at = data.max_output_tokens, ctx.clock.iso()
        s.flush()
        return _route_out(r, p)


def delete_route(ctx: AppContext, task: str) -> None:
    with ctx.db.tx() as s:
        s.execute(delete(TaskRoute).where(TaskRoute.task == task))


def _price_out(r: ModelPrice) -> PriceOut:
    return PriceOut(
        id=r.id,
        provider_id=r.provider_config_id,
        model_name=r.model_name,
        input_per_mtok=r.input_per_mtok,
        output_per_mtok=r.output_per_mtok,
        currency=r.currency,
        source_url=r.source_url,
        as_of=r.as_of,
        updated_at=r.updated_at,
    )


def list_prices(ctx: AppContext, provider_id: str) -> list[PriceOut]:
    with ctx.db.tx() as s:
        _require_provider(s, provider_id)
        rows = s.scalars(
            select(ModelPrice).where(ModelPrice.provider_config_id == provider_id).order_by(ModelPrice.model_name)
        )
        return [_price_out(r) for r in rows]


def put_price(ctx: AppContext, provider_id: str, data: PriceIn) -> PriceOut:
    with ctx.db.tx() as s:
        p = _require_provider(s, provider_id)
        r = s.scalars(
            select(ModelPrice).where(ModelPrice.provider_config_id == p.id, ModelPrice.model_name == data.model_name)
        ).one_or_none()
        if r is None:
            r = ModelPrice(
                id=ctx.ids.new(),
                provider_config_id=p.id,
                model_name=data.model_name,
                input_per_mtok="0",
                output_per_mtok="0",
                currency="USD",
                as_of=data.as_of,
                updated_at=ctx.clock.iso(),
            )
            s.add(r)
        r.input_per_mtok, r.output_per_mtok, r.currency = data.input_per_mtok, data.output_per_mtok, data.currency
        r.source_url, r.as_of, r.updated_at = data.source_url, data.as_of, ctx.clock.iso()
        s.flush()
        return _price_out(r)


def delete_price(ctx: AppContext, provider_id: str, price_id: str) -> None:
    with ctx.db.tx() as s:
        s.execute(delete(ModelPrice).where(ModelPrice.provider_config_id == provider_id, ModelPrice.id == price_id))


# ---------- per-project cloud consent ----------


def list_consent(ctx: AppContext, project_id: str) -> list[ConsentOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.execute(
            select(CloudConsent, ProviderConfig).join(ProviderConfig).where(CloudConsent.project_id == project_id)
        ).all()
        return [
            ConsentOut(project_id=c.project_id, provider_id=p.id, provider_label=p.label, granted_at=c.granted_at)
            for c, p in rows
        ]


def grant_consent(ctx: AppContext, project_id: str, provider_id: str) -> ConsentOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        p = _require_provider(s, provider_id)
        if registry.is_local(p):
            raise ValidationFailedError("Local providers do not need permission.")
        c = s.get(CloudConsent, (project_id, provider_id))
        if c is None:
            c = CloudConsent(project_id=project_id, provider_config_id=provider_id, granted_at=ctx.clock.iso())
            s.add(c)
            activity.record(
                s,
                ctx,
                kind="ai_consent_granted",
                project_id=project_id,
                summary=f"Allowed “{project.title}” to send text to {p.label}",
            )
        return ConsentOut(project_id=project_id, provider_id=p.id, provider_label=p.label, granted_at=c.granted_at)


def revoke_consent(ctx: AppContext, project_id: str, provider_id: str) -> None:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        c = s.get(CloudConsent, (project_id, provider_id))
        if c is not None:
            s.delete(c)
            activity.record(
                s,
                ctx,
                kind="ai_consent_revoked",
                project_id=project_id,
                summary=f"Stopped “{project.title}” from sending text to a cloud provider",
            )


# ---------- requests: estimate and enqueue ----------


@dataclass
class _Plan:
    project: Project
    chapter: Chapter
    head: ChapterRevision | None
    provider: ProviderConfig
    model: str
    temperature: float | None
    max_out: int
    mode: str
    sel_start: int | None
    sel_end: int | None
    selection: str | None
    template: str
    estimate: dict[str, Any]
    clipped: bool
    blocked: str | None
    passages: int
    answers: int


def _plan(ctx: AppContext, s: Session, project_id: str, data: AiRequestIn) -> _Plan:
    """Resolve and validate everything about a request. Raises with an actionable message."""
    project = require_active(s, project_id)
    chapter = chapters._require_chapter(s, project_id, data.chapter_id)
    if data.base_revision_no != chapter.head_revision_no:
        raise ConflictError("This chapter was saved elsewhere since you opened it. Reload, then ask again.")
    if s.get(ChapterDraft, chapter.id) is not None:
        raise ConflictError(
            "Save your changes first, so the AI works from the text you see.", extra={"reason": "unsaved_changes"}
        )
    if chapter.status == "approved":
        raise ConflictError(
            "This chapter is approved and locked. Reopen it for editing before asking for suggestions.",
            extra={"reason": "chapter_approved"},
        )
    head = chapters._head(s, chapter)
    text = head.source_md if head is not None else ""

    if data.provider_id:
        provider = _require_provider(s, data.provider_id)
        if not data.model_name:
            raise NeedsChoiceError("Choose a model for this provider.")
        model, temperature, max_out = data.model_name, data.temperature, data.max_output_tokens
    else:
        route = s.get(TaskRoute, data.task)
        if route is None:
            raise NeedsChoiceError(
                f"No model is set for “{data.task}”. Choose one here or set a default in AI settings."
            )
        provider = _require_provider(s, route.provider_config_id)
        model = data.model_name or route.model_name
        temperature = (
            data.temperature
            if data.temperature is not None
            else (float(route.temperature) if route.temperature not in (None, "") else None)
        )
        max_out = data.max_output_tokens or route.max_output_tokens
    if not provider.enabled:
        raise ConflictError(f"{provider.label} is turned off in AI settings.")

    sel_start, sel_end = data.selection_start, data.selection_end
    needs_selection = data.mode == "replace_selection" or data.task == "revise"
    if needs_selection and (sel_start is None or sel_end is None or not (0 <= sel_start < sel_end <= len(text))):
        raise ValidationFailedError("Select the passage you want changed first.")
    if data.mode == "insert_at" and (sel_start is None or sel_start > len(text)):
        raise ValidationFailedError("Place the cursor where the text should go.")
    if sel_start is not None and sel_end is not None and not (0 <= sel_start <= sel_end <= len(text)):
        raise ValidationFailedError("The selection is outside the chapter text. Reload and try again.")
    if data.task in ("brainstorm", "research", "outline", "summarize") and data.mode != "note":
        mode = "note"
    else:
        mode = data.mode
    limit = costs.MAX_CONTEXT_CHARS
    selection = text[sel_start:sel_end] if sel_start is not None and sel_end is not None else None
    if selection is not None and len(selection) > limit:
        raise ValidationFailedError(f"The selection is too long for one request (limit {limit:,} characters).")

    max_out = int(max_out or 2048)
    info = s.scalars(
        select(ModelInfo).where(ModelInfo.provider_config_id == provider.id, ModelInfo.name == model)
    ).one_or_none()
    if info is not None and info.max_output_tokens and max_out > info.max_output_tokens:
        max_out = info.max_output_tokens

    context = costs.clip_context(text, sel_start, sel_end, limit)
    # Preview of the knowledge the job will use (it is chosen again when the job runs).
    found = retrieval.retrieve(
        s,
        project_id,
        retrieval_query(data.instruction, selection, context, chapter.title),
        use_sources=data.use_sources,
        use_interview=data.use_interview,
    )
    voice = None
    if data.voice_profile_id:
        profile = s.get(AuthorProfile, data.voice_profile_id) if is_ulid(data.voice_profile_id) else None
        if profile is None:
            raise NotFoundError("Author voice profile not found.")
        if not profile.style_guide_md.strip():
            raise ConflictError("This voice profile has no style guide yet. Add writing samples first.")
        voice = {"name": profile.name, "guide": profile.style_guide_md}
    built = prompts.build(
        data.task,
        instruction=data.instruction,
        chapter_title=chapter.title,
        book_title=project.title,
        context_text=context,
        selection=selection,
        target_language=data.target_language,
        target_words=data.target_words,
        sources=[r for r in found.refs.values() if r.kind == "source"],
        answers=[r for r in found.refs.values() if r.kind == "interview"],
        voice=voice,
    )
    estimate = costs.estimate(s, provider, model, len(built.system) + len(built.user), max_out)

    blocked: str | None = None
    if not registry.is_local(provider):
        setting = s.get(AppSetting, "privacy_mode")  # same transaction: no nested lock
        if (json.loads(setting.value_json) if setting else "local_only") != "cloud_allowed":
            blocked = f"Local-only mode is on, so {provider.label} cannot be used. Nothing was sent."
        elif s.get(CloudConsent, (project_id, provider.id)) is None:
            blocked = f"This project has not been allowed to send text to {provider.label}."
    return _Plan(
        project=project,
        chapter=chapter,
        head=head,
        provider=provider,
        model=model,
        temperature=temperature,
        max_out=max_out,
        mode=mode,
        sel_start=sel_start,
        sel_end=sel_end,
        selection=selection,
        template=built.template,
        estimate=estimate,
        clipped=len(context) < len(text),
        blocked=blocked,
        passages=len(found.passages),
        answers=len(found.answers),
    )


def estimate(ctx: AppContext, project_id: str, data: AiRequestIn) -> EstimateOut:
    with ctx.db.tx() as s:
        plan = _plan(ctx, s, project_id, data)
        e = plan.estimate
        return EstimateOut(
            provider_id=plan.provider.id,
            provider_label=plan.provider.label,
            provider_local=registry.is_local(plan.provider),
            model_name=plan.model,
            input_tokens=int(e["input_tokens"]),
            max_output_tokens=int(e["max_output_tokens"]),
            is_estimate=True,
            basis=str(e["basis"]),
            cost_upper_bound=e["cost_upper_bound"],
            currency=e["currency"],
            cost_note=str(e["cost_note"]),
            context_clipped=plan.clipped,
            blocked_reason=plan.blocked,
            source_passages=plan.passages,
            interview_answers=plan.answers,
        )


def enqueue(ctx: AppContext, project_id: str, data: AiRequestIn) -> JobOut:
    key = f"{project_id}:{data.client_request_id}"
    with ctx.db.tx() as s:
        existing = s.scalars(select(Job).where(Job.idempotency_key == key)).one_or_none()
        if existing is not None:  # same request sent twice: same job
            return _job_out(s, existing)
        plan = _plan(ctx, s, project_id, data)
        if plan.blocked:
            raise CloudBlockedError(plan.blocked, extra={"reason": "cloud_blocked"})
        now = ctx.clock.iso()
        inp = {
            "instruction": data.instruction,
            "mode": plan.mode,
            "selection_start": plan.sel_start,
            "selection_end": plan.sel_end,
            "selection_text": plan.selection,
            "base_revision_id": plan.head.id if plan.head is not None else None,
            "base_revision_no": plan.chapter.head_revision_no,
            "target_language": data.target_language,
            "target_words": data.target_words,
            "max_context_chars": costs.MAX_CONTEXT_CHARS,
            "use_sources": data.use_sources,
            "use_interview": data.use_interview,
            "voice_profile_id": data.voice_profile_id,
        }
        job = Job(
            id=ctx.ids.new(),
            project_id=project_id,
            chapter_id=plan.chapter.id,
            task=data.task,
            provider_config_id=plan.provider.id,
            provider_kind=plan.provider.kind,
            model_name=plan.model,
            params_json=json.dumps({"temperature": plan.temperature, "max_output_tokens": plan.max_out}),
            input_json=json.dumps(inp),
            prompt_template=plan.template,
            estimate_json=json.dumps(plan.estimate),
            status="queued",
            stage="queued",
            attempt=0,
            max_attempts=3,
            run_after=now,
            cancel_requested=0,
            idempotency_key=key,
            created_at=now,
        )
        s.add(job)
        s.flush()
        where = "on this computer" if registry.is_local(plan.provider) else f"to {plan.provider.label} (cloud)"
        add_log(s, ctx, job.id, f"Queued: {data.task} with {plan.model}, sent {where}.")
        activity.record(
            s,
            ctx,
            kind="ai_job_queued",
            project_id=project_id,
            ref_type="job",
            ref_id=job.id,
            summary=f"Asked {plan.model} to {data.task} in “{plan.chapter.title}”",
        )
        s.flush()
        out = _job_out(s, job)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


# ---------- jobs ----------


def _job_out(s: Session, j: Job) -> JobOut:
    p = s.get(ProviderConfig, j.provider_config_id)
    project = s.get(Project, j.project_id)
    chapter = s.get(Chapter, j.chapter_id) if j.chapter_id else None
    proposal_id = s.scalar(select(Proposal.id).where(Proposal.job_id == j.id))
    return JobOut(
        id=j.id,
        project_id=j.project_id,
        project_title=project.title if project else None,
        chapter_id=j.chapter_id,
        chapter_title=chapter.title if chapter else None,
        task=j.task,
        provider_id=j.provider_config_id,
        provider_kind=j.provider_kind,
        provider_label=p.label if p else None,
        provider_local=registry.is_local(p) if p else True,
        model_name=j.model_name,
        status=j.status,
        stage=j.stage,
        received_chars=j.progress_done,
        attempt=j.attempt,
        max_attempts=j.max_attempts,
        run_after=j.run_after,
        cancel_requested=bool(j.cancel_requested),
        error_code=j.error_code,
        error_message=j.error_message,
        partial_output=j.partial_output if j.status != "succeeded" else None,
        proposal_id=proposal_id,
        estimate=json.loads(j.estimate_json or "{}"),
        created_at=j.created_at,
        started_at=j.started_at,
        finished_at=j.finished_at,
    )


def list_jobs(
    ctx: AppContext,
    *,
    project_id: str | None = None,
    chapter_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[JobOut]:
    stmt = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(max(1, min(limit, 500)))
    if project_id:
        stmt = stmt.where(Job.project_id == project_id)
    if chapter_id:
        stmt = stmt.where(Job.chapter_id == chapter_id)
    if status:
        stmt = stmt.where(Job.status == status)
    with ctx.db.tx() as s:
        return [_job_out(s, j) for j in s.scalars(stmt).all()]


def _require_job(s: Session, job_id: str) -> Job:
    j = s.get(Job, job_id) if is_ulid(job_id) else None
    if j is None:
        raise NotFoundError("Job not found.")
    return j


def get_job(ctx: AppContext, job_id: str) -> JobOut:
    with ctx.db.tx() as s:
        return _job_out(s, _require_job(s, job_id))


def job_logs(ctx: AppContext, job_id: str) -> list[JobLogOut]:
    with ctx.db.tx() as s:
        _require_job(s, job_id)
        rows = s.scalars(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.ts, JobLog.id)).all()
        return [JobLogOut(ts=r.ts, level=r.level, message=r.message) for r in rows]


def cancel_job(ctx: AppContext, job_id: str) -> JobOut:
    with ctx.db.tx() as s:
        j = _require_job(s, job_id)
        if j.status == "queued":
            j.status, j.stage, j.finished_at = "cancelled", "cancelled", ctx.clock.iso()
            j.cancel_requested = 1
            j.error_code, j.error_message = "cancelled", "Cancelled by the author before it ran."
            add_log(s, ctx, j.id, j.error_message)
        elif j.status == "running":
            j.cancel_requested = 1
            j.stage = "cancelling"
            add_log(s, ctx, j.id, "Cancel requested; stopping the model call.")
        else:
            raise ConflictError(f"This job is already {j.status}.")
        s.flush()
        out = _job_out(s, j)
    if ctx.jobs is not None:
        ctx.jobs.signal_cancel(job_id)
    return out


def retry_job(ctx: AppContext, job_id: str) -> JobOut:
    with ctx.db.tx() as s:
        j = _require_job(s, job_id)
        if j.status not in ("failed", "cancelled", "interrupted"):
            raise ConflictError("Only failed, cancelled or interrupted jobs can be retried.")
        if s.scalar(select(Proposal.id).where(Proposal.job_id == j.id)) is not None:
            raise ConflictError("This job already produced a suggestion.")
        p = s.get(ProviderConfig, j.provider_config_id)
        if p is None or not p.enabled:
            raise ConflictError("The provider for this job was removed or turned off.")
        j.status, j.stage, j.run_after = "queued", "queued", ctx.clock.iso()
        j.cancel_requested, j.max_attempts = 0, j.attempt + 3  # attempt numbers keep increasing
        j.error_code = j.error_message = j.partial_output = j.finished_at = None
        j.progress_done = None
        add_log(s, ctx, j.id, "Retry requested by the author.")
        s.flush()
        out = _job_out(s, j)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


# ---------- proposals ----------


def _applicability(p: Proposal, chapter: Chapter | None, head: ChapterRevision | None) -> tuple[bool, str | None]:
    if p.status != "pending":
        return False, f"This suggestion was already {p.status}."
    if p.mode == "note":
        return False, "This is a note for you to read; it is not inserted into the chapter."
    if chapter is None:
        return False, "The chapter no longer exists."
    current = head.source_md if head is not None else ""
    if p.mode == "replace_selection":
        start, end = p.selection_start or 0, p.selection_end or 0
        if current[start:end] != (p.original_text or ""):
            return False, "The selected passage has changed since you asked. Ask again on the current text."
    if p.mode == "insert_at" and chapter.head_revision_no != p.base_revision_no:
        return False, "The chapter has changed since you asked, so the insert position may be wrong. Ask again."
    return True, None


def _proposal_out(s: Session, p: Proposal) -> ProposalOut:
    chapter = s.get(Chapter, p.chapter_id) if p.chapter_id else None
    head = chapters._head(s, chapter) if chapter is not None else None
    ok, reason = _applicability(p, chapter, head)
    accepted_no = None
    if p.accepted_revision_id:
        accepted_no = s.scalar(select(ChapterRevision.revision_no).where(ChapterRevision.id == p.accepted_revision_id))
    return ProposalOut(
        id=p.id,
        job_id=p.job_id,
        project_id=p.project_id,
        chapter_id=p.chapter_id,
        mode=p.mode,
        status=p.status,
        base_revision_no=p.base_revision_no,
        current_head_no=chapter.head_revision_no if chapter else None,
        applicable=ok,
        not_applicable_reason=reason,
        selection_start=p.selection_start,
        selection_end=p.selection_end,
        original_text=p.original_text,
        payload_md=p.payload_md,
        accepted_revision_no=accepted_no,
        provenance=json.loads(p.provenance_json or "{}"),
        created_at=p.created_at,
        decided_at=p.decided_at,
    )


def _require_proposal(s: Session, project_id: str, proposal_id: str) -> Proposal:
    p = (
        s.scalars(select(Proposal).where(Proposal.project_id == project_id, Proposal.id == proposal_id)).one_or_none()
        if is_ulid(proposal_id)
        else None
    )
    if p is None:
        raise NotFoundError("Suggestion not found in this project.")
    return p


def list_proposals(
    ctx: AppContext, project_id: str, *, chapter_id: str | None = None, status: str | None = None
) -> list[ProposalOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        stmt = select(Proposal).where(Proposal.project_id == project_id).order_by(Proposal.created_at.desc()).limit(200)
        if chapter_id:
            stmt = stmt.where(Proposal.chapter_id == chapter_id)
        if status:
            stmt = stmt.where(Proposal.status == status)
        return [_proposal_out(s, p) for p in s.scalars(stmt).all()]


def get_proposal(ctx: AppContext, project_id: str, proposal_id: str) -> ProposalOut:
    with ctx.db.tx() as s:
        return _proposal_out(s, _require_proposal(s, project_id, proposal_id))


def _apply(mode: str, current: str, payload: str, start: int | None, end: int | None) -> str:
    if mode == "append":
        return (
            (current.rstrip("\n") + "\n\n" + payload.strip("\n") + "\n")
            if current.strip()
            else payload.strip("\n") + "\n"
        )
    if mode == "replace_selection":
        return current[: start or 0] + payload + current[end or 0 :]
    if mode == "insert_at":
        pos = start or 0
        return current[:pos] + payload + current[pos:]
    raise ValueError(mode)


def accept_proposal(ctx: AppContext, project_id: str, proposal_id: str, data: AcceptIn) -> AcceptOut:
    """Turn a suggestion into a new revision. Exactly once, against the head the author sees."""
    try:
        with ctx.db.tx() as s:
            require_active(s, project_id)
            p = _require_proposal(s, project_id, proposal_id)
            if p.status == "accepted":
                raise ConflictError("This suggestion was already applied.", extra={"reason": "already_applied"})
            chapter = chapters._require_chapter(s, project_id, p.chapter_id or "")
            head = chapters._head(s, chapter)
            if data.expected_head_no != chapter.head_revision_no:
                raise ConflictError("This chapter was saved elsewhere since you opened it. Reload and review again.")
            if s.get(ChapterDraft, chapter.id) is not None:
                raise ConflictError("Save or discard your unsaved changes first.", extra={"reason": "unsaved_changes"})
            ok, reason = _applicability(p, chapter, head)
            if not ok:
                raise ConflictError(reason or "This suggestion cannot be applied.", extra={"reason": "not_applicable"})
            chapters._check_editable(chapter)
            payload = data.edited_md if data.edited_md is not None else p.payload_md
            if not payload.strip():
                raise ValidationFailedError("The suggestion is empty.")
            origin = "ai_assisted" if data.edited_md is not None and data.edited_md != p.payload_md else "ai_generated"
            current = head.source_md if head is not None else ""
            source = bookmd.normalize_source(_apply(p.mode, current, payload, p.selection_start, p.selection_end))
            prov = json.loads(p.provenance_json or "{}")
            note = f"{prov.get('task', 'AI')} by {prov.get('model', '?')} ({prov.get('provider_label', '?')})"
            revision = chapters.append_revision(
                s, ctx, chapter, source, origin=origin, note=note[:500], accepted_proposal_id=p.id
            )
            p.status, p.decided_at, p.accepted_revision_id = "accepted", ctx.clock.iso(), revision.id
            evidence.on_proposal_decided(s, ctx, p.id, accepted=True, revision_id=revision.id)
            activity.record(
                s,
                ctx,
                kind="ai_suggestion_accepted",
                project_id=project_id,
                ref_type="chapter_revision",
                ref_id=revision.id,
                summary=f"Applied an AI suggestion to “{chapter.title}” (revision {revision.revision_no})",
            )
            s.flush()
            content = chapters._content_out(chapter, revision)
            from pbs_core.contracts import ChapterSaveOut

            return AcceptOut(proposal=_proposal_out(s, p), save=ChapterSaveOut(created=True, content=content))
    except IntegrityError as exc:  # unique index: a concurrent accept already applied it
        raise ConflictError("This suggestion was already applied.", extra={"reason": "already_applied"}) from exc


def reject_proposal(ctx: AppContext, project_id: str, proposal_id: str) -> ProposalOut:
    with ctx.db.tx() as s:
        p = _require_proposal(s, project_id, proposal_id)
        if p.status != "pending":
            raise ConflictError(f"This suggestion was already {p.status}.")
        p.status, p.decided_at = "rejected", ctx.clock.iso()
        evidence.on_proposal_decided(s, ctx, p.id, accepted=False, revision_id=None)
        s.flush()
        return _proposal_out(s, p)


# ---------- usage ----------


def usage(ctx: AppContext, *, project_id: str | None = None, limit: int = 200) -> UsageOut:
    stmt = (
        select(UsageRecord, Project.title)
        .outerjoin(Project, Project.id == UsageRecord.project_id)
        .order_by(UsageRecord.created_at.desc())
        .limit(max(1, min(limit, 1000)))
    )
    if project_id:
        stmt = stmt.where(UsageRecord.project_id == project_id)
    with ctx.db.tx() as s:
        rows = s.execute(stmt).all()
        out = [
            UsageRowOut(
                id=u.id,
                job_id=u.job_id,
                project_id=u.project_id,
                project_title=title,
                provider_kind=u.provider_kind,
                model_name=u.model_name,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                reported_by_provider=bool(u.reported_by_provider),
                cost_amount=u.cost_amount,
                currency=u.currency,
                price_basis=u.price_basis,
                attempt=u.attempt,
                created_at=u.created_at,
            )
            for u, title in rows
        ]
    groups: dict[str | None, list[UsageRowOut]] = defaultdict(list)
    for r in out:
        groups[r.currency].append(r)
    totals = []
    for cur, items in groups.items():
        known = [Decimal(r.cost_amount) for r in items if r.cost_amount is not None]
        totals.append(
            UsageTotalOut(
                currency=cur,
                amount=str(sum(known, Decimal(0))) if known else None,
                calls=len(items),
                unknown_cost_calls=sum(1 for r in items if r.cost_amount is None),
            )
        )
    return UsageOut(rows=out, totals=totals)
