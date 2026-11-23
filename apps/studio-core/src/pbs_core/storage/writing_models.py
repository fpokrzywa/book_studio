"""Phase 06 tables: the section-by-section writing pipeline, continuity memory and quality findings.

* A draft plan drafts ONE chapter, one outline section at a time. Each section is its own durable
  job, so a failed section is retried on its own and finished sections are never rewritten.
* Sections never touch the manuscript. When every section is done the plan assembles them into a
  single *proposal*; only the author's Accept turns that into a revision.
* Continuity memory (facts about characters, places, terms, threads and events) and chapter
  summaries keep later prompts small. AI-extracted facts stay "proposed" until the author confirms.
* Quality findings carry a stable fingerprint, so the author's review decision survives re-runs.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

PLAN_STATUSES = ("waiting", "running", "paused", "awaiting_review", "ready", "cancelled")
REVIEW_GATES = ("none", "each_section")
SECTION_STATUSES = ("pending", "active", "done", "cancelled")
FACT_KINDS = ("character", "location", "relationship", "event", "thread", "term", "other")
FACT_ORIGINS = ("author", "ai_extracted")
FACT_STATUSES = ("proposed", "confirmed", "rejected", "resolved")
SUMMARY_ORIGINS = ("ai_draft", "author")
FINDING_SEVERITIES = ("info", "warning")
FINDING_STATES = ("open", "needs_source", "will_fix", "dismissed", "fixed")
FINDING_ORIGINS_Q = ("rule", "ai_review")


class DraftPlan(Base):
    __tablename__ = "draft_plan"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text)
    run_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    outline_version_id: Mapped[str | None] = mapped_column(Text)
    outline_node_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    review_gate: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    base_revision_id: Mapped[str | None] = mapped_column(Text)
    base_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_config_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[str | None] = mapped_column(Text)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)  # per section
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False)  # input tokens per section prompt
    options_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    proposal_id: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("status", PLAN_STATUSES), name="status"),
        CheckConstraint(_in("review_gate", REVIEW_GATES), name="review_gate"),
        Index("ix_draft_plan_project", "project_id", "created_at"),
        Index("ix_draft_plan_run", "run_id", "run_order"),
    )


class DraftSection(Base):
    """One section of a plan. Its output is stored here, never in the chapter."""

    __tablename__ = "draft_section"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    plan_id: Mapped[str] = mapped_column(Text, ForeignKey("draft_plan.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    node_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")  # write "## title"?
    goal: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    target_words: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    job_id: Mapped[str | None] = mapped_column(Text)  # latest attempt
    job_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    output_md: Mapped[str | None] = mapped_column(Text)
    edited: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    summary: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    citations_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("plan_id", "ordinal"),
        CheckConstraint(_in("status", SECTION_STATUSES), name="status"),
        CheckConstraint("edited IN (0, 1)", name="edited"),
    )


class ContinuityFact(Base):
    """Running continuity memory / story bible. AI-extracted facts are 'proposed' until confirmed."""

    __tablename__ = "continuity_fact"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    attribute: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    value: Mapped[str] = mapped_column(Text, nullable=False)
    story_time: Mapped[str | None] = mapped_column(Text)
    chapter_id: Mapped[str | None] = mapped_column(Text)
    plan_id: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("kind", FACT_KINDS), name="kind"),
        CheckConstraint(_in("origin", FACT_ORIGINS), name="origin"),
        CheckConstraint(_in("status", FACT_STATUSES), name="status"),
        Index("ix_continuity_project", "project_id", "kind", "name"),
    )


class ChapterSummary(Base):
    """Short summary of a chapter for later prompts. The newest row per chapter is current."""

    __tablename__ = "chapter_summary"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False)
    plan_id: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("origin", SUMMARY_ORIGINS), name="origin"),
        Index("ix_chapter_summary_chapter", "chapter_id", "created_at"),
    )


class QualityFinding(Base):
    """A finding from the local checks or an AI review, with the author's decision."""

    __tablename__ = "quality_finding"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(Text)
    check_code: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    revision_no: Mapped[int | None] = mapped_column(Integer)
    present: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint"),
        CheckConstraint(_in("origin", FINDING_ORIGINS_Q), name="origin"),
        CheckConstraint(_in("severity", FINDING_SEVERITIES), name="severity"),
        CheckConstraint(_in("state", FINDING_STATES), name="state"),
        CheckConstraint("present IN (0, 1)", name="present"),
        Index("ix_quality_project_chapter", "project_id", "chapter_id"),
    )
