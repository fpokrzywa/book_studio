"""Document helpers bound to the app: parse with app IDs, upcast old BDM, render previews."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import PreviewOut, WarningOut
from pbs_core.document import bookmd
from pbs_core.document import html as html_render
from pbs_core.services.projects import require_project
from pbs_core.storage.models import Asset, ChapterRevision


def parse(ctx: AppContext, source: str, chapter_id: str, previous: dict[str, Any] | None = None) -> bookmd.ParseResult:
    return bookmd.parse(source, chapter_id=chapter_id, new_id=ctx.ids.new, previous=previous)


def bdm_of(ctx: AppContext, revision: ChapterRevision) -> dict[str, Any]:
    """Canonical bdm/1 for a revision; older schemas are re-derived from the authoritative source."""
    doc: dict[str, Any] = json.loads(revision.bdm_json)
    if doc.get("schema") == bookmd.BDM_SCHEMA:
        return doc
    return parse(ctx, revision.source_md, revision.chapter_id).doc


def asset_url(project_id: str, short_hash: str) -> str:
    return f"/api/projects/{project_id}/assets/{short_hash}"


def known_assets(s: Session, project_id: str) -> set[str]:
    return set(s.scalars(select(Asset.short_hash).where(Asset.project_id == project_id)).all())


def warnings_out(items: list[dict[str, Any]]) -> list[WarningOut]:
    return [WarningOut(code=w["code"], message=w["message"], line=w.get("line")) for w in items]


def preview(ctx: AppContext, project_id: str, source: str, chapter_id: str = "preview") -> PreviewOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        assets = known_assets(s, project_id)
    result = parse(ctx, source, chapter_id)
    rendered = html_render.render(
        result.doc, lambda h: asset_url(project_id, h) if h in assets else None, external_images=False
    )
    warnings = [w.as_dict() for w in result.warnings] + rendered.warnings
    return PreviewOut(
        html=rendered.html,
        word_count=result.word_count,
        warnings=warnings_out(warnings),
        citation_keys=bookmd.citation_keys(result.doc),
        block_count=sum(1 for _ in bookmd.walk_blocks(result.doc)),
    )
