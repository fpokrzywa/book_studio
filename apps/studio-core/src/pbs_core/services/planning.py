"""Planning: New Book wizard, book brief, research, outline versions, skeleton, generation runs.

Guarantees (docs/ADR/0006-planning.md):
* No market figure is ever invented: AI brainstorms lose any such statement, provider results carry
  bibliographic metadata only, and "measured" findings must name their source.
* Research search runs only when the author turned a provider on and cloud access is allowed; any
  failure is explicit and adds nothing.
* AI outlines are always new *proposed* versions; the author's draft and the approved outline are
  never overwritten, and locked entries are carried over.
* Only an approved outline is applied; applying never touches prose or revision history.
* Chapter drafting (one chapter or the whole book) needs an applied approved outline, respects locks,
  approvals and existing text, stays within the chapter limit and the hard budget cap, and produces
  suggestions for review, never applied text.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_ai import JobOut
from pbs_core.contracts_planning import (
    ApplyOut,
    BriefIn,
    BriefOut,
    FindingIn,
    FindingOut,
    FindingPatch,
    NewBookIn,
    NewBookOut,
    OutlineDraftIn,
    OutlineGenerateIn,
    OutlineOut,
    PlanChapterOut,
    PlanEstimateOut,
    PlanRequestIn,
    ResearchHitOut,
    ResearchIdeasIn,
    ResearchProviderOut,
    ResearchProvidersIn,
    ResearchSearchIn,
    ResearchSearchOut,
    RunOut,
    SaveHitIn,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.jobs import planning_prompts as pp
from pbs_core.knowledge import retrieval
from pbs_core.planning import outline as ol
from pbs_core.planning import skeleton
from pbs_core.planning.research import ResearchError, has_metric_claim, provider_search
from pbs_core.providers import registry
from pbs_core.providers.egress import EgressPermit
from pbs_core.providers.research_adapters import LABELS
from pbs_core.services import activity, ai, costs, knowledge, projects
from pbs_core.services import writing as writing_service
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.ai_models import Job, ModelInfo, ProviderConfig, UsageRecord
from pbs_core.storage.knowledge_models import AuthorProfile
from pbs_core.storage.models import AppSetting, Chapter, ChapterDraft, Project
from pbs_core.storage.planning_models import BookBrief, GenerationRun, OutlineVersion, ResearchFinding, ResearchQuery
from pbs_core.storage.writing_models import DraftPlan

PROJECT_TO_KIND = {
    "fiction": "fiction",
    "serial": "fiction",
    "memoir": "memoir",
    "workbook": "workbook",
    "course": "manual",
    "technical": "manual",
    "nonfiction": "nonfiction",
}


class ResearchUnavailableError(ConflictError):
    code = "research_unavailable"


class BudgetBlockedError(ConflictError):
    code = "run_blocked"


# ---------- brief ----------


def _brief_out(b: BookBrief) -> BriefOut:
    return BriefOut(
        project_id=b.project_id,
        kind=b.kind,
        genre=b.genre,
        purpose=b.purpose,
        promise=b.promise,
        tone=b.tone,
        author_profile_id=b.author_profile_id,
        desired_chapters=b.desired_chapters,
        approval_preference=b.approval_preference,
        budget_cap=b.budget_cap,
        budget_currency=b.budget_currency,
        max_chapters_per_run=b.max_chapters_per_run,
        words_per_hour=b.words_per_hour,
        target_reader=b.target_reader,
        exclusions=json.loads(b.exclusions_json),
        value_proposition=b.value_proposition,
        arc_md=b.arc_md,
        arc_label="Plot arc" if b.kind == "fiction" else "Teaching arc",
        assumptions=json.loads(b.assumptions_json),
        status=b.status,
        version=b.version,
        approved_at=b.approved_at,
        updated_at=b.updated_at,
    )


def _ensure_brief(s: Session, ctx: AppContext, project: Project) -> BookBrief:
    b = s.get(BookBrief, project.id)
    if b is None:
        now = ctx.clock.iso()
        b = BookBrief(
            project_id=project.id,
            kind=PROJECT_TO_KIND.get(project.project_type, "nonfiction"),
            created_at=now,
            updated_at=now,
        )
        s.add(b)
        s.flush()
    return b


def _apply_brief(s: Session, ctx: AppContext, b: BookBrief, data: BriefIn) -> None:
    if data.author_profile_id and (
        not is_ulid(data.author_profile_id) or s.get(AuthorProfile, data.author_profile_id) is None
    ):
        raise ValidationFailedError("That author profile does not exist.")
    if data.budget_cap and not data.budget_currency:
        raise ValidationFailedError("Choose the currency of the budget cap.")
    values = data.model_dump()
    values["exclusions_json"] = json.dumps(values.pop("exclusions"))
    values["assumptions_json"] = json.dumps(values.pop("assumptions"))
    changed = any(getattr(b, k) != v for k, v in values.items())
    for k, v in values.items():
        setattr(b, k, v)
    if changed:
        b.updated_at = ctx.clock.iso()
        if b.status == "approved":
            b.status, b.version, b.approved_at = "draft", b.version + 1, None


def get_brief(ctx: AppContext, project_id: str) -> BriefOut:
    with ctx.db.tx() as s:
        return _brief_out(_ensure_brief(s, ctx, require_project(s, project_id)))


def put_brief(ctx: AppContext, project_id: str, data: BriefIn) -> BriefOut:
    with ctx.db.tx() as s:
        b = _ensure_brief(s, ctx, require_active(s, project_id))
        _apply_brief(s, ctx, b, data)
        s.flush()
        return _brief_out(b)


def approve_brief(ctx: AppContext, project_id: str) -> BriefOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        b = _ensure_brief(s, ctx, project)
        if not (b.promise or b.purpose):
            raise ValidationFailedError("Write the book's purpose or main promise before approving the brief.")
        b.status, b.approved_at = "approved", ctx.clock.iso()
        activity.record(
            s,
            ctx,
            kind="brief_approved",
            project_id=project_id,
            summary=f"Approved the brief for “{project.title}” (version {b.version})",
        )
        s.flush()
        return _brief_out(b)


def new_book(ctx: AppContext, data: NewBookIn) -> NewBookOut:
    project = projects.create_project(ctx, data.project)
    with ctx.db.tx() as s:
        p = require_project(s, project.id)
        b = _ensure_brief(s, ctx, p)
        _apply_brief(s, ctx, b, data.brief)
        s.flush()
        brief = _brief_out(b)
    for lid in dict.fromkeys(data.shared_library_ids):
        knowledge.link(ctx, project.id, lid, True)
    return NewBookOut(project=projects.get_project(ctx, project.id), brief=brief)


# ---------- research providers and findings ----------


def _providers_setting(s: Session) -> dict[str, bool]:
    row = s.get(AppSetting, "research_providers")
    data = json.loads(row.value_json) if row else {}
    return {"openlibrary": bool(data.get("openlibrary")), "mock": bool(data.get("mock"))}


def list_providers(ctx: AppContext) -> list[ResearchProviderOut]:
    with ctx.db.tx() as s:
        cfg = _providers_setting(s)
    cloud = registry.privacy_mode(ctx) == "cloud_allowed"  # its own transaction: never nest
    out = [
        ResearchProviderOut(
            kind="openlibrary",
            label=LABELS["openlibrary"],
            enabled=cfg["openlibrary"],
            sends="Only the search words you type (never your manuscript) are sent to openlibrary.org.",
            available=cfg["openlibrary"] and cloud,
            unavailable_reason=None if cloud else "Local-only mode is on: internet research is off.",
        )
    ]
    if ctx.settings.env != "prod":
        out.append(
            ResearchProviderOut(
                kind="mock",
                label=LABELS["mock"],
                enabled=cfg["mock"],
                sends="Nothing leaves this computer.",
                available=cfg["mock"],
                unavailable_reason=None,
            )
        )
    return out


def set_providers(ctx: AppContext, data: ResearchProvidersIn) -> list[ResearchProviderOut]:
    if data.mock and ctx.settings.env == "prod":
        raise ValidationFailedError("The test catalogue is only available in development.")
    with ctx.db.tx() as s:
        row = s.get(AppSetting, "research_providers")
        value = json.dumps({"openlibrary": data.openlibrary, "mock": data.mock})
        if row is None:
            s.add(AppSetting(key="research_providers", value_json=value))
        else:
            row.value_json = value
        activity.record(
            s,
            ctx,
            kind="research_providers_changed",
            summary=f"Research search: Open Library {'on' if data.openlibrary else 'off'}",
        )
    return list_providers(ctx)


def _finding_out(f: ResearchFinding) -> FindingOut:
    return FindingOut(
        id=f.id,
        kind=f.kind,
        origin=f.origin,
        evidence="measured" if f.kind == "measured" else "heuristic",
        text=f.text,
        provider=f.provider,
        source_title=f.source_title,
        source_url=f.source_url,
        source_date=f.source_date,
        retrieved_at=f.retrieved_at,
        meta=json.loads(f.meta_json),
        metrics=json.loads(f.metrics_json),
        flags=json.loads(f.flags_json),
        selected=bool(f.selected),
        archived=f.archived_at is not None,
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


def _flags_for(kind: str, text: str, existing: list[str]) -> list[str]:
    flags = [x for x in existing if x != "unsourced_metric"]
    if kind != "measured" and has_metric_claim(text):
        flags.append("unsourced_metric")
    return flags


def list_findings(ctx: AppContext, project_id: str, include_archived: bool = False) -> list[FindingOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        stmt = select(ResearchFinding).where(ResearchFinding.project_id == project_id)
        if not include_archived:
            stmt = stmt.where(ResearchFinding.archived_at.is_(None))
        return [_finding_out(f) for f in s.scalars(stmt.order_by(ResearchFinding.created_at.desc())).all()]


def add_finding(ctx: AppContext, project_id: str, data: FindingIn) -> FindingOut:
    if data.kind == "measured" and not (data.source_url and data.source_title):
        raise ValidationFailedError(
            "Measured evidence needs the source's name and web address. Otherwise save it as a note."
        )
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        require_active(s, project_id)
        f = ResearchFinding(
            id=ctx.ids.new(),
            project_id=project_id,
            kind=data.kind,
            origin="author",
            text=data.text,
            source_title=data.source_title,
            source_url=data.source_url,
            source_date=data.source_date,
            retrieved_at=now if data.source_url else None,
            meta_json=json.dumps(data.meta),
            flags_json=json.dumps(_flags_for(data.kind, data.text, [])),
            created_at=now,
            updated_at=now,
        )
        s.add(f)
        s.flush()
        return _finding_out(f)


def patch_finding(ctx: AppContext, project_id: str, finding_id: str, data: FindingPatch) -> FindingOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        f = s.get(ResearchFinding, finding_id) if is_ulid(finding_id) else None
        if f is None or f.project_id != project_id:
            raise NotFoundError("Finding not found in this book.")
        fields = data.model_fields_set
        for name in ("text", "source_title", "source_url", "source_date"):
            if name in fields:
                if f.origin != "author" and name != "text":
                    raise ValidationFailedError("The source of a provider or AI finding cannot be changed.")
                setattr(f, name, getattr(data, name))
        if data.kind is not None:
            if data.kind == "measured" and f.origin == "ai_brainstorm":
                raise ValidationFailedError("An AI brainstorm cannot become measured evidence.")
            f.kind = data.kind
        if f.kind == "measured" and not (f.provider or (f.source_url and f.source_title)):
            raise ValidationFailedError("Measured evidence needs the source's name and web address.")
        if data.selected is not None:
            f.selected = 1 if data.selected else 0
        if data.archived is not None:
            f.archived_at = ctx.clock.iso() if data.archived else None
        f.flags_json = json.dumps(_flags_for(f.kind, f.text, json.loads(f.flags_json)))
        f.updated_at = ctx.clock.iso()
        s.flush()
        return _finding_out(f)


def search(ctx: AppContext, project_id: str, data: ResearchSearchIn) -> ResearchSearchOut:
    """Search a public source. Off, blocked or failing providers fail loudly and add nothing."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        cfg = _providers_setting(s)
    if not cfg.get(data.provider):
        raise ResearchUnavailableError(
            f"{LABELS[data.provider]} is not turned on. Turn it on in AI settings, or add findings by hand. "
            "Nothing was searched.",
            extra={"reason": "not_configured"},
        )
    if data.provider == "mock" and ctx.settings.env == "prod":
        raise ResearchUnavailableError("The test catalogue is not available.", extra={"reason": "not_configured"})
    cloud = registry.privacy_mode(ctx) == "cloud_allowed"
    permit = EgressPermit(
        data.provider,
        cloud_allowed=cloud,
        reason_if_blocked=f"Local-only mode is on, so {LABELS[data.provider]} cannot be searched. Nothing was sent.",
    )
    status, error, hits = "ok", None, []
    try:
        hits = provider_search(data.provider, data.query, permit=permit, transport=ctx.http_transport)
    except ResearchError as exc:
        status, error = ("blocked" if exc.code == "blocked" else "failed"), exc.message
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        q = ResearchQuery(
            id=ctx.ids.new(),
            project_id=project_id,
            provider=data.provider,
            query=data.query,
            status=status,
            result_count=len(hits),
            error=error,
            created_at=now,
            results_json=json.dumps([h.__dict__ for h in hits]),
        )
        s.add(q)
        activity.record(
            s,
            ctx,
            kind="research_search",
            project_id=project_id,
            summary=f"Searched {LABELS[data.provider]}: {status}, {len(hits)} result(s)",
        )
    if status != "ok":
        raise ResearchUnavailableError(
            f"{error} Your findings are unchanged; you can add one by hand.", extra={"reason": status}
        )
    return ResearchSearchOut(
        query_id=q.id,
        provider=data.provider,
        hits=[
            ResearchHitOut(
                index=i,
                title=h.title,
                url=h.url,
                authors=h.authors,
                year=h.year,
                publisher=h.publisher,
                subjects=h.subjects,
                source_label=h.source_label,
            )
            for i, h in enumerate(hits)
        ],
        note="Bibliographic details only. No sales, rankings, ratings or demand figures are collected.",
    )


def save_hit(ctx: AppContext, project_id: str, data: SaveHitIn) -> FindingOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        q = s.get(ResearchQuery, data.query_id) if is_ulid(data.query_id) else None
        if q is None or q.project_id != project_id or q.status != "ok":
            raise NotFoundError("That search result is not available. Search again.")
        results = json.loads(q.results_json)
        if data.index >= len(results):
            raise NotFoundError("That search result is not available. Search again.")
        h = results[data.index]
        who = ", ".join(h.get("authors") or []) or "author not listed"
        text = f"{h['title']} by {who}" + (f" ({h['year']})" if h.get("year") else "")
        if h.get("subjects"):
            text += "\nSubjects listed: " + ", ".join(h["subjects"])
        now = ctx.clock.iso()
        f = ResearchFinding(
            id=ctx.ids.new(),
            project_id=project_id,
            kind=data.kind,
            origin="provider",
            provider=q.provider,
            text=text,
            source_title=h.get("source_label"),
            source_url=h.get("url"),
            source_date=h.get("year"),
            retrieved_at=q.created_at,
            meta_json=json.dumps(
                {
                    k: v
                    for k, v in {
                        "title": h["title"],
                        "author": who,
                        "publisher": h.get("publisher"),
                        "year": h.get("year"),
                    }.items()
                    if v
                }
            ),
            flags_json="[]",
            created_at=now,
            updated_at=now,
        )
        s.add(f)
        s.flush()
        return _finding_out(f)


def _brief_dict(s: Session, project: Project, b: BookBrief) -> dict[str, Any]:
    out = {k: v for k, v in _brief_out(b).model_dump().items() if k not in ("project_id", "status", "updated_at")}
    out["audience"] = project.audience
    out["language"] = project.language
    return out


def _findings_for_prompt(s: Session, project_id: str, ids: list[str] | None) -> list[dict[str, Any]]:
    stmt = select(ResearchFinding).where(
        ResearchFinding.project_id == project_id, ResearchFinding.archived_at.is_(None)
    )
    stmt = stmt.where(ResearchFinding.id.in_(ids)) if ids else stmt.where(ResearchFinding.selected == 1)
    return [
        {
            "text": f.text,
            "evidence": "measured" if f.kind == "measured" else "heuristic",
            "source_title": f.source_title,
        }
        for f in s.scalars(stmt.order_by(ResearchFinding.created_at)).all()[:30]
    ]


def research_ideas(ctx: AppContext, project_id: str, data: ResearchIdeasIn) -> JobOut:
    key = f"{project_id}:{data.client_request_id}"
    with ctx.db.tx() as s:
        if (existing := ai.find_job(s, key)) is not None:
            return ai.job_out(s, existing)
        project = require_active(s, project_id)
        b = _ensure_brief(s, ctx, project)
        provider, model, temp, max_out = ai.resolve_model(s, "research", data.provider_id, data.model_name)
        if blocked := ai.cloud_block_reason(s, project_id, provider):
            raise ai.CloudBlockedError(blocked, extra={"reason": "cloud_blocked"})
        inp: dict[str, Any] = {
            "kind": "research_ideas",
            "what": data.what,
            "title": project.title,
            "brief": _brief_dict(s, project, b),
            "findings": _findings_for_prompt(s, project_id, None),
            "instruction": data.instruction,
        }
        built = pp.research(
            what=data.what,
            title=project.title,
            brief=inp["brief"],
            findings=inp["findings"],
            instruction=data.instruction,
        )
        est = costs.estimate(s, provider, model, len(built.system) + len(built.user), max_out)
        job = ai.queue_planning_job(
            s,
            ctx,
            project_id=project_id,
            task="research",
            provider=provider,
            model=model,
            temperature=temp,
            max_out=max_out,
            inp=inp,
            template=built.template,
            estimate=est,
            key=key,
            summary=f"brainstorm research {data.what}",
        )
        out = ai.job_out(s, job)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


# ---------- outline versions ----------


def _fiction(s: Session, ctx: AppContext, project: Project) -> bool:
    return _ensure_brief(s, ctx, project).kind == "fiction"


def _outline_out(s: Session, o: OutlineVersion, words_per_hour: int) -> OutlineOut:
    nodes = json.loads(o.nodes_json)
    return OutlineOut(
        id=o.id,
        version_no=o.version_no,
        status=o.status,
        origin=o.origin,
        nodes=nodes,
        totals=ol.totals(nodes, words_per_hour),
        based_on_id=o.based_on_id,
        brief_version=o.brief_version,
        research_ids=json.loads(o.research_ids_json),
        job_id=o.job_id,
        provenance=json.loads(o.provenance_json),
        note=o.note,
        approved_at=o.approved_at,
        applied_at=o.applied_at,
        apply_report=json.loads(o.apply_report_json) if o.apply_report_json else None,
        created_at=o.created_at,
        updated_at=o.updated_at,
    )


def _wph(s: Session, project_id: str) -> int:
    b = s.get(BookBrief, project_id)
    return b.words_per_hour if b else 500


def list_outlines(ctx: AppContext, project_id: str) -> list[OutlineOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.scalars(
            select(OutlineVersion)
            .where(OutlineVersion.project_id == project_id)
            .order_by(OutlineVersion.version_no.desc())
        ).all()
        return [_outline_out(s, o, _wph(s, project_id)) for o in rows]


def _require_outline(s: Session, project_id: str, outline_id: str) -> OutlineVersion:
    o = s.get(OutlineVersion, outline_id) if is_ulid(outline_id) else None
    if o is None or o.project_id != project_id:
        raise NotFoundError("Outline version not found in this book.")
    return o


def _next_no(s: Session, project_id: str) -> int:
    return (
        s.scalar(select(func.max(OutlineVersion.version_no)).where(OutlineVersion.project_id == project_id)) or 0
    ) + 1


def save_draft(ctx: AppContext, project_id: str, data: OutlineDraftIn) -> OutlineOut:
    """The author's working outline. Saving never changes a proposed or approved version."""
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        nodes = ol.normalise(data.nodes, fiction=_fiction(s, ctx, project), new_id=ctx.ids.new)
        draft = s.scalars(
            select(OutlineVersion).where(OutlineVersion.project_id == project_id, OutlineVersion.status == "draft")
        ).first()
        if draft is None:
            draft = OutlineVersion(
                id=ctx.ids.new(),
                project_id=project_id,
                version_no=_next_no(s, project_id),
                status="draft",
                origin="author",
                nodes_json="[]",
                based_on_id=data.based_on_id,
                created_at=now,
                updated_at=now,
            )
            s.add(draft)
        draft.nodes_json, draft.note, draft.updated_at = json.dumps(nodes), data.note, now
        if data.based_on_id:
            draft.based_on_id = data.based_on_id
        s.flush()
        return _outline_out(s, draft, _wph(s, project_id))


def edit_version(ctx: AppContext, project_id: str, outline_id: str) -> OutlineOut:
    """Start (or replace) the working draft from any version, e.g. to edit an AI proposal."""
    with ctx.db.tx() as s:
        o = _require_outline(s, project_id, outline_id)
        nodes = json.loads(o.nodes_json)
    return save_draft(
        ctx, project_id, OutlineDraftIn(nodes=nodes, based_on_id=outline_id, note=f"Edited from version {o.version_no}")
    )


def approve_outline(ctx: AppContext, project_id: str, outline_id: str) -> OutlineOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        o = _require_outline(s, project_id, outline_id)
        if o.status not in ("draft", "proposed"):
            raise ConflictError(f"This outline version is {o.status}; only a draft or a proposal can be approved.")
        nodes = json.loads(o.nodes_json)
        if not any(n["kind"] == "chapter" for n, _, _ in ol.walk(nodes)):
            raise ValidationFailedError("The outline needs at least one chapter.")
        for old in s.scalars(
            select(OutlineVersion).where(OutlineVersion.project_id == project_id, OutlineVersion.status == "approved")
        ).all():
            old.status = "superseded"
        s.flush()
        b = _ensure_brief(s, ctx, project)
        o.status, o.approved_at, o.brief_version, o.updated_at = "approved", ctx.clock.iso(), b.version, ctx.clock.iso()
        activity.record(
            s,
            ctx,
            kind="outline_approved",
            project_id=project_id,
            ref_type="outline",
            ref_id=o.id,
            summary=f"Approved outline version {o.version_no} for “{project.title}”",
        )
        s.flush()
        return _outline_out(s, o, _wph(s, project_id))


def reject_outline(ctx: AppContext, project_id: str, outline_id: str) -> OutlineOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        o = _require_outline(s, project_id, outline_id)
        if o.status != "proposed":
            raise ConflictError("Only a proposal can be rejected.")
        o.status, o.updated_at = "rejected", ctx.clock.iso()
        s.flush()
        return _outline_out(s, o, _wph(s, project_id))


def apply_outline(ctx: AppContext, project_id: str, outline_id: str) -> ApplyOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        o = _require_outline(s, project_id, outline_id)
        if o.status != "approved":
            raise ConflictError("Approve this outline before applying it to the manuscript.")
        report = skeleton.apply(s, ctx, project_id, json.loads(o.nodes_json))
        o.applied_at = o.updated_at = ctx.clock.iso()
        o.apply_report_json = json.dumps(report)
        activity.record(
            s,
            ctx,
            kind="outline_applied",
            project_id=project_id,
            ref_type="outline",
            ref_id=o.id,
            summary=f"Applied outline version {o.version_no} to “{project.title}”: {len(report['created'])} new, "
            f"{len(report['updated'])} updated; no prose was changed",
        )
        s.flush()
        return ApplyOut(outline=_outline_out(s, o, _wph(s, project_id)), report=report)


def generate_outline(ctx: AppContext, project_id: str, data: OutlineGenerateIn) -> JobOut:
    key = f"{project_id}:{data.client_request_id}"
    with ctx.db.tx() as s:
        if (existing := ai.find_job(s, key)) is not None:
            return ai.job_out(s, existing)
        project = require_active(s, project_id)
        b = _ensure_brief(s, ctx, project)
        if not (b.promise or b.purpose):
            raise ValidationFailedError("Write the book's purpose or main promise in the brief first.")
        provider, model, temp, max_out = ai.resolve_model(
            s, "outline", data.provider_id, data.model_name, data.max_output_tokens
        )
        if blocked := ai.cloud_block_reason(s, project_id, provider):
            raise ai.CloudBlockedError(blocked, extra={"reason": "cloud_blocked"})
        base = s.scalars(
            select(OutlineVersion)
            .where(OutlineVersion.project_id == project_id, OutlineVersion.status.in_(("draft", "approved")))
            .order_by(OutlineVersion.status.desc(), OutlineVersion.version_no.desc())  # prefer the draft
        ).first()
        locked = [n["title"] for n in json.loads(base.nodes_json) if n.get("locked")] if base else []
        brief = _brief_dict(s, project, b)
        findings = _findings_for_prompt(s, project_id, data.research_ids or None)
        has_sources = bool(retrieval.usable_source_ids(s, project_id))
        inp = {
            "kind": "outline",
            "title": project.title,
            "brief": brief,
            "findings": findings,
            "research_ids": data.research_ids,
            "desired_chapters": b.desired_chapters,
            "target_words": project.target_word_count,
            "locked_titles": locked,
            "instruction": data.instruction,
            "based_on_id": base.id if base else None,
            "brief_version": b.version,
            "default_citations_min": 1 if (has_sources and b.kind != "fiction") else 0,
        }
        built = pp.outline(
            title=project.title,
            brief=brief,
            findings=findings,
            desired_chapters=b.desired_chapters,
            target_words=project.target_word_count,
            locked_titles=locked,
            instruction=data.instruction,
        )
        est = costs.estimate(s, provider, model, len(built.system) + len(built.user), max_out)
        job = ai.queue_planning_job(
            s,
            ctx,
            project_id=project_id,
            task="outline",
            provider=provider,
            model=model,
            temperature=temp,
            max_out=max_out,
            inp=inp,
            template=built.template,
            estimate=est,
            key=key,
            summary="propose an outline",
        )
        out = ai.job_out(s, job)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


# ---------- estimates and generation runs ----------


def _approved(s: Session, project_id: str) -> OutlineVersion:
    o = s.scalars(
        select(OutlineVersion).where(OutlineVersion.project_id == project_id, OutlineVersion.status == "approved")
    ).first()
    if o is None or o.applied_at is None:
        raise ConflictError(
            "Approve an outline and apply it to the manuscript before drafting chapters.",
            extra={"reason": "outline_not_approved"},
        )
    return o


def _instruction(b: BookBrief, node: dict[str, Any], fiction: bool) -> str:
    lines = [f"Write the first full draft of this chapter: {node['title']}."]
    if node.get("goal"):
        lines.append(f"Chapter goal: {node['goal']}")
    sections = [c for c in node.get("children", []) if c["kind"] == "section"]
    if sections:
        lines.append("Cover these sections in order, each under a '## ' heading with its title:")
        lines += [f"- {c['title']}: {c.get('goal', '')}".rstrip(": ") for c in sections]
    if b.target_reader:
        lines.append(f"Reader: {b.target_reader}")
    if b.promise:
        lines.append(f"The book's promise: {b.promise}")
    if b.tone:
        lines.append(f"Tone: {b.tone}")
    excl = json.loads(b.exclusions_json)
    if excl:
        lines.append("Leave out: " + "; ".join(excl))
    req = node.get("requirements", {})
    if fiction:
        for label, key in (
            ("Plot points", "plot_points"),
            ("Characters who appear", "characters"),
            ("Continuity to keep", "continuity"),
        ):
            if req.get(key):
                lines.append(f"{label}: " + "; ".join(req[key]))
    else:
        if req.get("citations_min"):
            lines.append(f"Support at least {req['citations_min']} factual statement(s) with the provided sources.")
        if req.get("notes"):
            lines.append("Requirements: " + "; ".join(req["notes"]))
    if node.get("notes"):
        lines.append(f"Author's notes: {node['notes']}")
    text = "\n".join(lines)
    return text[:3900]


def _rate(s: Session, provider_id: str, model: str) -> float | None:
    """Measured output tokens per second for this model, from this workspace's finished jobs."""
    rows = s.execute(
        select(Job.started_at, Job.finished_at, UsageRecord.output_tokens)
        .join(UsageRecord, UsageRecord.job_id == Job.id)
        .where(
            Job.provider_config_id == provider_id,
            Job.model_name == model,
            Job.status == "succeeded",
            UsageRecord.output_tokens.is_not(None),
        )
        .order_by(Job.finished_at.desc())
        .limit(20)
    ).all()
    tokens, seconds = 0, 0.0
    for start, end, out in rows:
        if start and end and out:
            dt = (
                datetime.fromisoformat(end.replace("Z", "+00:00"))
                - datetime.fromisoformat(start.replace("Z", "+00:00"))
            ).total_seconds()
            if dt > 0:
                tokens, seconds = tokens + int(out), seconds + dt
    return tokens / seconds if seconds > 0 and tokens > 0 else None


def _plan_run(
    ctx: AppContext, s: Session, project_id: str, data: PlanRequestIn
) -> tuple[PlanEstimateOut, list[tuple[Chapter, dict[str, Any]]], OutlineVersion, ProviderConfig]:
    project = require_active(s, project_id)
    b = _ensure_brief(s, ctx, project)
    o = _approved(s, project_id)
    index = ol.node_index(json.loads(o.nodes_json))
    provider, model, _temp, max_out_default = ai.resolve_model(s, "draft", data.provider_id, data.model_name)
    info = s.scalars(
        select(ModelInfo).where(ModelInfo.provider_config_id == provider.id, ModelInfo.name == model)
    ).first()
    chapters = s.scalars(
        select(Chapter).where(
            Chapter.project_id == project_id, Chapter.archived_at.is_(None), Chapter.outline_node_id.is_not(None)
        )
    ).all()
    linked = [
        (c, index[c.outline_node_id][0])
        for c in chapters
        if c.outline_node_id in index and index[c.outline_node_id][0]["kind"] == "chapter"
    ]
    order = {nid: i for i, nid in enumerate(index)}
    linked.sort(key=lambda t: order[t[1]["id"]])
    if data.mode == "one_chapter":
        if len(data.chapter_ids) != 1:
            raise ValidationFailedError("Choose exactly one chapter.")
        linked = [t for t in linked if t[0].id == data.chapter_ids[0]]
        if not linked:
            raise NotFoundError("That chapter is not part of the approved outline.")
    elif data.chapter_ids:
        wanted = set(data.chapter_ids)
        linked = [t for t in linked if t[0].id in wanted]
    rows: list[PlanChapterOut] = []
    eligible: list[tuple[Chapter, dict[str, Any]]] = []
    total_cost: Decimal | None = Decimal(0)
    currency: str | None = None
    notes: set[str] = set()
    out_tokens_total = 0
    for c, node in linked:
        reason = None
        if c.locked or c.status == "approved":
            reason = "Locked or approved: left as it is."
        elif _drafting(s, c.id):
            reason = "Already has a draft in progress: finish or cancel it first."
        elif s.get(ChapterDraft, c.id) is not None:
            reason = "Has unsaved changes: save or discard them first."
        elif data.mode == "entire_book" and c.head_revision_no > 0:
            reason = "Already has text: your writing is kept (draft it on its own with 'one chapter')."
        target = node.get("target_words") or c.target_word_count
        # Phase 06: one model call per outline section, each within the token budget.
        split = writing_service.section_split(
            node, c, info.max_output_tokens if info and info.max_output_tokens else None, max_out_default
        )
        max_out = sum(int(x["max_out"]) for x in split)
        prompt_chars = len(split) * data.token_budget * 4
        est: dict[str, Any] = costs.estimate(s, provider, model, prompt_chars, max_out)
        rows.append(
            PlanChapterOut(
                chapter_id=c.id,
                title=c.title,
                eligible=reason is None,
                reason=reason,
                target_words=target,
                input_tokens=int(est["input_tokens"]),
                max_output_tokens=max_out,
                sections=len(split),
            )
        )
        if reason is not None:
            continue
        eligible.append((c, node))
        out_tokens_total += max_out
        notes.add(str(est["cost_note"]))
        if est["cost_upper_bound"] is None or total_cost is None:
            total_cost = None
        else:
            total_cost += Decimal(str(est["cost_upper_bound"]))
            currency = est["currency"] or currency
    local = registry.is_local(provider)
    rate = _rate(s, provider.id, model)
    minutes = round(out_tokens_total / rate / 60, 1) if rate and eligible else None
    blocked = ai.cloud_block_reason(s, project_id, provider)
    if not blocked and not eligible:
        blocked = "No chapter can be drafted: every chapter is locked, approved or already has text."
    if not blocked and len(eligible) > b.max_chapters_per_run:
        blocked = (
            f"This would draft {len(eligible)} chapters, but the limit per run is {b.max_chapters_per_run}. "
            "Raise the limit in the brief or choose fewer chapters."
        )
    if not blocked and b.budget_cap and not local:
        if total_cost is None:
            blocked = "The cost cannot be estimated (no price entered for this model), so the budget cap cannot be honoured. Enter the model's price in AI settings or remove the cap."
        elif currency and b.budget_currency and currency != b.budget_currency:
            blocked = f"The model is priced in {currency}, but the budget cap is in {b.budget_currency}."
        elif total_cost > Decimal(b.budget_cap):
            blocked = f"The estimated cost (up to {total_cost} {currency or ''}) is above the budget cap of {b.budget_cap} {b.budget_currency or ''}."
    est_out = PlanEstimateOut(
        mode=data.mode,
        provider_label=provider.label,
        model_name=model,
        provider_local=local,
        chapters=rows,
        eligible_count=len(eligible),
        chapter_limit=b.max_chapters_per_run,
        cost_upper_bound="0" if local else (str(total_cost) if total_cost is not None else None),
        currency=None if local else currency,
        cost_note="Local model: no API charge." if local else " ".join(sorted(notes)) or "Estimate.",
        minutes_estimate=minutes,
        time_note=(
            f"Estimate from this model's measured speed here ({rate:.1f} tokens per second), for the longest possible answers."
            if rate
            else "No timing history for this model yet, so time is unknown."
        ),
        budget_cap=b.budget_cap,
        budget_currency=b.budget_currency,
        blocked_reason=blocked,
    )
    return est_out, eligible, o, provider


def estimate_run(ctx: AppContext, project_id: str, data: PlanRequestIn) -> PlanEstimateOut:
    with ctx.db.tx() as s:
        est, _, _, _ = _plan_run(ctx, s, project_id, data)
        return est


def _drafting(s: Session, chapter_id: str) -> bool:
    return (
        s.scalars(
            select(DraftPlan.id).where(
                DraftPlan.chapter_id == chapter_id,
                DraftPlan.status.in_(("waiting", "running", "paused", "awaiting_review")),
            )
        ).first()
        is not None
    )


def _run_out(s: Session, r: GenerationRun) -> RunOut:
    ids = json.loads(r.job_ids_json)
    status = r.status
    plans = writing_service.run_plans(s, r.id)
    if status == "running" and plans:
        if all(p.status in ("ready", "cancelled") for p in plans):
            status = "done"
    elif status == "running" and ids:
        active = s.scalar(
            select(func.count()).select_from(Job).where(Job.id.in_(ids), Job.status.in_(("queued", "running")))
        )
        if not active:
            status = "done"
    return RunOut(
        id=r.id,
        mode=r.mode,
        status=status,
        job_ids=ids,
        plan_ids=[p.id for p in plans],
        skipped=json.loads(r.skipped_json),
        estimate=json.loads(r.estimate_json),
        budget_cap=r.budget_cap,
        currency=r.currency,
        spent=r.spent,
        unknown_cost_calls=r.unknown_cost_calls,
        stop_reason=r.stop_reason,
        created_at=r.created_at,
        finished_at=r.finished_at,
    )


def start_run(ctx: AppContext, project_id: str, data: PlanRequestIn) -> RunOut:
    with ctx.db.tx() as s:
        est, eligible, o, _provider = _plan_run(ctx, s, project_id, data)
        if est.blocked_reason:
            raise BudgetBlockedError(est.blocked_reason, extra={"reason": "blocked"})
        b = _ensure_brief(s, ctx, require_project(s, project_id))
        fiction = b.kind == "fiction"
        run = GenerationRun(
            id=ctx.ids.new(),
            project_id=project_id,
            mode=data.mode,
            status="running",
            outline_version_id=o.id,
            budget_cap=None if est.provider_local else b.budget_cap,
            currency=b.budget_currency or est.currency,
            estimate_json=est.model_dump_json(),
            skipped_json=json.dumps(
                [
                    {"chapter_id": r.chapter_id, "title": r.title, "reason": r.reason or ""}
                    for r in est.chapters
                    if not r.eligible
                ]
            ),
            created_at=ctx.clock.iso(),
        )
        s.add(run)
        s.flush()
        provider_obj, model, temperature, max_out_default = ai.resolve_model(
            s, "draft", data.provider_id, data.model_name
        )
        options = {
            "use_sources": data.use_sources,
            "use_interview": data.use_interview or b.kind == "memoir",
            "voice_profile_id": b.author_profile_id,
            "fiction": fiction,
        }
        for i, (c, node) in enumerate(eligible):
            writing_service.create_plan(
                s,
                ctx,
                project_id=project_id,
                chapter=c,
                node=node,
                outline_version_id=o.id,
                run_id=run.id,
                run_order=i,
                provider=provider_obj,
                model=model,
                temperature=temperature,
                default_out=max_out_default,
                token_budget=data.token_budget,
                review_gate=data.review_gate,
                options=options,
                start=i == 0,
            )
        run_id = run.id
    with ctx.db.tx() as s:
        run2 = s.get(GenerationRun, run_id)
        if run2 is None:  # pragma: no cover - created above
            raise NotFoundError("Run not found.")
        activity.record(
            s,
            ctx,
            kind="generation_run_started",
            project_id=project_id,
            ref_type="run",
            ref_id=run_id,
            summary=f"Started drafting {len(eligible)} chapter(s) section by section "
            f"({data.mode.replace('_', ' ')}); each chapter waits for your review",
        )
        s.flush()
        out = _run_out(s, run2)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


def list_runs(ctx: AppContext, project_id: str) -> list[RunOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.scalars(
            select(GenerationRun)
            .where(GenerationRun.project_id == project_id)
            .order_by(GenerationRun.created_at.desc())
        ).all()
        return [_run_out(s, r) for r in rows]


def stop_run(ctx: AppContext, project_id: str, run_id: str) -> RunOut:
    from pbs_core.planning import runs

    with ctx.db.tx() as s:
        r = s.get(GenerationRun, run_id) if is_ulid(run_id) else None
        if r is None or r.project_id != project_id:
            raise NotFoundError("Run not found in this book.")
        if r.status == "running":
            runs.stop(s, ctx, r, "Stopped by the author.")
        s.flush()
        return _run_out(s, r)
