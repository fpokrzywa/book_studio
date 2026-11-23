"""Generation runs: budget enforcement while jobs finish, and per-chapter requirement checks.

The budget cap is enforced twice: before a run starts (the estimated upper bound must fit) and as
each chapter finishes (actual cost from reported usage and the author's price). If the cap is
reached, or a cost cannot be known while a cap is set, every queued chapter of the run is cancelled
and the run is stopped with the reason. Nothing is ever applied automatically either way.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.jobs.runner import add_log
from pbs_core.storage.ai_models import Job
from pbs_core.storage.planning_models import GenerationRun


def record_cost(
    s: Session, ctx: AppContext, run_id: str, amount: str | None, currency: str | None, job_id: str
) -> None:
    run = s.get(GenerationRun, run_id)
    if run is None:
        return
    if amount is None:
        run.unknown_cost_calls += 1
    elif currency in (None, run.currency) or run.budget_cap is None:
        run.spent = str(Decimal(run.spent) + Decimal(amount))
    if run.budget_cap is None or run.status != "running":
        return
    reason = None
    if amount is None:
        reason = "Stopped: the cost of a chapter could not be determined while a budget cap is set."
    elif currency not in (None, run.currency):
        reason = f"Stopped: a chapter was priced in {currency}, but the budget is in {run.currency}."
    elif Decimal(run.spent) >= Decimal(run.budget_cap):
        reason = f"Stopped: the budget cap of {run.budget_cap} {run.currency or ''} was reached ({run.spent} spent)."
    if reason:
        stop(s, ctx, run, reason, except_job=job_id)


def stop(s: Session, ctx: AppContext, run: GenerationRun, reason: str, *, except_job: str | None = None) -> None:
    now = ctx.clock.iso()
    for jid in json.loads(run.job_ids_json):
        if jid == except_job:
            continue
        job = s.get(Job, jid)
        if job is None:
            continue
        if job.status == "queued":
            job.status, job.stage, job.finished_at = "cancelled", "cancelled", now
            job.cancel_requested = 1
            job.error_code, job.error_message = "budget_stop", reason
            add_log(s, ctx, jid, reason, "warning")
        elif job.status == "running":
            job.cancel_requested = 1
            add_log(s, ctx, jid, reason, "warning")
    run.status, run.stop_reason, run.finished_at = "stopped", reason, now


def requirements_check(req: dict[str, Any], processed: Any, payload: str) -> dict[str, Any]:
    """What can be checked mechanically against the chapter's outline requirements."""
    out: dict[str, Any] = {}
    if "citations_min" in req:
        found = sum(
            1 for p in processed.paragraphs for x in p["supports"] if x.get("kind") == "source" and x.get("located")
        )
        need = int(req.get("citations_min") or 0)
        out["citations"] = {"required": need, "found": found, "met": found >= need}
    if req.get("characters"):
        missing = [c for c in req["characters"] if not re.search(re.escape(c), payload, re.IGNORECASE)]
        out["characters"] = {"required": req["characters"], "missing": missing, "met": not missing}
    if req.get("plot_points") or req.get("continuity"):
        out["plot_and_continuity"] = {
            "met": None,
            "note": "Plot points and continuity cannot be checked automatically; review them yourself.",
        }
    return out
