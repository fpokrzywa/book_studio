"""Phase 03 tables: AI providers, models, routing, prices, consent, durable jobs, proposals, usage.

Secrets are NEVER stored here: `provider_config.credential_ref` names an entry in the OS
credential store (or the explicit development fallback); it is not the key.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

PROVIDER_KINDS = ("mock", "ollama", "openai", "anthropic", "gemini", "groq", "xai")
TASKS = ("brainstorm", "research", "outline", "draft", "revise", "summarize", "translate")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "interrupted")
PROPOSAL_STATUSES = ("pending", "accepted", "rejected", "stale")
PROPOSAL_MODES = ("append", "replace_selection", "insert_at", "note")


class ProviderConfig(Base):
    __tablename__ = "provider_config"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    health_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(_in("kind", PROVIDER_KINDS), name="kind"),)


class ModelInfo(Base):
    __tablename__ = "model_info"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_config_id: Mapped[str] = mapped_column(Text, ForeignKey("provider_config.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    context_tokens: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    # {"structured_output": "reported:true" | "reported:false" | "declared:true" | "unknown", ...}
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    source: Mapped[str] = mapped_column(Text, nullable=False)  # discovered | manual
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider_config_id", "name"),
        CheckConstraint("source IN ('discovered', 'manual')", name="source"),
    )


class TaskRoute(Base):
    __tablename__ = "task_route"

    task: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_config_id: Mapped[str] = mapped_column(Text, ForeignKey("provider_config.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[str | None] = mapped_column(Text)  # stored as text to keep exact user value
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(_in("task", TASKS), name="task"),)


class ModelPrice(Base):
    """User-entered prices. PBS ships no prices: unknown stays unknown."""

    __tablename__ = "model_price"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_config_id: Mapped[str] = mapped_column(Text, ForeignKey("provider_config.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    input_per_mtok: Mapped[str] = mapped_column(Text, nullable=False)  # decimal as text
    output_per_mtok: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("provider_config_id", "model_name"),)


class CloudConsent(Base):
    """Per-project permission to send that project's text to a specific cloud provider."""

    __tablename__ = "cloud_consent"

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), primary_key=True)
    provider_config_id: Mapped[str] = mapped_column(Text, ForeignKey("provider_config.id"), primary_key=True)
    granted_at: Mapped[str] = mapped_column(Text, nullable=False)


class Job(Base):
    __tablename__ = "job"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("project.id"), nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(Text)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    provider_config_id: Mapped[str] = mapped_column(Text, ForeignKey("provider_config.id"), nullable=False)
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)  # instruction, mode, selection, base revision
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    estimate_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    progress_done: Mapped[int | None] = mapped_column(Integer)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    run_after: Mapped[str] = mapped_column(Text, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    partial_output: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        CheckConstraint(_in("status", JOB_STATUSES), name="status"),
        CheckConstraint(_in("task", TASKS), name="task"),
        Index("ix_job_status_run_after", "status", "run_after"),
        Index("ix_job_project_created", "project_id", "created_at"),
    )


class JobLog(Base):
    __tablename__ = "job_log"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(Text, ForeignKey("job.id"), nullable=False)
    ts: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_job_log_job_ts", "job_id", "ts"),)


class Proposal(Base):
    """AI output awaiting the author's decision. Only an explicit accept turns it into a revision."""

    __tablename__ = "proposal"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str] = mapped_column(Text, ForeignKey("job.id"), nullable=False, unique=True)
    base_revision_id: Mapped[str | None] = mapped_column(Text)
    base_revision_no: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    selection_start: Mapped[int | None] = mapped_column(Integer)
    selection_end: Mapped[int | None] = mapped_column(Integer)
    original_text: Mapped[str | None] = mapped_column(Text)
    payload_md: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_revision_id: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[str | None] = mapped_column(Text)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "id"),
        ForeignKeyConstraint(["project_id", "job_id"], ["job.project_id", "job.id"], name="fk_proposal_job_project"),
        CheckConstraint(_in("status", PROPOSAL_STATUSES), name="status"),
        CheckConstraint(_in("mode", PROPOSAL_MODES), name="mode"),
        Index("ix_proposal_chapter_status", "chapter_id", "status"),
    )


class UsageRecord(Base):
    """Token usage per provider call. Immutable (DB trigger). Cost is NULL when the price is unknown."""

    __tablename__ = "usage_record"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(Text, ForeignKey("job.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_kind: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reported_by_provider: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_amount: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(Text)
    price_basis: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
