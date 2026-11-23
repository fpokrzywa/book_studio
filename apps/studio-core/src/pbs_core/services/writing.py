"""Phase 06 service: section-by-section draft plans, continuity memory, chapter summaries, quality
checks, AI review and the originality report."""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_ai import JobOut
from pbs_core.contracts_writing import (
    AiReviewIn,
    FactIn,
    FactOut,
    FactPatch,
    FindingPatchIn,
    JobHistoryOut,
    OriginalityOut,
    PlanOut,
    QualityFindingOut,
    QualityRunIn,
    QualityRunOut,
    SectionApproveIn,
    SectionOut,
    SummaryIn,
    SummaryOut,
    WritingSettingsIn,
    WritingSettingsOut,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.jobs import writing_exec
from pbs_core.jobs import writing_prompts as wp
from pbs_core.jobs.runner import add_log
from pbs_core.knowledge import retrieval
from pbs_core.services import activity, ai, documents
from pbs_core.services import chapters as chapter_service
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.ai_models import Job, JobLog, ModelInfo, Proposal, ProviderConfig, UsageRecord
from pbs_core.storage.knowledge_models import Source, SourceChunk
from pbs_core.storage.models import AppSetting, Chapter, ChapterDraft, ChapterRevision, Project
from pbs_core.storage.planning_models import BookBrief, GenerationRun, OutlineVersion
from pbs_core.storage.writing_models import (
    ChapterSummary,
    ContinuityFact,
    DraftPlan,
    DraftSection,
    QualityFinding,
)
from pbs_core.writing import memory, originality, pipeline, quality, store

DEFAULT_TOKEN_BUDGET = 6000
QUALITY_DISCLAIMER = (
    "These checks look for patterns. They do not decide whether a statement is true, and an AI review is a "
    "second opinion, not proof of factual correctness. You decide what to change."
)
CODE_NOTE = (
    "When allowed, Python and JSON code blocks are checked by parsing them only. Code is never run: PBS has no "
    "sandbox to execute it safely."
)
NO_SIMILARITY_PROVIDER = (
    "No external similarity provider is configured, so nothing was compared outside this computer. PBS does not "
    "ship one; it would be used only after you set one up and authorise it."
)


# ---------- plans ----------


def section_split(
    node: dict[str, Any], chapter: Chapter, max_out_cap: int | None, default_out: int
) -> list[dict[str, Any]]:
    """The sections a plan drafts, with per-section targets and output limits."""
    target = node.get("target_words") or chapter.target_word_count
    children = [c for c in node.get("children", []) if c.get("kind") == "section"]
    items = (
        [
            {"node_id": c["id"], "title": c["title"], "goal": c.get("goal", ""), "target": c.get("target_words")}
            for c in children
        ]
        if children
        else [
            {
                "node_id": node.get("id"),
                "title": chapter.title,
                "goal": node.get("goal", ""),
                "target": target,
                "heading": 0,
            }
        ]
    )
    n = len(items)
    for it in items:
        per = it["target"] or (math.ceil(target / n) if target else None)
        it["target"] = per
        out = math.ceil(per * 1.5) + 200 if per else default_out
        it["max_out"] = max(256, min(out, max_out_cap or 32_000))
        it.setdefault("heading", 1)
    return items


def create_plan(
    s: Session,
    ctx: AppContext,
    *,
    project_id: str,
    chapter: Chapter,
    node: dict[str, Any],
    outline_version_id: str,
    run_id: str | None,
    run_order: int,
    provider: ProviderConfig,
    model: str,
    temperature: float | None,
    default_out: int,
    token_budget: int,
    review_gate: str,
    options: dict[str, Any],
    start: bool,
) -> DraftPlan:
    if chapter.locked or chapter.status == "approved":
        raise ConflictError("This chapter is locked or approved; it is never drafted automatically.")
    busy = s.scalars(
        select(DraftPlan).where(
            DraftPlan.chapter_id == chapter.id,
            DraftPlan.status.in_(("waiting", "running", "paused", "awaiting_review")),
        )
    ).first()
    if busy is not None:
        raise ConflictError(f"“{chapter.title}” already has a draft in progress. Finish or cancel it first.")
    info = s.scalars(
        select(ModelInfo).where(ModelInfo.provider_config_id == provider.id, ModelInfo.name == model)
    ).first()
    items = section_split(node, chapter, info.max_output_tokens if info else None, default_out)
    now = ctx.clock.iso()
    plan = DraftPlan(
        id=ctx.ids.new(),
        project_id=project_id,
        chapter_id=chapter.id,
        run_id=run_id,
        run_order=run_order,
        outline_version_id=outline_version_id,
        outline_node_id=node.get("id"),
        status="running" if start else "waiting",
        review_gate=review_gate,
        base_revision_id=chapter.head_revision_id,
        base_revision_no=chapter.head_revision_no,
        provider_config_id=provider.id,
        provider_kind=provider.kind,
        model_name=model,
        temperature=None if temperature is None else str(temperature),
        max_output_tokens=max(it["max_out"] for it in items),
        token_budget=token_budget,
        options_json=json.dumps({**options, "requirements": node.get("requirements") or {}}),
        created_at=now,
        updated_at=now,
    )
    s.add(plan)
    s.flush()
    for i, it in enumerate(items, start=1):
        s.add(
            DraftSection(
                id=ctx.ids.new(),
                plan_id=plan.id,
                ordinal=i,
                node_id=it["node_id"],
                title=str(it["title"])[:300],
                heading=it["heading"],
                goal=str(it["goal"] or "")[:2000],
                target_words=it["target"],
                status="pending",
            )
        )
    s.flush()
    if start:
        pipeline.advance(s, ctx, plan)
    return plan


def _require_plan(s: Session, project_id: str, plan_id: str) -> DraftPlan:
    p = s.get(DraftPlan, plan_id) if is_ulid(plan_id) else None
    if p is None or p.project_id != project_id:
        raise NotFoundError("Draft plan not found in this book.")
    return p


def _next_step(s: Session, plan: DraftPlan, states: list[str]) -> str:
    if plan.status == "ready":
        return "All sections are done. The chapter draft waits for your review as one suggestion in the chapter."
    if plan.status == "cancelled":
        return "Cancelled. Finished sections are kept here; nothing was written into the chapter."
    if plan.status == "waiting":
        return "Waits for the previous chapter of this run to finish, so it can use that chapter's summary."
    if plan.status == "paused":
        return "Paused. Resume to continue with the next section; finished sections are kept."
    if plan.status == "awaiting_review":
        return "Review the finished section (edit it if you like) and approve it to continue."
    if "failed" in states or "cancelled" in states:
        return "A section failed. Retry it: finished sections are kept and not sent again."
    if "running" in states:
        return "Drafting a section now."
    return "The next section is queued."


def _plan_out(s: Session, plan: DraftPlan) -> PlanOut:
    chapter = s.get(Chapter, plan.chapter_id)
    provider = s.get(ProviderConfig, plan.provider_config_id)
    prop = s.get(Proposal, plan.proposal_id) if plan.proposal_id else None
    secs = pipeline.sections_of(s, plan.id)
    rows: list[SectionOut] = []
    states: list[str] = []
    for x in secs:
        st = pipeline.section_state(s, x)
        states.append(st)
        job = s.get(Job, x.job_id) if x.job_id else None
        rows.append(
            SectionOut(
                id=x.id,
                ordinal=x.ordinal,
                title=x.title,
                goal=x.goal,
                target_words=x.target_words,
                state=st,
                output_md=x.output_md,
                summary=x.summary,
                edited=bool(x.edited),
                reviewed=x.reviewed_at is not None,
                attempts=len(json.loads(x.job_ids_json)),
                job_ids=json.loads(x.job_ids_json),
                job_id=x.job_id,
                error=job.error_message if job is not None and st in ("failed", "cancelled") else None,
                context=json.loads(x.context_json or "{}"),
                provenance=json.loads(x.provenance_json or "{}"),
            )
        )
    return PlanOut(
        id=plan.id,
        chapter_id=plan.chapter_id,
        chapter_title=chapter.title if chapter else "?",
        run_id=plan.run_id,
        status=plan.status,
        review_gate=plan.review_gate,
        provider_label=provider.label if provider else "?",
        provider_kind=plan.provider_kind,
        model_name=plan.model_name,
        token_budget=plan.token_budget,
        max_output_tokens=plan.max_output_tokens,
        base_revision_no=plan.base_revision_no,
        proposal_id=plan.proposal_id,
        proposal_status=prop.status if prop else None,
        note=plan.note,
        sections=rows,
        next_step=_next_step(s, plan, states),
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        finished_at=plan.finished_at,
    )


def list_plans(ctx: AppContext, project_id: str, chapter_id: str | None = None) -> list[PlanOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        stmt = select(DraftPlan).where(DraftPlan.project_id == project_id)
        if chapter_id:
            stmt = stmt.where(DraftPlan.chapter_id == chapter_id)
        rows = s.scalars(stmt.order_by(DraftPlan.created_at.desc(), DraftPlan.run_order).limit(100)).all()
        return [_plan_out(s, p) for p in rows]


def get_plan(ctx: AppContext, project_id: str, plan_id: str) -> PlanOut:
    with ctx.db.tx() as s:
        return _plan_out(s, _require_plan(s, project_id, plan_id))


def _wake(ctx: AppContext) -> None:
    if ctx.jobs is not None:
        ctx.jobs.wake()


def pause_plan(ctx: AppContext, project_id: str, plan_id: str) -> PlanOut:
    with ctx.db.tx() as s:
        plan = _require_plan(s, project_id, plan_id)
        if plan.status not in ("running", "waiting", "awaiting_review"):
            raise ConflictError(f"This draft is {plan.status.replace('_', ' ')}; it cannot be paused.")
        plan.status, plan.updated_at = "paused", ctx.clock.iso()
        # A section that has not started yet goes back to the queue of pending sections.
        for sec in pipeline.sections_of(s, plan.id):
            job = s.get(Job, sec.job_id) if sec.status == "active" and sec.job_id else None
            if job is not None and job.status == "queued":
                job.status, job.stage, job.finished_at, job.cancel_requested = (
                    "cancelled",
                    "cancelled",
                    ctx.clock.iso(),
                    1,
                )
                job.error_code, job.error_message = "paused", "The draft was paused before this section started."
                add_log(s, ctx, job.id, job.error_message)
                sec.status = "pending"
        activity.record(
            s,
            ctx,
            kind="draft_paused",
            project_id=project_id,
            ref_type="draft_plan",
            ref_id=plan.id,
            summary="Paused a chapter draft",
        )
        s.flush()
        return _plan_out(s, plan)


def resume_plan(ctx: AppContext, project_id: str, plan_id: str) -> PlanOut:
    with ctx.db.tx() as s:
        plan = _require_plan(s, project_id, plan_id)
        if plan.status not in ("paused", "running"):
            raise ConflictError(f"This draft is {plan.status.replace('_', ' ')}; it cannot be resumed.")
        chapter = s.get(Chapter, plan.chapter_id)
        if chapter is None or chapter.locked or chapter.status == "approved":
            raise ConflictError("The chapter is now locked or approved, so drafting cannot continue. Cancel the draft.")
        if plan.run_id:
            run = s.get(GenerationRun, plan.run_id)
            if run is not None and run.status != "running":
                raise ConflictError(f"The run this draft belongs to was stopped: {run.stop_reason or ''}".strip())
        plan.status, plan.updated_at = "running", ctx.clock.iso()
        for sec in pipeline.sections_of(s, plan.id):  # resume = retry a failed or cancelled section
            if pipeline.section_state(s, sec) in ("failed", "cancelled"):
                pipeline.queue_section(s, ctx, plan, sec)
                break
        else:
            pipeline.advance(s, ctx, plan)
        s.flush()
        out = _plan_out(s, plan)
    _wake(ctx)
    return out


def cancel_plan(ctx: AppContext, project_id: str, plan_id: str) -> PlanOut:
    with ctx.db.tx() as s:
        plan = _require_plan(s, project_id, plan_id)
        if plan.status in ("ready", "cancelled"):
            raise ConflictError(f"This draft is already {plan.status}.")
        signal = pipeline.cancel_plan(s, ctx, plan, "Cancelled by the author. Finished sections are kept.")
        s.flush()
        out = _plan_out(s, plan)
    if ctx.jobs is not None:
        for jid in signal:
            ctx.jobs.signal_cancel(jid)
    return out


def retry_section(ctx: AppContext, project_id: str, plan_id: str, section_id: str) -> PlanOut:
    with ctx.db.tx() as s:
        plan = _require_plan(s, project_id, plan_id)
        sec = s.get(DraftSection, section_id) if is_ulid(section_id) else None
        if sec is None or sec.plan_id != plan.id:
            raise NotFoundError("Section not found in this draft.")
        state = pipeline.section_state(s, sec)
        if state not in ("failed", "cancelled"):
            raise ConflictError(
                "Only a failed or cancelled section can be retried."
                + (" Finished sections are never drafted again." if state == "done" else "")
            )
        if plan.status in ("ready", "cancelled"):
            raise ConflictError(f"This draft is {plan.status}; start a new draft instead.")
        plan.status, plan.updated_at = "running", ctx.clock.iso()
        if sec.status == "cancelled":
            sec.status = "pending"
        pipeline.queue_section(s, ctx, plan, sec)
        s.flush()
        out = _plan_out(s, plan)
    _wake(ctx)
    return out


def approve_section(ctx: AppContext, project_id: str, plan_id: str, section_id: str, data: SectionApproveIn) -> PlanOut:
    with ctx.db.tx() as s:
        plan = _require_plan(s, project_id, plan_id)
        sec = s.get(DraftSection, section_id) if is_ulid(section_id) else None
        if sec is None or sec.plan_id != plan.id:
            raise NotFoundError("Section not found in this draft.")
        if sec.status != "done":
            raise ConflictError("Only a finished section can be approved.")
        if plan.status in ("ready", "cancelled"):
            raise ConflictError(f"This draft is already {plan.status}.")
        if data.edited_md is not None and data.edited_md.strip() != (sec.output_md or "").strip():
            if not data.edited_md.strip():
                raise ValidationFailedError("The section text is empty.")
            sec.output_md, sec.edited = data.edited_md.strip(), 1
        sec.reviewed_at = ctx.clock.iso()
        if plan.status == "awaiting_review":
            plan.status = "running"
            pipeline.advance(s, ctx, plan)
        s.flush()
        out = _plan_out(s, plan)
    _wake(ctx)
    return out


def plan_history(ctx: AppContext, project_id: str, plan_id: str) -> list[JobHistoryOut]:
    """Every attempt of every section, with provider, model, template, usage and the job log."""
    with ctx.db.tx() as s:
        plan = _require_plan(s, project_id, plan_id)
        out: list[JobHistoryOut] = []
        for sec in pipeline.sections_of(s, plan.id):
            for n, jid in enumerate(json.loads(sec.job_ids_json), start=1):
                job = s.get(Job, jid)
                if job is None:
                    continue
                usage = s.scalars(
                    select(UsageRecord).where(UsageRecord.job_id == jid).order_by(UsageRecord.created_at.desc())
                ).first()
                logs = s.scalars(select(JobLog).where(JobLog.job_id == jid).order_by(JobLog.ts, JobLog.id)).all()
                out.append(
                    JobHistoryOut(
                        job_id=jid,
                        section=f"{sec.ordinal}. {sec.title}",
                        attempt_no=n,
                        status=job.status,
                        stage=job.stage,
                        task=job.task,
                        provider_kind=job.provider_kind,
                        model_name=job.model_name,
                        template=json.loads(sec.provenance_json or "{}").get("template") or job.prompt_template,
                        created_at=job.created_at,
                        finished_at=job.finished_at,
                        error_message=job.error_message,
                        input_tokens=usage.input_tokens if usage else None,
                        output_tokens=usage.output_tokens if usage else None,
                        cost=usage.cost_amount if usage else None,
                        currency=usage.currency if usage else None,
                        logs=[{"ts": x.ts, "level": x.level, "message": x.message} for x in logs],
                    )
                )
        return out


# ---------- continuity memory and summaries ----------


def _fact_out(s: Session, f: ContinuityFact) -> FactOut:
    ch = s.get(Chapter, f.chapter_id) if f.chapter_id else None
    return FactOut(
        id=f.id,
        kind=f.kind,
        name=f.name,
        attribute=f.attribute,
        value=f.value,
        story_time=f.story_time,
        chapter_id=f.chapter_id,
        chapter_title=ch.title if ch else None,
        origin=f.origin,
        status=f.status,
        updated_at=f.updated_at,
    )


def list_facts(ctx: AppContext, project_id: str) -> list[FactOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.scalars(
            select(ContinuityFact)
            .where(ContinuityFact.project_id == project_id)
            .order_by(ContinuityFact.kind, ContinuityFact.name, ContinuityFact.created_at)
        ).all()
        return [_fact_out(s, f) for f in rows]


def add_fact(ctx: AppContext, project_id: str, data: FactIn) -> FactOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        if data.chapter_id:
            chapter_service._require_chapter(s, project_id, data.chapter_id)
        now = ctx.clock.iso()
        f = ContinuityFact(
            id=ctx.ids.new(),
            project_id=project_id,
            kind=data.kind,
            name=data.name,
            attribute=data.attribute,
            value=data.value,
            story_time=data.story_time or None,
            chapter_id=data.chapter_id,
            origin="author",
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        s.add(f)
        s.flush()
        return _fact_out(s, f)


def patch_fact(ctx: AppContext, project_id: str, fact_id: str, data: FactPatch) -> FactOut:
    with ctx.db.tx() as s:
        f = s.get(ContinuityFact, fact_id) if is_ulid(fact_id) else None
        if f is None or f.project_id != project_id:
            raise NotFoundError("Continuity note not found in this book.")
        for k, v in data.model_dump(exclude_unset=True).items():
            if v is not None or k == "story_time":
                setattr(f, k, v)
        f.updated_at = ctx.clock.iso()
        s.flush()
        return _fact_out(s, f)


def list_summaries(ctx: AppContext, project_id: str) -> list[SummaryOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        out: list[SummaryOut] = []
        for c, _ in chapter_service.tree_order(chapter_service.active_chapters(s, project_id)):
            r = s.scalars(
                select(ChapterSummary)
                .where(ChapterSummary.chapter_id == c.id)
                .order_by(ChapterSummary.created_at.desc())
            ).first()
            basis = "No summary yet."
            if r is not None:
                if r.origin == "author":
                    basis = "Written by you."
                else:
                    plan = s.get(DraftPlan, r.plan_id) if r.plan_id else None
                    prop = s.get(Proposal, plan.proposal_id) if plan and plan.proposal_id else None
                    basis = {
                        "accepted": "From an AI draft you accepted.",
                        "rejected": "From an AI draft you rejected (not used in prompts).",
                    }.get(prop.status if prop else "", "From an AI draft that waits for your review.")
            out.append(
                SummaryOut(
                    chapter_id=c.id,
                    chapter_title=c.title,
                    text=r.text if r else None,
                    origin=r.origin if r else None,
                    basis=basis,
                    updated_at=r.created_at if r else None,
                )
            )
        return out


def put_summary(ctx: AppContext, project_id: str, chapter_id: str, data: SummaryIn) -> SummaryOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        c = chapter_service._require_chapter(s, project_id, chapter_id)
        now = ctx.clock.iso()
        s.add(
            ChapterSummary(
                id=ctx.ids.new(),
                project_id=project_id,
                chapter_id=c.id,
                text=data.text,
                origin="author",
                created_at=now,
            )
        )
        s.flush()
        return SummaryOut(
            chapter_id=c.id,
            chapter_title=c.title,
            text=data.text,
            origin="author",
            basis="Written by you.",
            updated_at=now,
        )


# ---------- quality ----------


def _code_setting_key(project_id: str) -> str:
    return f"code_check_authorized:{project_id}"


def _code_authorized(s: Session, project_id: str) -> bool:
    row = s.get(AppSetting, _code_setting_key(project_id))
    return bool(json.loads(row.value_json)) if row else False


def get_settings(ctx: AppContext, project_id: str) -> WritingSettingsOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        return WritingSettingsOut(
            code_check_authorized=_code_authorized(s, project_id),
            code_check_note=CODE_NOTE,
            similarity_provider=NO_SIMILARITY_PROVIDER,
        )


def put_settings(ctx: AppContext, project_id: str, data: WritingSettingsIn) -> WritingSettingsOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        key = _code_setting_key(project_id)
        row = s.get(AppSetting, key)
        if row is None:
            s.add(AppSetting(key=key, value_json=json.dumps(data.code_check_authorized)))
        else:
            row.value_json = json.dumps(data.code_check_authorized)
    return get_settings(ctx, project_id)


def _book_input(ctx: AppContext, s: Session, project: Project) -> quality.BookIn:
    ordered = chapter_service.tree_order(chapter_service.active_chapters(s, project.id))
    o = s.scalars(
        select(OutlineVersion).where(OutlineVersion.project_id == project.id, OutlineVersion.status == "approved")
    ).first()
    from pbs_core.planning import outline as ol

    index = ol.node_index(json.loads(o.nodes_json)) if o is not None else {}
    chapters: list[quality.ChapterIn] = []
    order_of: dict[str, int] = {}
    for i, (c, _) in enumerate(ordered):
        order_of[c.id] = i
        rev = s.get(ChapterRevision, c.head_revision_id) if c.head_revision_id else None
        text = rev.source_md if rev else ""
        node = index.get(c.outline_node_id or "", (None,))[0] if c.outline_node_id else None
        parsed = documents.parse(ctx, text, c.id) if text.strip() else None
        anchors = set()
        if parsed is not None:
            from pbs_core.document import bookmd

            anchors = {b["attrs"]["id"] for b in bookmd.walk_blocks(parsed.doc) if b.get("attrs", {}).get("id")}
        chapters.append(
            quality.ChapterIn(
                id=c.id,
                title=c.title,
                text=text,
                order=i,
                revision_no=c.head_revision_no,
                target_words=(node or {}).get("target_words") or c.target_word_count,
                outline_sections=[x["title"] for x in (node or {}).get("children", []) if x.get("kind") == "section"],
                requirements=(node or {}).get("requirements") or {},
                warnings=[w.as_dict() for w in parsed.warnings] if parsed is not None else [],
                anchors=anchors,
            )
        )
    facts = s.scalars(select(ContinuityFact).where(ContinuityFact.project_id == project.id)).all()
    return quality.BookIn(
        fiction=memory.is_fiction(s, project),
        exclusions=memory.exclusions(s, project.id),
        chapters=chapters,
        known_terms={f.name for f in facts if f.kind == "term" and f.status != "rejected"},
        facts=[
            quality.FactIn(
                id=f.id,
                kind=f.kind,
                name=f.name,
                attribute=f.attribute,
                value=f.value,
                story_time=f.story_time,
                chapter_id=f.chapter_id,
                chapter_order=order_of.get(f.chapter_id or "", 10_000),
                status=f.status,
            )
            for f in facts
        ],
        code_check=_code_authorized(s, project.id),
    )


def _finding_out(s: Session, f: QualityFinding, titles: dict[str, str]) -> QualityFindingOut:
    label = quality.CHECKS.get(f.check_code) or (
        "AI review: " + f.check_code.removeprefix("ai_").replace("_", " ")
        if f.check_code.startswith("ai_")
        else f.check_code
    )
    return QualityFindingOut(
        id=f.id,
        chapter_id=f.chapter_id,
        chapter_title=titles.get(f.chapter_id or ""),
        check=f.check_code,
        check_label=label,
        origin=f.origin,
        severity=f.severity,
        message=f.message,
        excerpt=f.excerpt,
        details={k: v for k, v in json.loads(f.details_json or "{}").items() if k != "_key"},
        revision_no=f.revision_no,
        present=bool(f.present),
        state=f.state,
        note=f.note,
        updated_at=f.updated_at,
    )


def _titles(s: Session, project_id: str) -> dict[str, str]:
    return {c.id: c.title for c in s.scalars(select(Chapter).where(Chapter.project_id == project_id))}


def list_findings(ctx: AppContext, project_id: str, chapter_id: str | None = None) -> list[QualityFindingOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        stmt = select(QualityFinding).where(QualityFinding.project_id == project_id)
        if chapter_id:
            stmt = stmt.where(QualityFinding.chapter_id == chapter_id)
        rows = s.scalars(
            stmt.order_by(QualityFinding.present.desc(), QualityFinding.check_code, QualityFinding.created_at)
        ).all()
        titles = _titles(s, project_id)
        return [_finding_out(s, f, titles) for f in rows]


def run_quality(ctx: AppContext, project_id: str, data: QualityRunIn) -> QualityRunOut:
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        if data.chapter_id:
            chapter_service._require_chapter(s, project_id, data.chapter_id)
        unknown = [c for c in data.checks if c not in quality.CHECKS]
        if unknown:
            raise ValidationFailedError("Unknown check: " + ", ".join(unknown))
        book = _book_input(ctx, s, project)
        findings, ran = quality.run(book, set(data.checks) or None)
        skipped: dict[str, str] = {}
        for c in data.checks or list(quality.CHECKS):
            if c in ran:
                continue
            if c == "code_syntax" and not book.code_check:
                skipped[c] = "Not allowed for this book. Turn on code checks first (parsing only, never run)."
            elif c in quality.NONFICTION_ONLY and book.fiction:
                skipped[c] = "Applies to nonfiction only."
            elif c in quality.FICTION_ONLY and not book.fiction:
                skipped[c] = "Applies to fiction only."
        scope = {data.chapter_id} if data.chapter_id else None
        if scope is not None:
            findings = [
                f
                for f in findings
                if f.chapter_id in scope
                or any(loc.get("chapter_id") in scope for loc in f.details.get("locations", []))
            ]
        revisions = {c.id: c.revision_no for c in book.chapters}
        new, seen = store.upsert(
            s, ctx, project_id, findings, origin="rule", checks=ran, chapter_ids=scope, revisions=revisions
        )
        activity.record(
            s,
            ctx,
            kind="quality_checked",
            project_id=project_id,
            ref_type="project",
            ref_id=project_id,
            summary=f"Ran quality checks: {len(findings)} finding(s), {new} new",
        )
        s.flush()
        stmt = select(QualityFinding).where(QualityFinding.project_id == project_id)
        if data.chapter_id:
            stmt = stmt.where(QualityFinding.chapter_id == data.chapter_id)
        titles = _titles(s, project_id)
        rows = s.scalars(stmt.order_by(QualityFinding.present.desc(), QualityFinding.check_code)).all()
        return QualityRunOut(
            checks_run=ran,
            checks_skipped=skipped,
            new=new,
            seen=seen,
            findings=[_finding_out(s, f, titles) for f in rows],
            disclaimer=QUALITY_DISCLAIMER,
        )


def patch_finding(ctx: AppContext, project_id: str, finding_id: str, data: FindingPatchIn) -> QualityFindingOut:
    with ctx.db.tx() as s:
        f = s.get(QualityFinding, finding_id) if is_ulid(finding_id) else None
        if f is None or f.project_id != project_id:
            raise NotFoundError("Finding not found in this book.")
        f.state, f.updated_at = data.state, ctx.clock.iso()
        if data.note is not None:
            f.note = data.note or None
        s.flush()
        return _finding_out(s, f, _titles(s, project_id))


def ai_review(ctx: AppContext, project_id: str, data: AiReviewIn) -> JobOut:
    key = f"{project_id}:{data.client_request_id}"
    with ctx.db.tx() as s:
        existing = ai.find_job(s, key)
        if existing is not None:
            return ai.job_out(s, existing)
        project = require_active(s, project_id)
        chapter = chapter_service._require_chapter(s, project_id, data.chapter_id)
        if not chapter.head_revision_id:
            raise ConflictError("This chapter has no saved text to review yet.")
        if s.get(ChapterDraft, chapter.id) is not None:
            raise ConflictError("Save your changes first, so the review sees the text you see.")
        provider, model, temperature, max_out = ai.resolve_model(s, "revise", data.provider_id, data.model_name, 2048)
        blocked = ai.cloud_block_reason(s, project_id, provider)
        if blocked:
            raise ai.CloudBlockedError(blocked, extra={"reason": "cloud_blocked"})
        rev = s.get(ChapterRevision, chapter.head_revision_id)
        from pbs_core.services import costs

        est = costs.estimate(
            s, provider, model, min(len(rev.source_md if rev else ""), writing_exec.REVIEW_TEXT_LIMIT) + 3000, max_out
        )
        job = ai.queue_planning_job(
            s,
            ctx,
            project_id=project_id,
            task="revise",
            provider=provider,
            model=model,
            temperature=temperature,
            max_out=max_out,
            inp={
                "kind": "quality_review",
                "project_id": project.id,
                "chapter_id": chapter.id,
                "base_revision_id": chapter.head_revision_id,
                "instruction": data.instruction,
            },
            template=f"review@{wp.TEMPLATE_VERSION}",
            estimate=dict(est),
            key=key,
            summary=f"review “{chapter.title}”",
        )
        job.chapter_id = chapter.id
        s.flush()
        out = ai.job_out(s, job)
    _wake(ctx)
    return out


# ---------- originality ----------


def originality_report(ctx: AppContext, project_id: str) -> OriginalityOut:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        book = _book_input(ctx, s, project)
        others: list[originality.OtherText] = []
        for p in s.scalars(select(Project).where(Project.id != project_id)):
            for c in chapter_service.active_chapters(s, p.id):
                rev = s.get(ChapterRevision, c.head_revision_id) if c.head_revision_id else None
                if rev and rev.source_md.strip():
                    others.append(originality.OtherText("book", p.id, f"{p.title}: {c.title}", rev.source_md))
        libraries = retrieval.library_ids(s, project_id)
        for src in s.scalars(select(Source).where(Source.library_id.in_(libraries), Source.removed_at.is_(None))):
            text = "\n\n".join(
                ch.text
                for ch in s.scalars(
                    select(SourceChunk).where(SourceChunk.source_id == src.id).order_by(SourceChunk.seq)
                )
            )
            if text.strip():
                others.append(
                    originality.OtherText("source", src.id, src.title, text, {"citation_key": src.citation_key})
                )
        rep = originality.report(book.chapters, others, NO_SIMILARITY_PROVIDER)
        return OriginalityOut(**rep)


# ---------- used by generation runs (Phase 05 "Draft chapters") ----------


def run_plans(s: Session, run_id: str) -> list[DraftPlan]:
    return list(s.scalars(select(DraftPlan).where(DraftPlan.run_id == run_id).order_by(DraftPlan.run_order)))


def brief_for(s: Session, project_id: str) -> BookBrief | None:
    return s.get(BookBrief, project_id)
