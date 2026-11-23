"""Text-based PDF import (pypdf). Text only: layout, tables, images and styling are not recovered."""

from __future__ import annotations

import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pbs_core.importers.base import ImportError_, ImportResult
from pbs_core.importers.text import paragraphs_to_chapters

MIN_TEXT_PER_PAGE = 25


def import_pdf(data: bytes, fallback_title: str) -> ImportResult:
    result = ImportResult("pdf", [], lossy=True)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception as exc:
                raise ImportError_("This PDF is encrypted. Remove the password and import it again.") from exc
            if not ok:
                raise ImportError_("This PDF is password-protected. Remove the password and import it again.")
            result.warn("pdf_encrypted", "The PDF was encrypted without a password; it was opened read-only.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ImportError_:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise ImportError_("The PDF could not be read. It may be damaged.") from exc

    if not pages:
        raise ImportError_("The PDF has no pages.")
    empty = [i + 1 for i, t in enumerate(pages) if len(t.strip()) < MIN_TEXT_PER_PAGE]
    if len(empty) == len(pages):
        raise ImportError_(
            "No text could be extracted. This looks like a scanned (image-only) PDF. "
            "Text recognition (OCR) is not available yet; use a text-based PDF, DOCX or Markdown instead."
        )
    if empty:
        listed = ", ".join(map(str, empty[:10])) + ("…" if len(empty) > 10 else "")
        result.warn(
            "pdf_scanned_pages", f"{len(empty)} page(s) contain little or no text and may be scanned: {listed}."
        )
    result.warn(
        "pdf_text_only",
        "PDF import keeps the text only. Headings, tables, images, footnotes and formatting are not recovered; "
        "check every chapter after importing.",
    )

    paragraphs = [[text] for _, text in page_paragraphs(pages)]
    result.chapters = paragraphs_to_chapters(paragraphs, fallback_title)
    return result


def read_pages(data: bytes) -> list[str]:
    """Text of each page (validated the same way as import_pdf). Used by knowledge indexing for page anchors."""
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def pdf_title(data: bytes) -> str | None:
    """The title recorded in the PDF's own metadata, if any (never guessed)."""
    try:
        meta = PdfReader(io.BytesIO(data)).metadata
        title = str(meta.title).strip() if meta and meta.title else ""
    except Exception:
        return None
    return title or None


def page_paragraphs(pages: list[str]) -> list[tuple[int, str]]:
    """Split page texts into paragraphs, keeping the 1-based page number each one starts on."""
    out: list[tuple[int, str]] = []
    for page_no, page_text in enumerate(pages, start=1):
        text = re.sub(r"-\n(?=[a-z])", "", page_text)  # re-join hyphenated line breaks
        current: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if current:
                    out.append((page_no, " ".join(current)))
                    current = []
                continue
            if re.fullmatch(r"\d{1,4}", stripped):
                continue  # bare page numbers
            if _looks_like_heading(stripped) and current:
                out.append((page_no, " ".join(current)))
                current = []
            current.append(stripped)
            if _looks_like_heading(stripped):
                out.append((page_no, " ".join(current)))
                current = []
        if current:
            out.append((page_no, " ".join(current)))
    return out


def _looks_like_heading(line: str) -> bool:
    from pbs_core.importers.base import is_chapter_line

    return is_chapter_line(line)
