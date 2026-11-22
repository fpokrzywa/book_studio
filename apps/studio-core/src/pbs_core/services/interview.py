"""Interview-to-book: questions about the author's own stories, and their exact answers.

Answers are stored verbatim with time and method, and are immutable (DB triggers): changing an
answer saves a new version that supersedes the old one. AI tasks may draw on answers only as the
author's own words; prompts forbid inventing experiences (jobs/prompts.py).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_knowledge import (
    AnswerIn,
    InterviewAnswerOut,
    InterviewOut,
    InterviewQuestionOut,
    QuestionCreate,
)
from pbs_core.domain.errors import NotFoundError
from pbs_core.services import activity
from pbs_core.services.projects import require_active, require_project
from pbs_core.storage.knowledge_models import InterviewAnswer, InterviewQuestion, InterviewSession

QUESTION_BANK = [
    "What first drew you to this subject? Describe the moment, where you were and who was there.",
    "Tell a story about a time something went wrong. What happened, and what did you do next?",
    "Who taught you the most about this? What did they say or do that stayed with you?",
    "Describe a turning point: what changed, and how did you know it had changed?",
    "What is a mistake you see others make that you once made yourself?",
    "Describe a place that matters to this story in as much sensory detail as you remember.",
    "What do you believe about this subject that many people would disagree with? Why?",
    "Tell about a small, ordinary day that shows what this work is really like.",
    "What would you want a reader to do differently after finishing this book?",
    "Is there anything you are unsure about or still learning? Describe it honestly.",
]


def _session(s: Session, ctx: AppContext, project_id: str, create: bool) -> InterviewSession | None:
    sess = s.scalars(select(InterviewSession).where(InterviewSession.project_id == project_id)).first()
    if sess is None and create:
        now = ctx.clock.iso()
        sess = InterviewSession(id=ctx.ids.new(), project_id=project_id, title="Interview", created_at=now)
        s.add(sess)
        s.flush()
        for i, q in enumerate(QUESTION_BANK):
            s.add(
                InterviewQuestion(
                    id=ctx.ids.new(),
                    session_id=sess.id,
                    project_id=project_id,
                    seq=i,
                    prompt=q,
                    origin="bank",
                    created_at=now,
                )
            )
        s.flush()
    return sess


def _a(a: InterviewAnswer) -> InterviewAnswerOut:
    return InterviewAnswerOut(
        id=a.id, answer_text=a.answer_text, answered_at=a.answered_at, supersedes_id=a.supersedes_id
    )


def _out(s: Session, sess: InterviewSession) -> InterviewOut:
    questions = s.scalars(
        select(InterviewQuestion).where(InterviewQuestion.session_id == sess.id).order_by(InterviewQuestion.seq)
    ).all()
    answers = s.scalars(
        select(InterviewAnswer)
        .where(InterviewAnswer.project_id == sess.project_id)
        .order_by(InterviewAnswer.answered_at)
    ).all()
    superseded = {a.supersedes_id for a in answers if a.supersedes_id}
    out = []
    answered = 0
    for q in questions:
        mine = [a for a in answers if a.question_id == q.id]
        current = next((a for a in reversed(mine) if a.id not in superseded), None)
        if current is not None and current.answer_text.strip():
            answered += 1
        out.append(
            InterviewQuestionOut(
                id=q.id,
                seq=q.seq,
                prompt=q.prompt,
                origin=q.origin,
                answer=_a(current) if current else None,
                history=[_a(a) for a in mine],
            )
        )
    return InterviewOut(
        session_id=sess.id, project_id=sess.project_id, title=sess.title, questions=out, answered=answered
    )


def get_interview(ctx: AppContext, project_id: str) -> InterviewOut:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        sess = _session(s, ctx, project_id, create=True)
        if sess is None:  # pragma: no cover - created above
            raise NotFoundError("Interview not found.")
        return _out(s, sess)


def add_question(ctx: AppContext, project_id: str, data: QuestionCreate) -> InterviewOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        sess = _session(s, ctx, project_id, create=True)
        if sess is None:  # pragma: no cover - created above
            raise NotFoundError("Interview not found.")
        seq = (
            s.scalar(select(func.max(InterviewQuestion.seq)).where(InterviewQuestion.session_id == sess.id)) or 0
        ) + 1
        s.add(
            InterviewQuestion(
                id=ctx.ids.new(),
                session_id=sess.id,
                project_id=project_id,
                seq=seq,
                prompt=data.prompt,
                origin="author",
                created_at=ctx.clock.iso(),
            )
        )
        s.flush()
        return _out(s, sess)


def answer(ctx: AppContext, project_id: str, question_id: str, data: AnswerIn) -> InterviewOut:
    with ctx.db.tx() as s:
        require_active(s, project_id)
        q = s.get(InterviewQuestion, question_id)
        if q is None or q.project_id != project_id:
            raise NotFoundError("Question not found in this book.")
        mine = s.scalars(
            select(InterviewAnswer).where(InterviewAnswer.question_id == q.id).order_by(InterviewAnswer.answered_at)
        ).all()
        superseded = {a.supersedes_id for a in mine if a.supersedes_id}
        current = next((a for a in reversed(mine) if a.id not in superseded), None)
        if current is None or current.answer_text != data.answer_text:
            s.add(
                InterviewAnswer(
                    id=ctx.ids.new(),
                    question_id=q.id,
                    project_id=project_id,
                    answer_text=data.answer_text,
                    method="typed",
                    supersedes_id=current.id if current else None,
                    answered_at=ctx.clock.iso(),
                )
            )
            activity.record(
                s,
                ctx,
                kind="interview_answered",
                project_id=project_id,
                summary="Saved an interview answer (your exact words)",
            )
        s.flush()
        sess = s.get(InterviewSession, q.session_id)
        if sess is None:  # pragma: no cover - created above
            raise NotFoundError("Interview not found.")
        return _out(s, sess)
