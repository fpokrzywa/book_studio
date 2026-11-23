"""API contracts for the knowledge workspace, evidence ledger, author voice and interviews (Phase 04)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from pbs_core.contracts import SingleLine, WarningOut, _Model

LibraryScope = Literal["project", "shared"]
SourceStatus = Literal["pending", "indexed", "failed"]
ClaimLifecycle = Literal["proposed", "in_text", "discarded"]
ClaimReview = Literal["needs_review", "verified", "disputed"]
ClaimSupportStatus = Literal["supported", "not_located", "unverified"]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[^\r\n,]+$")]
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_YEAR = re.compile(r"^\d{4}[a-z]?$")


class LibraryOut(BaseModel):
    id: str
    name: str
    scope: LibraryScope
    project_id: str | None
    description: str | None
    source_count: int
    linked_project_ids: list[str] = Field(description="Books that opted in (shared libraries only)")
    created_at: str


class LibraryCreate(_Model):
    name: Annotated[SingleLine, StringConstraints(min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None


class LibraryPatch(_Model):
    name: Annotated[SingleLine, StringConstraints(min_length=1, max_length=120)] | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None


class SourceOut(BaseModel):
    id: str
    library_id: str
    library_name: str
    kind: str
    title: str
    title_origin: str = Field(description="file_metadata | file_name | author: where the title came from")
    citation_key: str
    original_name: str
    file_sha256: str
    byte_size: int
    tags: list[str]
    enabled: bool
    status: SourceStatus
    error: str | None
    warnings: list[WarningOut]
    chunk_count: int
    word_count: int
    page_count: int | None
    authors: list[str]
    year: str | None
    publisher: str | None
    url: str | None
    doi: str | None
    created_at: str
    indexed_at: str | None
    removed_at: str | None


class SourcePatch(_Model):
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)] | None = None
    tags: Annotated[list[Tag], Field(max_length=20)] | None = None
    enabled: bool | None = None
    authors: (
        Annotated[list[Annotated[SingleLine, StringConstraints(min_length=1, max_length=120)]], Field(max_length=20)]
        | None
    ) = None
    year: str | None = None
    publisher: Annotated[SingleLine, StringConstraints(max_length=200)] | None = None
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    doi: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None

    @field_validator("year")
    @classmethod
    def _year(cls, v: str | None) -> str | None:
        if v and not _YEAR.match(v.strip()):
            raise ValueError("enter a year such as 2021")
        return v.strip() if v else None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("the address must start with https:// or http://")
        return v or None

    @field_validator("doi")
    @classmethod
    def _doi(cls, v: str | None) -> str | None:
        if v and not _DOI.match(v):
            raise ValueError("a DOI looks like 10.1234/abcd")
        return v or None


class DuplicateOut(BaseModel):
    source_id: str
    title: str
    reason: Literal["same_file", "same_text"]


class SourceImportOut(BaseModel):
    source: SourceOut | None
    duplicate: DuplicateOut | None = None


class SnippetPart(BaseModel):
    text: str
    hit: bool


class SearchHitOut(BaseModel):
    chunk_id: str
    source_id: str
    source_title: str
    citation_key: str
    locator: str
    heading_path: str
    snippet: list[SnippetPart] = Field(description="Plain text segments; hit=true marks matched words")
    reasons: list[str]
    score: float


class SearchOut(BaseModel):
    query: str
    mode: Literal["all", "any"] = Field(description="all = every word matched; any = some words matched")
    hits: list[SearchHitOut]
    searched_sources: int
    semantic: Literal["unavailable"] = "unavailable"
    semantic_note: str


class ChunkOut(BaseModel):
    id: str
    seq: int
    heading_path: str
    locator: str
    text: str


class SourceTextOut(BaseModel):
    source: SourceOut
    chunks: list[ChunkOut]


class BookKnowledgeOut(BaseModel):
    project_library: LibraryOut | None
    linked: list[LibraryOut]
    available_shared: list[LibraryOut]
    usable_source_count: int


class CitationOut(BaseModel):
    """Bibliographic metadata for one cited source: only fields the author entered or the file states."""

    id: str = Field(description="The citation key used in the text, e.g. [@smith2020]")
    title: str
    author: list[str]
    issued: str | None
    publisher: str | None
    URL: str | None
    DOI: str | None
    source_id: str
    cited_in_chapters: int


class SupportOut(BaseModel):
    id: str
    kind: Literal["source", "interview"]
    source_id: str | None
    source_title: str | None
    source_removed: bool
    chunk_id: str | None
    interview_answer_id: str | None
    citation_key: str | None
    locator: str | None
    quote: str
    located: bool


class ClaimOut(BaseModel):
    id: str
    project_id: str
    chapter_id: str | None
    chapter_title: str | None
    proposal_id: str | None
    text: str
    origin: Literal["ai_generated", "author"]
    lifecycle: ClaimLifecycle
    review_state: ClaimReview
    support_status: ClaimSupportStatus
    note: str | None
    supports: list[SupportOut]
    created_at: str
    updated_at: str


class ClaimCreate(_Model):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
    chapter_id: str | None = None
    chunk_ids: Annotated[list[str], Field(max_length=10)] = Field(default_factory=list)
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ClaimPatch(_Model):
    review_state: ClaimReview | None = None
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None
    add_chunk_ids: Annotated[list[str], Field(max_length=10)] = Field(default_factory=list)
    remove_support_ids: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)


class VoiceSampleOut(BaseModel):
    id: str
    title: str
    word_count: int
    rights_basis: Literal["own_writing", "licensed"]
    excerpt: str
    created_at: str


class CorrectionIn(_Model):
    before: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    after: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class CorrectionOut(BaseModel):
    before: str
    after: str
    note: str | None


class AuthorProfileOut(BaseModel):
    id: str
    name: str
    kind: Literal["author", "pen_name"]
    style_guide_md: str
    guide_edited: bool
    metrics: dict[str, object]
    labels: dict[str, str]
    examples: list[dict[str, str]]
    corrections: list[CorrectionOut]
    samples: list[VoiceSampleOut]
    analysis_note: str | None
    analyzed_at: str | None
    created_at: str
    pen_name: str | None = None
    voice_rules: list[dict[str, str]] = Field(default_factory=list, description="Editable do/avoid rules")


class AuthorProfileCreate(_Model):
    name: Annotated[SingleLine, StringConstraints(min_length=1, max_length=120)]
    kind: Literal["author", "pen_name"] = "author"


class AuthorProfilePatch(_Model):
    name: Annotated[SingleLine, StringConstraints(min_length=1, max_length=120)] | None = None
    style_guide_md: Annotated[str, StringConstraints(max_length=20_000)] | None = None
    corrections: Annotated[list[CorrectionIn], Field(max_length=50)] | None = None


class VoiceSampleIn(_Model):
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=400_000)]
    rights_confirmed: bool = Field(description="Must be true: this is my own writing or I have the rights to use it")
    rights_basis: Literal["own_writing", "licensed"] = "own_writing"


class InterviewAnswerOut(BaseModel):
    id: str
    answer_text: str
    answered_at: str
    supersedes_id: str | None


class InterviewQuestionOut(BaseModel):
    id: str
    seq: int
    prompt: str
    origin: Literal["bank", "author"]
    answer: InterviewAnswerOut | None
    history: list[InterviewAnswerOut]


class InterviewOut(BaseModel):
    session_id: str
    project_id: str
    title: str
    questions: list[InterviewQuestionOut]
    answered: int


class QuestionCreate(_Model):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class AnswerIn(_Model):
    answer_text: Annotated[str, StringConstraints(max_length=50_000)]
