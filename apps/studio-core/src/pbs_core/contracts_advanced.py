"""API contracts for Phase 08: series canon and continuity, pen names, translation, narration, recordings."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from pbs_core.contracts import SingleLine, _Model

CanonKind = Literal["character", "location", "thread", "event", "term", "other"]
CanonStatus = Literal["canon", "suggested", "rejected"]
Name = Annotated[SingleLine, StringConstraints(min_length=1, max_length=200)]
Text2k = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


# ---------- series ----------


class SeriesIn(_Model):
    title: Name
    description: Text2k = ""


class SeriesBookIn(_Model):
    project_id: str
    position: Annotated[int, Field(ge=1, le=999)] | None = None


class SeriesBookOut(BaseModel):
    project_id: str
    title: str
    position: int
    language: str


class SeriesOut(BaseModel):
    id: str
    title: str
    description: str
    books: list[SeriesBookOut]
    counts: dict[str, int]
    updated_at: str


class EntityIn(_Model):
    kind: CanonKind
    name: Name
    aliases: Annotated[list[Name], Field(max_length=20)] = Field(default_factory=list)
    summary: Text2k = ""


class EntityPatch(_Model):
    name: Name | None = None
    aliases: Annotated[list[Name], Field(max_length=20)] | None = None
    summary: Text2k | None = None
    status: CanonStatus | None = None


class CanonFactIn(_Model):
    entity_id: str
    attribute: Annotated[SingleLine, StringConstraints(min_length=1, max_length=100)]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    story_time: Annotated[SingleLine, StringConstraints(max_length=100)] | None = None
    book_project_id: str | None = None


class CanonFactPatch(_Model):
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    story_time: Annotated[SingleLine, StringConstraints(max_length=100)] | None = None
    status: CanonStatus | None = None


class RelationshipIn(_Model):
    from_entity_id: str
    to_entity_id: str
    label: Annotated[SingleLine, StringConstraints(min_length=1, max_length=100)]


class RelationshipPatch(_Model):
    label: Annotated[SingleLine, StringConstraints(min_length=1, max_length=100)] | None = None
    status: CanonStatus | None = None


class CanonFactOut(BaseModel):
    id: str
    entity_id: str
    attribute: str
    value: str
    story_time: str | None
    book_project_id: str | None
    book_title: str | None
    status: CanonStatus
    origin: str
    provenance: dict[str, Any]
    superseded_by: str | None
    updated_at: str


class EntityOut(BaseModel):
    id: str
    kind: CanonKind
    name: str
    aliases: list[str]
    summary: str
    status: CanonStatus
    origin: str
    provenance: dict[str, Any]
    facts: list[CanonFactOut]
    updated_at: str


class RelationshipOut(BaseModel):
    id: str
    from_entity_id: str
    to_entity_id: str
    label: str
    status: CanonStatus
    origin: str
    provenance: dict[str, Any]


class CanonOut(BaseModel):
    entities: list[EntityOut]
    relationships: list[RelationshipOut]
    chronology: list[dict[str, Any]]
    chronology_warnings: list[dict[str, str]]


class ImportNotesOut(BaseModel):
    entities_added: int
    facts_added: int
    skipped_existing: int


class IssueOut(BaseModel):
    id: str
    project_id: str
    book_title: str
    chapter_id: str
    chapter_title: str
    revision_no: int
    rule: str
    message: str
    excerpt: str
    start: int
    end: int
    found_value: str | None
    entity_id: str | None
    fact_id: str | None
    relationship_id: str | None
    present: bool
    state: Literal["open", "keep_canon", "canon_updated", "intended"]
    resolution_note: str | None
    link: str = Field(description="Opens the chapter with the passage selected")
    updated_at: str


class ReviewIn(_Model):
    project_id: str | None = Field(None, description="One book of the series; omit for every book")
    chapter_id: str | None = None


class ReviewOut(BaseModel):
    checked_chapters: int
    new: int
    issues: list[IssueOut]
    note: str


class ResolveIn(_Model):
    action: Literal["keep_canon", "update_canon", "intended", "reopen"]
    note: Text2k | None = None


# ---------- pen names and voice ----------


class VoiceRule(_Model):
    kind: Literal["do", "avoid"]
    rule: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class PenNameIn(_Model):
    pen_name: Annotated[SingleLine, StringConstraints(max_length=200)] | None = None
    voice_rules: Annotated[list[VoiceRule], Field(max_length=50)] = Field(default_factory=list)


class ProjectVoiceIn(_Model):
    author_profile_id: str | None


class ProjectVoiceOut(BaseModel):
    project_id: str
    author_profile_id: str | None
    profile_name: str | None
    pen_name: str | None
    voice_rules: list[dict[str, str]]
    has_style_guide: bool
    used_for: str


# ---------- translation ----------


class EditionIn(_Model):
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")]
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)] | None = None
    term_map: dict[
        Annotated[str, StringConstraints(max_length=100)], Annotated[str, StringConstraints(max_length=100)]
    ] = Field(default_factory=dict, description="Source term -> required translation")


class EditionOut(BaseModel):
    id: str
    source_project_id: str
    target_project_id: str
    target_title: str
    language: str
    term_map: dict[str, str]
    chapters: list[dict[str, Any]]
    created_at: str


class TranslateIn(_Model):
    source_chapter_id: str
    source_revision_no: Annotated[int, Field(ge=1)]
    provider_id: str | None = None
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    client_request_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]


class ChapterLinksOut(BaseModel):
    chapter_id: str
    language: str
    translation_of: dict[str, Any] | None
    translations: list[dict[str, Any]]


# ---------- narration ----------


class NarrationSettingsIn(_Model):
    enabled: bool = False
    provider: Literal["", "mock", "espeak", "piper", "openai"] = ""
    voice: Annotated[SingleLine, StringConstraints(max_length=100)] = ""
    model: Annotated[SingleLine, StringConstraints(max_length=100)] = ""
    openai_provider_id: str | None = None
    price_per_million_chars: Annotated[str, StringConstraints(pattern=r"^(\d{1,6}(\.\d{1,6})?)?$")] = ""
    currency: Annotated[str, StringConstraints(pattern=r"^([A-Z]{3})?$")] = ""
    max_chunk_chars: Annotated[int, Field(ge=200, le=4000)] = 1500


class NarrationOut(BaseModel):
    settings: dict[str, Any]
    providers: list[dict[str, Any]]
    chapters: list[dict[str, Any]]
    note: str


class SynthesizeOut(BaseModel):
    chapter_id: str
    done: int
    total: int
    failed: int
    message: str


class AudioExportOut(BaseModel):
    file_name: str
    path: str
    bytes: int
    chapters: list[dict[str, Any]]
    notes: str


# ---------- recordings ----------


class RecordingOut(BaseModel):
    id: str
    title: str
    mime: str
    byte_size: int
    duration_ms: int | None
    rights_note: str
    status: str
    provider: str | None
    model: str | None
    error: str | None
    segments: list[dict[str, Any]]
    created_at: str


class TranscribeIn(_Model):
    provider: Literal["mock", "whisper_cli", "openai"]
    model: Annotated[SingleLine, StringConstraints(max_length=100)] = ""
    openai_provider_id: str | None = None
    language: Annotated[str, StringConstraints(pattern=r"^([a-z]{2})?$")] = ""


class SpeakerIn(_Model):
    speaker: Annotated[SingleLine, StringConstraints(min_length=1, max_length=100)]
    all_with_label: bool = Field(False, description="Rename every segment that has the same speaker label")


class QuoteIn(_Model):
    segment_ids: Annotated[list[str], Field(min_length=1, max_length=50)]
    title: Annotated[SingleLine, StringConstraints(max_length=200)] | None = None


class MediaStatusOut(BaseModel):
    speech: list[dict[str, Any]]
    transcription: list[dict[str, Any]]
    privacy_mode: str
    optional_tools: list[dict[str, str]]


class TermsIn(_Model):
    term_map: dict[
        Annotated[str, StringConstraints(max_length=100)], Annotated[str, StringConstraints(max_length=100)]
    ] = Field(default_factory=dict)


class IssueStateIn(_Model):
    state: Literal["open", "reviewed", "will_fix"]


class QuoteOut(BaseModel):
    source: dict[str, Any]
    recording: RecordingOut
