"""Save quality findings so the author's decisions survive re-runs."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.storage.writing_models import QualityFinding
from pbs_core.writing.quality import Finding


def upsert(
    s: Session,
    ctx: AppContext,
    project_id: str,
    findings: list[Finding],
    *,
    origin: str,
    checks: list[str],
    chapter_ids: set[str] | None,
    revisions: dict[str, int],
) -> tuple[int, int]:
    """Insert new findings, refresh seen ones, and mark findings of the re-run checks that are no
    longer found as not present (they are kept, with the author's decision). Returns (new, seen)."""
    now = ctx.clock.iso()
    existing = {
        f.fingerprint: f
        for f in s.scalars(
            select(QualityFinding).where(QualityFinding.project_id == project_id, QualityFinding.origin == origin)
        )
    }
    new = seen = 0
    found_fps = set()
    for f in findings:
        fp = f.fingerprint
        found_fps.add(fp)
        row = existing.get(fp)
        if row is None:
            row = s.scalars(
                select(QualityFinding).where(QualityFinding.project_id == project_id, QualityFinding.fingerprint == fp)
            ).first()
        if row is None:
            s.add(
                QualityFinding(
                    id=ctx.ids.new(),
                    project_id=project_id,
                    chapter_id=f.chapter_id,
                    check_code=f.check,
                    origin=origin,
                    severity=f.severity,
                    fingerprint=fp,
                    message=f.message[:2000],
                    excerpt=(f.excerpt or "")[:1000] or None,
                    details_json=json.dumps({**f.details, "_key": f.key}, ensure_ascii=False),
                    revision_no=revisions.get(f.chapter_id or ""),
                    present=1,
                    state="open",
                    created_at=now,
                    updated_at=now,
                    last_seen_at=now,
                )
            )
            new += 1
        else:
            row.present, row.last_seen_at = 1, now
            row.message, row.details_json = (
                f.message[:2000],
                json.dumps({**f.details, "_key": f.key}, ensure_ascii=False),
            )
            row.revision_no = revisions.get(f.chapter_id or "", row.revision_no)
            if row.state == "fixed":  # it came back
                row.state, row.updated_at = "open", now
            seen += 1
    for fp, row in existing.items():
        if fp in found_fps or row.check_code not in checks:
            continue
        if chapter_ids is not None and row.chapter_id not in chapter_ids:
            continue
        if row.present:
            row.present, row.updated_at = 0, now
    return new, seen
