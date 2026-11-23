"""What a section prompt knows about the rest of the book: brief, local outline, earlier chapters
(summaries), running continuity memory. Read from the database at the moment the job runs."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.planning import outline as ol
from pbs_core.services import chapters as chapter_service
from pbs_core.storage.ai_models import Proposal
from pbs_core.storage.models import Chapter, ChapterRevision, Project
from pbs_core.storage.planning_models import BookBrief, OutlineVersion
from pbs_core.storage.writing_models import ChapterSummary, ContinuityFact, DraftPlan, DraftSection

FICTION_TYPES = ("fiction", "serial")


def brief_of(s: Session, project_id: str) -> BookBrief | None:
    return s.get(BookBrief, project_id)


def is_fiction(s: Session, project: Project) -> bool:
    b = brief_of(s, project.id)
    return (b.kind == "fiction") if b is not None else project.project_type in FICTION_TYPES


def exclusions(s: Session, project_id: str) -> list[str]:
    b = brief_of(s, project_id)
    return [str(x) for x in json.loads(b.exclusions_json)] if b is not None else []


def brief_text(s: Session, project: Project) -> str:
    b = brief_of(s, project.id)
    lines = [f"Title: {project.title}"]
    if project.audience:
        lines.append(f"Audience: {project.audience}")
    if b is not None:
        for label, value in (
            ("Kind of book", b.kind),
            ("Genre", b.genre),
            ("Purpose", b.purpose),
            ("Target reader", b.target_reader),
            ("Core promise", b.promise),
            ("Value proposition", b.value_proposition),
            ("Tone", b.tone),
            ("Arc", b.arc_md),
        ):
            if value:
                lines.append(f"{label}: {value}")
        ex = json.loads(b.exclusions_json)
        if ex:
            lines.append("Leave out: " + "; ".join(ex))
        assumptions = json.loads(b.assumptions_json)
        if assumptions:
            lines.append(
                "Stated assumptions: "
                + "; ".join(str(a.get("text", "")) if isinstance(a, dict) else str(a) for a in assumptions)
            )
    return "\n".join(lines)


def node_for(s: Session, plan: DraftPlan) -> dict[str, Any] | None:
    if not plan.outline_version_id or not plan.outline_node_id:
        return None
    o = s.get(OutlineVersion, plan.outline_version_id)
    if o is None:
        return None
    found = ol.node_index(json.loads(o.nodes_json)).get(plan.outline_node_id)
    return found[0] if found else None


def outline_text(chapter: Chapter, node: dict[str, Any] | None, secs: list[DraftSection], current: DraftSection) -> str:
    lines = [f"Chapter: {chapter.title}"]
    if node and node.get("goal"):
        lines.append(f"Chapter goal: {node['goal']}")
    req = (node or {}).get("requirements") or {}
    for label, key in (("Plot points", "plot_points"), ("Characters", "characters"), ("Continuity", "continuity")):
        if req.get(key):
            lines.append(f"{label}: " + "; ".join(req[key]))
    if req.get("citations_min"):
        lines.append(f"Back at least {req['citations_min']} factual statement(s) in the chapter with sources.")
    if req.get("notes"):
        lines.append("Requirements: " + "; ".join(req["notes"]))
    lines.append("Sections:")
    for x in secs:
        mark = "→ (write this one)" if x.id == current.id else ("(done)" if x.status == "done" else "")
        goal = f": {x.goal}" if x.goal else ""
        words = f" (about {x.target_words} words)" if x.target_words and x.id == current.id else ""
        lines.append(f"{x.ordinal}. {x.title}{goal}{words} {mark}".rstrip())
    return "\n".join(lines)


def so_far(s: Session, plan: DraftPlan, secs: list[DraftSection], current: DraftSection) -> str:
    base = ""
    if plan.base_revision_id:
        rev = s.get(ChapterRevision, plan.base_revision_id)
        base = rev.source_md if rev else ""
    parts = [base.strip()] if base.strip() else []
    for x in secs:
        if x.ordinal >= current.ordinal or x.status != "done":
            continue
        if x.heading:
            parts.append(f"## {x.title}")
        parts.append((x.output_md or "").strip())
    return "\n\n".join(p for p in parts if p)


def _first_lines(text: str, n: int = 3) -> str:
    out = []
    for para in re.split(r"\n\s*\n", text):
        p = " ".join(para.split())
        if not p or p.startswith(("#", "```", "|", "!")):
            continue
        m = re.match(r"(.+?[.!?])(\s|$)", p)
        out.append((m.group(1) if m else p)[:300])
        if len(out) >= n:
            break
    return " ".join(out)


def summary_items(s: Session, project_id: str, chapter_id: str) -> list[str]:
    """Earlier chapters, nearest first: the newest usable summary, or the chapter's first lines."""
    ordered = [c for c, _ in chapter_service.tree_order(chapter_service.active_chapters(s, project_id))]
    ids = [c.id for c in ordered]
    if chapter_id not in ids:
        return []
    earlier = ordered[: ids.index(chapter_id)]
    items: list[str] = []
    for no, c in reversed(list(enumerate(earlier, start=1))):
        rows = s.scalars(
            select(ChapterSummary).where(ChapterSummary.chapter_id == c.id).order_by(ChapterSummary.created_at.desc())
        ).all()
        text = None
        for r in rows:
            if r.plan_id:
                plan = s.get(DraftPlan, r.plan_id)
                prop = s.get(Proposal, plan.proposal_id) if plan and plan.proposal_id else None
                if prop is not None and prop.status == "rejected":
                    continue  # the draft it summarised was rejected
                label = "summary of a draft" if prop is None or prop.status != "accepted" else "summary"
            else:
                label = "author's summary"
            text = f"Chapter {no}, “{c.title}” ({label}): {r.text}"
            break
        if text is None and c.head_revision_id:
            rev = s.get(ChapterRevision, c.head_revision_id)
            first = _first_lines(rev.source_md) if rev else ""
            if first:
                text = f"Chapter {no}, “{c.title}” (first lines, no summary yet): {first}"
        if text:
            items.append(text)
    return items


def fact_line(f: ContinuityFact) -> str:
    attr = f" {f.attribute}:" if f.attribute else ":"
    when = f" (story time: {f.story_time})" if f.story_time else ""
    state = "confirmed by the author" if f.status in ("confirmed", "resolved") else "from an earlier draft, unconfirmed"
    return f"[{f.kind}] {f.name}{attr} {f.value}{when} ({state})"


def fact_items(s: Session, project_id: str) -> list[str]:
    rows = s.scalars(
        select(ContinuityFact)
        .where(ContinuityFact.project_id == project_id, ContinuityFact.status != "rejected")
        .order_by(ContinuityFact.updated_at.desc())
    ).all()
    usable = []
    for f in rows:
        if f.plan_id and f.origin == "ai_extracted":
            plan = s.get(DraftPlan, f.plan_id)
            prop = s.get(Proposal, plan.proposal_id) if plan and plan.proposal_id else None
            if prop is not None and prop.status == "rejected":
                continue
        usable.append(f)
    usable.sort(key=lambda f: 0 if f.status in ("confirmed", "resolved") else 1)
    return [fact_line(f) for f in usable]
