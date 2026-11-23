"""Assembled book -> one Markdown file (chapters verbatim) plus images, as a deterministic ZIP."""

from __future__ import annotations

import io
import json
import re
import zipfile

from pbs_core.publishing.book import Book

_FIXED = (2026, 1, 1, 0, 0, 0)
_ASSET = re.compile(r"\(asset:([0-9a-f]{16})")


def build(book: Book) -> tuple[bytes, str]:
    """Returns (zip bytes, markdown text)."""
    lines = ["---", f"title: {json.dumps(book.title, ensure_ascii=False)}"]
    if book.subtitle:
        lines.append(f"subtitle: {json.dumps(book.subtitle, ensure_ascii=False)}")
    if book.author:
        lines.append(f"author: {json.dumps(book.author, ensure_ascii=False)}")
    lines += [f"lang: {book.language}", "generator: pbs-md-book/1", "---", ""]
    for m in [*book.front]:
        if m.body_md:
            lines += [f"# {m.title}", "", m.body_md.strip(), ""]
    for ch in book.chapters:
        src = ch.source_md.strip()
        first = src.splitlines()[0].strip() if src else ""
        if first.lstrip("#").strip().lower() != ch.title.strip().lower() or not first.startswith("# "):
            lines += ["#" * min(ch.depth + 1, 6) + f" {ch.title}", ""]
        lines += [
            _ASSET.sub(
                lambda m: (
                    f"(images/{m.group(1)}.{book.assets[m.group(1)].ext}" if m.group(1) in book.assets else m.group(0)
                ),
                src,
            ),
            "",
        ]
    for m in book.back:
        if m.body_md:
            lines += [f"# {m.title}", "", m.body_md.strip(), ""]
        elif m.kind == "glossary" and book.glossary:
            lines += [f"# {m.title}", ""] + [f"- **{t}**: {d}" for t, d in book.glossary] + [""]
    text = "\n".join(lines).rstrip() + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("book.md", date_time=_FIXED)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, text.encode("utf-8"))
        for a in book.assets.values():
            info = zipfile.ZipInfo(f"images/{a.short_hash}.{a.ext}", date_time=_FIXED)
            z.writestr(info, a.data)
    return buf.getvalue(), text
