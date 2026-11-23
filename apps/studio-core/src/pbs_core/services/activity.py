"""User-facing activity log (never holds secrets or manuscript text)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import ActivityOut
from pbs_core.storage.models import ActivityEvent, Project


def record(
    s: Session,
    ctx: AppContext,
    *,
    kind: str,
    summary: str,
    project_id: str | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> None:
    s.add(
        ActivityEvent(
            id=ctx.ids.new(),
            project_id=project_id,
            kind=kind,
            summary=summary[:500],
            ref_type=ref_type,
            ref_id=ref_id,
            created_at=ctx.clock.iso(),
        )
    )


def list_activity(ctx: AppContext, *, project_id: str | None = None, limit: int = 50) -> list[ActivityOut]:
    stmt = (
        select(ActivityEvent, Project.title)
        .outerjoin(Project, Project.id == ActivityEvent.project_id)
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    if project_id is not None:
        stmt = stmt.where(ActivityEvent.project_id == project_id)
    with ctx.db.tx() as s:
        return [
            ActivityOut(
                id=e.id,
                project_id=e.project_id,
                project_title=title,
                kind=e.kind,
                summary=e.summary,
                ref_type=e.ref_type,
                ref_id=e.ref_id,
                created_at=e.created_at,
            )
            for e, title in s.execute(stmt).all()
        ]
