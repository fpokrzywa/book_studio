"""API contracts for AI settings, jobs, proposals and usage (Phase 03)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SecretStr, StringConstraints, field_validator

from pbs_core.contracts import ChapterSaveOut, SingleLine, _Model

ProviderKind = Literal["mock", "ollama", "openai", "anthropic", "gemini", "groq", "xai"]
AiTask = Literal["brainstorm", "research", "outline", "draft", "revise", "summarize", "translate"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
ProposalStatus = Literal["pending", "accepted", "rejected", "stale"]
ProposalMode = Literal["append", "replace_selection", "insert_at", "note"]
EditorAction = Literal[
    "rewrite",
    "expand",
    "shorten",
    "tone",
    "clarity",
    "repetition",
    "transitions",
    "explain",
    "exercises",
    "quiz",
    "glossary",
]
PrivacyMode = Literal["local_only", "cloud_allowed"]
KeyStatus = Literal["stored", "env", "missing", "not_needed"]
DeclaredCapability = Literal["unknown", "declared:true", "declared:false"]

MAX_INSTRUCTION_CHARS = 4000
_DECIMAL = re.compile(r"^\d{1,6}(\.\d{1,6})?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class SecretStoreOut(BaseModel):
    backend: str
    secure: bool
    writable: bool
    warning: str | None


class AiStatusOut(BaseModel):
    privacy_mode: PrivacyMode
    external_requests: dict[str, int] = Field(description="Requests sent to internet hosts since Core started")
    active_cloud_calls: dict[str, int]
    queued_jobs: int
    running_jobs: int
    pending_proposals: int
    secret_store: SecretStoreOut


class PrivacyIn(_Model):
    mode: PrivacyMode
    confirm: bool = Field(False, description="Must be true to allow cloud providers")


class ProviderKindOut(BaseModel):
    kind: ProviderKind
    label: str
    local: bool
    needs_key: bool
    default_url: str
    url_editable: bool
    note: str


class HealthOut(BaseModel):
    ok: bool
    message: str
    code: str | None = None
    version: str | None = None
    latency_ms: int | None = None
    checked_at: str


class ModelOut(BaseModel):
    name: str
    display_name: str | None
    context_tokens: int | None
    max_output_tokens: int | None
    capabilities: dict[str, str] = Field(
        description="reported:* = said by the provider API; documented:* = provider docs; declared:* = by you; unknown"
    )
    source: Literal["discovered", "manual"]
    updated_at: str


class ProviderOut(BaseModel):
    id: str
    kind: ProviderKind
    label: str
    base_url: str
    local: bool
    enabled: bool
    key_status: KeyStatus
    health: HealthOut | None
    models: list[ModelOut]
    created_at: str


class ProviderCreate(_Model):
    kind: ProviderKind
    label: Annotated[SingleLine, StringConstraints(max_length=80)] | None = None
    base_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = Field(
        None, description="Only Ollama's address can be changed, and it must be on this computer"
    )


class ProviderPatch(_Model):
    label: Annotated[SingleLine, StringConstraints(min_length=1, max_length=80)] | None = None
    enabled: bool | None = None
    base_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class KeyIn(_Model):
    api_key: SecretStr = Field(description="Stored in the OS credential store; never returned or logged")

    @field_validator("api_key")
    @classmethod
    def _shape(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value().strip()
        if not (8 <= len(raw) <= 400) or any(c.isspace() for c in raw):
            raise ValueError("an API key is 8-400 characters with no spaces")
        return SecretStr(raw)


class ManualModelIn(_Model):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\s]+$")]
    context_tokens: Annotated[int, Field(ge=1, le=100_000_000)] | None = None
    max_output_tokens: Annotated[int, Field(ge=1, le=10_000_000)] | None = None
    structured_output: DeclaredCapability = "unknown"


class RouteIn(_Model):
    provider_id: str
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    max_output_tokens: Annotated[int, Field(ge=16, le=200_000)] | None = None


class RouteOut(BaseModel):
    task: AiTask
    provider_id: str
    provider_label: str
    provider_local: bool
    model_name: str
    temperature: float | None
    max_output_tokens: int | None
    updated_at: str


class PriceIn(_Model):
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    input_per_mtok: str = Field(description="Price per million input tokens, e.g. '3.00'")
    output_per_mtok: str
    currency: str = "USD"
    source_url: Annotated[str, StringConstraints(max_length=500)] | None = None
    as_of: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]

    @field_validator("input_per_mtok", "output_per_mtok")
    @classmethod
    def _decimal(cls, v: str) -> str:
        v = v.strip()
        if not _DECIMAL.match(v):
            raise ValueError("enter a number such as 3 or 0.25")
        try:
            Decimal(v)
        except InvalidOperation as exc:
            raise ValueError("enter a number") from exc
        return v

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        v = v.strip().upper()
        if not _CURRENCY.match(v):
            raise ValueError("use a 3-letter currency code such as USD")
        return v

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.startswith("https://"):
            raise ValueError("the source must be an https:// address")
        return v or None


class PriceOut(BaseModel):
    id: str
    provider_id: str
    model_name: str
    input_per_mtok: str
    output_per_mtok: str
    currency: str
    source_url: str | None
    as_of: str
    updated_at: str


class ConsentOut(BaseModel):
    project_id: str
    provider_id: str
    provider_label: str
    granted_at: str


class AiRequestIn(_Model):
    chapter_id: str
    task: AiTask
    instruction: Annotated[str, StringConstraints(max_length=MAX_INSTRUCTION_CHARS)] = ""
    mode: ProposalMode = "append"
    selection_start: Annotated[int, Field(ge=0)] | None = None
    selection_end: Annotated[int, Field(ge=0)] | None = None
    base_revision_no: Annotated[int, Field(ge=0)]
    provider_id: str | None = Field(None, description="Overrides the task default when given")
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    max_output_tokens: Annotated[int, Field(ge=16, le=200_000)] | None = None
    target_language: Annotated[SingleLine, StringConstraints(max_length=40)] | None = None
    target_words: Annotated[int, Field(ge=10, le=20_000)] | None = None
    use_sources: bool = Field(True, description="Give the model passages from this book's enabled sources")
    use_interview: bool = Field(False, description="Give the model the author's interview answers")
    voice_profile_id: str | None = Field(None, description="Rewrite in this author's voice (style guide)")
    action: EditorAction | None = Field(
        None, description="An editor action; sets the task, placement and instruction (the instruction adds detail)"
    )
    client_request_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")] = Field(
        description="Random ID chosen by the client; sending the same ID twice returns the same job"
    )


class EstimateOut(BaseModel):
    provider_id: str
    provider_label: str
    provider_local: bool
    model_name: str
    input_tokens: int
    max_output_tokens: int
    is_estimate: bool
    basis: str
    cost_upper_bound: str | None
    currency: str | None
    cost_note: str
    context_clipped: bool
    source_passages: int = Field(0, description="Passages from the book's sources that would be sent")
    interview_answers: int = Field(0, description="Interview answers that would be sent")
    blocked_reason: str | None = Field(None, description="Why this request cannot run now (nothing was sent)")


class JobOut(BaseModel):
    id: str
    project_id: str
    project_title: str | None
    chapter_id: str | None
    chapter_title: str | None
    task: AiTask
    provider_id: str
    provider_kind: ProviderKind
    provider_label: str | None
    provider_local: bool
    model_name: str
    status: JobStatus
    stage: str = Field(
        description="queued, preparing, calling_model, receiving, waiting_to_retry, ready_for_review, ..."
    )
    received_chars: int | None = Field(description="Characters received so far (no percentage is known)")
    attempt: int
    max_attempts: int
    run_after: str
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    partial_output: str | None
    proposal_id: str | None
    estimate: dict[str, Any]
    created_at: str
    started_at: str | None
    finished_at: str | None


class JobLogOut(BaseModel):
    ts: str
    level: str
    message: str


class ProposalOut(BaseModel):
    id: str
    job_id: str
    project_id: str
    chapter_id: str | None
    mode: ProposalMode
    status: ProposalStatus
    base_revision_no: int | None
    current_head_no: int | None
    applicable: bool = Field(description="False when the chapter changed so the suggestion no longer fits")
    not_applicable_reason: str | None
    selection_start: int | None
    selection_end: int | None
    original_text: str | None
    payload_md: str
    accepted_revision_no: int | None
    provenance: dict[str, Any]
    created_at: str
    decided_at: str | None
    diff: list[DiffSegment] | None = Field(None, description="Word-level changes for a replacement")


class DiffSegment(BaseModel):
    op: Literal["equal", "delete", "insert"]
    text: str


class AcceptIn(_Model):
    expected_head_no: Annotated[int, Field(ge=0)]
    edited_md: Annotated[str, StringConstraints(max_length=200_000)] | None = Field(
        None, description="Your edited version of the suggestion; the revision is then marked ai_assisted"
    )


class AcceptOut(BaseModel):
    proposal: ProposalOut
    save: ChapterSaveOut


class UsageRowOut(BaseModel):
    id: str
    job_id: str
    project_id: str
    project_title: str | None
    provider_kind: str
    model_name: str
    input_tokens: int | None
    output_tokens: int | None
    reported_by_provider: bool
    cost_amount: str | None
    currency: str | None
    price_basis: str | None
    attempt: int
    created_at: str


class UsageTotalOut(BaseModel):
    currency: str | None
    amount: str | None
    calls: int
    unknown_cost_calls: int


class UsageOut(BaseModel):
    rows: list[UsageRowOut]
    totals: list[UsageTotalOut]
