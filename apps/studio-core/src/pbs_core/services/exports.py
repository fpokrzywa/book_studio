"""Exports. Phase 01: deterministic Markdown (`pbs-md-export/1`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import and_, select

from pbs_core.context import AppContext
from pbs_core.contracts import ExportOut
from pbs_core.domain.errors import NotFoundError
from pbs_core.domain.ids import is_ulid
from pbs_core.services import activity
from pbs_core.services.projects import require_project
from pbs_core.storage.models import Chapter, ChapterRevision, ExportRun, Project
from pbs_core.storage.paths import atomic_write_bytes, safe_join, sanitize_filename

EXPORT_SCHEMA = "pbs-md-export/1"


def _q(value: str) -> str:
    """YAML double-quoted scalar (JSON string syntax is valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def render_markdown(
    project: Project, export_id: str, chapters: list[tuple[Chapter, ChapterRevision | None]]
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    lines = ["---", f"title: {_q(project.title)}"]
    if project.subtitle:
        lines.append(f"subtitle: {_q(project.subtitle)}")
    if project.author_name:
        lines.append(f"author: {_q(project.author_name)}")
    lines += [
        f"lang: {_q(project.language)}",
        "pbs_export:",
        f"  schema: {_q(EXPORT_SCHEMA)}",
        f"  project_id: {_q(project.id)}",
        f"  export_id: {_q(export_id)}",
        "---",
        "",
    ]
    body = "\n".join(lines)
    parts: list[str] = [body]
    for chapter, head in chapters:
        section = f"# {chapter.title} {{#ch-{chapter.slug}}}\n\n"
        if head is None or not head.source_md.strip():
            warnings.append(f"Chapter “{chapter.title}” has no saved content; exported as a heading only.")
        else:
            text = head.source_md if head.source_md.endswith("\n") else head.source_md + "\n"
            section += text
        parts.append(section)
    if not chapters:
        warnings.append("The project has no chapters; the export contains metadata only.")
    return "\n".join(parts), warnings


def _out(run: ExportRun) -> ExportOut:
    revision_set = json.loads(run.revision_set_json)
    return ExportOut(
        id=run.id,
        project_id=run.project_id,
        format="markdown",
        status=run.status,
        file_name=run.file_name,
        sha256=run.sha256,
        byte_size=run.byte_size,
        chapter_count=len(revision_set),
        warnings=json.loads(run.warnings_json),
        started_at=run.started_at,
        finished_at=run.finished_at,
        download_url=(f"/api/projects/{run.project_id}/exports/{run.id}/file" if run.status == "completed" else None),
    )


def export_markdown(ctx: AppContext, project_id: str) -> ExportOut:
    started = ctx.clock.iso()
    export_id = ctx.ids.new()
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        rows = s.execute(
            select(Chapter, ChapterRevision)
            .outerjoin(
                ChapterRevision,
                and_(
                    ChapterRevision.project_id == Chapter.project_id,
                    ChapterRevision.id == Chapter.head_revision_id,
                ),
            )
            .where(Chapter.project_id == project_id, Chapter.archived_at.is_(None))
            .order_by(Chapter.position, Chapter.id)
        ).all()
        chapters: list[tuple[Chapter, ChapterRevision | None]] = [(c, r) for c, r in rows]
        text, warnings = render_markdown(project, export_id, chapters)
        data = text.encode("utf-8")
        file_name = f"{sanitize_filename(project.title)}.md"
        rel = f"exports/{export_id}/{file_name}"
        target = safe_join(ctx.workspace.project_dir(project_id), rel)
        atomic_write_bytes(target, data)
        run = ExportRun(
            id=export_id,
            project_id=project_id,
            format="markdown",
            revision_set_json=json.dumps({c.id: (r.id if r else None) for c, r in chapters}),
            status="completed",
            output_path=rel,
            file_name=file_name,
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            warnings_json=json.dumps(warnings, ensure_ascii=False),
            started_at=started,
            finished_at=ctx.clock.iso(),
        )
        s.add(run)
        activity.record(
            s,
            ctx,
            kind="export_completed",
            summary=f"Exported “{project.title}” as Markdown",
            project_id=project_id,
            ref_type="export_run",
            ref_id=export_id,
        )
        s.flush()
        return _out(run)


def list_exports(ctx: AppContext, project_id: str) -> list[ExportOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        runs = s.scalars(
            select(ExportRun).where(ExportRun.project_id == project_id).order_by(ExportRun.started_at.desc()).limit(20)
        ).all()
        return [_out(r) for r in runs]


def export_file(ctx: AppContext, project_id: str, export_id: str) -> tuple[Path, str]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        run = (
            s.scalars(
                select(ExportRun).where(ExportRun.project_id == project_id, ExportRun.id == export_id)
            ).one_or_none()
            if is_ulid(export_id)
            else None
        )
        if run is None or run.output_path is None or run.file_name is None:
            raise NotFoundError("Export not found.")
        path = safe_join(ctx.workspace.project_dir(project_id), run.output_path)
        if not path.is_file():
            raise NotFoundError("The export file is missing from disk.")
        return path, run.file_name
