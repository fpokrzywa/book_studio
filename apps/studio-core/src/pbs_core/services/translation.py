"""Phase 08: translated editions. The source book is only read; each edition is its own linked book."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import ProjectCreate
from pbs_core.contracts_advanced import ChapterLinksOut, EditionIn, EditionOut, TranslateIn
from pbs_core.contracts_ai import JobOut
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.jobs import translation_exec
from pbs_core.services import activity, ai
from pbs_core.services import chapters as chapter_service
from pbs_core.services.projects import insert_project, require_active, require_project
from pbs_core.storage.advanced_models import CanonEntity, ChapterTranslation, SeriesBook, TranslationEdition
from pbs_core.storage.ai_models import Proposal
from pbs_core.storage.models import Chapter, ChapterRevision, Project, RevisionTag
from pbs_core.storage.writing_models import ContinuityFact

APPROVAL_RULE = (
    "Only an approved original is translated: the current text of a chapter marked Approved, or any revision you "
    "labelled “Approved” in its history."
)


def _status(s: Session, ct: ChapterTranslation) -> str:
    if ct.proposal_id:
        p = s.get(Proposal, ct.proposal_id)
        if p is not None:
            return {"pending": "suggested", "accepted": "accepted", "rejected": "rejected"}.get(p.status, ct.status)
    return ct.status


def _edition_out(s: Session, ed: TranslationEdition) -> EditionOut:
    target = s.get(Project, ed.target_project_id)
    rows = []
    for ct in s.scalars(select(ChapterTranslation).where(ChapterTranslation.edition_id == ed.id)):
        src = s.get(Chapter, ct.source_chapter_id)
        tgt = s.get(Chapter, ct.target_chapter_id)
        if src is None or tgt is None or tgt.archived_at is not None:
            continue
        rows.append({
            "source_chapter_id": src.id, "source_title": src.title, "source_head_no": src.head_revision_no,
            "source_status": src.status, "target_chapter_id": tgt.id, "target_title": tgt.title,
            "status": _status(s, ct), "source_revision_no": ct.source_revision_no,
            "stale": bool(ct.source_revision_no and src.head_revision_no > ct.source_revision_no),
            "suggested_title": ct.suggested_title, "issues": json.loads(ct.issues_json), "proposal_id": ct.proposal_id,
            "position": src.position,
        })  # fmt: skip
    rows.sort(key=lambda r: r["position"])
    return EditionOut(
        id=ed.id, source_project_id=ed.source_project_id, target_project_id=ed.target_project_id,
        target_title=target.title if target else "?", language=ed.language, term_map=json.loads(ed.term_map_json),
        chapters=rows, created_at=ed.created_at,
    )  # fmt: skip


def list_editions(ctx: AppContext, project_id: str) -> list[EditionOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        eds = s.scalars(
            select(TranslationEdition)
            .where(TranslationEdition.source_project_id == project_id)
            .order_by(TranslationEdition.language)
        ).all()
        return [_edition_out(s, e) for e in eds]


def create_edition(ctx: AppContext, project_id: str, data: EditionIn) -> EditionOut:
    with ctx.db.tx() as s:
        src = require_active(s, project_id)
        if data.language.split("-")[0] == src.language.split("-")[0]:
            raise ValidationFailedError("Choose a language different from the original's.")
        if s.scalars(
            select(TranslationEdition).where(
                TranslationEdition.source_project_id == project_id, TranslationEdition.language == data.language
            )
        ).first():
            raise ConflictError(f"This book already has a {data.language} edition.")
        if s.scalars(select(TranslationEdition).where(TranslationEdition.target_project_id == project_id)).first():
            raise ConflictError("This book is itself a translation; create editions from the original.")
        target = insert_project(s, ctx, ProjectCreate(
            title=data.title or f"{src.title} ({data.language})", subtitle=src.subtitle, author_name=src.author_name,
            project_type=src.project_type, language=data.language, audience=src.audience, target_word_count=src.target_word_count,
        ))  # fmt: skip
        now = ctx.clock.iso()
        ed = TranslationEdition(id=ctx.ids.new(), source_project_id=src.id, target_project_id=target.id, language=data.language,
                                term_map_json=json.dumps(data.term_map, ensure_ascii=False), created_at=now)  # fmt: skip
        s.add(ed)
        s.flush()
        # Mirror the chapter tree: same slugs, kinds, order and outline links, so structure and anchors carry over.
        id_map: dict[str, str] = {}
        for ch, _depth in chapter_service.tree_order(chapter_service.active_chapters(s, src.id)):
            nid = ctx.ids.new()
            id_map[ch.id] = nid
            s.add(Chapter(
                id=nid, project_id=target.id, parent_id=id_map.get(ch.parent_id or ""), kind=ch.kind, position=ch.position,
                title=ch.title, slug=ch.slug, status="draft", locked=0, target_word_count=ch.target_word_count,
                head_revision_id=None, head_revision_no=0, outline_node_id=ch.outline_node_id, created_at=now, updated_at=now,
            ))  # fmt: skip
            s.flush()
            s.add(
                ChapterTranslation(
                    target_chapter_id=nid,
                    edition_id=ed.id,
                    source_chapter_id=ch.id,
                    status="not_started",
                    updated_at=now,
                )
            )
        activity.record(s, ctx, kind="edition_created", project_id=src.id, ref_type="translation_edition", ref_id=ed.id,
                        summary=f"Created a {data.language} edition of “{src.title}” (the original is unchanged)")  # fmt: skip
        s.flush()
        return _edition_out(s, ed)


def _require_edition(s: Session, project_id: str, edition_id: str) -> TranslationEdition:
    ed = s.get(TranslationEdition, edition_id) if is_ulid(edition_id) else None
    if ed is None or ed.source_project_id != project_id:
        raise NotFoundError("Edition not found for this book.")
    return ed


def get_edition(ctx: AppContext, project_id: str, edition_id: str) -> EditionOut:
    with ctx.db.tx() as s:
        return _edition_out(s, _require_edition(s, project_id, edition_id))


def set_terms(ctx: AppContext, project_id: str, edition_id: str, terms: dict[str, str]) -> EditionOut:
    with ctx.db.tx() as s:
        ed = _require_edition(s, project_id, edition_id)
        ed.term_map_json = json.dumps(terms, ensure_ascii=False)
        s.flush()
        return _edition_out(s, ed)


def _names(s: Session, project_id: str) -> list[str]:
    names: set[str] = set()
    sb = s.scalars(select(SeriesBook).where(SeriesBook.project_id == project_id)).first()
    if sb is not None:
        for e in s.scalars(select(CanonEntity).where(CanonEntity.series_id == sb.series_id, CanonEntity.status == "canon",
                                                     CanonEntity.kind.in_(("character", "location")))):  # fmt: skip
            names.add(e.name)
            names.update(json.loads(e.aliases_json))
    for f in s.scalars(select(ContinuityFact).where(ContinuityFact.project_id == project_id, ContinuityFact.kind.in_(("character", "location")),
                                                    ContinuityFact.status.in_(("confirmed", "resolved")))):  # fmt: skip
        names.add(f.name)
    return sorted(n for n in names if n.strip())


def translate(ctx: AppContext, project_id: str, edition_id: str, data: TranslateIn) -> JobOut:
    with ctx.db.tx() as s:
        ed = _require_edition(s, project_id, edition_id)
        src_project = require_active(s, project_id)
        target_project = require_active(s, ed.target_project_id)
        ch = chapter_service._require_chapter(s, project_id, data.source_chapter_id)
        rev = s.scalars(
            select(ChapterRevision).where(
                ChapterRevision.chapter_id == ch.id, ChapterRevision.revision_no == data.source_revision_no
            )
        ).first()
        if rev is None:
            raise NotFoundError("That revision does not exist.")
        tag = s.get(RevisionTag, rev.id)
        approved = (ch.status == "approved" and ch.head_revision_no == rev.revision_no) or (
            tag is not None and (tag.label or "").strip().lower() == "approved"
        )
        if not approved:
            raise ConflictError(APPROVAL_RULE, extra={"reason": "not_approved"})
        ct = s.scalars(
            select(ChapterTranslation).where(
                ChapterTranslation.edition_id == ed.id, ChapterTranslation.source_chapter_id == ch.id
            )
        ).first()
        if ct is None:
            raise NotFoundError(
                "This chapter has no counterpart in the edition (it was added after the edition was created)."
            )
        tgt = s.get(Chapter, ct.target_chapter_id)
        if tgt is None or tgt.locked or tgt.status == "approved":
            raise ConflictError("The edition's chapter is locked or approved; unlock it to translate again.")
        provider, model, temperature, max_out = ai.resolve_model(
            s, "translate", data.provider_id, data.model_name, 8000
        )
        for pid in (src_project.id, target_project.id):  # the original's text leaves the computer: both must allow it
            blocked = ai.cloud_block_reason(s, pid, provider)
            if blocked:
                raise ai.CloudBlockedError(blocked, extra={"reason": "cloud_blocked"})
        from pbs_core.services import costs

        est = costs.estimate(s, provider, model, len(rev.source_md) + 2000, max_out)
        job = ai.queue_planning_job(
            s, ctx, project_id=target_project.id, task="translate", provider=provider, model=model, temperature=temperature,
            max_out=max_out,
            inp={
                "kind": "translate_chapter", "edition_id": ed.id, "source_project_id": src_project.id,
                "source_chapter_id": ch.id, "source_revision_id": rev.id, "source_revision_no": rev.revision_no,
                "target_chapter_id": ct.target_chapter_id, "language": ed.language, "names": _names(s, src_project.id),
                "term_map": json.loads(ed.term_map_json),
            },
            template=f"translate-chapter@{translation_exec.TEMPLATE_VERSION}", estimate=dict(est),
            key=f"{target_project.id}:{data.client_request_id}", summary=f"translate “{ch.title}” into {ed.language}",
        )  # fmt: skip
        job.chapter_id = ct.target_chapter_id
        ct.status, ct.job_id, ct.source_revision_id, ct.source_revision_no = (
            "requested",
            job.id,
            rev.id,
            rev.revision_no,
        )
        ct.updated_at = ctx.clock.iso()
        s.flush()
        out = ai.job_out(s, job)
    if ctx.jobs is not None:
        ctx.jobs.wake()
    return out


def review_issue(
    ctx: AppContext, project_id: str, edition_id: str, target_chapter_id: str, index: int, state: str
) -> EditionOut:
    with ctx.db.tx() as s:
        ed = _require_edition(s, project_id, edition_id)
        ct = s.get(ChapterTranslation, target_chapter_id)
        if ct is None or ct.edition_id != ed.id:
            raise NotFoundError("Chapter not found in this edition.")
        issues = json.loads(ct.issues_json)
        if not 0 <= index < len(issues):
            raise NotFoundError("No such item.")
        if state not in ("open", "reviewed", "will_fix"):
            raise ValidationFailedError("Unknown state.")
        issues[index]["state"] = state
        ct.issues_json, ct.updated_at = json.dumps(issues, ensure_ascii=False), ctx.clock.iso()
        s.flush()
        return _edition_out(s, ed)


def chapter_links(ctx: AppContext, project_id: str, chapter_id: str) -> ChapterLinksOut:
    with ctx.db.tx() as s:
        project = require_project(s, project_id)
        ch = chapter_service._require_chapter(s, project_id, chapter_id)
        of: dict[str, Any] | None = None
        ct = s.get(ChapterTranslation, ch.id)
        if ct is not None:
            ed = s.get(TranslationEdition, ct.edition_id)
            src = s.get(Chapter, ct.source_chapter_id)
            sp = s.get(Project, ed.source_project_id) if ed else None
            if ed and src and sp:
                of = {"project_id": sp.id, "project_title": sp.title, "chapter_id": src.id, "chapter_title": src.title,
                      "language": sp.language, "source_revision_no": ct.source_revision_no, "status": _status(s, ct),
                      "link": f"/projects/{sp.id}/chapters/{src.id}"}  # fmt: skip
        out = []
        for row in s.scalars(select(ChapterTranslation).where(ChapterTranslation.source_chapter_id == ch.id)):
            ed = s.get(TranslationEdition, row.edition_id)
            tgt = s.get(Chapter, row.target_chapter_id)
            if ed and tgt:
                out.append({"language": ed.language, "edition_id": ed.id, "project_id": ed.target_project_id,
                            "chapter_id": tgt.id, "chapter_title": tgt.title, "status": _status(s, row),
                            "source_revision_no": row.source_revision_no,
                            "stale": bool(row.source_revision_no and ch.head_revision_no > row.source_revision_no),
                            "link": f"/projects/{ed.target_project_id}/chapters/{tgt.id}"})  # fmt: skip
        out.sort(key=lambda r: str(r["language"]))
        return ChapterLinksOut(chapter_id=ch.id, language=project.language, translation_of=of, translations=out)
