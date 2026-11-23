"""The section-by-section drafting pipeline: queue, advance, assemble. Database helpers only.

Rules that keep the author's work safe:
* a plan only ever writes into its own sections; the chapter changes only when the author accepts
  the single assembled proposal;
* each section is one durable job; a failed section is retried alone, and finished sections are
  never sent to the model again;
* a paused, cancelled or review-gated plan queues nothing; a plan that belongs to a run starts only
  after the previous chapter of that run is assembled (so it can use that chapter's summary).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.jobs.runner import add_log
from pbs_core.knowledge.citations import ClaimDraft, Processed, Support
from pbs_core.planning import runs as run_rules
from pbs_core.providers import registry
from pbs_core.services import activity, evidence
from pbs_core.storage.ai_models import Job, Proposal, ProviderConfig
from pbs_core.storage.models import Chapter
from pbs_core.storage.planning_models import GenerationRun
from pbs_core.storage.writing_models import ChapterSummary, DraftPlan, DraftSection

ACTIVE_JOB = ("queued", "running")


def sections_of(s: Session, plan_id: str) -> list[DraftSection]:
    return list(s.scalars(select(DraftSection).where(DraftSection.plan_id == plan_id).order_by(DraftSection.ordinal)))


def section_state(s: Session, sec: DraftSection) -> str:
    """pending | queued | running | done | failed | cancelled (failed and cancelled come from the job)."""
    if sec.status != "active":
        return sec.status
    job = s.get(Job, sec.job_id) if sec.job_id else None
    if job is None:
        return "pending"
    if job.status in ACTIVE_JOB:
        return job.status
    if job.status in ("failed", "interrupted"):
        return "failed"
    if job.status == "cancelled":
        return "cancelled"
    return "running"  # succeeded but not yet committed as done (same transaction normally)


def queue_section(s: Session, ctx: AppContext, plan: DraftPlan, sec: DraftSection) -> Job:
    now = ctx.clock.iso()
    attempts: list[str] = json.loads(sec.job_ids_json)
    provider = s.get(ProviderConfig, plan.provider_config_id)
    job = Job(
        id=ctx.ids.new(),
        project_id=plan.project_id,
        chapter_id=plan.chapter_id,
        task="draft",
        provider_config_id=plan.provider_config_id,
        provider_kind=plan.provider_kind,
        model_name=plan.model_name,
        params_json=json.dumps({"temperature": plan.temperature, "max_output_tokens": plan.max_output_tokens}),
        input_json=json.dumps(
            {"kind": "section_draft", "plan_id": plan.id, "section_id": sec.id, "run_id": plan.run_id}
        ),
        prompt_template="section",
        estimate_json="{}",
        status="queued",
        stage="queued",
        attempt=0,
        max_attempts=3,
        run_after=now,
        cancel_requested=0,
        idempotency_key=f"section:{sec.id}:{len(attempts) + 1}",
        created_at=now,
    )
    s.add(job)
    s.flush()
    attempts.append(job.id)
    sec.job_ids_json, sec.job_id, sec.status = json.dumps(attempts), job.id, "active"
    plan.updated_at = now
    if plan.run_id:
        run = s.get(GenerationRun, plan.run_id)
        if run is not None:
            ids = json.loads(run.job_ids_json)
            ids.append(job.id)
            run.job_ids_json = json.dumps(ids)
    where = "on this computer" if provider is not None and registry.is_local(provider) else "to the cloud provider"
    add_log(
        s,
        ctx,
        job.id,
        f"Queued: section {sec.ordinal} “{sec.title}” of a chapter draft with {plan.model_name}, sent {where}.",
    )
    return job


def advance(s: Session, ctx: AppContext, plan: DraftPlan) -> str:
    """Queue the next section, stop at a review gate, or assemble. Returns what happened."""
    if plan.status != "running":
        return "idle"
    secs = sections_of(s, plan.id)
    states = [section_state(s, x) for x in secs]
    if any(st in ACTIVE_JOB for st in states):
        return "busy"
    if any(st in ("failed", "cancelled") for st in states):
        return "needs_retry"
    if plan.review_gate == "each_section" and any(x.status == "done" and not x.reviewed_at for x in secs):
        plan.status, plan.updated_at = "awaiting_review", ctx.clock.iso()
        return "awaiting_review"
    for sec in secs:
        if sec.status == "pending":
            queue_section(s, ctx, plan, sec)
            return "queued"
    assemble(s, ctx, plan)
    return "assembled"


def _merged_processed(secs: list[DraftSection], text: str) -> Processed:
    out = Processed(text_md=text)
    offset = 0
    for sec in secs:
        c = json.loads(sec.citations_json or "{}")
        for p in c.get("paragraphs", []):
            out.paragraphs.append({**p, "index": int(p.get("index", 0)) + offset})
        for cl in c.get("claims", []):
            out.claims.append(
                ClaimDraft(
                    text=cl["text"],
                    paragraph=int(cl.get("paragraph", 0)) + offset,
                    supports=[Support(**sp) for sp in cl.get("supports", [])],
                )
            )
        out.dropped += c.get("dropped", [])
        offset += len(c.get("paragraphs", [])) + (1 if sec.heading else 0)
    return out


def assemble(s: Session, ctx: AppContext, plan: DraftPlan) -> Proposal:
    """All sections done: offer the chapter draft as ONE proposal. The chapter itself is untouched."""
    secs = sections_of(s, plan.id)
    parts: list[str] = []
    for sec in secs:
        if sec.heading:
            parts.append(f"## {sec.title}")
        parts.append((sec.output_md or "").strip())
    payload = "\n\n".join(p for p in parts if p) + "\n"
    last_job = secs[-1].job_id or ""
    provider = s.get(ProviderConfig, plan.provider_config_id)
    chapter = s.get(Chapter, plan.chapter_id)
    processed = _merged_processed(secs, payload)
    sources: dict[str, dict[str, Any]] = {}
    for sec in secs:
        for src in json.loads(sec.citations_json or "{}").get("sources", []):
            sources.setdefault(f"{src.get('source_id')}:{src.get('chunk_id')}", src)
    options = json.loads(plan.options_json or "{}")
    requirements = options.get("requirements") or {}
    now = ctx.clock.iso()
    proposal = Proposal(
        id=ctx.ids.new(),
        project_id=plan.project_id,
        chapter_id=plan.chapter_id,
        job_id=last_job,
        base_revision_id=plan.base_revision_id,
        base_revision_no=plan.base_revision_no,
        mode="append",
        selection_start=None,
        selection_end=None,
        original_text=None,
        payload_md=payload,
        status="pending",
        provenance_json=json.dumps(
            {
                "provider_kind": plan.provider_kind,
                "provider_label": provider.label if provider else "?",
                "model": plan.model_name,
                "task": "draft",
                "template": "section pipeline",
                "instruction": f"Drafted section by section ({len(secs)} sections).",
                "generated_at": now,
                "outline_node_id": plan.outline_node_id,
                "pipeline": {
                    "plan_id": plan.id,
                    "sections": [
                        {
                            "title": x.title,
                            "job_ids": json.loads(x.job_ids_json),
                            "edited_by_author": bool(x.edited),
                            "model": json.loads(x.provenance_json or "{}").get("model"),
                        }
                        for x in secs
                    ],
                },
                "knowledge": {
                    "sources": list(sources.values()),
                    "paragraphs": processed.paragraphs,
                    "dropped_labels": processed.dropped,
                    "used_sources": bool(options.get("use_sources", True)),
                },
                "requirements_check": run_rules.requirements_check(requirements, processed, payload)
                if requirements
                else None,
            }
        ),
        created_at=now,
    )
    s.add(proposal)
    s.flush()
    evidence.record_proposal_claims(
        s, ctx, project_id=plan.project_id, chapter_id=plan.chapter_id, proposal_id=proposal.id, processed=processed
    )
    summary = " ".join((x.summary or "").strip() for x in secs if (x.summary or "").strip())
    if summary:
        s.add(
            ChapterSummary(
                id=ctx.ids.new(),
                project_id=plan.project_id,
                chapter_id=plan.chapter_id,
                plan_id=plan.id,
                text=summary[:4000],
                origin="ai_draft",
                created_at=now,
            )
        )
    plan.status, plan.proposal_id, plan.finished_at, plan.updated_at = "ready", proposal.id, now, now
    if last_job:
        add_log(s, ctx, last_job, f"All {len(secs)} sections are done; the chapter draft is ready for your review.")
    activity.record(
        s,
        ctx,
        kind="ai_suggestion_ready",
        project_id=plan.project_id,
        ref_type="draft_plan",
        ref_id=plan.id,
        summary=f"Chapter draft ready for review: “{chapter.title if chapter else '?'}” ({len(secs)} sections)",
    )
    if plan.run_id:
        start_next_in_run(s, ctx, plan.run_id)
    return proposal


def start_next_in_run(s: Session, ctx: AppContext, run_id: str) -> DraftPlan | None:
    run = s.get(GenerationRun, run_id)
    if run is None or run.status != "running":
        return None
    nxt = s.scalars(
        select(DraftPlan)
        .where(DraftPlan.run_id == run_id, DraftPlan.status == "waiting")
        .order_by(DraftPlan.run_order)
        .limit(1)
    ).first()
    if nxt is None:
        return None
    nxt.status, nxt.updated_at = "running", ctx.clock.iso()
    advance(s, ctx, nxt)
    return nxt


def cancel_plan(s: Session, ctx: AppContext, plan: DraftPlan, reason: str) -> list[str]:
    """Cancel queued work; ask running jobs to stop. Finished sections are kept. Returns jobs to signal."""
    signal: list[str] = []
    now = ctx.clock.iso()
    for sec in sections_of(s, plan.id):
        if sec.status == "pending":
            sec.status = "cancelled"
        elif sec.status == "active" and sec.job_id:
            job = s.get(Job, sec.job_id)
            if job is not None and job.status == "queued":
                job.status, job.stage, job.finished_at, job.cancel_requested = "cancelled", "cancelled", now, 1
                job.error_code, job.error_message = "cancelled", reason
                add_log(s, ctx, job.id, reason)
            elif job is not None and job.status == "running":
                job.cancel_requested, job.stage = 1, "cancelling"
                add_log(s, ctx, job.id, reason)
                signal.append(job.id)
    if plan.status not in ("ready", "cancelled"):
        plan.status, plan.note, plan.finished_at, plan.updated_at = "cancelled", reason, now, now
    return signal


def stop_run_plans(s: Session, ctx: AppContext, run_id: str, reason: str) -> list[str]:
    signal: list[str] = []
    for plan in s.scalars(select(DraftPlan).where(DraftPlan.run_id == run_id)):
        if plan.status not in ("ready", "cancelled"):
            signal += cancel_plan(s, ctx, plan, reason)
    return signal
