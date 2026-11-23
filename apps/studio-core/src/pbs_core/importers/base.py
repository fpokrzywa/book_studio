"""Shared import types, format detection, decoding and chapter splitting."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from pbs_core.document import bookmd, serialize


class ImportError_(ValueError):
    """The file cannot be imported (encrypted, unreadable, unsupported). Message is user-facing."""


@dataclass
class ProposedChapter:
    title: str
    source_md: str
    word_count: int = 0
    block_count: int = 0
    image_count: int = 0


@dataclass
class ImportResult:
    importer: str
    chapters: list[ProposedChapter]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    lossy: bool = False
    images: dict[str, tuple[bytes, str]] = field(default_factory=dict)  # short hash -> (bytes, name)

    def warn(self, code: str, message: str) -> None:
        if not any(w["code"] == code and w["message"] == message for w in self.warnings):
            self.warnings.append({"code": code, "message": message})


EXTENSIONS = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".docx": "docx",
    ".pdf": "pdf",
}


def detect_format(filename: str, data: bytes) -> str:
    """Decide the importer from magic bytes first, then the file extension."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise ImportError_(
            "This is an old Word (.doc) file or an encrypted, password-protected document. "
            "Open it in Word, remove any password, and save it as .docx to import it."
        )
    ext = PurePath(filename.lower()).suffix
    if data.startswith(b"PK\x03\x04") and (
        ext == ".docx" or b"word/document.xml" in data[:4096] or ext not in EXTENSIONS
    ):
        return "docx"
    fmt = EXTENSIONS.get(ext)
    if fmt is None:
        raise ImportError_("Unsupported file type. Import Markdown (.md), text (.txt), HTML, Word (.docx) or PDF.")
    if fmt in ("docx", "pdf"):
        raise ImportError_(f"This file is named {ext} but its contents are not a valid {ext[1:].upper()} file.")
    return fmt


def decode_text(data: bytes, result: ImportResult) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        result.warn(
            "encoding_guess",
            "The file is not UTF-8. It was read as Windows-1252; check accented letters and quotes.",
        )
        return data.decode("cp1252", errors="replace")


def short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


_CHAPTER_LINE = re.compile(r"^\s*(chapter|part|prologue|epilogue|introduction)\b[\s\w.:'’\-]{0,80}$", re.IGNORECASE)


def is_chapter_line(line: str) -> bool:
    return bool(_CHAPTER_LINE.match(line)) and len(line.strip()) <= 90


def finish(result: ImportResult, fallback_title: str) -> ImportResult:
    """Compute statistics and collect per-chapter fidelity warnings."""
    counter = iter(range(10**9))
    if not result.chapters:
        result.chapters = [ProposedChapter(title=fallback_title, source_md="")]
    for ch in result.chapters:
        parsed = bookmd.parse(ch.source_md, chapter_id="import", new_id=lambda: f"{next(counter):026d}")
        ch.word_count = parsed.word_count
        ch.block_count = len(parsed.doc["blocks"])
        ch.image_count = sum(1 for b in bookmd.walk_blocks(parsed.doc) if b["type"] == "figure")
        for w in parsed.warnings:
            if w.code in ("unsupported_block", "external_image", "unresolved_image", "missing_alt", "missing_footnote"):
                result.warn(w.code, f"{ch.title}: {w.message}")
    return result


def split_markdown(source: str, fallback_title: str) -> list[ProposedChapter]:
    """Split BookMD/Markdown text into chapters at level-1 headings (or level-2 if there are none).

    The text of each chapter is kept exactly as written (lossless); only the heading line that
    became the chapter title is removed.
    """
    text = bookmd.normalize_source(source)
    lines = text.split("\n")
    tokens = bookmd._MD.parse(text)
    heads: list[tuple[int, int, int, str]] = []  # (level, start, end, title)
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.level == 0 and tok.map:
            inline = tokens[i + 1]
            title = inline.content
            stripped = re.sub(r"\s*\{[^{}]*\}\s*$", "", title).strip()
            heads.append((int(tok.tag[1]), tok.map[0], tok.map[1], stripped))
    level = 1 if any(h[0] == 1 for h in heads) else (2 if sum(1 for h in heads if h[0] == 2) >= 2 else None)
    if level is None:
        return [ProposedChapter(title=fallback_title, source_md=text.strip("\n") + "\n" if text.strip() else "")]
    cuts = [h for h in heads if h[0] == level]
    chapters: list[ProposedChapter] = []
    before = "\n".join(lines[: cuts[0][1]]).strip("\n")
    if before.strip():
        chapters.append(ProposedChapter(title="Front matter", source_md=before + "\n"))
    for idx, (_, _start, end, title) in enumerate(cuts):
        stop = cuts[idx + 1][1] if idx + 1 < len(cuts) else len(lines)
        body = "\n".join(lines[end:stop]).strip("\n")
        chapters.append(ProposedChapter(title=title or f"Chapter {idx + 1}", source_md=(body + "\n") if body else ""))
    return chapters


def split_blocks(doc: dict[str, Any], fallback_title: str) -> list[ProposedChapter]:
    """Split a bdm/1 document at its top-level H1 (or H2) headings and serialize each part."""
    blocks = doc.get("blocks", [])
    footnotes: dict[str, Any] = doc.get("footnotes", {})
    level = 1 if any(b["type"] == "heading" and b["level"] == 1 for b in blocks) else 2
    if not any(b["type"] == "heading" and b["level"] == level for b in blocks) or (
        level == 2 and sum(1 for b in blocks if b["type"] == "heading" and b["level"] == 2) < 2
    ):
        groups = [(fallback_title, blocks)]
    else:
        groups = []
        current: list[dict[str, Any]] = []
        title: str | None = None
        for b in blocks:
            if b["type"] == "heading" and b["level"] == level:
                if current or title is not None:
                    groups.append((title or "Front matter", current))
                title, current = bookmd.inline_text(b["inlines"]).strip() or "Untitled", []
            else:
                current.append(b)
        groups.append((title or fallback_title, current))
    chapters = []
    for title, group in groups:
        used = _footnote_labels(group)
        part: dict[str, Any] = {"schema": bookmd.BDM_SCHEMA, "blocks": group}
        notes = {k: v for k, v in footnotes.items() if k in used}
        if notes:
            part["footnotes"] = notes
        chapters.append(ProposedChapter(title=title, source_md=serialize.serialize(part)))
    return chapters


def _footnote_labels(blocks: list[dict[str, Any]]) -> set[str]:
    doc = {"blocks": blocks}
    return {n["label"] for n in bookmd.iter_all_inlines(doc) if n["t"] == "footnote_ref"}


def run_importer(fmt: str, filename: str, data: bytes) -> ImportResult:
    from pbs_core.importers import docx, html_import, pdf, text

    title = PurePath(filename).stem or "Imported"
    if fmt == "markdown":
        result = ImportResult("markdown", [])
        result.chapters = split_markdown(decode_text(data, result), title)
        return finish(result, title)
    if fmt == "text":
        return finish(text.import_text(data, title), title)
    if fmt == "html":
        return finish(html_import.import_html(data, title), title)
    if fmt == "docx":
        return finish(docx.import_docx(data, title), title)
    if fmt == "pdf":
        return finish(pdf.import_pdf(data, title), title)
    raise ImportError_(f"Unsupported import format: {fmt}")
