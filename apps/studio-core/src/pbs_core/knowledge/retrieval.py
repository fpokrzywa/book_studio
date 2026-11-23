"""Pick the passages and interview answers a chapter task may see.

Only sources that are enabled, indexed and not removed, in this book's own libraries or shared
libraries the book opted into, are ever eligible. Disabling a source takes effect at the next
generation because retrieval runs when the job runs, not when it was queued.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.knowledge import search
from pbs_core.knowledge.citations import Ref, content_words
from pbs_core.storage.knowledge_models import (
    InterviewAnswer,
    InterviewQuestion,
    KnowledgeLibrary,
    LibraryLink,
    Source,
)

MAX_PASSAGES = 6
PASSAGE_BUDGET = 12_000
MAX_ANSWERS = 5
ANSWER_BUDGET = 6_000


def library_ids(s: Session, project_id: str) -> list[str]:
    own = select(KnowledgeLibrary.id).where(
        KnowledgeLibrary.scope == "project",
        KnowledgeLibrary.project_id == project_id,
        KnowledgeLibrary.archived_at.is_(None),
    )
    linked = (
        select(KnowledgeLibrary.id)
        .join(LibraryLink, LibraryLink.library_id == KnowledgeLibrary.id)
        .where(LibraryLink.project_id == project_id, KnowledgeLibrary.archived_at.is_(None))
    )
    return list(s.scalars(own).all()) + list(s.scalars(linked).all())


def usable_source_ids(s: Session, project_id: str) -> list[str]:
    libs = library_ids(s, project_id)
    if not libs:
        return []
    return list(
        s.scalars(
            select(Source.id).where(
                Source.library_id.in_(libs),
                Source.enabled == 1,
                Source.status == "indexed",
                Source.removed_at.is_(None),
            )
        ).all()
    )


@dataclass
class Retrieved:
    refs: dict[str, Ref]
    passages: list[search.Hit]
    answers: list[tuple[InterviewAnswer, InterviewQuestion]]
    query: str
    source_count: int


def retrieve(s: Session, project_id: str, query: str, *, use_sources: bool, use_interview: bool) -> Retrieved:
    refs: dict[str, Ref] = {}
    passages: list[search.Hit] = []
    ids = usable_source_ids(s, project_id) if use_sources else []
    if ids:
        hits, _ = search.search(s, source_ids=ids, query=query, limit=20, mode="any", drop_stopwords=True)
        used = 0
        for h in hits:
            if len(passages) >= MAX_PASSAGES or used + len(h.text) > PASSAGE_BUDGET:
                continue
            passages.append(h)
            used += len(h.text)
        for i, h in enumerate(passages, start=1):
            refs[f"S{i}"] = Ref(
                label=f"S{i}",
                kind="source",
                text=h.text,
                title=h.title,
                source_id=h.source_id,
                chunk_id=h.chunk_id,
                citation_key=h.citation_key,
                locator=h.locator,
            )
    answers: list[tuple[InterviewAnswer, InterviewQuestion]] = []
    if use_interview:
        answers = _answers(s, project_id, query)
        for i, (a, q) in enumerate(answers, start=1):
            refs[f"I{i}"] = Ref(label=f"I{i}", kind="interview", text=a.answer_text, title=q.prompt, answer_id=a.id)
    return Retrieved(refs, passages, answers, query, len(ids))


def current_answers(s: Session, project_id: str) -> list[tuple[InterviewAnswer, InterviewQuestion]]:
    rows = s.execute(
        select(InterviewAnswer, InterviewQuestion)
        .join(InterviewQuestion, InterviewQuestion.id == InterviewAnswer.question_id)
        .where(InterviewAnswer.project_id == project_id)
        .order_by(InterviewAnswer.answered_at)
    ).all()
    superseded = {a.supersedes_id for a, _ in rows if a.supersedes_id}
    return [(a, q) for a, q in rows if a.id not in superseded and a.answer_text.strip()]


def _answers(s: Session, project_id: str, query: str) -> list[tuple[InterviewAnswer, InterviewQuestion]]:
    want = content_words(query)
    scored = []
    for a, q in current_answers(s, project_id):
        overlap = len(want & content_words(a.answer_text + " " + q.prompt))
        scored.append((overlap, a.answered_at, a, q))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: list[tuple[InterviewAnswer, InterviewQuestion]] = []
    used = 0
    for overlap, _, a, q in scored:
        if len(out) >= MAX_ANSWERS or (want and overlap == 0 and out):
            break
        if used + len(a.answer_text) > ANSWER_BUDGET:
            continue
        out.append((a, q))
        used += len(a.answer_text)
    return out
