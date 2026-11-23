"""Planning jobs (outline generation, research brainstorms): prompt, validate, commit.

Called from jobs/execute.py for jobs whose input has ``kind`` set. Retries, cancellation, the
egress gate and usage accounting work exactly as for chapter jobs; only the prompt and what is
committed differ:

* an outline becomes a NEW *proposed* outline version (never overwriting the author's draft or the
  approved outline), with the author's locked entries carried over unchanged;
* a brainstorm becomes heuristic research findings with every unsupported market figure removed.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from pbs_core.context import AppContext
from pbs_core.jobs import planning_prompts as pp
from pbs_core.jobs.prompts import BuiltPrompt
from pbs_core.jobs.runner import add_log
from pbs_core.planning import outline as ol
from pbs_core.planning.research import FORBIDDEN_NOTE, strip_metric_claims
from pbs_core.providers.base import ProviderError
from pbs_core.services import activity, costs
from pbs_core.storage.ai_models import Job, ProviderConfig, UsageRecord
from pbs_core.storage.planning_models import OutlineVersion, ResearchFinding

KINDS = frozenset({"outline", "research_ideas"})


def build(inp: dict[str, Any]) -> BuiltPrompt:
    if inp["kind"] == "outline":
        return pp.outline(
            title=inp.get("title", ""),
            brief=inp.get("brief", {}),
            findings=inp.get("findings", []),
            desired_chapters=inp.get("desired_chapters"),
            target_words=inp.get("target_words"),
            locked_titles=inp.get("locked_titles", []),
            instruction=inp.get("instruction", ""),
        )
    return pp.research(
        what=inp["what"],
        title=inp.get("title", ""),
        brief=inp.get("brief", {}),
        findings=inp.get("findings", []),
        instruction=inp.get("instruction", ""),
    )


def parse(inp: dict[str, Any], payload: str, new_id: Any) -> Any:
    try:
        data = pp.parse_json(payload)
        if inp["kind"] == "outline":
            chapters = data["chapters"]
            if not isinstance(chapters, list) or not chapters:
                raise ValueError("no chapters")
            fiction = inp.get("brief", {}).get("kind") == "fiction"
            nodes = []
            for c in chapters[:120]:
                reqs = [str(x) for x in (c.get("requirements") or []) if str(x).strip()]
                requirements = (
                    {"plot_points": reqs, "characters": [], "continuity": []}
                    if fiction
                    else {"citations_min": int(inp.get("default_citations_min", 0)), "source_ids": [], "notes": reqs}
                )
                nodes.append(
                    {
                        "kind": "chapter",
                        "title": c["title"],
                        "goal": c.get("goal", ""),
                        "target_words": c.get("target_words"),
                        "requirements": requirements,
                        "children": [
                            {"kind": "section", "title": x["title"], "goal": x.get("goal", "")}
                            for x in (c.get("sections") or [])
                        ],
                    }
                )
            return ol.normalise(nodes, fiction=fiction, new_id=new_id)
        items = data["items"]
        if not isinstance(items, list) or not items:
            raise ValueError("no items")
        return [
            {"text": str(i["text"]).strip(), "rationale": str(i.get("rationale", "")).strip()}
            for i in items[:50]
            if str(i.get("text", "")).strip()
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("invalid_output", "The model did not return the requested structured answer.") from exc


def commit(
    ctx: AppContext,
    job_id: str,
    inp: dict[str, Any],
    parsed: Any,
    result: Any,
    provider: ProviderConfig,
    snapshot: dict[str, Any],
    template: str,
) -> None:
    pid = snapshot["project_id"]
    with ctx.db.tx() as s:
        job = s.get(Job, job_id)
        if job is None or job.status != "running":
            return
        if job.cancel_requested:
            job.status, job.stage, job.finished_at, job.lease_owner = "cancelled", "cancelled", ctx.clock.iso(), None
            job.error_code, job.error_message = "cancelled", "Cancelled by the author. Nothing was saved."
            add_log(s, ctx, job_id, job.error_message)
            return
        cost = costs.cost_of(s, provider, snapshot["model"], result.usage)
        s.add(
            UsageRecord(
                id=ctx.ids.new(),
                job_id=job_id,
                project_id=pid,
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
        now = ctx.clock.iso()
        provenance = {
            "provider_kind": snapshot["kind"],
            "provider_label": provider.label,
            "model": result.model or snapshot["model"],
            "template": template,
            "generated_at": now,
            "job_id": job_id,
        }
        if inp["kind"] == "outline":
            exists = s.scalars(select(OutlineVersion).where(OutlineVersion.job_id == job_id)).first()
            if exists is None:  # one outline per job, even across retries
                base = s.get(OutlineVersion, inp["based_on_id"]) if inp.get("based_on_id") else None
                nodes, kept = ol.keep_locked(parsed, json.loads(base.nodes_json) if base else [])
                no = (
                    s.scalar(select(func.max(OutlineVersion.version_no)).where(OutlineVersion.project_id == pid)) or 0
                ) + 1
                s.add(
                    OutlineVersion(
                        id=ctx.ids.new(),
                        project_id=pid,
                        version_no=no,
                        status="proposed",
                        origin="ai_generated",
                        nodes_json=json.dumps(nodes),
                        based_on_id=base.id if base else None,
                        brief_version=inp.get("brief_version"),
                        research_ids_json=json.dumps(inp.get("research_ids", [])),
                        job_id=job_id,
                        provenance_json=json.dumps({**provenance, "kept_locked": kept}),
                        note=f"Proposed by {snapshot['model']}",
                        created_at=now,
                        updated_at=now,
                    )
                )
                summary = f"AI outline proposal ready ({len(nodes)} entries)"
            else:
                summary = "AI outline proposal ready"
        else:
            kind = {"topics": "topic", "queries": "query", "keywords": "keyword"}[inp["what"]]
            removed_total = 0
            if (
                s.scalar(
                    select(func.count())
                    .select_from(ResearchFinding)
                    .where(ResearchFinding.meta_json.like(f'%"job_id": "{job_id}"%'))
                )
                == 0
            ):
                for item in parsed:
                    text = strip_metric_claims(item["text"])
                    why = strip_metric_claims(item["rationale"])
                    removed = text.removed + why.removed
                    if not text.text:
                        removed_total += len(removed)
                        continue
                    flags = ["ai_brainstorm_not_measured"] + (["removed_unsupported_metric"] if removed else [])
                    if kind == "keyword":
                        flags.append("no_search_volume_data")
                    removed_total += len(removed)
                    s.add(
                        ResearchFinding(
                            id=ctx.ids.new(),
                            project_id=pid,
                            kind=kind,
                            origin="ai_brainstorm",
                            text=text.text + (f"\n\nWhy: {why.text}" if why.text else ""),
                            meta_json=json.dumps(
                                {
                                    "job_id": job_id,
                                    "model": provenance["model"],
                                    **({"removed": FORBIDDEN_NOTE} if removed else {}),
                                }
                            ),
                            flags_json=json.dumps(flags),
                            created_at=now,
                            updated_at=now,
                        )
                    )
            summary = f"Research ideas ready ({inp['what']})" + (
                f"; {removed_total} unsupported market statement(s) removed" if removed_total else ""
            )
        job.status, job.stage = "succeeded", "ready_for_review"
        job.finished_at, job.lease_owner, job.partial_output = now, None, None
        add_log(s, ctx, job_id, summary)
        activity.record(
            s, ctx, kind="ai_planning_ready", summary=summary, project_id=pid, ref_type="job", ref_id=job_id
        )
