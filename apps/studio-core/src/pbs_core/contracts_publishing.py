"""API contracts for publishing: profile, builds, covers, previews and the publish package (Phase 07)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from pbs_core.contracts import SingleLine, _Model

TemplateKey = Literal["technical_manual", "nonfiction", "novel", "workbook"]
InkPaper = Literal["bw_white", "bw_cream", "bw_groundwood", "standard_color_white", "premium_color_white"]
BuildFormat = Literal["markdown", "html", "epub", "docx", "pdf"]
AiAnswer = Literal["", "none", "assisted", "generated"]
Short = Annotated[SingleLine, StringConstraints(max_length=300)]
Long = Annotated[str, StringConstraints(max_length=20_000)]


class MatterItemIn(_Model):
    kind: Annotated[str, StringConstraints(max_length=40)]
    enabled: bool = False
    title: Short = ""
    body_md: Long = ""
    include_story_bible_terms: bool = True


class CopyrightIn(_Model):
    holder: Short = ""
    year: Annotated[str, StringConstraints(max_length=20)] = ""
    edition: Short = ""
    isbn: Annotated[str, StringConstraints(max_length=20)] = ""
    notice_md: Annotated[str, StringConstraints(max_length=5000)] = Field(
        "", description="Your own notice; PBS writes none"
    )


class CoverLayerIn(_Model):
    role: Literal["title", "subtitle", "author", "spine", "back_text"]
    text: Annotated[str, StringConstraints(max_length=2000)] = ""
    font: Literal["Libertinus Serif", "New Computer Modern", "DejaVu Sans Mono"] = "Libertinus Serif"
    size_pt: Annotated[float, Field(ge=7, le=120)] = 12
    weight: Literal["regular", "bold"] = "regular"
    y: Annotated[float, Field(ge=0, le=1)] = 0.2
    align: Literal["left", "center", "right"] = "center"
    color: Annotated[str, StringConstraints(pattern=r"^(#[0-9a-fA-F]{6})?$")] = ""


class ArtworkLicenseIn(_Model):
    source: Short = ""
    license: Short = ""
    confirmed: bool = False


class CoverIn(_Model):
    background: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")] = "#1f3a5f"
    text_color: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")] = "#ffffff"
    artwork_asset: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")] | None = None
    artwork_fit: Literal["front", "wrap"] = "front"
    artwork_license: ArtworkLicenseIn = Field(default_factory=ArtworkLicenseIn)
    layers: Annotated[list[CoverLayerIn], Field(max_length=10)] = Field(default_factory=list)


class AiDisclosureIn(_Model):
    text: AiAnswer = ""
    images: AiAnswer = ""
    translation: AiAnswer = ""


class CategoryIn(_Model):
    text: Short
    verified: Literal[False] = False


class MetadataIn(_Model):
    description: Annotated[str, StringConstraints(max_length=4000)] = ""
    keywords: Annotated[list[Annotated[SingleLine, StringConstraints(max_length=100)]], Field(max_length=7)] = Field(
        default_factory=list
    )
    categories: Annotated[list[CategoryIn], Field(max_length=3)] = Field(default_factory=list)
    age_min: Annotated[int, Field(ge=0, le=18)] | None = None
    age_max: Annotated[int, Field(ge=0, le=18)] | None = None
    formats: list[Literal["paperback", "ebook"]] = Field(
        default_factory=lambda: list[Literal["paperback", "ebook"]](["paperback", "ebook"])
    )
    ai_disclosure: AiDisclosureIn = Field(default_factory=AiDisclosureIn)


class ProfileIn(_Model):
    template: TemplateKey
    trim: Annotated[str, StringConstraints(max_length=20)]
    ink_paper: InkPaper
    matter: Annotated[list[MatterItemIn], Field(max_length=40)]
    copyright: CopyrightIn = Field(default_factory=CopyrightIn)
    metadata: MetadataIn = Field(default_factory=MetadataIn)
    cover: CoverIn = Field(default_factory=CoverIn)
    index_terms: Annotated[list[Annotated[SingleLine, StringConstraints(max_length=100)]], Field(max_length=500)] = (
        Field(default_factory=list)
    )


class ProfileOut(BaseModel):
    template: TemplateKey
    trim: str
    ink_paper: InkPaper
    matter: list[dict[str, Any]]
    copyright: dict[str, Any]
    metadata: dict[str, Any]
    cover: dict[str, Any]
    index_terms: list[str]
    options: dict[str, Any] = Field(description="Templates, trims, ink/paper choices, matter kinds, fonts")
    rules: dict[str, Any] = Field(description="KDP rule-set version, checked-on date, source URLs, known gaps")
    tools: dict[str, Any] = Field(description="What is installed: Typst, EPUBCheck, image generation")
    ai_evidence: dict[str, Any]
    updated_at: str | None


class BuildIn(_Model):
    formats: Annotated[list[BuildFormat], Field(min_length=1, max_length=5)]


class PublicationOut(BaseModel):
    id: str
    kind: str
    status: str
    package_id: str | None
    file_name: str | None
    sha256: str | None
    byte_size: int | None
    page_count: int | None
    template: str
    trim: str
    ink_paper: str
    ruleset: str
    settings: dict[str, Any]
    report_summary: dict[str, int]
    fidelity: str | None
    error: str | None
    created_at: str


class BuildOut(BaseModel):
    publications: list[PublicationOut]
    warnings: list[dict[str, str]]


class CoverSpecOut(BaseModel):
    spec: dict[str, Any] | None
    based_on_pdf: dict[str, Any] | None = Field(description="The interior PDF whose final page count sized the cover")
    latest_cover: dict[str, Any] | None = Field(description="The last print cover built, and whether it is stale")
    message: str


class PreviewHtmlOut(BaseModel):
    html: str
    sha256: str
    identical_to_last_export: bool | None
    note: str


class PackageOut(BaseModel):
    publication: PublicationOut
    folder: str
    files: list[dict[str, Any]]
    report_summary: dict[str, int]
