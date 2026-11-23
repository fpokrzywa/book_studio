"""Phase 08 tables: series and canon, continuity issues, translation editions, narration, recordings.

* Canon rows carry status (canon = author-approved, suggested = from AI or a book's draft notes,
  rejected) and provenance (which book, chapter, revision or note they came from).
* A translation is a separate, linked book; its chapters mirror the source chapters (same slugs and
  order) and every translated chapter remembers the exact source revision it came from. The source
  book is never written to.
* Narration chunks keep the chapter, revision and source blocks they were made from (alignment).
* Transcript segment text is immutable (DB trigger): speech is never rewritten, only speaker labels.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

CANON_KINDS = ("character", "location", "thread", "event", "term", "other")
CANON_STATUSES = ("canon", "suggested", "rejected")
CANON_ORIGINS = ("author", "ai_suggested", "book_note")
ISSUE_STATES = ("open", "keep_canon", "canon_updated", "intended")
CT_STATUSES = ("not_started", "requested", "suggested", "accepted", "rejected")
CHUNK_STATUSES = ("pending", "done", "failed")
RECORDING_STATUSES = ("imported", "transcribed", "failed")


class Series(Base):
    __tablename__ = "series"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class SeriesBook(Base):
    __tablename__ = "series_book"

    series_id: Mapped[str] = mapped_column(Text, ForeignKey("series.id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("project_id"),)  # a book belongs to at most one series


class CanonEntity(Base):
    __tablename__ = "canon_entity"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[str] = mapped_column(Text, ForeignKey("series.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("kind", CANON_KINDS), name="kind"),
        CheckConstraint(_in("status", CANON_STATUSES), name="status"),
        CheckConstraint(_in("origin", CANON_ORIGINS), name="origin"),
        Index("ix_canon_entity_series", "series_id", "kind", "name"),
    )


class CanonFact(Base):
    __tablename__ = "canon_fact"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[str] = mapped_column(Text, ForeignKey("series.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, ForeignKey("canon_entity.id"), nullable=False)
    attribute: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    story_time: Mapped[str | None] = mapped_column(Text)
    book_project_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    superseded_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("status", CANON_STATUSES), name="status"),
        CheckConstraint(_in("origin", CANON_ORIGINS), name="origin"),
        Index("ix_canon_fact_entity", "entity_id"),
    )


class CanonRelationship(Base):
    __tablename__ = "canon_relationship"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[str] = mapped_column(Text, ForeignKey("series.id"), nullable=False)
    from_entity_id: Mapped[str] = mapped_column(Text, ForeignKey("canon_entity.id"), nullable=False)
    to_entity_id: Mapped[str] = mapped_column(Text, ForeignKey("canon_entity.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("status", CANON_STATUSES), name="status"),
        CheckConstraint(_in("origin", CANON_ORIGINS), name="origin"),
    )


class ContinuityIssue(Base):
    """A place where a chapter seems to contradict series canon, and the author's resolution."""

    __tablename__ = "continuity_issue"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[str] = mapped_column(Text, ForeignKey("series.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    fact_id: Mapped[str | None] = mapped_column(Text)
    relationship_id: Mapped[str | None] = mapped_column(Text)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    found_value: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    present: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("series_id", "fingerprint"),
        CheckConstraint(_in("state", ISSUE_STATES), name="state"),
        CheckConstraint("present IN (0, 1)", name="present"),
    )


class TranslationEdition(Base):
    __tablename__ = "translation_edition"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    target_project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False, unique=True)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    term_map_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("source_project_id", "language"),)


class ChapterTranslation(Base):
    __tablename__ = "chapter_translation"

    target_chapter_id: Mapped[str] = mapped_column(Text, primary_key=True)
    edition_id: Mapped[str] = mapped_column(Text, ForeignKey("translation_edition.id"), nullable=False)
    source_chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_revision_id: Mapped[str | None] = mapped_column(Text)
    source_revision_no: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_started")
    job_id: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[str | None] = mapped_column(Text)
    suggested_title: Mapped[str | None] = mapped_column(Text)
    issues_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("status", CT_STATUSES), name="status"),
        Index("ix_chapter_translation_source", "source_chapter_id"),
    )


class NarrationChunk(Base):
    __tablename__ = "narration_chunk"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    block_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    notes_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    provider: Mapped[str | None] = mapped_column(Text)
    voice: Mapped[str | None] = mapped_column(Text)
    audio_path: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_amount: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("revision_id", "ordinal"),
        CheckConstraint(_in("status", CHUNK_STATUSES), name="status"),
        Index("ix_narration_chapter", "chapter_id", "revision_no"),
    )


class Recording(Base):
    __tablename__ = "recording"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    original_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    rights_note: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="imported")
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    transcribed_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("status", RECORDING_STATUSES), name="status"),)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segment"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    recording_id: Mapped[str] = mapped_column(Text, ForeignKey("recording.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(Text, nullable=False)
    provider_speaker: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(Text)  # knowledge source made from this quote
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("recording_id", "ordinal"),)
