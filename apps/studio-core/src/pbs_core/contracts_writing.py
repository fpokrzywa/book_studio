"""API contracts for the writing pipeline, continuity memory, quality reviews and originality (Phase 06)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from pbs_core.contracts import SingleLine, _Model

PlanStatus = Literal["waiting", "running", "paused", "awaiting_review", "ready", "cancelled"]
SectionState = Literal["pending", "queued", "running", "done", "failed", "cancelled"]
FactKind = Literal["character", "location", "relationship", "event", "thread", "term", "other"]
FactStatus = Literal["proposed", "confirmed", "rejected", "resolved"]
FindingState = Literal["open", "needs_source", "will_fix", "dismissed", "fixed"]
Short = Annotated[SingleLine, StringConstraints(max_length=200)]
Text2k = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class SectionOut(BaseModel):
    id: str
    ordinal: int
    title: str
    goal: str
    target_words: int | None
    state: SectionState
    output_md: str | None
    summary: str | None
    edited: bool
    reviewed: bool
    attempts: int
    job_ids: list[str]
    job_id: str | None
    error: str | None = Field(None, description="Why the latest attempt failed")
    context: dict[str, Any] = Field(description="Token budget report: what this section's prompt included")
    provenance: dict[str, Any]


class PlanOut(BaseModel):
    id: str
    chapter_id: str
    chapter_title: str
    run_id: str | None
    status: PlanStatus
    review_gate: Literal["none", "each_section"]
    provider_label: str
    provider_kind: str
    model_name: str
    token_budget: int
    max_output_tokens: int
    base_revision_no: int
    proposal_id: str | None
    proposal_status: str | None
    note: str | None
    sections: list[SectionOut]
    next_step: str = Field(description="What happens next, in plain words")
    created_at: str
    updated_at: str
    finished_at: str | None


class SectionApproveIn(_Model):
    edited_md: Annotated[str, StringConstraints(max_length=200_000)] | None = Field(
        None, description="The author's corrected text for this section (optional)"
    )


class JobHistoryOut(BaseModel):
    job_id: str
    section: str
    attempt_no: int
    status: str
    stage: str
    task: str
    provider_kind: str
    model_name: str
    template: str
    created_at: str
    finished_at: str | None
    error_message: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost: str | None
    currency: str | None
    logs: list[dict[str, str]]


class FactIn(_Model):
    kind: FactKind
    name: Annotated[SingleLine, StringConstraints(min_length=1, max_length=200)]
    attribute: Short = ""
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    story_time: Annotated[SingleLine, StringConstraints(max_length=100)] | None = None
    chapter_id: str | None = None


class FactPatch(_Model):
    status: FactStatus | None = None
    name: Annotated[SingleLine, StringConstraints(min_length=1, max_length=200)] | None = None
    attribute: Short | None = None
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    story_time: Annotated[SingleLine, StringConstraints(max_length=100)] | None = None


class FactOut(BaseModel):
    id: str
    kind: FactKind
    name: str
    attribute: str
    value: str
    story_time: str | None
    chapter_id: str | None
    chapter_title: str | None
    origin: Literal["author", "ai_extracted"]
    status: FactStatus
    updated_at: str


class SummaryIn(_Model):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class SummaryOut(BaseModel):
    chapter_id: str
    chapter_title: str
    text: str | None
    origin: Literal["ai_draft", "author"] | None
    basis: str = Field(description="Where the summary comes from (a draft, an accepted draft, the author)")
    updated_at: str | None


class QualityRunIn(_Model):
    chapter_id: str | None = Field(None, description="One chapter; omit for the whole book")
    checks: Annotated[list[str], Field(max_length=30)] = Field(default_factory=list, description="Empty: all")


class QualityFindingOut(BaseModel):
    id: str
    chapter_id: str | None
    chapter_title: str | None
    check: str
    check_label: str
    origin: Literal["rule", "ai_review"]
    severity: Literal["info", "warning"]
    message: str
    excerpt: str | None
    details: dict[str, Any]
    revision_no: int | None
    present: bool
    state: FindingState
    note: str | None
    updated_at: str


class QualityRunOut(BaseModel):
    checks_run: list[str]
    checks_skipped: dict[str, str]
    new: int
    seen: int
    findings: list[QualityFindingOut]
    disclaimer: str


class FindingPatchIn(_Model):
    state: FindingState
    note: Text2k | None = None


class AiReviewIn(_Model):
    chapter_id: str
    provider_id: str | None = None
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    instruction: Text2k = ""
    client_request_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]


class WritingSettingsOut(BaseModel):
    code_check_authorized: bool
    code_check_note: str
    similarity_provider: str


class WritingSettingsIn(_Model):
    code_check_authorized: bool


class OriginalityOut(BaseModel):
    scope: list[str]
    not_covered: list[str]
    external_provider: str
    statement: str
    chapters_checked: int
    compared_with: dict[str, int]
    within_book: list[dict[str, Any]]
    overlaps: list[dict[str, Any]]
