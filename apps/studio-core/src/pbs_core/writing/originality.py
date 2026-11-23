"""The originality report: local overlap checks with an explicit, limited scope.

What it compares: this book's paragraphs with each other, with the other books in this workspace,
and with the text of this book's knowledge sources (long word-for-word runs). What it does not do:
search the web, published books or any database. An external similarity provider would be used
only if one were configured and authorised; none ships with PBS. The report always says so, and it
always says that finding no match is not proof of originality or of non-infringement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from pbs_core.writing.quality import ChapterIn, check_duplicates, paragraphs, words

RUN_WORDS = 12  # a shared run of this many words in a row counts as an overlap

SCOPE = [
    "Paragraphs repeated within this book (exact or nearly identical).",
    "Word-for-word runs of 12 or more words shared with the other books in this workspace.",
    "Word-for-word runs of 12 or more words shared with this book's knowledge sources.",
]
NOT_COVERED = [
    "The web, published books, journals or any online database.",
    "Paraphrase, translation or close imitation that does not repeat the exact words.",
    "Images, tables of data and code listings.",
]
STATEMENT = (
    "This is a local check with the scope listed above. Finding no match does not mean the text is original, "
    "unique worldwide or free of infringement, and a match is not proof of copying."
)


@dataclass
class OtherText:
    kind: str  # book | source
    ref_id: str
    title: str
    text: str
    extra: dict[str, Any] = field(default_factory=dict)


def _runs(ws: list[str], k: int = RUN_WORDS) -> dict[int, tuple[str, ...]]:
    return {i: tuple(ws[i : i + k]) for i in range(max(0, len(ws) - k + 1))}


def _hash(g: tuple[str, ...]) -> str:
    return hashlib.sha1(" ".join(g).encode("utf-8"), usedforsecurity=False).hexdigest()


def report(chapters: list[ChapterIn], others: list[OtherText], provider_note: str) -> dict[str, Any]:
    internal = [
        {
            "kind": "within_book",
            "message": f.message,
            "excerpt": f.excerpt,
            "similarity": f.details.get("similarity"),
            "locations": f.details.get("locations", []),
        }
        for f in check_duplicates(chapters)
    ]
    index: dict[str, list[int]] = {}
    other_words = [words(o.text) for o in others]
    for oi, ws in enumerate(other_words):
        for g in _runs(ws).values():
            index.setdefault(_hash(g), []).append(oi)
    external: list[dict[str, Any]] = []
    for ch in chapters:
        for pi, para in enumerate(paragraphs(ch.text)):
            ws = words(para)
            hits: dict[int, int] = {}
            for g in _runs(ws).values():
                for oi in set(index.get(_hash(g), [])):
                    hits[oi] = hits.get(oi, 0) + 1
            for oi, n in hits.items():
                o = others[oi]
                external.append(
                    {
                        "kind": "workspace_book" if o.kind == "book" else "knowledge_source",
                        "chapter_id": ch.id,
                        "chapter": ch.title,
                        "paragraph": pi + 1,
                        "matched_with": o.title,
                        "ref_id": o.ref_id,
                        "shared_words_at_least": RUN_WORDS + n - 1,
                        "cited_in_paragraph": "[@" in para,
                        "excerpt": " ".join(para.split())[:220],
                        **o.extra,
                    }
                )
    return {
        "scope": SCOPE,
        "not_covered": NOT_COVERED,
        "external_provider": provider_note,
        "statement": STATEMENT,
        "chapters_checked": len(chapters),
        "compared_with": {
            "workspace_books": len({o.ref_id for o in others if o.kind == "book"}),
            "knowledge_sources": len({o.ref_id for o in others if o.kind == "source"}),
        },
        "within_book": internal,
        "overlaps": external,
    }
