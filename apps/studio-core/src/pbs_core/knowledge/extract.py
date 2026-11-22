"""Turn an uploaded source file into anchored paragraphs and chunks.

Reuses the Phase 02 importers (same safety checks: archive limits, XXE, encrypted and scanned
files, unsafe HTML dropped), then walks the resulting text so every chunk knows its heading path,
paragraph numbers and, for PDFs, page numbers. Nothing here invents a title, author or page: the
title comes from the file's own metadata or its name, and pages come from the PDF itself.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import PurePath

from pbs_core.importers import run_importer
from pbs_core.importers.base import ImportError_

PARSER_VERSION = "knowledge-1"
TARGET_CHARS = 1200
MAX_PARAGRAPH_CHARS = 2400
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*(\{[^}]*\})?\s*$")
_FENCE = re.compile(r"^(```|~~~)")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+")
_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>|~\"'$@^&=:])")


@dataclass
class Unit:
    """One paragraph (or a part of a very long paragraph)."""

    heading_path: str
    para_no: int
    page: int | None
    text: str


@dataclass
class ChunkSpec:
    seq: int
    heading_path: str
    page_start: int | None
    page_end: int | None
    para_start: int
    para_end: int
    text: str


@dataclass
class Extracted:
    title: str
    title_origin: str
    kind: str
    units: list[Unit]
    chunks: list[ChunkSpec]
    warnings: list[dict[str, str]] = field(default_factory=list)
    page_count: int | None = None

    @property
    def word_count(self) -> int:
        return sum(len(u.text.split()) for u in self.units)

    @property
    def text_sha256(self) -> str:
        normal = " ".join(" ".join(u.text.split()) for u in self.units).casefold()
        return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def locator(page_start: int | None, page_end: int | None, para_start: int, para_end: int) -> str:
    """A human locator that only uses anchors the source really has."""
    if page_start is not None:
        return f"p. {page_start}" if page_end in (None, page_start) else f"pp. {page_start}–{page_end}"
    return f"para. {para_start}" if para_end == para_start else f"paras. {para_start}–{para_end}"


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_PARAGRAPH_CHARS:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + len(sentence) + 1 > TARGET_CHARS:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def markdown_units(chapters: list[tuple[str, str]]) -> list[Unit]:
    """Paragraphs of BookMD text with heading paths. Fenced code stays one paragraph."""
    units: list[Unit] = []
    para_no = 0
    multi = len(chapters) > 1
    for chapter_title, source in chapters:
        prefix = [chapter_title] if multi else []
        stack: list[tuple[int, str]] = []
        buf: list[str] = []
        in_fence = False

        def flush() -> None:
            nonlocal para_no
            text = "\n".join(buf).strip()  # noqa: B023 - called within the same iteration
            buf.clear()  # noqa: B023
            if not text:
                return
            para_no += 1
            path = " › ".join([*prefix, *(t for _, t in stack)])  # noqa: B023
            if not _FENCE.match(text):
                text = _MD_ESCAPE.sub(r"\1", text)  # the source's literal text, not Markdown escapes
            for part in _split_long(text):
                units.append(Unit(path, para_no, None, part))

        for line in source.splitlines():
            if _FENCE.match(line.strip()):
                in_fence = not in_fence
                buf.append(line)
                if not in_fence:
                    flush()
                continue
            if in_fence:
                buf.append(line)
                continue
            m = _HEADING.match(line)
            if m:
                flush()
                level = len(m.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, m.group(2).strip()))
                continue
            if not line.strip():
                flush()
            else:
                buf.append(line)
        flush()
    return units


def pdf_units(pages: list[str]) -> list[Unit]:
    from pbs_core.importers.pdf import _looks_like_heading, page_paragraphs

    units: list[Unit] = []
    heading = ""
    para_no = 0
    for page, text in page_paragraphs(pages):
        if _looks_like_heading(text) and len(text) < 120:
            heading = text
            continue
        para_no += 1
        for part in _split_long(text):
            units.append(Unit(heading, para_no, page, part))
    return units


def chunk(units: list[Unit]) -> list[ChunkSpec]:
    """Group consecutive paragraphs under the same heading into chunks of about TARGET_CHARS."""
    chunks: list[ChunkSpec] = []
    group: list[Unit] = []

    def emit() -> None:
        if not group:
            return
        pages = [u.page for u in group if u.page is not None]
        chunks.append(
            ChunkSpec(
                seq=len(chunks),
                heading_path=group[0].heading_path,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                para_start=group[0].para_no,
                para_end=group[-1].para_no,
                text="\n\n".join(u.text for u in group),
            )
        )
        group.clear()

    size = 0
    for u in units:
        new_page = group and u.page is not None and u.page != group[-1].page  # keep page citations exact
        if group and (new_page or u.heading_path != group[0].heading_path or size + len(u.text) > TARGET_CHARS):
            emit()
            size = 0
        group.append(u)
        size += len(u.text) + 2
    emit()
    return chunks


def extract(fmt: str, filename: str, data: bytes) -> Extracted:
    """Raises ImportError_ with a user-facing message when the file cannot be used."""
    stem = PurePath(filename).stem or "Untitled source"
    if fmt == "pdf":
        from pbs_core.importers.pdf import pdf_title, read_pages

        result = run_importer(fmt, filename, data)  # validation: encrypted, scanned, damaged
        pages = read_pages(data)
        units = pdf_units(pages)
        meta_title = pdf_title(data)
        title, origin = (meta_title, "file_metadata") if meta_title else (stem, "file_name")
        ex = Extracted(title, origin, fmt, units, chunk(units), list(result.warnings), page_count=len(pages))
    else:
        result = run_importer(fmt, filename, data)
        units = markdown_units([(c.title, c.source_md) for c in result.chapters])
        ex = Extracted(stem, "file_name", fmt, units, chunk(units), list(result.warnings))
    if not ex.units:
        raise ImportError_("No readable text was found in this file.")
    ex.warnings = [w for w in ex.warnings if w.get("code") != "pdf_text_only"]
    if fmt == "pdf":
        ex.warnings.append(
            {
                "code": "pdf_pages",
                "message": "Passages are anchored to PDF page numbers as printed by the file's page order.",
            }
        )
    return ex
