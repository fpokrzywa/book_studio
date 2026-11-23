"""Describe an author's style from their own writing. Local, deterministic, no AI.

Every number is computed from the samples, and every example is an exact excerpt. The labels
("conversational", "formal", …) are heuristics and are presented as such; the author edits the
resulting style guide, which is what generation actually uses.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Any

_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+")
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ'’]+")
_CONTRACTION = re.compile(r"\b\w+['’](s|t|re|ve|ll|d|m)\b", re.I)
_FIRST = re.compile(r"\b(I|me|my|mine|myself)\b")
_SECOND = re.compile(r"\b(you|your|yours|yourself)\b", re.I)
_VOWELS = re.compile(r"[aeiouy]+", re.I)


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para or para.startswith(("#", "|", "```")):
            continue
        out.extend(s.strip() for s in _SENT_SPLIT.split(para) if len(_WORD.findall(s)) >= 2)
    return out


def _syllables(word: str) -> int:
    n = len(_VOWELS.findall(word))
    if word.lower().endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def _per(count: int, words: int, per: int = 100) -> float:
    return round(count * per / words, 2) if words else 0.0


def analyze(samples: list[tuple[str, str]]) -> dict[str, Any]:
    """samples: (title, text). Returns metrics, labels, examples and a draft style guide."""
    text = "\n\n".join(t for _, t in samples)
    sents = _sentences(text)
    words = _WORD.findall(text)
    n_words = len(words)
    if n_words < 50 or len(sents) < 3:
        return {
            "enough": False,
            "word_count": n_words,
            "message": "Add at least a few paragraphs (50+ words) of your own writing.",
        }
    lengths = [len(_WORD.findall(s)) for s in sents]
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    lower = [w.lower().strip("'’") for w in words]
    window = lower[:5000]
    contractions = len(_CONTRACTION.findall(text))
    syll = sum(_syllables(w) for w in words)
    flesch = 206.835 - 1.015 * (n_words / len(sents)) - 84.6 * (syll / n_words)
    openers = Counter(s.split()[0].strip('"“‘(').lower() for s in sents if s.split())
    dialogue = sum(1 for p in paragraphs if re.search(r"[\"“][^\"”]{3,}[\"”]", p))
    metrics: dict[str, Any] = {
        "word_count": n_words,
        "sentence_count": len(sents),
        "sentence_words_mean": round(statistics.mean(lengths), 1),
        "sentence_words_median": statistics.median(lengths),
        "sentence_words_stdev": round(statistics.pstdev(lengths), 1),
        "short_sentence_share": round(sum(1 for n in lengths if n <= 8) / len(lengths), 2),
        "long_sentence_share": round(sum(1 for n in lengths if n >= 30) / len(lengths), 2),
        "sentences_per_paragraph": round(len(sents) / max(1, len(paragraphs)), 1),
        "word_length_mean": round(sum(len(w) for w in words) / n_words, 2),
        "vocabulary_variety": round(len(set(window)) / len(window), 2),
        "contractions_per_100_words": _per(contractions, n_words),
        "first_person_per_100_words": _per(len(_FIRST.findall(text)), n_words),
        "second_person_per_100_words": _per(len(_SECOND.findall(text)), n_words),
        "questions_share": round(sum(1 for s in sents if s.rstrip('"”’)').endswith("?")) / len(sents), 2),
        "exclamations_share": round(sum(1 for s in sents if s.rstrip('"”’)').endswith("!")) / len(sents), 2),
        "dialogue_paragraph_share": round(dialogue / max(1, len(paragraphs)), 2),
        "em_dashes_per_1000_words": _per(text.count("—") + text.count(" -- "), n_words, 1000),
        "semicolons_per_1000_words": _per(text.count(";"), n_words, 1000),
        "colons_per_1000_words": _per(text.count(":"), n_words, 1000),
        "parentheses_per_1000_words": _per(text.count("("), n_words, 1000),
        "ly_adverbs_per_100_words": _per(sum(1 for w in lower if len(w) > 4 and w.endswith("ly")), n_words),
        "reading_ease_flesch": round(flesch, 1),
        "common_openers": [w for w, _ in openers.most_common(5)],
    }
    labels = _labels(metrics)
    examples = _examples(samples)
    return {
        "enough": True,
        "metrics": metrics,
        "labels": labels,
        "examples": examples,
        "guide": _guide(metrics, labels),
    }


def _labels(m: dict[str, Any]) -> dict[str, str]:
    informal = m["contractions_per_100_words"] >= 1.5 or m["second_person_per_100_words"] >= 1.5
    formal = m["contractions_per_100_words"] < 0.3 and m["word_length_mean"] >= 4.9
    formality = "conversational" if informal else ("formal" if formal else "neutral")
    mean = m["sentence_words_mean"]
    rhythm = "short and punchy" if mean < 12 else ("long and flowing" if mean > 24 else "medium-length")
    if m["sentence_words_stdev"] >= 9:
        rhythm += ", with strong variation"
    person = (
        "first person"
        if m["first_person_per_100_words"] >= 1.0
        else ("addresses the reader directly" if m["second_person_per_100_words"] >= 1.0 else "mostly third person")
    )
    return {"formality": formality, "rhythm": rhythm, "point_of_view": person}


def _examples(samples: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Exact sentences from the samples: typical ones first, then the shortest and longest."""
    pool = [(title, s, len(_WORD.findall(s))) for title, t in samples for s in _sentences(t)]
    if not pool:
        return []
    median = statistics.median(n for _, _, n in pool)
    typical = sorted(pool, key=lambda x: (abs(x[2] - median), x[1]))[:3]
    picks = [*typical, min(pool, key=lambda x: (x[2], x[1])), max(pool, key=lambda x: (x[2], x[1]))]
    out, seen = [], set()
    for title, s, _ in picks:
        if s not in seen:
            seen.add(s)
            out.append({"sample": title, "text": s[:400]})
    return out


def _guide(m: dict[str, Any], labels: dict[str, str]) -> str:
    def yes(v: float, hi: float, lo: float, a: str, b: str, c: str) -> str:
        return a if v >= hi else (c if v < lo else b)

    lines = [
        "<!-- Drafted from your samples by a heuristic analysis. Edit anything that is not you. -->",
        f"- Tone: {labels['formality']}; point of view: {labels['point_of_view']}.",
        f"- Sentences: {labels['rhythm']} (about {m['sentence_words_mean']} words on average).",
        "- Contractions: "
        + yes(m["contractions_per_100_words"], 1.5, 0.3, "use them freely", "use them sometimes", "avoid them")
        + ".",
        "- Questions to the reader: " + yes(m["questions_share"], 0.08, 0.02, "often", "occasionally", "rarely") + ".",
        "- Em dashes: "
        + yes(m["em_dashes_per_1000_words"], 4, 1, "a favourite", "now and then", "rarely")
        + "; semicolons: "
        + yes(m["semicolons_per_1000_words"], 3, 0.5, "often", "sometimes", "rarely")
        + ".",
        "- Adverbs ending in -ly: "
        + yes(m["ly_adverbs_per_100_words"], 1.5, 0.5, "common", "moderate", "sparing")
        + ".",
    ]
    if m["common_openers"]:
        lines.append("- Frequent sentence openers: " + ", ".join(f"“{w}”" for w in m["common_openers"][:3]) + ".")
    return "\n".join(lines)
