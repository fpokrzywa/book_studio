"""Run one AI job: build the prompt from the immutable base revision, call the provider through the
egress gate, and commit the proposal + usage exactly once."""

from __future__ import annotations

import json
import random
import threading
import time
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select

from pbs_core.context import AppContext
from pbs_core.domain.clock import to_iso
from pbs_core.jobs import planning_exec, prompts, writing_exec
from pbs_core.jobs.runner import LEASE_SECONDS, add_log
from pbs_core.knowledge import citations, retrieval
from pbs_core.planning import runs
from pbs_core.providers import registry
from pbs_core.providers.base import Cancelled, ChatMessage, GenRequest, ProviderError, extract_json
from pbs_core.providers.egress import EgressBlockedError, cloud_activity
from pbs_core.services import activity, costs, evidence
from pbs_core.services import voice as voice_service
from pbs_core.storage.ai_models import Job, Proposal, ProviderConfig, UsageRecord
from pbs_core.storage.models import Chapter, ChapterRevision, Project
from pbs_core.writing import protect

log = structlog.get_logger(__name__)
PROGRESS_EVERY_S = 0.5


def _backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(120.0, retry_after)
    return min(60.0, 2.0**attempt + random.uniform(0, 1))  # noqa: S311 - jitter, not crypto


def _finish(
    ctx: AppContext, job_id: str, *, status: str, code: str | None, message: str | None, partial: str | None
) -> None:
    with ctx.db.tx() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        job.status, job.stage = status, status
        job.error_code, job.error_message = code, message
        job.finished_at = ctx.clock.iso()
        job.lease_owner = None
        if partial:
            job.partial_output = partial[:200_000]
        add_log(s, ctx, job_id, message or status, "error" if status == "failed" else "info")


def run_job(ctx: AppContext, job_id: str, cancel: threading.Event, ollama_slot: threading.Semaphore) -> None:
    with ctx.db.tx() as s:
        job = s.get(Job, job_id)
        if job is None or job.status != "running":
            return
        if job.cancel_requested:
            cancel.set()
        provider = s.get(ProviderConfig, job.provider_config_id)
        project = s.get(Project, job.project_id)
        chapter = s.get(Chapter, job.chapter_id) if job.chapter_id else None
        inp: dict[str, Any] = json.loads(job.input_json)
        params: dict[str, Any] = json.loads(job.params_json)
        base_text = ""
        if inp.get("base_revision_id"):
            rev = s.scalars(
                select(ChapterRevision).where(
                    ChapterRevision.project_id == job.project_id, ChapterRevision.id == inp["base_revision_id"]
                )
            ).one_or_none()
            base_text = rev.source_md if rev else ""
        snapshot: dict[str, Any] = {
            "attempt": job.attempt,
            "max_attempts": job.max_attempts,
            "task": job.task,
            "model": job.model_name,
            "kind": job.provider_kind,
            "project_id": job.project_id,
            "chapter_id": job.chapter_id,
            "book_title": project.title if project else "",
            "chapter_title": chapter.title if chapter else "",
        }
    if cancel.is_set():
        _finish(ctx, job_id, status="cancelled", code="cancelled", message="Cancelled before it started.", partial=None)
        return
    if provider is None or not provider.enabled:
        _finish(
            ctx,
            job_id,
            status="failed",
            code="provider_missing",
            message="The AI provider was removed or disabled.",
            partial=None,
        )
        return

    planning = inp.get("kind") in planning_exec.KINDS
    writing = inp.get("kind") in writing_exec.KINDS
    found = retrieval.Retrieved({}, [], [], "", 0)
    voice = None
    processed: citations.Processed | None = None
    masked: protect.Masked | None = None
    prepared: writing_exec.Prepared | None = None
    if planning:
        built = planning_exec.build(inp)
    elif writing:
        try:
            prepared = writing_exec.prepare(ctx, job_id, inp)
        except ProviderError as exc:
            _finish(ctx, job_id, status="failed", code=exc.code, message=exc.message, partial=None)
            return
        built = prepared.built
    else:
        sel_start, sel_end = inp.get("selection_start"), inp.get("selection_end")
        selection = base_text[sel_start:sel_end] if sel_start is not None and sel_end is not None else None
        if selection and snapshot["task"] in ("revise", "translate"):
            # Code blocks and math are swapped for placeholders the model must keep; restored afterwards.
            masked = protect.mask(selection)
            if masked.spans:
                selection = masked.text
            else:
                masked = None
        context_text = costs.clip_context(
            base_text, sel_start, sel_end, int(inp.get("max_context_chars", costs.MAX_CONTEXT_CHARS))
        )
        # Knowledge is chosen now, at run time: a source disabled after queueing is not used.
        query = retrieval_query(inp.get("instruction", ""), selection, context_text, snapshot["chapter_title"])
        with ctx.db.tx() as s:
            found = retrieval.retrieve(
                s,
                snapshot["project_id"],
                query,
                use_sources=bool(inp.get("use_sources", True)),
                use_interview=bool(inp.get("use_interview", False)),
            )
            add_log(
                s,
                ctx,
                job_id,
                f"Knowledge: {len(found.passages)} passage(s) from {found.source_count} usable source(s); "
                f"{len(found.answers)} interview answer(s).",
            )
        voice = voice_service.for_prompt(ctx, inp["voice_profile_id"]) if inp.get("voice_profile_id") else None
        built = prompts.build(
            snapshot["task"],
            instruction=inp.get("instruction", ""),
            chapter_title=snapshot["chapter_title"],
            book_title=snapshot["book_title"],
            context_text=context_text,
            selection=selection,
            target_language=inp.get("target_language"),
            target_words=inp.get("target_words"),
            sources=[r for r in found.refs.values() if r.kind == "source"],
            answers=[r for r in found.refs.values() if r.kind == "interview"],
            voice=voice,
        )
    temperature = params.get("temperature")
    native_schema = built.json_schema is not None and registry.native_schema_ok(
        registry.model_capabilities(ctx, provider.id, snapshot["model"])
    )
    user_text = built.user
    if built.json_schema is not None and not native_schema:
        # Capability not confirmed for this model: ask for JSON in the prompt and validate the reply.
        user_text += "\nReply with JSON only, matching this JSON Schema:\n" + json.dumps(built.json_schema)
    req = GenRequest(
        model=snapshot["model"],
        system=built.system,
        messages=[ChatMessage("user", user_text)],
        temperature=float(temperature) if temperature not in (None, "") else None,
        max_output_tokens=int(params.get("max_output_tokens") or 2048),
        json_schema=built.json_schema if native_schema else None,
    )

    received: list[str] = []
    last = [time.monotonic()]
    last_db_check = [time.monotonic()]

    def on_delta(text: str) -> None:
        received.append(text)
        now = time.monotonic()
        if now - last[0] >= PROGRESS_EVERY_S:
            last[0] = now
            with ctx.db.tx() as s2:
                j = s2.get(Job, job_id)
                if j is not None:
                    j.stage = "receiving"
                    j.progress_done = sum(len(x) for x in received)
                    j.partial_output = "".join(received)[-20_000:]
                    j.lease_expires_at = to_iso(ctx.clock.now() + timedelta(seconds=LEASE_SECONDS))
                    if j.cancel_requested:
                        cancel.set()

    def should_cancel() -> bool:
        now = time.monotonic()
        if not cancel.is_set() and now - last_db_check[0] > 1.0:
            last_db_check[0] = now
            with ctx.db.tx() as s3:
                j = s3.get(Job, job_id)
                if j is not None and j.cancel_requested:
                    cancel.set()
        return cancel.is_set()

    try:
        with ctx.db.tx() as s:
            j = s.get(Job, job_id)
            if j is not None:
                j.stage = "calling_model"
                add_log(
                    s, ctx, job_id, f"Calling {snapshot['kind']} model {snapshot['model']} (template {built.template})."
                )
        permit = registry.permit_for(ctx, provider, project_id=snapshot["project_id"])
        adapter = registry.build(ctx, provider, permit)
        slot = ollama_slot if snapshot["kind"] == "ollama" else None
        if slot:
            slot.acquire()
        try:
            with cloud_activity(snapshot["kind"], adapter.local):
                result = adapter.stream_chat(req, on_delta, should_cancel)
        finally:
            if slot:
                slot.release()
        payload = result.text.strip()
        if not payload:
            raise ProviderError("invalid_output", "The model returned an empty answer.")
        if planning:
            planned = planning_exec.parse(inp, payload, ctx.ids.new)
        elif writing and prepared is not None:
            written = writing_exec.parse(inp, payload, prepared)
        elif built.json_schema is not None:
            payload = _structured_to_markdown(payload)
        if masked is not None:
            try:
                payload = protect.unmask(payload, masked)
            except protect.ProtectedContentChanged as exc:
                raise ProviderError(
                    "invalid_output",
                    "The suggestion changed, dropped or repeated protected code or math "
                    f"({len(exc.missing)} missing, {len(exc.repeated)} repeated); it was discarded.",
                ) from exc
        # Check every citation marker against the passages actually provided; flag the rest.
        if not planning and not writing:
            processed = citations.process(payload, found.refs)
            payload = processed.text_md
    except Cancelled:
        _finish(
            ctx,
            job_id,
            status="cancelled",
            code="cancelled",
            message="Cancelled by the author. Nothing was applied.",
            partial="".join(received),
        )
        return
    except EgressBlockedError as exc:
        _finish(ctx, job_id, status="failed", code="egress_blocked", message=str(exc), partial=None)
        return
    except ProviderError as exc:
        partial = "".join(received)
        if exc.retryable and snapshot["attempt"] < snapshot["max_attempts"]:
            delay = _backoff(snapshot["attempt"], exc.retry_after)
            with ctx.db.tx() as s:
                j = s.get(Job, job_id)
                if j is not None:
                    j.status, j.stage = "queued", "waiting_to_retry"
                    j.run_after = to_iso(ctx.clock.now() + timedelta(seconds=delay))
                    j.error_code, j.error_message = exc.code, exc.message
                    j.lease_owner = None
                    add_log(s, ctx, job_id, f"{exc.message} Retrying in {delay:.1f} s.", "warning")
            return
        _finish(ctx, job_id, status="failed", code=exc.code, message=exc.message, partial=partial)
        return
    except Exception as exc:
        log.exception("job_failed_unexpectedly", job_id=job_id)
        _finish(
            ctx,
            job_id,
            status="failed",
            code="internal_error",
            message=f"Unexpected error: {type(exc).__name__}. See the Core log.",
            partial="".join(received),
        )
        return

    if planning:
        planning_exec.commit(ctx, job_id, inp, planned, result, provider, snapshot, built.template)
        return
    if writing and prepared is not None:
        writing_exec.commit(ctx, job_id, inp, written, prepared, result, provider, snapshot)
        return
    if processed is None:  # pragma: no cover - chapter jobs always process citations above
        raise RuntimeError("chapter job finished without citation processing")
    knowledge = {
        "query": found.query[:300],
        "sources": [
            {
                "label": r.label,
                "source_id": r.source_id,
                "chunk_id": r.chunk_id,
                "title": r.title,
                "citation_key": r.citation_key,
                "locator": r.locator,
            }
            for r in found.refs.values()
            if r.kind == "source"
        ],
        "interview_answers": [
            {"label": r.label, "answer_id": r.answer_id, "question": r.title}
            for r in found.refs.values()
            if r.kind == "interview"
        ],
        "usable_sources": found.source_count,
        "used_sources": bool(inp.get("use_sources", True)),
        "voice_profile": voice.get("name") if voice else None,
        **processed.summary(),
        **({"protected": protect.summary(masked)} if masked is not None else {}),
        **({"editor_action": inp["action"]} if inp.get("action") else {}),
    }
    _commit(ctx, job_id, payload, result, provider, snapshot, built.template, inp, knowledge, processed)


def retrieval_query(instruction: str, selection: str | None, context_text: str, chapter_title: str) -> str:
    """What to search the book's sources for: the request, the selection or the end of the chapter, the title."""
    focus = selection if selection else context_text[-1500:]
    return f"{instruction} {focus} {chapter_title}"


def _structured_to_markdown(text: str) -> str:
    try:
        data = extract_json(text)
        ideas = data["ideas"]
        if not isinstance(ideas, list) or not ideas:
            raise ValueError("empty")
        lines = [f"- **{str(i['title']).strip()}**: {str(i['description']).strip()}" for i in ideas]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderError("invalid_output", "The model did not return the requested structured answer.") from exc
    return "\n".join(lines)


def _commit(
    ctx: AppContext,
    job_id: str,
    payload: str,
    result: Any,
    provider: ProviderConfig,
    snapshot: dict[str, Any],
    template: str,
    inp: dict[str, Any],
    knowledge: dict[str, Any],
    processed: citations.Processed,
) -> None:
    with ctx.db.tx() as s:
        job = s.get(Job, job_id)
        if job is None or job.status != "running":
            return  # finished elsewhere meanwhile: discard
        if job.cancel_requested:
            job.status, job.stage, job.finished_at, job.lease_owner = "cancelled", "cancelled", ctx.clock.iso(), None
            job.error_code, job.error_message = "cancelled", "Cancelled by the author. Nothing was applied."
            add_log(s, ctx, job_id, job.error_message)
            return
        existing = s.scalars(select(Proposal).where(Proposal.job_id == job_id)).one_or_none()
        cost = costs.cost_of(s, provider, snapshot["model"], result.usage)
        if inp.get("run_id"):  # part of a generation run: enforce its budget cap
            runs.record_cost(s, ctx, inp["run_id"], cost.amount, cost.currency, job_id)
        s.add(
            UsageRecord(
                id=ctx.ids.new(),
                job_id=job_id,
                project_id=snapshot["project_id"],
                provider_kind=snapshot["kind"],
                model_name=snapshot["model"],
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                reported_by_provider=1 if result.usage.reported else 0,
                cost_amount=cost.amount,
                currency=cost.currency,
                price_basis=cost.basis,
                attempt=snapshot["attempt"],
                created_at=ctx.clock.iso(),
            )
        )
        if existing is None:  # exactly one proposal per job, even across retries and restarts
            mode = inp.get("mode", "note")
            proposal_id = ctx.ids.new()
            s.add(
                Proposal(
                    id=proposal_id,
                    project_id=snapshot["project_id"],
                    chapter_id=snapshot["chapter_id"],
                    job_id=job_id,
                    base_revision_id=inp.get("base_revision_id"),
                    base_revision_no=inp.get("base_revision_no"),
                    mode=mode,
                    selection_start=inp.get("selection_start"),
                    selection_end=inp.get("selection_end"),
                    original_text=inp.get("selection_text"),
                    payload_md=payload,
                    status="pending",
                    provenance_json=json.dumps(
                        {
                            "provider_kind": snapshot["kind"],
                            "provider_label": provider.label,
                            "model": result.model or snapshot["model"],
                            "task": snapshot["task"],
                            "template": template,
                            "instruction": inp.get("instruction", "")[:500],
                            "finish_reason": result.finish_reason,
                            "generated_at": ctx.clock.iso(),
                            "knowledge": knowledge,
                            "outline_node_id": inp.get("outline_node_id"),
                            "requirements_check": runs.requirements_check(inp["requirements"], processed, payload)
                            if inp.get("requirements")
                            else None,
                        }
                    ),
                    created_at=ctx.clock.iso(),
                )
            )
            s.flush()
            evidence.record_proposal_claims(
                s,
                ctx,
                project_id=snapshot["project_id"],
                chapter_id=snapshot["chapter_id"],
                proposal_id=proposal_id,
                processed=processed,
            )
        job.status, job.stage = "succeeded", "ready_for_review"
        job.finished_at = ctx.clock.iso()
        job.lease_owner = None
        job.partial_output = None
        job.progress_done = len(payload)
        tokens = f"{result.usage.input_tokens or '?'} in / {result.usage.output_tokens or '?'} out"
        add_log(
            s,
            ctx,
            job_id,
            f"Finished: {tokens} tokens ({'reported' if result.usage.reported else 'estimated'}). Ready for review.",
        )
        activity.record(
            s,
            ctx,
            kind="ai_suggestion_ready",
            summary=f"AI suggestion ready ({snapshot['task']}, {snapshot['model']})",
            project_id=snapshot["project_id"],
            ref_type="job",
            ref_id=job_id,
        )
