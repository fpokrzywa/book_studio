"""The evidence ledger: statements, what supports them, and the author's review of each.

Claims live apart from the prose. AI-proposed claims start as `proposed` and become `in_text` when
the author accepts the suggestion (or `discarded` when they reject it). Every support row keeps a
copy of the exact quote, citation key and locator, so evidence survives re-indexing or removal of
its source.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_knowledge import ClaimCreate, ClaimOut, ClaimPatch, SupportOut
from pbs_core.domain.errors import NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.knowledge.citations import Processed
from pbs_core.knowledge.extract import locator
from pbs_core.knowledge.retrieval import usable_source_ids
from pbs_core.services import activity
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.knowledge_models import Claim, ClaimSupport, Source, SourceChunk
from pbs_core.storage.models import Chapter

QUOTE_CHARS = 600


def record_proposal_claims(
    s: Session, ctx: AppContext, *, project_id: str, chapter_id: str | None, proposal_id: str, processed: Processed
) -> int:
    now = ctx.clock.iso()
    for draft in processed.claims:
        claim = Claim(
            id=ctx.ids.new(),
            project_id=project_id,
            chapter_id=chapter_id,
            proposal_id=proposal_id,
            revision_id=None,
            text=draft.text[:2000],
            origin="ai_generated",
            lifecycle="proposed",
            review_state="needs_review",
            support_status=draft.status,
            note=None,
            created_at=now,
            updated_at=now,
        )
        s.add(claim)
        for sup in draft.supports:
            s.add(
                ClaimSupport(
                    id=ctx.ids.new(),
                    claim_id=claim.id,
                    kind=sup.kind,
                    source_id=sup.source_id,
                    chunk_id=sup.chunk_id,
                    interview_answer_id=sup.answer_id,
                    citation_key=sup.citation_key,
                    locator=sup.locator,
                    quote=sup.quote[:QUOTE_CHARS],
                    located=1 if sup.located else 0,
                    score=sup.score,
                    created_at=now,
                )
            )
    return len(processed.claims)


def on_proposal_decided(
    s: Session, ctx: AppContext, proposal_id: str, *, accepted: bool, revision_id: str | None
) -> None:
    for claim in s.scalars(select(Claim).where(Claim.proposal_id == proposal_id)).all():
        claim.lifecycle = "in_text" if accepted else "discarded"
        claim.revision_id = revision_id
        claim.updated_at = ctx.clock.iso()


def _support_status(supports: list[ClaimSupport]) -> str:
    if not supports:
        return "unverified"
    return "supported" if any(x.located for x in supports) else "not_located"


def _out(s: Session, c: Claim) -> ClaimOut:
    supports = s.scalars(
        select(ClaimSupport).where(ClaimSupport.claim_id == c.id).order_by(ClaimSupport.created_at)
    ).all()
    sources = {
        x.id: x for x in s.scalars(select(Source).where(Source.id.in_([y.source_id for y in supports if y.source_id])))
    }
    chapter = s.get(Chapter, c.chapter_id) if c.chapter_id else None
    return ClaimOut(
        id=c.id,
        project_id=c.project_id,
        chapter_id=c.chapter_id,
        chapter_title=chapter.title if chapter else None,
        proposal_id=c.proposal_id,
        text=c.text,
        origin=c.origin,
        lifecycle=c.lifecycle,
        review_state=c.review_state,
        support_status=c.support_status,
        note=c.note,
        supports=[
            SupportOut(
                id=x.id,
                kind=x.kind,
                source_id=x.source_id,
                source_title=sources[x.source_id].title if x.source_id in sources else None,
                source_removed=bool(x.source_id in sources and sources[x.source_id].removed_at),
                chunk_id=x.chunk_id,
                interview_answer_id=x.interview_answer_id,
                citation_key=x.citation_key,
                locator=x.locator,
                quote=x.quote,
                located=bool(x.located),
            )
            for x in supports
        ],
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def list_claims(
    ctx: AppContext, project_id: str, *, include_proposed: bool = False, chapter_id: str | None = None
) -> list[ClaimOut]:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        stmt = select(Claim).where(Claim.project_id == project_id, Claim.lifecycle != "discarded")
        if not include_proposed:
            stmt = stmt.where(Claim.lifecycle == "in_text")
        if chapter_id:
            stmt = stmt.where(Claim.chapter_id == chapter_id)
        return [_out(s, c) for c in s.scalars(stmt.order_by(Claim.created_at.desc())).all()]


def _support_from_chunk(s: Session, ctx: AppContext, project_id: str, claim_id: str, chunk_id: str) -> ClaimSupport:
    chunk = s.get(SourceChunk, chunk_id) if is_ulid(chunk_id) else None
    if chunk is None:
        raise ValidationFailedError("That passage no longer exists. Search again and pick it from the results.")
    if chunk.source_id not in usable_source_ids(s, project_id):
        raise ValidationFailedError("That passage is not in a source this book can use.")
    src = s.get(Source, chunk.source_id)
    if src is None:  # pragma: no cover - foreign key
        raise NotFoundError("Source not found.")
    return ClaimSupport(
        id=ctx.ids.new(),
        claim_id=claim_id,
        kind="source",
        source_id=src.id,
        chunk_id=chunk.id,
        interview_answer_id=None,
        citation_key=src.citation_key,
        locator=locator(chunk.page_start, chunk.page_end, chunk.para_start, chunk.para_end),
        quote=chunk.text[:QUOTE_CHARS],
        located=1,
        score=None,
        created_at=ctx.clock.iso(),
    )


def create_claim(ctx: AppContext, project_id: str, data: ClaimCreate) -> ClaimOut:
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        require_active(s, project_id)
        if data.chapter_id:
            ch = s.get(Chapter, data.chapter_id)
            if ch is None or ch.project_id != project_id:
                raise NotFoundError("Chapter not found in this book.")
        claim = Claim(
            id=ctx.ids.new(),
            project_id=project_id,
            chapter_id=data.chapter_id,
            proposal_id=None,
            revision_id=None,
            text=data.text,
            origin="author",
            lifecycle="in_text",
            review_state="needs_review",
            support_status="unverified",
            note=data.note,
            created_at=now,
            updated_at=now,
        )
        s.add(claim)
        s.flush()
        sups = [_support_from_chunk(s, ctx, project_id, claim.id, cid) for cid in dict.fromkeys(data.chunk_ids)]
        s.add_all(sups)
        claim.support_status = _support_status(sups)
        activity.record(
            s,
            ctx,
            kind="claim_added",
            project_id=project_id,
            ref_type="claim",
            ref_id=claim.id,
            summary=f"Added a claim to the evidence ledger ({len(sups)} source passages)",
        )
        s.flush()
        return _out(s, claim)


def patch_claim(ctx: AppContext, project_id: str, claim_id: str, data: ClaimPatch) -> ClaimOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        claim = s.get(Claim, claim_id) if is_ulid(claim_id) else None
        if claim is None or claim.project_id != project_id:
            raise NotFoundError("Claim not found in this book.")
        if data.review_state is not None:
            claim.review_state = data.review_state
        if data.note is not None:
            claim.note = data.note or None
        for sid in data.remove_support_ids:
            row = s.get(ClaimSupport, sid)
            if row is not None and row.claim_id == claim.id:
                s.delete(row)
        s.flush()
        existing = {x.chunk_id for x in s.scalars(select(ClaimSupport).where(ClaimSupport.claim_id == claim.id))}
        for cid in dict.fromkeys(data.add_chunk_ids):
            if cid not in existing:
                s.add(_support_from_chunk(s, ctx, project_id, claim.id, cid))
        s.flush()
        claim.support_status = _support_status(
            list(s.scalars(select(ClaimSupport).where(ClaimSupport.claim_id == claim.id)))
        )
        claim.updated_at = ctx.clock.iso()
        s.flush()
        return _out(s, claim)
