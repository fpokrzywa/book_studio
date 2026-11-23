"""Writing-pipeline jobs: one outline section of a chapter draft, or an AI quality review.

Called from jobs/execute.py for jobs whose input ``kind`` is in KINDS. Retries, cancellation, the
egress gate and usage accounting are shared with every other job. What differs:

* a section prompt is assembled when the job RUNS, inside an explicit token budget (brief, local
  outline, this chapter so far, earlier-chapter summaries, continuity notes, style guide, source
  passages), and the budget report is stored with the section;
* a finished section is stored on the plan, never in the chapter; the plan then queues the next
  section, stops at a review gate, or assembles the whole chapter into one proposal;
* an AI review finding is kept only if its quote is really in the chapter text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from pbs_core.context import AppContext
from pbs_core.jobs import writing_prompts as wp
from pbs_core.jobs.prompts import BuiltPrompt
from pbs_core.jobs.runner import add_log
from pbs_core.knowledge import citations, retrieval
from pbs_core.knowledge.citations import Ref
from pbs_core.planning import runs
from pbs_core.providers.base import ProviderError
from pbs_core.services import activity, costs
from pbs_core.services import voice as voice_service
from pbs_core.storage.ai_models import Job, ProviderConfig, UsageRecord
from pbs_core.storage.models import Chapter, ChapterRevision, Project
from pbs_core.storage.writing_models import ContinuityFact, DraftPlan, DraftSection
from pbs_core.writing import context as budget
from pbs_core.writing import memory, pipeline, store
from pbs_core.writing.quality import Finding

KINDS = frozenset({"section_draft", "quality_review"})
INSTRUCTION_OVERHEAD = 450  # tokens reserved for the fixed instructions of a section prompt
REVIEW_TEXT_LIMIT = 60_000
DISCLAIMER = (
    "AI review is a second opinion from a language model. It can miss problems and can be wrong; it is not a "
    "check of factual correctness."
)


@dataclass
class Prepared:
    built: BuiltPrompt
    refs: dict[str, Ref] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def prepare(ctx: AppContext, job_id: str, inp: dict[str, Any]) -> Prepared:
    if inp["kind"] == "section_draft":
        return _prepare_section(ctx, job_id, inp)
    return _prepare_review(ctx, job_id, inp)


def _prepare_section(ctx: AppContext, job_id: str, inp: dict[str, Any]) -> Prepared:
    with ctx.db.tx() as s:
        plan = s.get(DraftPlan, inp["plan_id"])
        sec = s.get(DraftSection, inp["section_id"])
        if plan is None or sec is None:
            raise ProviderError("invalid_request", "The draft plan for this section no longer exists.")
        options = json.loads(plan.options_json or "{}")
        voice_id = options.get("voice_profile_id")
    voice = voice_service.for_prompt(ctx, voice_id) if voice_id else None
    with ctx.db.tx() as s:
        plan = s.get(DraftPlan, inp["plan_id"])
        sec = s.get(DraftSection, inp["section_id"])
        project = s.get(Project, plan.project_id) if plan else None
        chapter = s.get(Chapter, plan.chapter_id) if plan else None
        if plan is None or sec is None or project is None or chapter is None:
            raise ProviderError("invalid_request", "The chapter for this section no longer exists.")
        secs = pipeline.sections_of(s, plan.id)
        fiction = memory.is_fiction(s, project)
        node = memory.node_for(s, plan)
        found = retrieval.retrieve(
            s,
            plan.project_id,
            f"{sec.title} {sec.goal} {chapter.title}",
            use_sources=bool(options.get("use_sources", True)),
            use_interview=bool(options.get("use_interview", False)),
        )
        source_refs = [r for r in found.refs.values() if r.kind == "source"]
        answer_refs = [r for r in found.refs.values() if r.kind == "interview"]
        style = ""
        if voice:
            style = "\n\n".join(
                x
                for x in (
                    str(voice.get("guide") or ""),
                    "\n".join(
                        f"- {'Do' if r.get('kind') == 'do' else 'Avoid'}: {r.get('rule', '')}"
                        for r in voice.get("rules") or []  # type: ignore[attr-defined]
                    ),
                    "\n".join(f"- {e}" for e in voice.get("examples", [])),  # type: ignore[attr-defined]
                )
                if x
            )
        parts = [
            budget.Part("brief", "Book brief", memory.brief_text(s, project), required=True),
            budget.Part(
                "outline", "Local outline and targets", memory.outline_text(chapter, node, secs, sec), required=True
            ),
            budget.Part("so_far", "This chapter so far", memory.so_far(s, plan, secs, sec), keep="end"),
            budget.Part("style", "Approved style guide", style),
            budget.Part("continuity", "Continuity memory", items=memory.fact_items(s, plan.project_id)),
            budget.Part(
                "summaries", "Earlier chapters (summaries)", items=memory.summary_items(s, plan.project_id, chapter.id)
            ),
            budget.Part(
                "passages",
                "Knowledge passages",
                items=[f"[{r.label}] {r.title}: {r.text}" for r in source_refs]
                + [f"[{r.label}] {r.title}: {r.text}" for r in answer_refs],
            ),
        ]
        fitted = budget.fit(parts, max(500, plan.token_budget - INSTRUCTION_OVERHEAD))
        kept_n = fitted.kept_items.get("passages", 0)
        kept_sources = source_refs[:kept_n]
        kept_answers = answer_refs[: max(0, kept_n - len(source_refs))]
        built = wp.section(
            book_title=project.title,
            chapter_title=chapter.title,
            section_title=sec.title,
            section_no=sec.ordinal,
            section_count=len(secs),
            goal=sec.goal,
            target_words=sec.target_words,
            fiction=fiction,
            texts=fitted.texts,
            sources=kept_sources,
            answers=kept_answers,
            exclusions=memory.exclusions(s, plan.project_id),
        )
        report = {
            **fitted.report,
            "prompt_tokens_estimate": budget.tokens(built.system) + budget.tokens(built.user),
            "retrieval_query": found.query[:300],
        }
        add_log(
            s,
            ctx,
            job_id,
            f"Context for section {sec.ordinal} “{sec.title}”: about {report['prompt_tokens_estimate']} tokens "
            f"(budget {plan.token_budget}); "
            + ", ".join(f"{p['label'].lower()} {p['status']}" for p in fitted.report["parts"] if p["status"] != "empty")
            + ".",
        )
        refs = {r.label: r for r in kept_sources + kept_answers}
        return Prepared(built=built, refs=refs, report=report, extra={"fiction": fiction})


def _prepare_review(ctx: AppContext, job_id: str, inp: dict[str, Any]) -> Prepared:
    with ctx.db.tx() as s:
        project = s.get(Project, inp["project_id"])
        chapter = s.get(Chapter, inp["chapter_id"])
        rev = s.get(ChapterRevision, inp["base_revision_id"]) if inp.get("base_revision_id") else None
        if project is None or chapter is None or rev is None:
            raise ProviderError("invalid_request", "The chapter to review no longer exists.")
        text = rev.source_md
        clipped = len(text) > REVIEW_TEXT_LIMIT
        fiction = memory.is_fiction(s, project)
        goal = ""
        if chapter.outline_node_id:
            from pbs_core.storage.planning_models import OutlineVersion

            o = s.scalars(
                select(OutlineVersion).where(
                    OutlineVersion.project_id == project.id, OutlineVersion.status == "approved"
                )
            ).first()
            if o is not None:
                from pbs_core.planning import outline as ol

                hit = ol.node_index(json.loads(o.nodes_json)).get(chapter.outline_node_id)
                goal = str(hit[0].get("goal") or "") if hit else ""
        built = wp.review(
            book_title=project.title,
            chapter_title=chapter.title,
            text=text[:REVIEW_TEXT_LIMIT],
            fiction=fiction,
            brief=memory.brief_text(s, project),
            goal=goal,
            continuity="\n".join(memory.fact_items(s, project.id)[:60]) if fiction else "",
            instruction=str(inp.get("instruction") or ""),
        )
        add_log(s, ctx, job_id, f"Reviewing “{chapter.title}” (revision {rev.revision_no}).")
        return Prepared(built=built, extra={"text": text, "clipped": clipped, "revision_no": rev.revision_no})


def parse(inp: dict[str, Any], payload: str, prep: Prepared) -> dict[str, Any]:
    try:
        if inp["kind"] == "section_draft":
            data = wp.parse_section(payload)
            processed = citations.process(data["text"], prep.refs)
            data["processed"] = processed
            return data
        return {"findings": wp.parse_review(payload)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("invalid_output", "The model did not return the requested structured answer.") from exc


def _usage(
    s: Any, ctx: AppContext, job_id: str, project_id: str, provider: ProviderConfig, snap: dict[str, Any], result: Any
) -> costs.Cost:
    cost = costs.cost_of(s, provider, snap["model"], result.usage)
    s.add(
        UsageRecord(
            id=ctx.ids.new(),
            job_id=job_id,
            project_id=project_id,
            provider_kind=snap["kind"],
            model_name=snap["model"],
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            reported_by_provider=1 if result.usage.reported else 0,
            cost_amount=cost.amount,
            currency=cost.currency,
            price_basis=cost.basis,
            attempt=snap["attempt"],
            created_at=ctx.clock.iso(),
        )
    )
    return cost


def commit(
    ctx: AppContext,
    job_id: str,
    inp: dict[str, Any],
    parsed: dict[str, Any],
    prep: Prepared,
    result: Any,
    provider: ProviderConfig,
    snap: dict[str, Any],
) -> None:
    with ctx.db.tx() as s:
        job = s.get(Job, job_id)
        if job is None or job.status != "running":
            return
        if job.cancel_requested:
            job.status, job.stage, job.finished_at, job.lease_owner = "cancelled", "cancelled", ctx.clock.iso(), None
            job.error_code, job.error_message = "cancelled", "Cancelled by the author. Nothing was saved."
            add_log(s, ctx, job_id, job.error_message)
            return
        cost = _usage(s, ctx, job_id, snap["project_id"], provider, snap, result)
        if inp.get("run_id"):
            runs.record_cost(s, ctx, inp["run_id"], cost.amount, cost.currency, job_id)
        now = ctx.clock.iso()
        tokens = f"{result.usage.input_tokens or '?'} in / {result.usage.output_tokens or '?'} out"
        if inp["kind"] == "section_draft":
            _commit_section(s, ctx, job_id, inp, parsed, prep, result, provider, snap, tokens)
        else:
            _commit_review(s, ctx, job_id, inp, parsed, prep, snap)
        job.status, job.finished_at, job.lease_owner, job.partial_output = "succeeded", now, None, None
        job.stage = "section_done" if inp["kind"] == "section_draft" else "ready_for_review"
        add_log(s, ctx, job_id, f"Finished: {tokens} tokens ({'reported' if result.usage.reported else 'estimated'}).")
        if inp["kind"] == "section_draft":
            plan = s.get(DraftPlan, inp["plan_id"])
            if plan is not None:
                pipeline.advance(s, ctx, plan)


def _commit_section(
    s: Any,
    ctx: AppContext,
    job_id: str,
    inp: dict[str, Any],
    parsed: dict[str, Any],
    prep: Prepared,
    result: Any,
    provider: ProviderConfig,
    snap: dict[str, Any],
    tokens: str,
) -> None:
    sec = s.get(DraftSection, inp["section_id"])
    plan = s.get(DraftPlan, inp["plan_id"])
    if sec is None or plan is None or sec.status == "done":
        return  # already stored (a retry raced a restart): never overwrite a finished section
    processed: citations.Processed = parsed["processed"]
    now = ctx.clock.iso()
    sec.output_md = processed.text_md
    sec.summary = parsed["summary"] or None
    sec.status, sec.finished_at = "done", now
    sec.context_json = json.dumps(prep.report)
    sec.citations_json = json.dumps(
        {
            "paragraphs": processed.paragraphs,
            "claims": [
                {"text": c.text, "paragraph": c.paragraph, "supports": [x.as_dict() for x in c.supports]}
                for c in processed.claims
            ],
            "dropped": processed.dropped,
            "sources": [
                {
                    "label": r.label,
                    "source_id": r.source_id,
                    "chunk_id": r.chunk_id,
                    "title": r.title,
                    "citation_key": r.citation_key,
                    "locator": r.locator,
                }
                for r in prep.refs.values()
                if r.kind == "source"
            ],
        }
    )
    sec.provenance_json = json.dumps(
        {
            "task": "draft (section)",
            "provider_kind": snap["kind"],
            "provider_label": provider.label,
            "model": result.model or snap["model"],
            "template": prep.built.template,
            "job_id": job_id,
            "attempt": snap["attempt"],
            "finish_reason": result.finish_reason,
            "tokens": tokens,
            "generated_at": now,
        }
    )
    added = 0
    for f in parsed["facts"]:
        dup = s.scalars(
            select(ContinuityFact).where(
                ContinuityFact.project_id == plan.project_id,
                ContinuityFact.kind == f["kind"],
                ContinuityFact.name == f["name"],
                ContinuityFact.attribute == f["attribute"],
                ContinuityFact.value == f["value"],
                ContinuityFact.status != "rejected",
            )
        ).first()
        if dup is not None:
            continue
        s.add(
            ContinuityFact(
                id=ctx.ids.new(),
                project_id=plan.project_id,
                kind=f["kind"],
                name=f["name"],
                attribute=f["attribute"],
                value=f["value"],
                story_time=f["story_time"],
                chapter_id=plan.chapter_id,
                plan_id=plan.id,
                origin="ai_extracted",
                status="proposed",
                created_at=now,
                updated_at=now,
            )
        )
        added += 1
    add_log(
        s,
        ctx,
        job_id,
        f"Section {sec.ordinal} “{sec.title}” stored on the draft plan (not in the chapter)"
        + (f"; {added} continuity note(s) proposed" if added else "")
        + ".",
    )


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[*_`]", "", text).split()).lower()


def _commit_review(
    s: Any,
    ctx: AppContext,
    job_id: str,
    inp: dict[str, Any],
    parsed: dict[str, Any],
    prep: Prepared,
    snap: dict[str, Any],
) -> None:
    text = _norm(prep.extra.get("text", ""))
    kept: list[Finding] = []
    dropped = 0
    for f in parsed["findings"]:
        quote = f["quote"]
        if len(quote) < 4 or _norm(quote) not in text:
            dropped += 1  # a finding about text that is not in the chapter is not kept
            continue
        kept.append(
            Finding(
                check=f"ai_{f['check']}",
                chapter_id=inp["chapter_id"],
                severity="info",
                message=f["message"] or "The reviewer flagged this passage.",
                excerpt=quote[:600],
                key=f"ai:{f['check']}:{_norm(quote)[:160]}",
                details={"model": snap["model"], "job_id": job_id, "disclaimer": DISCLAIMER},
            )
        )
    checks = sorted({k.check for k in kept} | {f"ai_{c}" for c in wp.REVIEW_CHECKS})
    store.upsert(
        s,
        ctx,
        snap["project_id"],
        kept,
        origin="ai_review",
        checks=checks,
        chapter_ids={inp["chapter_id"]},
        revisions={inp["chapter_id"]: int(prep.extra.get("revision_no") or 0)},
    )
    add_log(
        s,
        ctx,
        job_id,
        f"AI review: {len(kept)} finding(s) kept"
        + (f"; {dropped} dropped because their quote is not in the chapter" if dropped else "")
        + (
            " (the chapter was longer than the review limit, so only its beginning was reviewed)"
            if prep.extra.get("clipped")
            else ""
        )
        + ". "
        + DISCLAIMER,
    )
    activity.record(
        s,
        ctx,
        kind="ai_review_ready",
        project_id=snap["project_id"],
        ref_type="job",
        ref_id=job_id,
        summary=f"AI review ready for “{snap['chapter_title']}”: {len(kept)} finding(s)",
    )
