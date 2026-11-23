"""The publish package: a folder (and ZIP) to upload to KDP by hand. Nothing is sent anywhere."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from pbs_core.publishing import kdp_rules
from pbs_core.publishing.book import FONT_LICENSES, Book

_FIXED = (2026, 1, 1, 0, 0, 0)


def upload_steps(book: Book, files: dict[str, str], cover: dict[str, Any] | None) -> str:
    s = kdp_rules.SOURCES
    spine = (
        f"{cover['spine_width_in']} in spine, {cover['cover_width_in']} × {cover['cover_height_in']} in full cover"
        if cover
        else "no print cover built"
    )
    return (
        f"""# Manual KDP upload and preview steps

Personal Book Studio does not publish anything and never logs in to KDP. Do these steps yourself.
Passing PBS preflight does not mean KDP will accept the book: KDP reviews every title, and its
rules can change. Rule set used: **{kdp_rules.RULESET}** (checked {kdp_rules.CHECKED_ON}).

## Before you start
1. Read `preflight-report.html` and fix every **fail**. Look at every **manual** and **unavailable** line.
2. Compare the current KDP pages with what PBS used (links at the end). If a number changed, rebuild.

## eBook (Kindle)
1. In KDP, create a Kindle eBook. Enter the details from `metadata.txt` (title, author, description,
   keywords, categories, age range, language, and the AI questions).
2. Upload `{files.get("epub", "book.epub")}` as the manuscript (KDP also accepts DOCX).
3. Upload `cover/ebook-cover.jpg` as the cover (KDP's ideal is 1600 × 2560 px; this file is that size).
4. Open the book in KDP's online previewer, or in Kindle Previewer on your computer ({s["kindle_previewer"]}),
   and page through every chapter: tables, images, equations and links.

## Paperback
1. Create a paperback. Choose trim **{book.template.get("trim")}** (or the trim you built with), the ink and
   paper you chose in PBS, no bleed, and the cover finish you want.
2. Upload `{files.get("pdf", "interior.pdf")}` as the manuscript.
3. Check the cover numbers in KDP's cover calculator ({s["cover_calculator"]}) with your final page count:
   PBS built {spine}. If they differ, rebuild the cover in PBS with the same page count.
4. Upload `cover/print-cover.pdf` (not the proof with guides). Let KDP place the barcode in the white area,
   or use your own barcode there.
5. Open the print previewer, check every page, the spine and the barcode area, then order a printed proof
   before you publish.

## Sources (checked {kdp_rules.CHECKED_ON})
"""
        + "\n".join(f"- {k}: {v}" for k, v in s.items())
        + "\n"
    )


def licenses_text(book: Book, cover_cfg: dict[str, Any] | None) -> str:
    c = book.copyright
    lines = ["COPYRIGHT AND LICENSE NOTES", "", "Book copyright (as you entered it; PBS writes no legal text for you):"]
    if any((c.get(k) or "").strip() for k in ("holder", "year", "notice_md", "isbn", "edition")):
        lines += [f"  Holder: {c.get('holder') or '-'}", f"  Year: {c.get('year') or '-'}", f"  Edition: {c.get('edition') or '-'}",
                  f"  ISBN: {c.get('isbn') or '(none: KDP can assign a free ISBN for paperbacks)'}"]  # fmt: skip
        if (c.get("notice_md") or "").strip():
            lines += ["  Notice:", *["    " + ln for ln in c["notice_md"].splitlines()]]
    else:
        lines.append("  Nothing entered.")
    lines += ["", "Fonts embedded in the PDF files (all freely licensed for embedding):"]
    for f in sorted({book.template["body_font"], book.template["code_font"], book.template["math_font"]}):
        lines.append(f"  {f}: {FONT_LICENSES.get(f, 'see font')}")
    lines += ["", "Cover artwork:"]
    art = (cover_cfg or {}).get("artwork_license") or {}
    if (cover_cfg or {}).get("artwork_asset"):
        lines += [f"  Source: {art.get('source') or '-'}", f"  License: {art.get('license') or '-'}",
                  f"  You confirmed you may use it on a commercially sold cover: {'yes' if art.get('confirmed') else 'NO'}"]  # fmt: skip
    else:
        lines.append("  No artwork (plain background and typography).")
    lines += ["", "Cover lettering is typography set by PBS (not drawn by an image model).",
              "No image generation provider is configured in PBS."]  # fmt: skip
    return "\n".join(lines) + "\n"


def sources_text(book: Book, knowledge: list[dict[str, Any]]) -> str:
    lines = ["SOURCES", "", "Cited in the book (details as you entered them):"]
    for key in book.cited_keys:
        e = book.bibliography.get(key)
        if e is None:
            lines.append(f"  [{key}] no details entered")
        else:
            lines.append(
                f"  [{key}] {', '.join(e.authors) or '-'} ({e.year or 'n.d.'}). {e.title}. {e.publisher or ''} {e.url or ''} {('doi:' + e.doi) if e.doi else ''}".rstrip()
            )
    lines += ["", "Knowledge sources attached to this book:"]
    lines += [f"  - {k['title']} ({k['kind']}){' [removed]' if k.get('removed') else ''}" for k in knowledge] or [
        "  none"
    ]
    return "\n".join(lines) + "\n"


def write(folder: Path, files: dict[str, bytes]) -> dict[str, Any]:
    """Write files into the package folder and return the manifest (sha256 per file)."""
    manifest: dict[str, Any] = {"files": {}}
    for name, data in sorted(files.items()):
        p = folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return manifest


def zip_folder(files: dict[str, bytes], root: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"{root}/{name}", date_time=_FIXED)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


def dumps(x: Any) -> bytes:
    return (json.dumps(x, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
