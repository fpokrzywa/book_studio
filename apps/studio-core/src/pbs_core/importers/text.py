"""Plain-text import: paragraphs separated by blank lines; 'Chapter …' lines start chapters."""

from __future__ import annotations

from typing import Any

from pbs_core.document import serialize
from pbs_core.importers.base import ImportResult, ProposedChapter, decode_text, is_chapter_line


def paragraphs_to_chapters(paragraphs: list[list[str]], fallback_title: str) -> list[ProposedChapter]:
    chapters: list[ProposedChapter] = []
    title: str | None = None
    blocks: list[dict[str, Any]] = []

    def flush() -> None:
        if title is not None or blocks:
            text = serialize.serialize({"blocks": blocks})
            chapters.append(ProposedChapter(title=title or fallback_title, source_md=text))

    for para in paragraphs:
        if len(para) == 1 and is_chapter_line(para[0]):
            flush()
            title, blocks = para[0].strip(), []
            continue
        inlines: list[dict[str, Any]] = []
        for i, line in enumerate(para):
            if i:
                inlines.append({"t": "softbreak"})
            inlines.append({"t": "text", "v": line.strip()})
        blocks.append({"type": "paragraph", "inlines": inlines})
    flush()
    return chapters


def split_paragraphs(text: str) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append(current)
            current = []
    if current:
        paragraphs.append(current)
    return paragraphs


def import_text(data: bytes, fallback_title: str) -> ImportResult:
    result = ImportResult("text", [])
    text = decode_text(data, result)
    result.chapters = paragraphs_to_chapters(split_paragraphs(text), fallback_title)
    return result
