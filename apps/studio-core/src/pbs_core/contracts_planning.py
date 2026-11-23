"""API contracts for planning: book brief, research, outline versions and generation runs (Phase 05)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from pbs_core.contracts import ProjectCreate, ProjectOut, SingleLine, _Model

BookKind = Literal["fiction", "nonfiction", "manual", "workbook", "memoir"]
ApprovalPreference = Literal["review_each_chapter", "review_outline_then_batch"]
FindingKind = Literal["measured", "heuristic", "note", "competitor", "keyword", "topic", "query"]
FindingOrigin = Literal["author", "ai_brainstorm", "provider"]
OutlineStatus = Literal["draft", "proposed", "approved", "superseded", "rejected"]
RunMode = Literal["one_chapter", "entire_book"]
Text2k = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Short = Annotated[SingleLine, StringConstraints(max_length=300)]
_DECIMAL = re.compile(r"^\d{1,7}(\.\d{1,4})?$")


class Assumption(_Model):
    kind: Literal["factual", "creative"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class BriefIn(_Model):
    kind: BookKind
    genre: Short | None = None
    purpose: Text2k | None = None
    promise: Text2k | None = Field(None, description="The main promise to the reader")
    tone: Short | None = None
    author_profile_id: str | None = None
    desired_chapters: Annotated[int, Field(ge=1, le=200)] | None = None
    approval_preference: ApprovalPreference = "review_each_chapter"
    budget_cap: str | None = Field(None, description="Hard spending cap per generation run, e.g. '5.00'")
    budget_currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    max_chapters_per_run: Annotated[int, Field(ge=1, le=200)] = 10
    words_per_hour: Annotated[int, Field(ge=50, le=10_000)] = 500
    target_reader: Text2k | None = None
    exclusions: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]],
        Field(max_length=30),
    ] = Field(default_factory=list)
    value_proposition: Text2k | None = None
    arc_md: Annotated[str, StringConstraints(max_length=10_000)] | None = Field(
        None, description="Teaching arc (nonfiction) or plot arc (fiction)"
    )
    assumptions: Annotated[list[Assumption], Field(max_length=50)] = Field(default_factory=list)

    @field_validator("budget_cap")
    @classmethod
    def _cap(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        v = v.strip()
        if not _DECIMAL.match(v):
            raise ValueError("enter an amount such as 5 or 12.50")
        try:
            Decimal(v)
        except InvalidOperation as exc:
            raise ValueError("enter an amount") from exc
        return v


class BriefOut(BaseModel):
    project_id: str
    kind: BookKind
    genre: str | None
    purpose: str | None
    promise: str | None
    tone: str | None
    author_profile_id: str | None
    desired_chapters: int | None
    approval_preference: ApprovalPreference
    budget_cap: str | None
    budget_currency: str | None
    max_chapters_per_run: int
    words_per_hour: int
    target_reader: str | None
    exclusions: list[str]
    value_proposition: str | None
    arc_md: str | None
    arc_label: str = Field(description="'Teaching arc' or 'Plot arc'")
    assumptions: list[Assumption]
    status: Literal["draft", "approved"]
    version: int
    approved_at: str | None
    updated_at: str


class NewBookIn(_Model):
    """The New Book wizard: the project plus its brief and the sources it starts with."""

    project: ProjectCreate
    brief: BriefIn
    shared_library_ids: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)


class NewBookOut(BaseModel):
    project: ProjectOut
    brief: BriefOut


class FindingIn(_Model):
    kind: FindingKind
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    source_title: Short | None = None
    source_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    source_date: Annotated[str, StringConstraints(pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")] | None = None
    meta: dict[str, str] = Field(
        default_factory=dict, description="Competitor notes: title, author, publisher, year, format, notes"
    )

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("the address must start with https:// or http://")
        return v or None

    @field_validator("meta")
    @classmethod
    def _meta(cls, v: dict[str, str]) -> dict[str, str]:
        allowed = {"title", "author", "publisher", "year", "format", "notes"}
        if set(v) - allowed:
            raise ValueError(f"meta may only contain {sorted(allowed)}")
        return {k: str(x)[:1000] for k, x in v.items()}


class FindingPatch(_Model):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)] | None = None
    kind: FindingKind | None = None
    source_title: Short | None = None
    source_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    source_date: Annotated[str, StringConstraints(pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")] | None = None
    selected: bool | None = None
    archived: bool | None = None


class FindingOut(BaseModel):
    id: str
    kind: FindingKind
    origin: FindingOrigin
    evidence: Literal["measured", "heuristic"] = Field(
        description="measured = a named source supplied it; everything else is heuristic"
    )
    text: str
    provider: str | None
    source_title: str | None
    source_url: str | None
    source_date: str | None
    retrieved_at: str | None
    meta: dict[str, Any]
    metrics: dict[str, Any] = Field(description="Only ever filled by a provider that supplies the figure")
    flags: list[str]
    selected: bool
    archived: bool
    created_at: str
    updated_at: str


class ResearchProviderOut(BaseModel):
    kind: Literal["openlibrary", "mock"]
    label: str
    enabled: bool
    sends: str
    available: bool
    unavailable_reason: str | None


class ResearchProvidersIn(_Model):
    openlibrary: bool = False
    mock: bool = False


class ResearchSearchIn(_Model):
    provider: Literal["openlibrary", "mock"]
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]


class ResearchHitOut(BaseModel):
    index: int
    title: str
    url: str | None
    authors: list[str]
    year: str | None
    publisher: str | None
    subjects: list[str]
    source_label: str


class ResearchSearchOut(BaseModel):
    query_id: str
    provider: str
    hits: list[ResearchHitOut]
    note: str


class SaveHitIn(_Model):
    query_id: str
    index: Annotated[int, Field(ge=0, le=50)]
    kind: Literal["competitor", "note"] = "competitor"


class ResearchIdeasIn(_Model):
    what: Literal["topics", "queries", "keywords"]
    instruction: Annotated[str, StringConstraints(max_length=2000)] = ""
    provider_id: str | None = None
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    client_request_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]


class OutlineOut(BaseModel):
    id: str
    version_no: int
    status: OutlineStatus
    origin: Literal["author", "ai_generated"]
    nodes: list[dict[str, Any]]
    totals: dict[str, Any]
    based_on_id: str | None
    brief_version: int | None
    research_ids: list[str]
    job_id: str | None
    provenance: dict[str, Any]
    note: str | None
    approved_at: str | None
    applied_at: str | None
    apply_report: dict[str, Any] | None
    created_at: str
    updated_at: str


class OutlineDraftIn(_Model):
    nodes: Annotated[list[dict[str, Any]], Field(max_length=500)]
    note: Annotated[str, StringConstraints(max_length=1000)] | None = None
    based_on_id: str | None = None


class OutlineGenerateIn(_Model):
    instruction: Annotated[str, StringConstraints(max_length=2000)] = ""
    research_ids: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)
    provider_id: str | None = None
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    max_output_tokens: Annotated[int, Field(ge=256, le=200_000)] | None = None
    client_request_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]


class ApplyOut(BaseModel):
    outline: OutlineOut
    report: dict[str, Any]


class PlanRequestIn(_Model):
    mode: RunMode
    chapter_ids: Annotated[list[str], Field(max_length=200)] = Field(
        default_factory=list, description="one_chapter: exactly one"
    )
    provider_id: str | None = None
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    use_sources: bool = True
    use_interview: bool = False
    client_request_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")] = "estimate-only"


class PlanChapterOut(BaseModel):
    chapter_id: str
    title: str
    eligible: bool
    reason: str | None
    target_words: int | None
    input_tokens: int
    max_output_tokens: int


class PlanEstimateOut(BaseModel):
    mode: RunMode
    provider_label: str
    model_name: str
    provider_local: bool
    chapters: list[PlanChapterOut]
    eligible_count: int
    chapter_limit: int
    is_estimate: bool = True
    cost_upper_bound: str | None
    currency: str | None
    cost_note: str
    minutes_estimate: float | None
    time_note: str
    budget_cap: str | None
    budget_currency: str | None
    blocked_reason: str | None


class RunOut(BaseModel):
    id: str
    mode: RunMode
    status: Literal["running", "done", "stopped"]
    job_ids: list[str]
    skipped: list[dict[str, str]]
    estimate: dict[str, Any]
    budget_cap: str | None
    currency: str | None
    spent: str
    unknown_cost_calls: int
    stop_reason: str | None
    created_at: str
    finished_at: str | None
