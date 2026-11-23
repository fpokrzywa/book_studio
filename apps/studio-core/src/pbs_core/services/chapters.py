"""Manuscript use cases: chapter tree, reorder, metadata, drafts (autosave), revisions, compare, restore."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import (
    ChapterContentOut,
    ChapterCreate,
    ChapterMove,
    ChapterOut,
    ChapterPatch,
    ChapterSaveIn,
    ChapterSaveOut,
    CompareOut,
    DiffRow,
    DiffSegment,
    DraftIn,
    DraftOut,
    RestoreIn,
    RevisionMetaOut,
    RevisionOut,
    RevisionTagIn,
)
from pbs_core.document import bookmd
from pbs_core.domain.diff import side_by_side
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.domain.position import key_between
from pbs_core.services import activity, documents
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.models import Chapter, ChapterDraft, ChapterRevision, Project, RevisionTag
from pbs_core.storage.paths import slugify

MAX_DEPTH = 2  # part > chapter > section (depths 0, 1, 2)


# ---------- helpers ----------


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


def active_chapters(s: Session, project_id: str) -> list[Chapter]:
    return list(
        s.scalars(
            select(Chapter)
            .where(Chapter.project_id == project_id, Chapter.archived_at.is_(None))
            .order_by(Chapter.position, Chapter.id)
        ).all()
    )


def tree_order(chapters: Sequence[Chapter]) -> list[tuple[Chapter, int]]:
    """Depth-first reading order with depth. Children whose parent is missing become top level."""
    ids = {c.id for c in chapters}
    children: dict[str | None, list[Chapter]] = {}
    for c in chapters:
        parent = c.parent_id if c.parent_id in ids else None
        children.setdefault(parent, []).append(c)
    for lst in children.values():
        lst.sort(key=lambda c: (c.position, c.id))
    out: list[tuple[Chapter, int]] = []

    def visit(parent: str | None, depth: int) -> None:
        for c in children.get(parent, []):
            out.append((c, depth))
            visit(c.id, depth + 1)

    visit(None, 0)
    return out


def _depth_of(s: Session, project_id: str, chapter_id: str | None) -> int:
    depth = -1
    cur = chapter_id
    while cur is not None and depth < 10:
        depth += 1
        ch = s.scalars(select(Chapter).where(Chapter.project_id == project_id, Chapter.id == cur)).one_or_none()
        cur = ch.parent_id if ch else None
    return depth


def _subtree_height(chapters: Sequence[Chapter], root_id: str) -> int:
    kids = [c for c in chapters if c.parent_id == root_id]
    return 0 if not kids else 1 + max(_subtree_height(chapters, k.id) for k in kids)


def _out(chapter: Chapter, words: int | None, depth: int = 0) -> ChapterOut:
    return ChapterOut(
        id=chapter.id,
        project_id=chapter.project_id,
        parent_id=chapter.parent_id,
        depth=depth,
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


def _draft_out(d: ChapterDraft | None) -> DraftOut | None:
    if d is None:
        return None
    return DraftOut(source_md=d.source_md, base_revision_no=d.base_revision_no, updated_at=d.updated_at)


def _content_out(
    chapter: Chapter, head: ChapterRevision | None, draft: ChapterDraft | None = None
) -> ChapterContentOut:
    return ChapterContentOut(
        chapter_id=chapter.id,
        revision_id=head.id if head else None,
        revision_no=head.revision_no if head else 0,
        source_md=head.source_md if head else "",
        word_count=head.word_count if head else 0,
        saved_at=head.created_at if head else None,
        draft=_draft_out(draft),
    )


def _touch_project(s: Session, project_id: str, now: str) -> None:
    project = s.get(Project, project_id)
    if project is not None:
        project.updated_at = now


def _words_by_chapter(s: Session, project_id: str) -> dict[str, int]:
    rows = s.execute(
        select(Chapter.id, ChapterRevision.word_count)
        .join(
            ChapterRevision,
            and_(ChapterRevision.project_id == Chapter.project_id, ChapterRevision.id == Chapter.head_revision_id),
        )
        .where(Chapter.project_id == project_id)
    ).all()
    return {cid: int(w) for cid, w in rows}


def _record(s: Session, ctx: AppContext, kind: str, summary: str, project_id: str, ref_type: str, ref_id: str) -> None:
    activity.record(s, ctx, kind=kind, summary=summary, project_id=project_id, ref_type=ref_type, ref_id=ref_id)


# ---------- tree ----------


def list_chapters(ctx: AppContext, project_id: str) -> list[ChapterOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        words = _words_by_chapter(s, project_id)
        return [_out(c, words.get(c.id, 0), d) for c, d in tree_order(active_chapters(s, project_id))]


def get_chapter(ctx: AppContext, project_id: str, chapter_id: str) -> ChapterOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        head = _head(s, chapter)
        return _out(chapter, head.word_count if head else 0, _depth_of(s, project_id, chapter.id))


def _unique_slug(s: Session, project_id: str, title: str) -> str:
    base = slugify(title)
    taken = set(s.scalars(select(Chapter.slug).where(Chapter.project_id == project_id)).all())
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _check_parent(s: Session, project_id: str, parent_id: str | None) -> int:
    """Validate a prospective parent; returns the depth a child would have."""
    if parent_id is None:
        return 0
    _require_chapter(s, project_id, parent_id)
    depth = _depth_of(s, project_id, parent_id) + 1
    if depth > MAX_DEPTH:
        raise ValidationFailedError("Chapters can be nested at most three levels deep (part, chapter, section).")
    return depth


def append_chapter(
    s: Session, ctx: AppContext, project_id: str, title: str, *, kind: str = "chapter", parent_id: str | None = None
) -> Chapter:
    siblings = [c for c in active_chapters(s, project_id) if c.parent_id == parent_id]
    last = max((c.position for c in siblings), default=None)
    now = ctx.clock.iso()
    chapter = Chapter(
        id=ctx.ids.new(),
        project_id=project_id,
        parent_id=parent_id,
        kind=kind,
        position=key_between(last, None),
        title=(title or "Untitled")[:300],
        slug=_unique_slug(s, project_id, title or "untitled"),
        status="draft",
        locked=0,
        head_revision_no=0,
        created_at=now,
        updated_at=now,
    )
    s.add(chapter)
    s.flush()
    return chapter


def create_chapter(ctx: AppContext, project_id: str, data: ChapterCreate) -> ChapterOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        depth = _check_parent(s, project_id, data.parent_id)
        chapter = append_chapter(s, ctx, project_id, data.title, kind=data.kind, parent_id=data.parent_id)
        _touch_project(s, project_id, chapter.created_at)
        _record(s, ctx, "chapter_created", f"Added chapter “{chapter.title}”", project_id, "chapter", chapter.id)
        s.flush()
        return _out(chapter, 0, depth)


def update_chapter(ctx: AppContext, project_id: str, chapter_id: str, patch: ChapterPatch) -> ChapterOut:
    changes = patch.model_dump(exclude_unset=True)
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        old_title = chapter.title
        new_slug = changes.get("slug")
        if new_slug and new_slug != chapter.slug:
            clash = s.scalars(
                select(Chapter.id).where(
                    Chapter.project_id == project_id, Chapter.slug == new_slug, Chapter.id != chapter.id
                )
            ).first()
            if clash:
                raise ConflictError(
                    f"Another chapter already uses the slug “{new_slug}”.", extra={"reason": "slug_taken"}
                )
        for key, value in changes.items():
            if key in ("title", "status", "slug", "kind") and value is None:
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
        _record(s, ctx, "chapter_updated", summary, project_id, "chapter", chapter.id)
        s.flush()
        head = _head(s, chapter)
        return _out(chapter, head.word_count if head else 0, _depth_of(s, project_id, chapter.id))


def move_chapter(ctx: AppContext, project_id: str, chapter_id: str, move: ChapterMove) -> list[ChapterOut]:
    """Re-parent and/or reorder one chapter.

    Only the chapter's parent and position change. IDs, slugs, revisions, drafts, images and
    anchors are untouched, so no reference can be orphaned by reordering.
    """
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        all_ch = active_chapters(s, project_id)
        if move.parent_id is not None:
            by_id = {c.id: c for c in all_ch}
            cur: str | None = move.parent_id
            while cur is not None:
                if cur == chapter.id:
                    raise ValidationFailedError("A chapter cannot be placed inside itself or one of its sections.")
                cur = by_id[cur].parent_id if cur in by_id else None
        new_depth = _check_parent(s, project_id, move.parent_id)
        if new_depth + _subtree_height(all_ch, chapter.id) > MAX_DEPTH:
            raise ValidationFailedError("That move would nest sections more than three levels deep.")
        siblings = sorted(
            (c for c in all_ch if c.parent_id == move.parent_id and c.id != chapter.id),
            key=lambda c: (c.position, c.id),
        )
        index = min(move.index, len(siblings))
        before = siblings[index - 1].position if index > 0 else None
        after = siblings[index].position if index < len(siblings) else None
        chapter.parent_id = move.parent_id
        chapter.position = key_between(before, after)
        now = ctx.clock.iso()
        chapter.updated_at = now
        _touch_project(s, project_id, now)
        _record(s, ctx, "chapter_moved", f"Moved “{chapter.title}”", project_id, "chapter", chapter.id)
        s.flush()
        words = _words_by_chapter(s, project_id)
        return [_out(c, words.get(c.id, 0), d) for c, d in tree_order(active_chapters(s, project_id))]


def archive_chapter(ctx: AppContext, project_id: str, chapter_id: str) -> None:
    """Archive a chapter together with its sections (nothing is deleted)."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        all_ch = active_chapters(s, project_id)
        doomed = {chapter.id}
        changed = True
        while changed:
            changed = False
            for c in all_ch:
                if c.parent_id in doomed and c.id not in doomed:
                    doomed.add(c.id)
                    changed = True
        now = ctx.clock.iso()
        for c in all_ch:
            if c.id in doomed:
                c.archived_at = now
                c.updated_at = now
        _touch_project(s, project_id, now)
        extra = f" and {len(doomed) - 1} section(s)" if len(doomed) > 1 else ""
        summary = f"Archived chapter “{chapter.title}”{extra}"
        _record(s, ctx, "chapter_archived", summary, project_id, "chapter", chapter.id)


# ---------- content and drafts ----------


def get_content(ctx: AppContext, project_id: str, chapter_id: str) -> ChapterContentOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        return _content_out(chapter, _head(s, chapter), s.get(ChapterDraft, chapter.id))


def _check_editable(chapter: Chapter) -> None:
    if chapter.status == "approved":
        raise ConflictError(
            "This chapter is approved. Reopen it (set status to In review) before editing.",
            extra={"reason": "chapter_approved"},
        )


def _conflict(chapter: Chapter, head: ChapterRevision | None, title: str, detail: str) -> ConflictError:
    return ConflictError(title, detail=detail, extra={"current": _content_out(chapter, head).model_dump()})


def put_draft(ctx: AppContext, project_id: str, chapter_id: str, data: DraftIn) -> ChapterContentOut:
    """Autosave: keep a durable working copy. Only an explicit save creates a revision."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        head = _head(s, chapter)
        if data.base_revision_no != chapter.head_revision_no:
            raise _conflict(
                chapter, head, "This chapter was saved elsewhere since you opened it.",
                "Your text is still in the editor. Choose which version to keep.",
            )  # fmt: skip
        _check_editable(chapter)
        source = bookmd.normalize_source(data.source_md)
        draft = s.get(ChapterDraft, chapter.id)
        unchanged = source == (head.source_md if head is not None else "")
        if unchanged:
            if draft is not None:
                s.delete(draft)
            s.flush()
            return _content_out(chapter, head, None)
        now = ctx.clock.iso()
        if draft is None:
            draft = ChapterDraft(
                chapter_id=chapter.id,
                project_id=project_id,
                base_revision_no=data.base_revision_no,
                source_md=source,
                updated_at=now,
            )
            s.add(draft)
        else:
            draft.source_md, draft.base_revision_no, draft.updated_at = source, data.base_revision_no, now
        s.flush()
        return _content_out(chapter, head, draft)


def discard_draft(ctx: AppContext, project_id: str, chapter_id: str) -> ChapterContentOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        draft = s.get(ChapterDraft, chapter.id)
        if draft is not None:
            s.delete(draft)
            summary = f"Discarded unsaved changes in “{chapter.title}”"
            _record(s, ctx, "draft_discarded", summary, project_id, "chapter", chapter.id)
        s.flush()
        return _content_out(chapter, _head(s, chapter), None)


def append_revision(
    s: Session,
    ctx: AppContext,
    chapter: Chapter,
    source: str,
    *,
    origin: str,
    label: str | None = None,
    note: str | None = None,
    restored_from: str | None = None,
    import_run_id: str | None = None,
    accepted_proposal_id: str | None = None,
) -> ChapterRevision:
    """Append an immutable revision inside the caller's transaction and move the head to it."""
    head = _head(s, chapter)
    previous = documents.bdm_of(ctx, head) if head is not None else None
    parsed = documents.parse(ctx, source, chapter.id, previous)
    now = ctx.clock.iso()
    revision = ChapterRevision(
        id=ctx.ids.new(),
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        revision_no=chapter.head_revision_no + 1,
        parent_revision_id=head.id if head else None,
        origin=origin,
        source_md=source,
        bdm_json=json.dumps(parsed.doc, ensure_ascii=False),
        parser_version=bookmd.PARSER_VERSION,
        content_hash=bookmd.content_hash(source),
        word_count=parsed.word_count,
        label=label,
        note=note,
        restored_from_revision_id=restored_from,
        import_run_id=import_run_id,
        accepted_proposal_id=accepted_proposal_id,
        created_at=now,
    )
    s.add(revision)
    s.flush()
    chapter.head_revision_id = revision.id
    chapter.head_revision_no = revision.revision_no
    chapter.updated_at = now
    draft = s.get(ChapterDraft, chapter.id)
    if draft is not None:
        s.delete(draft)
    _touch_project(s, chapter.project_id, now)
    s.flush()
    return revision


def save_content(ctx: AppContext, project_id: str, chapter_id: str, data: ChapterSaveIn) -> ChapterSaveOut:
    """Append an immutable human revision, guarded by optimistic concurrency."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        head = _head(s, chapter)
        if data.expected_head_no != chapter.head_revision_no:
            raise _conflict(
                chapter, head, "This chapter was saved elsewhere since you opened it.",
                "Reload to see the latest version, or save again to keep yours as a new revision.",
            )  # fmt: skip
        _check_editable(chapter)
        source = bookmd.normalize_source(data.source_md)
        if head is not None and head.content_hash == bookmd.content_hash(source) and data.label is None:
            draft = s.get(ChapterDraft, chapter.id)
            if draft is not None:
                s.delete(draft)
            s.flush()
            return ChapterSaveOut(created=False, content=_content_out(chapter, head))
        revision = append_revision(s, ctx, chapter, source, origin="human", label=data.label, note=data.note)
        summary = f"Saved “{chapter.title}” (revision {revision.revision_no}, {revision.word_count} words)"
        _record(s, ctx, "chapter_saved", summary, project_id, "chapter_revision", revision.id)
        s.flush()
        return ChapterSaveOut(created=True, content=_content_out(chapter, revision))


# ---------- revisions ----------


def _revisions_of(project_id: str, chapter_id: str) -> Any:
    return select(ChapterRevision).where(
        ChapterRevision.project_id == project_id, ChapterRevision.chapter_id == chapter_id
    )


def _require_revision(s: Session, project_id: str, chapter: Chapter, revision_no: int) -> ChapterRevision:
    rev: ChapterRevision | None = s.scalars(
        _revisions_of(project_id, chapter.id).where(ChapterRevision.revision_no == revision_no)
    ).one_or_none()
    if rev is None:
        raise NotFoundError(f"Revision {revision_no} does not exist for this chapter.")
    return rev


def _meta(r: ChapterRevision, tag: RevisionTag | None, head_id: str | None, numbers: dict[str, int]) -> RevisionMetaOut:
    return RevisionMetaOut(
        id=r.id,
        revision_no=r.revision_no,
        origin=r.origin,
        word_count=r.word_count,
        content_hash=r.content_hash,
        parser_version=r.parser_version,
        label=tag.label if tag is not None and tag.label is not None else r.label,
        note=tag.note if tag is not None and tag.note is not None else r.note,
        restored_from_revision_no=numbers.get(r.restored_from_revision_id or ""),
        is_head=r.id == head_id,
        created_at=r.created_at,
    )


def _numbers(s: Session, project_id: str, chapter_id: str) -> dict[str, int]:
    return {r.id: r.revision_no for r in s.scalars(_revisions_of(project_id, chapter_id)).all()}


def list_revisions(ctx: AppContext, project_id: str, chapter_id: str) -> list[RevisionMetaOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        revisions = s.scalars(_revisions_of(project_id, chapter.id).order_by(ChapterRevision.revision_no.desc())).all()
        ids = [r.id for r in revisions]
        tags = {t.revision_id: t for t in s.scalars(select(RevisionTag).where(RevisionTag.revision_id.in_(ids))).all()}
        numbers = {r.id: r.revision_no for r in revisions}
        return [_meta(r, tags.get(r.id), chapter.head_revision_id, numbers) for r in revisions]


def get_revision(ctx: AppContext, project_id: str, chapter_id: str, revision_no: int) -> RevisionOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        r = _require_revision(s, project_id, chapter, revision_no)
        meta = _meta(r, s.get(RevisionTag, r.id), chapter.head_revision_id, _numbers(s, project_id, chapter.id))
        return RevisionOut(**meta.model_dump(), source_md=r.source_md)


def compare(ctx: AppContext, project_id: str, chapter_id: str, from_no: int, to_no: int) -> CompareOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        old = _require_revision(s, project_id, chapter, from_no).source_md
        new = _require_revision(s, project_id, chapter, to_no).source_md
    rows = side_by_side(old, new)
    return CompareOut(
        from_revision_no=from_no,
        to_revision_no=to_no,
        rows=[
            DiffRow(
                kind=r.kind,
                left_no=r.left_no,
                right_no=r.right_no,
                left=[DiffSegment(text=x.text, changed=x.changed) for x in r.left],
                right=[DiffSegment(text=x.text, changed=x.changed) for x in r.right],
            )
            for r in rows
        ],
        added_lines=sum(1 for r in rows if r.kind == "insert"),
        removed_lines=sum(1 for r in rows if r.kind == "delete"),
        changed_lines=sum(1 for r in rows if r.kind == "replace"),
    )


def restore_revision(
    ctx: AppContext, project_id: str, chapter_id: str, revision_no: int, data: RestoreIn
) -> ChapterSaveOut:
    """Copy an earlier revision into a NEW head revision. History is never rewritten."""
    with ctx.db.tx() as s:
        require_active(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        head = _head(s, chapter)
        if data.expected_head_no != chapter.head_revision_no:
            raise _conflict(
                chapter, head, "This chapter changed since you opened its history.",
                "Review the latest version before restoring.",
            )  # fmt: skip
        _check_editable(chapter)
        old = _require_revision(s, project_id, chapter, revision_no)
        revision = append_revision(
            s,
            ctx,
            chapter,
            old.source_md,
            origin="restored",
            note=data.note or f"Restored from revision {old.revision_no}",
            restored_from=old.id,
        )
        summary = f"Restored “{chapter.title}” revision {old.revision_no} as revision {revision.revision_no}"
        _record(s, ctx, "revision_restored", summary, project_id, "chapter_revision", revision.id)
        s.flush()
        return ChapterSaveOut(created=True, content=_content_out(chapter, revision))


def tag_revision(
    ctx: AppContext, project_id: str, chapter_id: str, revision_no: int, data: RevisionTagIn
) -> RevisionMetaOut:
    """Label or annotate a revision. The revision row itself never changes."""
    with ctx.db.tx() as s:
        require_project(s, project_id)
        chapter = _require_chapter(s, project_id, chapter_id)
        r = _require_revision(s, project_id, chapter, revision_no)
        tag = s.get(RevisionTag, r.id)
        now = ctx.clock.iso()
        if tag is None:
            tag = RevisionTag(revision_id=r.id, project_id=project_id, label=data.label, note=data.note, updated_at=now)
            s.add(tag)
        else:
            tag.label, tag.note, tag.updated_at = data.label, data.note, now
        s.flush()
        return _meta(r, tag, chapter.head_revision_id, _numbers(s, project_id, chapter.id))
