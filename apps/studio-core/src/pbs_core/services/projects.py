"""Project library use cases: create, read, list/search/sort, edit, archive, duplicate."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import ProjectCreate, ProjectList, ProjectOut, ProjectPatch
from pbs_core.document import bookmd_v0
from pbs_core.domain.errors import ArchivedError, NotFoundError
from pbs_core.domain.ids import is_ulid
from pbs_core.services import activity
from pbs_core.storage.models import Chapter, ChapterRevision, Project


def _stats_subquery() -> Any:
    return (
        select(
            Chapter.project_id.label("project_id"),
            func.count(Chapter.id).label("chapters"),
            func.coalesce(func.sum(ChapterRevision.word_count), 0).label("words"),
        )
        .select_from(Chapter)
        .outerjoin(
            ChapterRevision,
            and_(
                ChapterRevision.project_id == Chapter.project_id,
                ChapterRevision.id == Chapter.head_revision_id,
            ),
        )
        .where(Chapter.archived_at.is_(None))
        .group_by(Chapter.project_id)
        .subquery()
    )


def _to_out(p: Project, chapters: int | None, words: int | None) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        title=p.title,
        subtitle=p.subtitle,
        author_name=p.author_name,
        project_type=p.project_type,
        language=p.language,
        audience=p.audience,
        target_word_count=p.target_word_count,
        publication_formats=json.loads(p.publication_formats),
        status=p.status,
        is_demo=bool(p.is_demo),
        duplicated_from_id=p.duplicated_from_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        archived_at=p.archived_at,
        chapter_count=int(chapters or 0),
        word_count=int(words or 0),
    )


def _with_stats() -> tuple[Select[Any], Any]:
    stats = _stats_subquery()
    stmt = select(Project, stats.c.chapters, stats.c.words).outerjoin(stats, stats.c.project_id == Project.id)
    return stmt, stats


def require_project(s: Session, project_id: str) -> Project:
    project = s.get(Project, project_id) if is_ulid(project_id) else None
    if project is None:
        raise NotFoundError("Project not found.")
    return project


def require_active(s: Session, project_id: str) -> Project:
    project = require_project(s, project_id)
    if project.status != "active":
        raise ArchivedError("This project is archived and read-only. Unarchive it to make changes.")
    return project


def _load_out(s: Session, project_id: str) -> ProjectOut:
    stmt, _ = _with_stats()
    row = s.execute(stmt.where(Project.id == project_id)).one_or_none()
    if row is None:
        raise NotFoundError("Project not found.")
    return _to_out(*row)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_projects(
    ctx: AppContext,
    *,
    q: str | None = None,
    project_type: str | None = None,
    language: str | None = None,
    publication_format: str | None = None,
    status: str = "active",
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> ProjectList:
    stmt, _ = _with_stats()
    filters = []
    if status != "all":
        filters.append(Project.status == status)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip().casefold())}%"
        filters.append(
            or_(
                *(
                    func.pbs_fold(col).like(pattern, escape="\\")
                    for col in (Project.title, Project.subtitle, Project.audience, Project.author_name)
                )
            )
        )
    if project_type:
        filters.append(Project.project_type == project_type)
    if language:
        filters.append(func.pbs_fold(Project.language) == language.casefold())
    if publication_format:
        # Values are validated enum members, so a JSON-token LIKE is exact and injection-safe.
        filters.append(Project.publication_formats.like(f'%"{publication_format}"%'))
    if filters:
        stmt = stmt.where(*filters)

    sort_cols: dict[str, Any] = {
        "title": func.pbs_fold(Project.title),
        "project_type": Project.project_type,
        "language": func.pbs_fold(Project.language),
        "audience": func.pbs_fold(Project.audience),
        "target_word_count": Project.target_word_count,
        "updated_at": Project.updated_at,
        "created_at": Project.created_at,
    }
    col = sort_cols[sort]
    ordering: list[Any] = [case((col.is_(None), 1), else_=0)]  # nulls last in both directions
    ordering.append(col.desc() if order == "desc" else col.asc())
    ordering += [Project.updated_at.desc(), Project.id]

    with ctx.db.tx() as s:
        total = s.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = s.execute(stmt.order_by(*ordering).limit(limit).offset(offset)).all()
        return ProjectList(items=[_to_out(*r) for r in rows], total=int(total))


def get_project(ctx: AppContext, project_id: str) -> ProjectOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        return _load_out(s, project_id)


def create_project(ctx: AppContext, data: ProjectCreate, *, is_demo: bool = False) -> ProjectOut:
    now = ctx.clock.iso()
    project = Project(
        id=ctx.ids.new(),
        title=data.title,
        subtitle=data.subtitle or None,
        author_name=data.author_name or None,
        project_type=data.project_type,
        language=data.language,
        audience=data.audience or None,
        target_word_count=data.target_word_count,
        publication_formats=json.dumps(data.publication_formats),
        status="active",
        is_demo=1 if is_demo else 0,
        created_at=now,
        updated_at=now,
    )
    with ctx.db.tx() as s:
        s.add(project)
        s.flush()
        activity.record(
            s,
            ctx,
            kind="project_created",
            summary=f"Created “{project.title}”",
            project_id=project.id,
            ref_type="project",
            ref_id=project.id,
        )
        out = _load_out(s, project.id)
    ctx.workspace.project_dir(project.id).mkdir(parents=True, exist_ok=True)
    return out


def update_project(ctx: AppContext, project_id: str, patch: ProjectPatch) -> ProjectOut:
    changes = patch.model_dump(exclude_unset=True)
    with ctx.db.tx() as s:
        project = require_active(s, project_id)
        old_title = project.title
        for key, value in changes.items():
            if key == "title" and value is None:
                continue  # title is required; ignore explicit null
            if key == "publication_formats":
                value = json.dumps(value or [])
            if isinstance(value, str) and value == "" and key != "title":
                value = None
            setattr(project, key, value)
        project.updated_at = ctx.clock.iso()
        summary = (
            f"Renamed “{old_title}” to “{project.title}”"
            if "title" in changes and project.title != old_title
            else f"Edited details of “{project.title}”"
        )
        activity.record(
            s,
            ctx,
            kind="project_updated",
            summary=summary,
            project_id=project.id,
            ref_type="project",
            ref_id=project.id,
        )
        s.flush()
        return _load_out(s, project_id)


def set_archived(ctx: AppContext, project_id: str, archived: bool) -> ProjectOut:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        now = ctx.clock.iso()
        if archived and project.status != "archived":
            project.status, project.archived_at = "archived", now
            activity.record(
                s,
                ctx,
                kind="project_archived",
                summary=f"Archived “{project.title}”",
                project_id=project.id,
                ref_type="project",
                ref_id=project.id,
            )
        elif not archived and project.status == "archived":
            project.status, project.archived_at = "active", None
            activity.record(
                s,
                ctx,
                kind="project_unarchived",
                summary=f"Unarchived “{project.title}”",
                project_id=project.id,
                ref_type="project",
                ref_id=project.id,
            )
        project.updated_at = now
        s.flush()
        return _load_out(s, project_id)


def duplicate_project(ctx: AppContext, project_id: str) -> ProjectOut:
    """Copy metadata and each chapter's current text (as revision 1). History is not copied."""
    with ctx.db.tx() as s:
        src = require_project(s, project_id)
        now = ctx.clock.iso()
        dup = Project(
            id=ctx.ids.new(),
            title=f"{src.title} (copy)"[:300],
            subtitle=src.subtitle,
            author_name=src.author_name,
            project_type=src.project_type,
            language=src.language,
            audience=src.audience,
            target_word_count=src.target_word_count,
            publication_formats=src.publication_formats,
            status="active",
            is_demo=src.is_demo,
            duplicated_from_id=src.id,
            created_at=now,
            updated_at=now,
        )
        s.add(dup)
        s.flush()
        chapters = s.scalars(
            select(Chapter)
            .where(Chapter.project_id == src.id, Chapter.archived_at.is_(None))
            .order_by(Chapter.position)
        ).all()
        for ch in chapters:
            new_ch = Chapter(
                id=ctx.ids.new(),
                project_id=dup.id,
                kind=ch.kind,
                position=ch.position,
                title=ch.title,
                slug=ch.slug,
                status="draft" if ch.status == "approved" else ch.status,
                locked=0,
                target_word_count=ch.target_word_count,
                head_revision_no=0,
                created_at=now,
                updated_at=now,
            )
            s.add(new_ch)
            s.flush()
            head = s.get(ChapterRevision, ch.head_revision_id) if ch.head_revision_id else None
            if head is None:
                continue
            bdm, words = bookmd_v0.parse(head.source_md, chapter_id=new_ch.id, new_id=ctx.ids.new)
            rev = ChapterRevision(
                id=ctx.ids.new(),
                project_id=dup.id,
                chapter_id=new_ch.id,
                revision_no=1,
                origin="imported",
                source_md=head.source_md,
                bdm_json=json.dumps(bdm, ensure_ascii=False),
                parser_version=bookmd_v0.PARSER_VERSION,
                content_hash=head.content_hash,
                word_count=words,
                note=f"Duplicated from project {src.id}, revision {head.id}",
                created_at=now,
            )
            s.add(rev)
            s.flush()
            new_ch.head_revision_id, new_ch.head_revision_no = rev.id, 1
        activity.record(
            s,
            ctx,
            kind="project_duplicated",
            summary=f"Duplicated “{src.title}” as “{dup.title}”",
            project_id=dup.id,
            ref_type="project",
            ref_id=src.id,
        )
        s.flush()
        out = _load_out(s, dup.id)
    ctx.workspace.project_dir(out.id).mkdir(parents=True, exist_ok=True)
    return out
