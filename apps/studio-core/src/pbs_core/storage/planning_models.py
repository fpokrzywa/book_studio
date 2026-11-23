"""Phase 05 tables: book brief, research findings, outline versions and generation runs.

* Research findings keep "measured" (a real source supplied it) apart from "heuristic"/brainstormed
  material. A measured finding must name its source (DB CHECK), and market figures are never stored
  unless a configured provider supplied them.
* Outline versions are immutable snapshots once proposed; the author edits a draft, AI output is
  always a new proposed version, and only an approved version is applied to the manuscript.
* Chapters keep their prose: applying an outline only creates, renames, moves or archives *empty*
  chapters, matched by the stable `chapter.outline_node_id`.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

BOOK_KINDS = ("fiction", "nonfiction", "manual", "workbook", "memoir")
APPROVAL_PREFERENCES = ("review_each_chapter", "review_outline_then_batch")
FINDING_KINDS = ("measured", "heuristic", "note", "competitor", "keyword", "topic", "query")
FINDING_ORIGINS = ("author", "ai_brainstorm", "provider")
OUTLINE_STATUSES = ("draft", "proposed", "approved", "superseded", "rejected")
RUN_MODES = ("one_chapter", "entire_book")
RUN_STATUSES = ("running", "done", "stopped")


class BookBrief(Base):
    __tablename__ = "book_brief"

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    genre: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(Text)
    promise: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(Text)
    author_profile_id: Mapped[str | None] = mapped_column(Text)
    desired_chapters: Mapped[int | None] = mapped_column(Integer)
    approval_preference: Mapped[str] = mapped_column(Text, nullable=False, server_default="review_each_chapter")
    budget_cap: Mapped[str | None] = mapped_column(Text)  # decimal as text; None = no cap
    budget_currency: Mapped[str | None] = mapped_column(Text)
    max_chapters_per_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    words_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="500")
    target_reader: Mapped[str | None] = mapped_column(Text)
    exclusions_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    value_proposition: Mapped[str | None] = mapped_column(Text)
    arc_md: Mapped[str | None] = mapped_column(Text)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    approved_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("kind", BOOK_KINDS), name="kind"),
        CheckConstraint(_in("approval_preference", APPROVAL_PREFERENCES), name="approval_preference"),
        CheckConstraint("status IN ('draft', 'approved')", name="status"),
    )


class ResearchFinding(Base):
    __tablename__ = "research_finding"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_date: Mapped[str | None] = mapped_column(Text)  # when the source published it (if known)
    retrieved_at: Mapped[str | None] = mapped_column(Text)  # when it was captured
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    flags_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    selected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    archived_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("kind", FINDING_KINDS), name="kind"),
        CheckConstraint(_in("origin", FINDING_ORIGINS), name="origin"),
        # Measured evidence must say where it came from.
        CheckConstraint("kind <> 'measured' OR source_url IS NOT NULL OR provider IS NOT NULL", name="measured_source"),
        # Only a provider may attach metrics, and AI brainstorms never carry any.
        CheckConstraint("metrics_json = '{}' OR origin = 'provider'", name="metrics_from_provider"),
        Index("ix_finding_project", "project_id", "created_at"),
    )


class ResearchQuery(Base):
    """Every search sent to an external research provider, including failures (fail-safe audit)."""

    __tablename__ = "research_query"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok | failed | blocked
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    results_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")  # what the provider returned
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("status IN ('ok', 'failed', 'blocked')", name="status"),)


class OutlineVersion(Base):
    __tablename__ = "outline_version"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)  # author | ai_generated
    nodes_json: Mapped[str] = mapped_column(Text, nullable=False)
    based_on_id: Mapped[str | None] = mapped_column(Text)
    brief_version: Mapped[int | None] = mapped_column(Integer)
    research_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    job_id: Mapped[str | None] = mapped_column(Text)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[str | None] = mapped_column(Text)
    apply_report_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "version_no"),
        CheckConstraint(_in("status", OUTLINE_STATUSES), name="status"),
        CheckConstraint("origin IN ('author', 'ai_generated')", name="origin"),
        # At most one approved outline per book.
        Index("uq_outline_one_approved", "project_id", unique=True, sqlite_where=text("status = 'approved'")),
    )


class GenerationRun(Base):
    """A batch of chapter drafts with an estimate, a hard budget cap and a chapter limit."""

    __tablename__ = "generation_run"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    outline_version_id: Mapped[str] = mapped_column(Text, nullable=False)
    budget_cap: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(Text)
    spent: Mapped[str] = mapped_column(Text, nullable=False, server_default="0")
    unknown_cost_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    job_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    skipped_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    estimate_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    stop_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("mode", RUN_MODES), name="mode"),
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        Index("ix_run_project", "project_id", "created_at"),
    )
