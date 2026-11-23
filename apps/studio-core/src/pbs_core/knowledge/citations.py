"""Check what a model cited, link each claim to an exact passage, and flag the rest.

The model sees sources as labelled envelopes (S1, S2, …; interview answers I1, I2, …) and is
asked to put the label after each sentence that uses it, like ``[[S2]]``. Afterwards:

* labels that were not provided are dropped and reported (no invented sources survive);
* each cited sentence is matched against the cited passage; the best-matching sentence of the
  passage becomes the quote, and a weak match is flagged "not located";
* paragraphs with no citation are flagged "unverified";
* source labels become BookMD citations ``[@key, p. 4]`` with the source's stable key and a
  locator the source really has. Interview labels are removed from the prose (the evidence ledger
  keeps the link to the exact answer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pbs_core.knowledge.search import STOPWORDS, fold

MARKER = re.compile(r"\s?\[\[\s*([SI]\d{1,3})\s*\]\]")
_MARKER_AFTER_PUNCT = re.compile(r"([.!?][\"”’)]*)((?:\s?\[\[\s*[SI]\d{1,3}\s*\]\])+)")
_SENTENCE = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+(?=[\"“‘(A-Z0-9])")
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_LOCATE_MIN_WORDS = 2
_LOCATE_MIN_SCORE = 0.25


@dataclass
class Ref:
    label: str
    kind: str  # source | interview
    text: str
    title: str
    source_id: str | None = None
    chunk_id: str | None = None
    citation_key: str | None = None
    locator: str | None = None
    answer_id: str | None = None


@dataclass
class Support:
    label: str
    kind: str
    title: str
    quote: str
    located: bool
    score: float
    source_id: str | None
    chunk_id: str | None
    citation_key: str | None
    locator: str | None
    answer_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ClaimDraft:
    text: str
    paragraph: int
    supports: list[Support]

    @property
    def status(self) -> str:
        return "supported" if any(s.located for s in self.supports) else "not_located"


@dataclass
class Processed:
    text_md: str
    paragraphs: list[dict[str, Any]] = field(default_factory=list)
    claims: list[ClaimDraft] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"paragraphs": self.paragraphs, "dropped_labels": self.dropped}


def content_words(s: str) -> set[str]:
    return {f for f in (fold(w.strip("'’-")) for w in _WORD.findall(s)) if len(f) > 2 and f not in STOPWORDS}


def sentences(text: str) -> list[str]:
    return [p for p in _SENTENCE.split(text.strip()) if p.strip()]


def locate(claim: str, passage: str) -> tuple[str, bool, float]:
    """Best-matching sentence of the passage, whether it supports the claim, and the score."""
    want = content_words(claim)
    if not want:
        return "", False, 0.0
    best, best_score, best_overlap = "", 0.0, 0
    for sent in sentences(passage) or [passage]:
        overlap = len(want & content_words(sent))
        score = overlap / len(want)
        if score > best_score:
            best, best_score, best_overlap = sent.strip(), score, overlap
    located = best_overlap >= min(_LOCATE_MIN_WORDS, len(want)) and best_score >= _LOCATE_MIN_SCORE
    return best[:600], located, round(best_score, 3)


def _cite(supports: list[Support]) -> str:
    keys: list[str] = []
    for s in supports:
        if s.kind == "source" and s.citation_key:
            item = f"@{s.citation_key}, {s.locator}" if s.locator else f"@{s.citation_key}"
            if item not in keys:
                keys.append(item)
    return f" [{'; '.join(keys)}]" if keys else ""


def process(payload: str, refs: dict[str, Ref]) -> Processed:
    out = Processed(text_md="")
    new_paragraphs: list[str] = []
    for p_index, para in enumerate(re.split(r"\n\s*\n", payload.strip())):
        para = _MARKER_AFTER_PUNCT.sub(lambda m: f"{m.group(2)}{m.group(1)}", para)
        parts: list[str] = []
        para_supports: list[Support] = []
        para_dropped: list[str] = []
        cited = False
        for sent in sentences(para) if para.strip() else []:
            labels = [m.group(1) for m in MARKER.finditer(sent)]
            clean = MARKER.sub("", sent).strip()
            known = [lb for lb in dict.fromkeys(labels) if lb in refs]
            for lb in labels:
                if lb not in refs and lb not in para_dropped:
                    para_dropped.append(lb)
            supports: list[Support] = []
            for lb in known:
                ref = refs[lb]
                quote, located, score = locate(clean, ref.text)
                supports.append(
                    Support(
                        label=lb,
                        kind=ref.kind,
                        title=ref.title,
                        quote=quote or ref.text[:300],
                        located=located,
                        score=score,
                        source_id=ref.source_id,
                        chunk_id=ref.chunk_id,
                        citation_key=ref.citation_key,
                        locator=ref.locator,
                        answer_id=ref.answer_id,
                    )
                )
            if supports:
                cited = True
                para_supports.extend(supports)
                out.claims.append(ClaimDraft(clean, p_index, supports))
            m = re.match(r"^(.*?)([.!?][\"”’)]*)?$", clean, re.S)
            body, end = (m.group(1), m.group(2) or "") if m else (clean, "")
            parts.append(f"{body}{_cite(supports)}{end}" if supports else clean)
        if not MARKER.search(para):
            new_para = para  # nothing cited: keep the text exactly as written
        elif "\n" in para:
            new_para = _keep_lines(para, refs)
        else:
            new_para = " ".join(parts)
        new_paragraphs.append(new_para)
        out.dropped.extend(d for d in para_dropped if d not in out.dropped)
        if not cited:
            status = "unverified"
        elif any(s.located for s in para_supports):
            status = "supported"
        else:
            status = "not_located"
        out.paragraphs.append(
            {
                "index": p_index,
                "preview": MARKER.sub("", para).strip()[:160],
                "status": status,
                "supports": [s.as_dict() for s in para_supports],
                "dropped_labels": para_dropped,
            }
        )
    out.text_md = "\n\n".join(new_paragraphs)
    return out


def _keep_lines(para: str, refs: dict[str, Ref]) -> str:
    """Multi-line blocks (lists, tables, verse) keep their line breaks; markers become citations per line."""
    lines = []
    for line in para.split("\n"):
        labels = [m.group(1) for m in MARKER.finditer(line)]
        clean = MARKER.sub("", line).rstrip()
        sup = [
            Support(
                lb,
                refs[lb].kind,
                refs[lb].title,
                "",
                False,
                0.0,
                refs[lb].source_id,
                refs[lb].chunk_id,
                refs[lb].citation_key,
                refs[lb].locator,
                refs[lb].answer_id,
            )
            for lb in dict.fromkeys(labels)
            if lb in refs
        ]
        lines.append(clean + _cite(sup))
    return "\n".join(lines)
