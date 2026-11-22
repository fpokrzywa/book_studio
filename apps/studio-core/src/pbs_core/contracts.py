"""Pydantic API contracts (source of truth for the generated TypeScript client)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ProjectType = Literal["nonfiction", "technical", "course", "workbook", "memoir", "fiction", "serial"]
PublicationFormat = Literal["ebook", "paperback", "hardcover"]
ProjectStatus = Literal["active", "archived"]
ChapterStatus = Literal["planned", "draft", "in_review", "approved"]
ChapterKind = Literal["part", "chapter", "section", "front_matter", "back_matter"]
RevisionOrigin = Literal["human", "ai_generated", "ai_assisted", "imported", "restored", "system_migration"]
ProjectSort = Literal["title", "project_type", "language", "audience", "target_word_count", "updated_at", "created_at"]

_BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
MAX_SOURCE_CHARS = 2_000_000

SingleLine = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[^\r\n]*$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_language(value: str) -> str:
    if not _BCP47.match(value):
        raise ValueError("language must be a BCP-47 tag such as 'en' or 'en-GB'")
    return value


def _check_formats(value: list[PublicationFormat]) -> list[PublicationFormat]:
    if len(set(value)) != len(value):
        raise ValueError("publication formats must be unique")
    order = ["ebook", "paperback", "hardcover"]
    return sorted(value, key=order.index)


def _default_formats() -> list[PublicationFormat]:
    return ["ebook"]


class ProjectCreate(_Model):
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)]
    subtitle: Annotated[SingleLine, StringConstraints(max_length=300)] | None = None
    author_name: Annotated[SingleLine, StringConstraints(max_length=200)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    project_type: ProjectType
    language: str = "en"
    audience: Annotated[SingleLine, StringConstraints(max_length=500)] | None = None
    target_word_count: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    publication_formats: list[PublicationFormat] = Field(default_factory=_default_formats)

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _check_language(v)

    @field_validator("publication_formats")
    @classmethod
    def _fmts(cls, v: list[PublicationFormat]) -> list[PublicationFormat]:
        return _check_formats(v)


class ProjectPatch(_Model):
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)] | None = None
    subtitle: Annotated[SingleLine, StringConstraints(max_length=300)] | None = None
    author_name: Annotated[SingleLine, StringConstraints(max_length=200)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    project_type: ProjectType | None = None
    language: str | None = None
    audience: Annotated[SingleLine, StringConstraints(max_length=500)] | None = None
    target_word_count: Annotated[int, Field(ge=0, le=5_000_000)] | None = None
    publication_formats: list[PublicationFormat] | None = None

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        return None if v is None else _check_language(v)

    @field_validator("publication_formats")
    @classmethod
    def _fmts(cls, v: list[PublicationFormat] | None) -> list[PublicationFormat] | None:
        return None if v is None else _check_formats(v)


class ProjectOut(BaseModel):
    id: str
    title: str
    subtitle: str | None
    author_name: str | None
    description: str | None
    project_type: ProjectType
    language: str
    audience: str | None
    target_word_count: int | None
    publication_formats: list[PublicationFormat]
    status: ProjectStatus
    is_demo: bool
    duplicated_from_id: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    chapter_count: int
    word_count: int


class ProjectList(BaseModel):
    items: list[ProjectOut]
    total: int


class ChapterCreate(_Model):
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)]
    kind: ChapterKind = "chapter"
    parent_id: str | None = None


class ChapterPatch(_Model):
    title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)] | None = None
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)] | None = None
    status: ChapterStatus | None = None
    kind: ChapterKind | None = None
    target_word_count: Annotated[int, Field(ge=0, le=5_000_000)] | None = None


class ChapterMove(_Model):
    parent_id: str | None = Field(None, description="New parent (null = top level)")
    index: Annotated[int, Field(ge=0, description="Position among the new parent's children")]


class ChapterOut(BaseModel):
    id: str
    project_id: str
    parent_id: str | None
    depth: int
    kind: ChapterKind
    position: str
    title: str
    slug: str
    status: ChapterStatus
    locked: bool
    target_word_count: int | None
    head_revision_id: str | None
    head_revision_no: int
    word_count: int
    created_at: str
    updated_at: str


class DraftOut(BaseModel):
    source_md: str
    base_revision_no: int
    updated_at: str


class ChapterContentOut(BaseModel):
    chapter_id: str
    revision_id: str | None
    revision_no: int
    source_md: str
    word_count: int
    saved_at: str | None
    draft: DraftOut | None = Field(None, description="Autosaved text not yet saved as a revision")


class DraftIn(_Model):
    source_md: Annotated[str, StringConstraints(max_length=MAX_SOURCE_CHARS)]
    base_revision_no: Annotated[int, Field(ge=0)]


class ChapterSaveIn(_Model):
    source_md: Annotated[str, StringConstraints(max_length=MAX_SOURCE_CHARS)]
    expected_head_no: Annotated[int, Field(ge=0)]
    label: Annotated[SingleLine, StringConstraints(max_length=120)] | None = None
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ChapterSaveOut(BaseModel):
    created: bool = Field(description="False when the content was identical to the current head")
    content: ChapterContentOut


class RevisionMetaOut(BaseModel):
    id: str
    revision_no: int
    origin: RevisionOrigin
    word_count: int
    content_hash: str
    parser_version: str
    label: str | None
    note: str | None
    restored_from_revision_no: int | None
    is_head: bool
    created_at: str


class RevisionOut(RevisionMetaOut):
    source_md: str


class RevisionTagIn(_Model):
    label: Annotated[SingleLine, StringConstraints(max_length=120)] | None = None
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class RestoreIn(_Model):
    expected_head_no: Annotated[int, Field(ge=0)]
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class DiffSegment(BaseModel):
    text: str
    changed: bool


class DiffRow(BaseModel):
    kind: Literal["equal", "replace", "insert", "delete"]
    left_no: int | None
    right_no: int | None
    left: list[DiffSegment]
    right: list[DiffSegment]


class CompareOut(BaseModel):
    from_revision_no: int
    to_revision_no: int
    rows: list[DiffRow]
    added_lines: int
    removed_lines: int
    changed_lines: int


class WarningOut(BaseModel):
    code: str
    message: str
    line: int | None = None


class PreviewIn(_Model):
    source_md: Annotated[str, StringConstraints(max_length=MAX_SOURCE_CHARS)]


class PreviewOut(BaseModel):
    html: str = Field(description="Sanitized HTML rendered by Core")
    word_count: int
    warnings: list[WarningOut]
    citation_keys: list[str]
    block_count: int


class AssetOut(BaseModel):
    id: str
    short_hash: str
    mime: str
    byte_size: int
    width_px: int | None
    height_px: int | None
    original_name: str | None
    reference: str = Field(description="Use in text as the image address, e.g. ![Caption](asset:...)")
    url: str
    created_at: str


class ExportCreate(_Model):
    format: Literal["markdown", "html"] = "markdown"


class ExportOut(BaseModel):
    id: str
    project_id: str
    format: Literal["markdown", "markdown_zip", "html"]
    status: Literal["completed", "failed"]
    file_name: str | None
    sha256: str | None
    byte_size: int | None
    chapter_count: int
    warnings: list[str]
    started_at: str
    finished_at: str | None
    download_url: str | None


class ActivityOut(BaseModel):
    id: str
    project_id: str | None
    project_title: str | None
    kind: str
    summary: str
    ref_type: str | None
    ref_id: str | None
    created_at: str


class SystemInfoOut(BaseModel):
    app_version: str
    schema_revision: str
    workspace_path: str
    privacy_mode: Literal["local_only", "cloud_allowed"]
    env: Literal["dev", "test", "prod"]


class CapabilityOut(BaseModel):
    id: str
    label: str
    purpose: str
    needed_from_phase: str
    found: bool
    detail: str


class Problem(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None


ImportFormat = Literal["markdown", "text", "html", "docx", "pdf"]


class ImportChapterOut(BaseModel):
    index: int
    title: str
    word_count: int
    block_count: int
    image_count: int
    preview_source: str = Field(description="Beginning of the BookMD text that will be created")
    duplicate_of_chapter_id: str | None = None
    duplicate_reason: str | None = None


class ImportPreviewOut(BaseModel):
    id: str
    status: Literal["preview_ready", "committed", "failed", "cancelled"]
    importer: ImportFormat
    original_name: str
    sha256: str
    byte_size: int
    lossy: bool
    target_project_id: str | None
    project_id: str | None
    suggested_title: str
    chapters: list[ImportChapterOut]
    warnings: list[WarningOut]
    previously_imported_at: str | None
    created_at: str


class ImportCommitIn(_Model):
    mode: Literal["new_project", "existing_project"]
    project_id: str | None = None
    project_title: Annotated[SingleLine, StringConstraints(min_length=1, max_length=300)] | None = None
    project_type: ProjectType = "nonfiction"
    include: list[Annotated[int, Field(ge=0)]] | None = Field(None, description="Chapter indexes to import")


class ImportCommitOut(BaseModel):
    project_id: str
    chapter_ids: list[str]
    import_run: ImportPreviewOut


class BookOut(BaseModel):
    project: ProjectOut
    chapters: list[ChapterOut] = Field(description="Canonical reading order (depth-first)")


class BackupOut(BaseModel):
    id: str
    project_id: str
    file_name: str
    byte_size: int
    manifest_sha256: str
    schema_revision: str
    created_at: str
    download_url: str


class RestoreOut(BaseModel):
    project: ProjectOut
    restored_from_project_id: str
    chapters: int
    revisions: int
    assets: int
    warnings: list[WarningOut]
