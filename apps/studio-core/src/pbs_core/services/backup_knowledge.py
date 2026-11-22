"""Knowledge, evidence and interview rows in a book backup (manifest/1, Phase 04 tables).

Backup: the book's own libraries plus the shared libraries it opted into, their sources (removed
ones too, so ledger evidence keeps its title), chunks and preserved originals; the book's ledger
claims with their supports; and the interview with every answer version.

Restore: everything comes back under new IDs as libraries owned by the restored book. Citation
keys are kept exactly, so `[@key]` citations in the chapters keep resolving; the full-text index is
rebuilt from the chunks. Author voice profiles are workspace-wide and are not part of a book backup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import WarningOut
from pbs_core.knowledge import retrieval, search
from pbs_core.storage.knowledge_models import (
    Claim,
    ClaimSupport,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    KnowledgeLibrary,
    Source,
    SourceChunk,
)
from pbs_core.storage.models import Base, OriginalFile

RowFn = Callable[[Any], dict[str, Any]]


def collect(s: Session, project_id: str, row: RowFn) -> tuple[dict[str, list[dict[str, Any]]], list[OriginalFile]]:
    lib_ids = retrieval.library_ids(s, project_id)
    libs = s.scalars(select(KnowledgeLibrary).where(KnowledgeLibrary.id.in_(lib_ids))).all() if lib_ids else []
    sources = s.scalars(select(Source).where(Source.library_id.in_(lib_ids))).all() if lib_ids else []
    src_ids = [x.id for x in sources]
    chunks = s.scalars(select(SourceChunk).where(SourceChunk.source_id.in_(src_ids))).all() if src_ids else []
    claims = s.scalars(select(Claim).where(Claim.project_id == project_id, Claim.lifecycle != "discarded")).all()
    claim_ids = [c.id for c in claims]
    supports = s.scalars(select(ClaimSupport).where(ClaimSupport.claim_id.in_(claim_ids))).all() if claim_ids else []
    sessions = s.scalars(select(InterviewSession).where(InterviewSession.project_id == project_id)).all()
    questions = s.scalars(select(InterviewQuestion).where(InterviewQuestion.project_id == project_id)).all()
    answers = s.scalars(select(InterviewAnswer).where(InterviewAnswer.project_id == project_id)).all()
    originals = [o for o in (s.get(OriginalFile, x.original_file_id) for x in sources) if o is not None]
    tables = {
        "knowledge_library": [row(x) for x in libs],
        "source": [row(x) for x in sources],
        "source_chunk": sorted((row(x) for x in chunks), key=lambda r: (r["source_id"], r["seq"])),
        "claim": [row(x) for x in claims],
        "claim_support": [row(x) for x in supports],
        "interview_session": [row(x) for x in sessions],
        "interview_question": [row(x) for x in questions],
        "interview_answer": sorted((row(x) for x in answers), key=lambda r: r["answered_at"]),
    }
    return tables, originals


def restore(
    s: Session,
    ctx: AppContext,
    rows: Callable[[str], list[dict[str, Any]]],
    kwargs: Callable[[type[Base], dict[str, Any]], dict[str, Any]],
    *,
    new_pid: str,
    original_map: dict[str, str],
    chapter_map: dict[str, str],
    revision_map: dict[str, str],
    warnings: list[WarningOut],
) -> dict[str, int]:
    new = ctx.ids.new
    lib_map: dict[str, str] = {}
    for r in rows("knowledge_library"):
        kw = kwargs(KnowledgeLibrary, r)
        kw.update(id=new(), scope="project", project_id=new_pid, archived_at=None)
        if r["scope"] == "shared":
            kw["name"] = f"{r['name']} (copy from shared)"[:120]
        lib_map[r["id"]] = kw["id"]
        s.add(KnowledgeLibrary(**kw))
    s.flush()

    source_map: dict[str, str] = {}
    taken: set[str] = set()
    titles: dict[str, str] = {}
    for r in rows("source"):
        if r["library_id"] not in lib_map:
            continue
        if r["original_file_id"] not in original_map:
            warnings.append(
                WarningOut(code="source_missing", message=f"Source “{r['title']}” had no original file in the backup.")
            )
            continue
        kw = kwargs(Source, r)
        key = r["citation_key"]
        if key in taken:  # a book-owned and a shared source used the same key
            n = 2
            while f"{key}-{n}" in taken:
                n += 1
            warnings.append(
                WarningOut(
                    code="citation_key_renamed",
                    message=f"Citation key @{key} was used twice; the second source is now @{key}-{n}.",
                )
            )
            key = f"{key}-{n}"
        taken.add(key)
        kw.update(
            id=new(),
            library_id=lib_map[r["library_id"]],
            original_file_id=original_map[r["original_file_id"]],
            key_scope=new_pid,
            citation_key=key,
        )
        source_map[r["id"]] = kw["id"]
        titles[kw["id"]] = kw["title"]
        s.add(Source(**kw))
    s.flush()

    chunk_map: dict[str, str] = {}
    for r in rows("source_chunk"):
        if r["source_id"] not in source_map:
            continue
        kw = kwargs(SourceChunk, r)
        kw.update(id=new(), source_id=source_map[r["source_id"]])
        chunk_map[r["id"]] = kw["id"]
        s.add(SourceChunk(**kw))
        search.index_chunk(
            s,
            chunk_id=kw["id"],
            source_id=kw["source_id"],
            title=titles[kw["source_id"]],
            heading=kw["heading_path"],
            body=kw["text"],
        )
    s.flush()

    session_map: dict[str, str] = {}
    for r in rows("interview_session"):
        kw = kwargs(InterviewSession, r)
        kw.update(id=new(), project_id=new_pid)
        session_map[r["id"]] = kw["id"]
        s.add(InterviewSession(**kw))
    s.flush()  # no ORM relationships: insert parents before children explicitly
    question_map: dict[str, str] = {}
    for r in rows("interview_question"):
        if r["session_id"] in session_map:
            kw = kwargs(InterviewQuestion, r)
            kw.update(id=new(), session_id=session_map[r["session_id"]], project_id=new_pid)
            question_map[r["id"]] = kw["id"]
            s.add(InterviewQuestion(**kw))
    s.flush()
    answer_map: dict[str, str] = {}
    for r in rows("interview_answer"):
        if r["question_id"] in question_map:
            kw = kwargs(InterviewAnswer, r)
            answer_map[r["id"]] = new()
            kw.update(
                id=answer_map[r["id"]],
                question_id=question_map[r["question_id"]],
                project_id=new_pid,
                supersedes_id=answer_map.get(r.get("supersedes_id") or ""),
            )
            s.add(InterviewAnswer(**kw))
    s.flush()

    claim_map: dict[str, str] = {}
    for r in rows("claim"):
        kw = kwargs(Claim, r)
        kw.update(
            id=new(),
            project_id=new_pid,
            chapter_id=chapter_map.get(r.get("chapter_id") or ""),
            proposal_id=None,
            revision_id=revision_map.get(r.get("revision_id") or ""),
        )
        claim_map[r["id"]] = kw["id"]
        s.add(Claim(**kw))
    s.flush()
    for r in rows("claim_support"):
        if r["claim_id"] not in claim_map:
            continue
        kw = kwargs(ClaimSupport, r)
        kw.update(
            id=new(),
            claim_id=claim_map[r["claim_id"]],
            source_id=source_map.get(r.get("source_id") or ""),
            chunk_id=chunk_map.get(r.get("chunk_id") or ""),
            interview_answer_id=answer_map.get(r.get("interview_answer_id") or ""),
        )
        s.add(ClaimSupport(**kw))
    s.flush()
    return {"sources": len(source_map), "claims": len(claim_map), "answers": len(answer_map)}
