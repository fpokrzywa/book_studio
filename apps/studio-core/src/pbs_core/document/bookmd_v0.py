"""BookMD parser v0 (Phase 01): CommonMark top-level blocks -> provisional BDM (`bdm/0`).

Lossless by construction: every block keeps its exact source span (`src`), and the
author's `source_md` remains authoritative. Structures v0 does not model yet (tables,
math, footnotes, citations, attributes) stay inside their block's `src` verbatim and are
modelled properly by bookmd-1 / `bdm/1` in Phase 02.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from markdown_it import MarkdownIt

from pbs_core.domain.wordcount import count_words

PARSER_VERSION = "bookmd-0.1"
BDM_SCHEMA = "bdm/0"

_md = MarkdownIt("commonmark", {"html": False})

_OPEN_TO_TYPE = {
    "heading_open": "heading",
    "paragraph_open": "paragraph",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "blockquote_open": "quote",
}
_LEAF_TO_TYPE = {"fence": "code", "code_block": "code", "hr": "thematic_break", "html_block": "unsupported"}


def normalize_source(source: str) -> str:
    """Line endings to LF (browsers already submit LF); nothing else is changed."""
    return source.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(source: str) -> str:
    return hashlib.sha256(normalize_source(source).encode("utf-8")).hexdigest()


def _block_hash(src: str) -> str:
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def parse(
    source: str,
    *,
    chapter_id: str,
    new_id: Callable[[], str],
    previous: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Return (bdm document, word count). Block IDs are reused for unchanged blocks."""
    text = normalize_source(source)
    lines = text.split("\n")
    tokens = _md.parse(text)

    reusable: dict[str, list[str]] = {}
    for block in (previous or {}).get("blocks", []):
        reusable.setdefault(block.get("hash", ""), []).append(block["id"])

    blocks: list[dict[str, Any]] = []
    words = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.level != 0 or tok.map is None:
            i += 1
            continue
        if tok.type in _OPEN_TO_TYPE:
            btype = _OPEN_TO_TYPE[tok.type]
            close = tok.type.replace("_open", "_close")
            depth, j = 0, i
            while j < len(tokens):
                if tokens[j].type == tok.type:
                    depth += 1
                elif tokens[j].type == close:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            inline_text = " ".join(t.content for t in tokens[i : j + 1] if t.type == "inline")
            extra: dict[str, Any] = {}
            if btype == "heading":
                extra["level"] = int(tok.tag[1])
            if btype == "list":
                extra["ordered"] = tok.type == "ordered_list_open"
            i = j + 1
        elif tok.type in _LEAF_TO_TYPE:
            btype = _LEAF_TO_TYPE[tok.type]
            inline_text = ""
            extra = {"lang": tok.info.strip()} if btype == "code" and tok.info.strip() else {}
            i += 1
        else:
            btype, inline_text, extra = "unsupported", "", {}
            i += 1

        start, end = tok.map
        src = "\n".join(lines[start:end])
        h = _block_hash(src)
        ids = reusable.get(h)
        block_id = ids.pop(0) if ids else new_id()
        if btype not in ("code", "thematic_break", "unsupported"):
            words += count_words(inline_text)
        blocks.append({"id": block_id, "type": btype, "src": src, "line": start, "hash": h, **extra})

    doc = {"schema": BDM_SCHEMA, "parser": PARSER_VERSION, "chapter_id": chapter_id, "blocks": blocks}
    return doc, words
