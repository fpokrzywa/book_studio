"""SQLite FTS5 index and search over source chunks.

* User text never reaches FTS5 syntax: queries are reduced to word tokens and each is quoted.
* Highlights come back as plain-text segments (`{"text", "hit"}`), never as HTML, so the UI shows
  source text as text. Match reasons say which words matched in the title, heading or passage.
* Only enabled, indexed, not-removed sources in libraries the book can use are searched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from pbs_core.knowledge.extract import locator

HIT_OPEN, HIT_CLOSE = "", ""
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "too",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "after",
        "again",
        "all",
        "also",
        "any",
        "because",
        "before",
        "being",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "over",
        "same",
        "some",
        "such",
        "only",
        "own",
        "very",
        "just",
        "should",
        "now",
        "write",
        "paragraph",
        "chapter",
        "one",
        "two",
        "three",
        "please",
        "make",
        "add",
        "use",
        "using",
        "new",
        "text",
    ]
)


def fold(s: str) -> str:
    """Case- and accent-insensitive form used for match reasons (mirrors remove_diacritics)."""
    nfkd = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def terms_of(query: str, *, drop_stopwords: bool = False, limit: int = 16) -> list[str]:
    seen: dict[str, None] = {}
    for w in _WORD.findall(query):
        w = w.strip("'’-")
        if len(w) < 2 and not w.isdigit():
            continue
        if drop_stopwords and fold(w) in STOPWORDS:
            continue
        seen.setdefault(w, None)
        if len(seen) >= limit:
            break
    return list(seen)


def _fts_query(terms: list[str], mode: str) -> str:
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    return (" OR " if mode == "any" else " ").join(quoted)


def index_chunk(s: Session, *, chunk_id: str, source_id: str, title: str, heading: str, body: str) -> None:
    s.execute(
        text("INSERT INTO source_chunk_fts (text, heading, title, chunk_id, source_id) VALUES (:b, :h, :t, :c, :s)"),
        {"b": body, "h": heading, "t": title, "c": chunk_id, "s": source_id},
    )


def unindex_source(s: Session, source_id: str) -> None:
    s.execute(text("DELETE FROM source_chunk_fts WHERE source_id = :s"), {"s": source_id})


def retitle_source(s: Session, source_id: str, title: str) -> None:
    s.execute(text("UPDATE source_chunk_fts SET title = :t WHERE source_id = :s"), {"t": title, "s": source_id})


@dataclass
class Hit:
    chunk_id: str
    source_id: str
    title: str
    citation_key: str
    library_id: str
    heading_path: str
    page_start: int | None
    page_end: int | None
    para_start: int
    para_end: int
    text: str
    score: float
    snippet: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    @property
    def locator(self) -> str:
        return locator(self.page_start, self.page_end, self.para_start, self.para_end)


def segments(marked: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, part in enumerate(re.split(f"[{HIT_OPEN}{HIT_CLOSE}]", marked)):
        if part:
            out.append({"text": part, "hit": i % 2 == 1})
    return out


def _reasons(terms: list[str], title: str, heading: str, body: str) -> tuple[list[str], list[str]]:
    ft, fh, fb = fold(title), fold(heading), fold(body)
    matched, reasons = [], []
    in_title, in_heading, in_body = [], [], []
    for t in terms:
        f = fold(t)
        hit = False
        if f in fb:
            in_body.append(t)
            hit = True
        if f in fh:
            in_heading.append(t)
            hit = True
        if f in ft:
            in_title.append(t)
            hit = True
        if hit:
            matched.append(t)
    if in_body:
        reasons.append("Passage contains: " + ", ".join(in_body))
    if in_heading:
        reasons.append("Section heading contains: " + ", ".join(in_heading))
    if in_title:
        reasons.append("Source title contains: " + ", ".join(in_title))
    missing = [t for t in terms if t not in matched]
    if missing:
        reasons.append("Not found here: " + ", ".join(missing))
    return matched, reasons


def search(
    s: Session,
    *,
    source_ids: list[str],
    query: str,
    limit: int = 20,
    mode: str = "all",
    drop_stopwords: bool = False,
) -> tuple[list[Hit], str]:
    """Returns (hits, mode_used). mode "all" falls back to "any" when nothing matches every word."""
    terms = terms_of(query, drop_stopwords=drop_stopwords)
    if not terms or not source_ids:
        return [], mode
    modes = [mode] if mode == "any" else ["all", "any"]
    placeholders = ", ".join(f":s{i}" for i in range(len(source_ids)))
    params: dict[str, Any] = {f"s{i}": sid for i, sid in enumerate(source_ids)}
    for m in modes:
        params.update(q=_fts_query(terms, m), lim=max(1, min(limit, 100)))
        rows = s.execute(
            text(
                f"""
                SELECT f.chunk_id, f.source_id, bm25(source_chunk_fts, 1.0, 2.0, 2.0) AS score,
                       snippet(source_chunk_fts, 0, '{HIT_OPEN}', '{HIT_CLOSE}', '…', 40) AS snip,
                       c.heading_path, c.page_start, c.page_end, c.para_start, c.para_end, c.text,
                       src.title, src.citation_key, src.library_id
                FROM source_chunk_fts f
                JOIN source_chunk c ON c.id = f.chunk_id
                JOIN source src ON src.id = f.source_id
                WHERE source_chunk_fts MATCH :q AND f.source_id IN ({placeholders})
                ORDER BY score
                LIMIT :lim
                """  # noqa: S608 - only bound parameters and generated placeholder names
            ),
            params,
        ).all()
        if rows:
            hits = []
            for r in rows:
                matched, reasons = _reasons(terms, r.title, r.heading_path, r.text)
                hits.append(
                    Hit(
                        chunk_id=r.chunk_id,
                        source_id=r.source_id,
                        title=r.title,
                        citation_key=r.citation_key,
                        library_id=r.library_id,
                        heading_path=r.heading_path,
                        page_start=r.page_start,
                        page_end=r.page_end,
                        para_start=r.para_start,
                        para_end=r.para_end,
                        text=r.text,
                        score=round(-float(r.score), 4),
                        snippet=segments(r.snip),
                        reasons=reasons,
                        matched_terms=matched,
                    )
                )
            return hits, m
    return [], modes[-1]
