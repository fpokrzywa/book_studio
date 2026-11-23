"""Turn a chapter into speech-ready chunks, keeping which source blocks each chunk came from.

Prose is read as written (emphasis and link markup dropped, citations and footnote markers left
out). Things a listener cannot hear are announced and noted for the author: code listings, equations,
tables and figures (their alt text is read). Chunks break at sentence ends and never exceed the
engine's limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pbs_core.document.bookmd import inline_text

_SENT = re.compile(r"(?<=[.!?…])\s+")


@dataclass
class Chunk:
    text: str
    block_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _spoken(nodes: list[dict[str, Any]], notes: list[str]) -> str:
    out = []
    for n in nodes:
        t = n["t"]
        if t == "text":
            out.append(n["v"])
        elif t in ("softbreak", "hardbreak"):
            out.append(" ")
        elif t == "code":
            out.append(n["v"])
        elif t == "math":
            notes.append(f"Inline equation read as “an equation”: {n['tex'][:60]}")
            out.append("an equation")
        elif t in ("emph", "strong", "strike", "link"):
            out.append(_spoken(n["c"], notes))
        elif t == "image":
            out.append(n.get("alt") or inline_text(n["c"]))
        # citations and footnote markers are not read aloud
    return re.sub(r"\s+", " ", "".join(out)).strip()


def units(doc: dict[str, Any], title: str) -> list[tuple[str, str, list[str]]]:
    """(block id, text to read, notes) in reading order."""
    out: list[tuple[str, str, list[str]]] = [("title", f"{title}.", [])]

    def walk(blocks: list[dict[str, Any]]) -> None:
        for b in blocks:
            notes: list[str] = []
            t = b.get("type")
            bid = str(b.get("id", ""))
            if t in ("heading", "paragraph"):
                text = _spoken(b["inlines"], notes)
                if text:
                    out.append(
                        (bid, text + ("." if t == "heading" and not text.endswith((".", "?", "!")) else ""), notes)
                    )
            elif t == "code":
                out.append((bid, "A code listing appears here in the book.", ["Code listing announced, not read."]))
            elif t == "math_block":
                out.append(
                    (bid, "An equation appears here in the book.", [f"Equation announced, not read: {b['tex'][:60]}"])
                )
            elif t == "table":
                cap = inline_text(b.get("caption") or [])
                out.append(
                    (
                        bid,
                        f"A table appears here in the book{': ' + cap if cap else ''}.",
                        ["Table announced, not read."],
                    )
                )
            elif t == "figure":
                alt = b.get("alt") if b.get("alt") is not None else inline_text(b.get("caption") or [])
                out.append(
                    (
                        bid,
                        f"Figure: {alt}." if alt else "A figure appears here in the book.",
                        ["Figure read from its alt text."],
                    )
                )
            elif t in ("quote", "div"):
                walk(b["blocks"])
            elif t == "list":
                for it in b["items"]:
                    walk(it["blocks"])
            elif t == "unsupported":
                out.append((bid, "", ["Unsupported content skipped."]))

    walk(doc.get("blocks", []))
    return [u for u in out if u[1] or u[2]]


def chunk(doc: dict[str, Any], title: str, max_chars: int = 1500) -> list[Chunk]:
    chunks: list[Chunk] = []
    cur = Chunk("")
    for bid, text, notes in units(doc, title):
        pieces = [text] if len(text) <= max_chars else _split(text, max_chars)
        for piece in pieces:
            if cur.text and len(cur.text) + 1 + len(piece) > max_chars:
                chunks.append(cur)
                cur = Chunk("")
            cur.text = (cur.text + " " + piece).strip() if piece else cur.text
            if bid not in cur.block_ids:
                cur.block_ids.append(bid)
        cur.notes += notes
    if cur.text or cur.notes:
        chunks.append(cur)
    return [c for c in chunks if c.text]


def _split(text: str, max_chars: int) -> list[str]:
    out, cur = [], ""
    for s in _SENT.split(text):
        while len(s) > max_chars:  # a single enormous sentence: cut at a space
            cut = s.rfind(" ", 0, max_chars) or max_chars
            out.append(s[:cut])
            s = s[cut:].strip()
        if cur and len(cur) + 1 + len(s) > max_chars:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out
