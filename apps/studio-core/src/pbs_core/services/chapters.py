"""Chapter use cases: create, list, rename/status, archive, read content, save as a new revision."""

from __future__ import annotations

import json

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import (
    ChapterContentOut,
    ChapterCreate,
    ChapterOut,
    ChapterPatch,
    ChapterSaveIn,
    ChapterSaveOut,
    RevisionMetaOut,
)
from pbs_core.document import bookmd_v0
from pbs_core.domain.errors import ConflictError, NotFoundError
from pbs_core.domain.ids import is_ulid
from pbs_core.domain.position import key_between
from pbs_core.services import activity
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.models import Chapter, ChapterRevision, Project
from pbs_core.storage.paths import slugify


def _require_chapter(s: Session, project_id: str, chapter_id: str) -> Chapter:
    # Always scoped by project: a chapter ID from another project is simply "not found".
    chapter = (
        s.scalars(
            select(Chapter).where(
                Chapter.project_id == project_id, Chapter.id == chapter_id, Chapter.archived_at.is_(None)
            )
        ).one_or_none()
        if is_ulid(chapter_id)
        else None
    )
    if chapter is None:
        raise NotFoundError("Chapter not found in this project.")
    return chapter


def _head(s: Session, chapter: Chapter) -> ChapterRevision | None:
    if chapter.head_revision_id is None:
        return None
    return s.scalars(
        select(ChapterRevision).where(
            ChapterRevision.project_id == chapter.project_id, ChapterRevision.id == chapter.head_revision_id
        )
    ).one()


def _out(chapter: Chapter, words: int | None) -> ChapterOut:
    return ChapterOut(
        id=chapter.id,
        project_id=chapter.project_id,
        kind=chapter.kind,
        position=chapter.position,
        title=chapter.title,
        slug=chapter.slug,
        status=chapter.status,
        locked=bool(chapter.locked),
        target_word_count=chapter.target_word_count,
        head_revision_id=chapter.head_revision_id,
        head_revision_no=chapter.head_revision_no,
        word_count=int(words or 0),
        created_at=chapter.created_at,
        updated_at=chapter.updated_at,
    )


def _content_out(chapter: Chapter, head: ChapterRevision | None) -> ChapterContentOut:
    return ChapterContentOut(
        chapter_id=chapter.id,
        revision_id=head.id if head else None,
        revision_no=head.revision_no if head else 0,
        source_md=head.source_md if head else "",
        word_count=head.word_count if head else 0,
        saved_at=head.created_at if head else None,
    )


def _touch_project(s: Session, project_id: str, now: str) -> None:
    project = s.get(Project, project_id)
    if project is not None:
        project.updated_at = now


def list_chapters(ctx: AppContext, project_id: str) -> list[ChapterOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        rows = s.execute(
            select(Chapter, ChapterRevision.word_count)
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
        return [_out(c, w) for c, w in rows]


def get_chapter(ctx: AppContext, project_id: str, chapter_id: str) -> ChapterOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        head = _head(s, chapter)
        return _out(chapter, head.word_count if head else 0)


def _unique_slug(s: Session, project_id: str, title: str) -> str:
    base = slugify(title)
    taken = set(s.scalars(select(Chapter.slug).where(Chapter.project_id == project_id)).all())
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def create_chapter(ctx: AppContext, project_id: str, data: ChapterCreate) -> ChapterOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        last = s.scalar(select(func.max(Chapter.position)).where(Chapter.project_id == project_id))
        now = ctx.clock.iso()
        chapter = Chapter(
            id=ctx.ids.new(),
            project_id=project_id,
            kind=data.kind,
            position=key_between(last, None),
            title=data.title,
            slug=_unique_slug(s, project_id, data.title),
            status="draft",
            locked=0,
            head_revision_no=0,
            created_at=now,
            updated_at=now,
        )
        s.add(chapter)
        _touch_project(s, project_id, now)
        activity.record(
            s,
            ctx,
            kind="chapter_created",
            summary=f"Added chapter “{chapter.title}”",
            project_id=project_id,
            ref_type="chapter",
            ref_id=chapter.id,
        )
        s.flush()
        return _out(chapter, 0)


def update_chapter(ctx: AppContext, project_id: str, chapter_id: str, patch: ChapterPatch) -> ChapterOut:
    changes = patch.model_dump(exclude_unset=True)
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        old_title = chapter.title
        for key, value in changes.items():
            if key in ("title", "status") and value is None:
                continue
            setattr(chapter, key, value)
        now = ctx.clock.iso()
        chapter.updated_at = now
        _touch_project(s, project_id, now)
        if "title" in changes and chapter.title != old_title:
            summary = f"Renamed chapter “{old_title}” to “{chapter.title}”"
        elif "status" in changes:
            summary = f"Set “{chapter.title}” status to {chapter.status.replace('_', ' ')}"
        else:
            summary = f"Edited chapter “{chapter.title}”"
        activity.record(
            s,
            ctx,
            kind="chapter_updated",
            summary=summary,
            project_id=project_id,
            ref_type="chapter",
            ref_id=chapter.id,
        )
        s.flush()
        head = _head(s, chapter)
        return _out(chapter, head.word_count if head else 0)


def archive_chapter(ctx: AppContext, project_id: str, chapter_id: str) -> None:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        now = ctx.clock.iso()
        chapter.archived_at = now
        chapter.updated_at = now
        _touch_project(s, project_id, now)
        activity.record(
            s,
            ctx,
            kind="chapter_archived",
            summary=f"Archived chapter “{chapter.title}”",
            project_id=project_id,
            ref_type="chapter",
            ref_id=chapter.id,
        )


def get_content(ctx: AppContext, project_id: str, chapter_id: str) -> ChapterContentOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        return _content_out(chapter, _head(s, chapter))


def save_content(ctx: AppContext, project_id: str, chapter_id: str, data: ChapterSaveIn) -> ChapterSaveOut:
    """Append an immutable human revision, guarded by optimistic concurrency."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        head = _head(s, chapter)
        if data.expected_head_no != chapter.head_revision_no:
            raise ConflictError(
                "This chapter was saved elsewhere since you opened it.",
                detail="Reload to see the latest version, or save again to keep yours as a new revision.",
                extra={"current": _content_out(chapter, head).model_dump()},
            )
        if chapter.status == "approved":
            raise ConflictError(
                "This chapter is approved. Reopen it (set status to In review) before editing.",
                extra={"reason": "chapter_approved"},
            )
        source = bookmd_v0.normalize_source(data.source_md)
        digest = bookmd_v0.content_hash(source)
        if head is not None and head.content_hash == digest and data.label is None:
            return ChapterSaveOut(created=False, content=_content_out(chapter, head))

        previous = json.loads(head.bdm_json) if head is not None else None
        bdm, words = bookmd_v0.parse(source, chapter_id=chapter.id, new_id=ctx.ids.new, previous=previous)
        now = ctx.clock.iso()
        revision = ChapterRevision(
            id=ctx.ids.new(),
            project_id=project_id,
            chapter_id=chapter.id,
            revision_no=chapter.head_revision_no + 1,
            parent_revision_id=head.id if head else None,
            origin="human",
            source_md=source,
            bdm_json=json.dumps(bdm, ensure_ascii=False),
            parser_version=bookmd_v0.PARSER_VERSION,
            content_hash=digest,
            word_count=words,
            label=data.label,
            created_at=now,
        )
        s.add(revision)
        s.flush()
        chapter.head_revision_id = revision.id
        chapter.head_revision_no = revision.revision_no
        chapter.updated_at = now
        _touch_project(s, project_id, now)
        activity.record(
            s,
            ctx,
            kind="chapter_saved",
            summary=f"Saved “{chapter.title}” (revision {revision.revision_no}, {words} words)",
            project_id=project_id,
            ref_type="chapter_revision",
            ref_id=revision.id,
        )
        s.flush()
        return ChapterSaveOut(created=True, content=_content_out(chapter, revision))


def list_revisions(ctx: AppContext, project_id: str, chapter_id: str) -> list[RevisionMetaOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        revisions = s.scalars(
            select(ChapterRevision)
            .where(ChapterRevision.project_id == project_id, ChapterRevision.chapter_id == chapter.id)
            .order_by(ChapterRevision.revision_no.desc())
        ).all()
        return [
            RevisionMetaOut(
                id=r.id,
                revision_no=r.revision_no,
                origin=r.origin,
                word_count=r.word_count,
                content_hash=r.content_hash,
                parser_version=r.parser_version,
                label=r.label,
                created_at=r.created_at,
            )
            for r in revisions
        ]
