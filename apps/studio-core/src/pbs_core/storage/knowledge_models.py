"""Phase 04 tables: knowledge libraries, sources and chunks, the evidence ledger, author voice and
interviews.

* Source text is untrusted reference material. It is stored, searched and quoted, never executed.
* Originals stay in `original_file` (immutable, content-addressed). Chunks can always be rebuilt.
* Citation keys are stable: `UNIQUE(key_scope, citation_key)`. The scope is the owning project
  (project libraries) or `shared`, so a restored book keeps the keys its chapters cite.
* The full-text index `source_chunk_fts` (SQLite FTS5) is created by migration 0005 and is not
  mapped here; `knowledge.index` keeps it in step with `source_chunk`.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

SOURCE_KINDS = ("markdown", "text", "html", "docx", "pdf")
SOURCE_STATUSES = ("pending", "indexed", "failed")
CLAIM_LIFECYCLE = ("proposed", "in_text", "discarded")
CLAIM_REVIEW = ("needs_review", "verified", "disputed")
CLAIM_SUPPORT = ("supported", "not_located", "unverified")


class KnowledgeLibrary(Base):
    __tablename__ = "knowledge_library"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)  # project | shared
    project_id: Mapped[str | None] = mapped_column(Text, ForeignKey("project.id"))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "(scope = 'project' AND project_id IS NOT NULL) OR (scope = 'shared' AND project_id IS NULL)",
            name="scope",
        ),
        Index("ix_library_project", "project_id"),
    )


class LibraryLink(Base):
    """A book opting in to a shared library."""

    __tablename__ = "library_link"

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), primary_key=True)
    library_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_library.id"), primary_key=True)
    linked_at: Mapped[str] = mapped_column(Text, nullable=False)


class Source(Base):
    __tablename__ = "source"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    library_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_library.id"), nullable=False)
    original_file_id: Mapped[str] = mapped_column(Text, ForeignKey("original_file.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_origin: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # file_metadata | first_heading | file_name | author
    citation_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_scope: Mapped[str] = mapped_column(Text, nullable=False)  # project id or "shared"
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    page_count: Mapped[int | None] = mapped_column(Integer)
    # Bibliographic fields: only what the author typed (never guessed).
    authors_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    year: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    indexed_at: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("key_scope", "citation_key"),
        CheckConstraint(_in("kind", SOURCE_KINDS), name="kind"),
        CheckConstraint(_in("status", SOURCE_STATUSES), name="status"),
        Index(
            "uq_source_file_per_library",
            "library_id",
            "file_sha256",
            unique=True,
            sqlite_where=text("removed_at IS NULL"),
        ),
        Index("ix_source_library", "library_id"),
    )


class SourceChunk(Base):
    __tablename__ = "source_chunk"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("source.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    para_start: Mapped[int] = mapped_column(Integer, nullable=False)
    para_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("source_id", "seq"),)


class Claim(Base):
    """An entry in the evidence ledger: a statement and what supports it. Kept apart from prose."""

    __tablename__ = "claim"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[str | None] = mapped_column(Text)
    revision_id: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)  # ai_generated | author
    lifecycle: Mapped[str] = mapped_column(Text, nullable=False)
    review_state: Mapped[str] = mapped_column(Text, nullable=False)
    support_status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("origin IN ('ai_generated', 'author')", name="origin"),
        CheckConstraint(_in("lifecycle", CLAIM_LIFECYCLE), name="lifecycle"),
        CheckConstraint(_in("review_state", CLAIM_REVIEW), name="review_state"),
        CheckConstraint(_in("support_status", CLAIM_SUPPORT), name="support_status"),
        Index("ix_claim_project", "project_id", "created_at"),
        Index("ix_claim_proposal", "proposal_id"),
    )


class ClaimSupport(Base):
    """One piece of evidence for a claim. The quote and locator are copied so the evidence survives
    the source being re-indexed or removed."""

    __tablename__ = "claim_support"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    claim_id: Mapped[str] = mapped_column(Text, ForeignKey("claim.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # source | interview
    source_id: Mapped[str | None] = mapped_column(Text, ForeignKey("source.id"))
    chunk_id: Mapped[str | None] = mapped_column(Text)
    interview_answer_id: Mapped[str | None] = mapped_column(Text)
    citation_key: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    located: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('source', 'interview')", name="kind"),
        Index("ix_claim_support_claim", "claim_id"),
    )


class AuthorProfile(Base):
    """An author or pen name, with a style guide the author can edit."""

    __tablename__ = "author_profile"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # author | pen_name
    style_guide_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    guide_edited: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    examples_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    corrections_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    pen_name: Mapped[str | None] = mapped_column(Text)
    voice_rules_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    analyzed_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("kind IN ('author', 'pen_name')", name="kind"),)


class VoiceSample(Base):
    """The author's own writing (or writing they have the rights to use), for style analysis only."""

    __tablename__ = "voice_sample"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    profile_id: Mapped[str] = mapped_column(Text, ForeignKey("author_profile.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_file_id: Mapped[str | None] = mapped_column(Text, ForeignKey("original_file.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rights_confirmed: Mapped[int] = mapped_column(Integer, nullable=False)
    rights_basis: Mapped[str] = mapped_column(Text, nullable=False)  # own_writing | licensed
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "text_sha256"),
        CheckConstraint("rights_confirmed = 1", name="rights_confirmed"),
        CheckConstraint("rights_basis IN ('own_writing', 'licensed')", name="rights_basis"),
    )


class InterviewSession(Base):
    __tablename__ = "interview_session"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class InterviewQuestion(Base):
    __tablename__ = "interview_question"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("interview_session.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)  # bank | author
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("origin IN ('bank', 'author')", name="origin"),)


class InterviewAnswer(Base):
    """The author's exact words. Immutable (DB trigger): a changed answer is a new row that supersedes it."""

    __tablename__ = "interview_answer"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    question_id: Mapped[str] = mapped_column(Text, ForeignKey("interview_question.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)  # typed
    supersedes_id: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_answer_question", "question_id", "answered_at"),)
