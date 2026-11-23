"""Local, deterministic quality checks over a book's saved chapters. No network, no AI.

Each check returns findings with a stable key, so a finding keeps the author's decision (needs a
source, will fix, dismissed) across re-runs. These are mechanical hints: they find patterns, they
do not judge truth. "Unsupported claim" means "a factual-looking sentence with no citation in its
paragraph", never "false".
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from pbs_core.knowledge.search import STOPWORDS

CHECKS: dict[str, str] = {
    "style": "Style hints (doubled words, very long sentences)",
    "repeated_phrase": "Repeated phrases",
    "duplicate_paragraph": "Duplicated paragraphs",
    "unsupported_claim": "Factual-looking sentences without a citation",
    "missing_citations": "Fewer citations than the outline asks for",
    "outline_mismatch": "Differences from the outline and brief",
    "broken_link": "Broken or unsafe links and images",
    "missing_alt": "Figures without alt text",
    "inconsistent_term": "Terms spelled more than one way",
    "undefined_acronym": "Acronyms used without being spelled out",
    "continuity": "Continuity: conflicting facts, chronology, unresolved threads",
    "code_syntax": "Code snippets that do not parse (syntax only, never run)",
}
NONFICTION_ONLY = {"unsupported_claim", "missing_citations"}
FICTION_ONLY = {"continuity"}

_FENCE = re.compile(r"^(`{3,}|~{3,})([^\n]*)\n([\s\S]*?)^\1[ \t]*$", re.MULTILINE)
_MATH = re.compile(r"\$\$[\s\S]+?\$\$|(?<![\\$\w])\$(?![\s$])[^$\n]+?(?<![\s\\])\$(?![\w$])")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_CITE = re.compile(r"\[@[^\]]+\]|\[\[[SI]\d+\]\]")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]*)(?:\s+\"[^\"]*\")?\)")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+(?=[\"“‘(A-Z0-9])")
_ACRONYM = re.compile(r"\b([A-Z][A-Z0-9]{1,5})(s?)\b")
_ROMAN = re.compile(r"^[IVXLCDM]+$")
_ACRONYM_OK = {"OK", "TV", "US", "UK", "EU", "USA", "AM", "PM", "ID", "PDF", "HTML", "URL", "DIY", "FAQ", "AD", "BC"}

_FACTUAL = [
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|per ?cent\b)", re.IGNORECASE), "a percentage"),
    (re.compile(r"\b(?:in|by|since|from|until|before|after) (?:1[5-9]\d{2}|20\d{2})\b", re.IGNORECASE), "a date"),
    (re.compile(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{4,}\b(?<!\b1[5-9]\d{2}\b)(?<!\b20\d{2}\b)"), "a large number"),
    (
        re.compile(
            r"\b(?:studies|research|experts|scientists|surveys?|data|statistics) "
            r"(?:show|shows|showed|found|find|suggests?|proves?|confirms?)\b",
            re.IGNORECASE,
        ),
        "an appeal to research",
    ),
    (re.compile(r"\baccording to\b", re.IGNORECASE), "an attribution"),
    (re.compile(r"\b(?:proven|clinically|statistically|scientifically)\b", re.IGNORECASE), "a proof claim"),
    (
        re.compile(r"\bthe (?:first|largest|biggest|smallest|oldest|fastest|most|least|only) \w+", re.IGNORECASE),
        "a superlative",
    ),
    (
        re.compile(r"\b(?:double|doubles|doubled|triple|triples|halves|halved)\b", re.IGNORECASE),
        "a quantity claim",
    ),
]


@dataclass
class ChapterIn:
    id: str
    title: str
    text: str
    order: int
    revision_no: int
    target_words: int | None = None
    outline_sections: list[str] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)  # bookmd fidelity warnings
    anchors: set[str] = field(default_factory=set)


@dataclass
class FactIn:
    id: str
    kind: str
    name: str
    attribute: str
    value: str
    story_time: str | None
    chapter_id: str | None
    chapter_order: int
    status: str


@dataclass
class BookIn:
    fiction: bool
    exclusions: list[str]
    chapters: list[ChapterIn]
    known_terms: set[str] = field(default_factory=set)
    facts: list[FactIn] = field(default_factory=list)
    code_check: bool = False


@dataclass
class Finding:
    check: str
    chapter_id: str | None
    severity: str
    message: str
    excerpt: str | None
    key: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.check}|{self.chapter_id or ''}|{self.key}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ---------- text helpers ----------


def prose(text: str) -> str:
    """Chapter text with code and math blanked out (offsets are not needed by the checks)."""
    t = _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    t = _MATH.sub(" ", t)
    return _INLINE_CODE.sub(" ", t)


def paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", prose(text)):
        b = block.strip()
        if not b or b.startswith(("#", "|", ":::", "<!--", "![")) or re.match(r"^\[\^[^\]]+\]:", b):
            continue
        out.append(b)
    return out


def sentences(para: str) -> list[str]:
    one = " ".join(para.split())
    return [s.strip() for s in _SENTENCE_SPLIT.split(one) if s.strip()]


def words(text: str) -> list[str]:
    return [w.lower().strip("'’-") for w in _WORD.findall(_CITE.sub(" ", text))]


def _norm(text: str) -> str:
    return " ".join(words(text))


def _excerpt(text: str, n: int = 220) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def headings(text: str) -> list[str]:
    return [m.group(2).strip() for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*(?:\{[^}]*\})?\s*$", prose(text), re.M)]


# ---------- checks ----------


def check_style(ch: ChapterIn) -> list[Finding]:
    out: list[Finding] = []
    for para in paragraphs(ch.text):
        for m in re.finditer(r"\b([A-Za-z]+)\s+\1\b", para, re.IGNORECASE):
            if m.group(1).lower() in {"had", "that", "is"}:  # often intentional
                continue
            out.append(
                Finding(
                    "style",
                    ch.id,
                    "info",
                    f"Doubled word: “{m.group(0)}”.",
                    _excerpt(para),
                    f"doubled:{m.group(0).lower()}:{_norm(para)[:80]}",
                    {"rule": "doubled_word"},
                )
            )
        for sent in sentences(para):
            n = len(words(sent))
            if n > 45:
                out.append(
                    Finding(
                        "style",
                        ch.id,
                        "info",
                        f"Very long sentence ({n} words). Consider splitting it.",
                        _excerpt(sent),
                        f"long:{_norm(sent)[:120]}",
                        {"rule": "long_sentence", "words": n},
                    )
                )
    return out


def check_repeated_phrases(ch: ChapterIn, n: int = 5, min_count: int = 3) -> list[Finding]:
    toks: list[str] = []
    for para in paragraphs(ch.text):
        toks.extend(words(para))
        toks.append("¶")  # phrases never span paragraphs
    grams: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for i in range(len(toks) - n + 1):
        g = tuple(toks[i : i + n])
        if "¶" in g or sum(1 for w in g if w not in STOPWORDS) < 3:
            continue
        grams[g].append(i)
    reported: set[int] = set()
    out: list[Finding] = []
    for g, pos in sorted(grams.items(), key=lambda kv: (-len(kv[1]), kv[1][0])):
        if len(pos) < min_count or all(p in reported for p in pos):
            continue
        for p in pos:
            reported.update(range(p - n + 1, p + n))
        phrase = " ".join(g)
        out.append(
            Finding(
                "repeated_phrase",
                ch.id,
                "info",
                f"The phrase “{phrase}” appears {len(pos)} times in this chapter.",
                phrase,
                f"phrase:{phrase}",
                {"count": len(pos)},
            )
        )
        if len(out) >= 15:
            break
    return out


def _shingles(ws: list[str], k: int = 3) -> set[tuple[str, ...]]:
    return {tuple(ws[i : i + k]) for i in range(max(0, len(ws) - k + 1))}


def check_duplicates(chs: list[ChapterIn], min_words: int = 12, near: float = 0.8) -> list[Finding]:
    items: list[tuple[ChapterIn, int, str, list[str]]] = []
    for ch in chs:
        for i, para in enumerate(paragraphs(ch.text)):
            ws = words(para)
            if len(ws) >= min_words:
                items.append((ch, i, para, ws))
    items = items[:3000]
    out: list[Finding] = []
    seen_pairs: set[tuple[int, int]] = set()
    by_norm: dict[str, list[int]] = defaultdict(list)
    for idx, (_, _, _, ws) in enumerate(items):
        by_norm[" ".join(ws)].append(idx)
    for norm, idxs in by_norm.items():
        if len(idxs) < 2:
            continue
        first = items[idxs[0]]
        where = [
            {"chapter_id": items[j][0].id, "chapter": items[j][0].title, "paragraph": items[j][1] + 1} for j in idxs
        ]
        for a in idxs:
            for b in idxs:
                if a < b:
                    seen_pairs.add((a, b))
        out.append(
            Finding(
                "duplicate_paragraph",
                first[0].id,
                "warning",
                f"The same paragraph appears {len(idxs)} times: "
                + "; ".join(f"“{w['chapter']}”, paragraph {w['paragraph']}" for w in where)
                + ".",
                _excerpt(first[2]),
                f"dup:{hashlib.sha256(norm.encode()).hexdigest()[:16]}",
                {"locations": where, "similarity": 1.0},
            )
        )
    sh = [_shingles(ws) for (_, _, _, ws) in items]
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if (a, b) in seen_pairs or not sh[a] or not sh[b]:
                continue
            sim = len(sh[a] & sh[b]) / len(sh[a] | sh[b])
            if sim >= near:
                ca, cb = items[a], items[b]
                where = [
                    {"chapter_id": ca[0].id, "chapter": ca[0].title, "paragraph": ca[1] + 1},
                    {"chapter_id": cb[0].id, "chapter": cb[0].title, "paragraph": cb[1] + 1},
                ]
                key = hashlib.sha256((" ".join(ca[3]) + "|" + " ".join(cb[3])).encode()).hexdigest()[:16]
                out.append(
                    Finding(
                        "duplicate_paragraph",
                        ca[0].id,
                        "warning",
                        f"Two nearly identical paragraphs ({round(sim * 100)}% the same wording): "
                        f"“{ca[0].title}”, paragraph {ca[1] + 1} and “{cb[0].title}”, paragraph {cb[1] + 1}.",
                        _excerpt(ca[2]),
                        f"near:{key}",
                        {"locations": where, "similarity": round(sim, 2)},
                    )
                )
    return out


def check_unsupported(ch: ChapterIn) -> list[Finding]:
    out: list[Finding] = []
    for para in paragraphs(ch.text):
        if _CITE.search(para) or para.startswith(">"):
            continue
        for sent in sentences(para):
            reasons = [label for rx, label in _FACTUAL if rx.search(sent)]
            if not reasons:
                continue
            out.append(
                Finding(
                    "unsupported_claim",
                    ch.id,
                    "warning",
                    "This sentence states a fact (" + ", ".join(dict.fromkeys(reasons)) + ") but its paragraph has "
                    "no citation. Add a source, or mark it as reviewed.",
                    _excerpt(sent),
                    f"claim:{_norm(sent)[:160]}",
                    {"signals": list(dict.fromkeys(reasons))},
                )
            )
    return out


def check_citations_required(ch: ChapterIn) -> list[Finding]:
    need = int(ch.requirements.get("citations_min") or 0)
    if not need or not ch.text.strip():
        return []
    found = len(re.findall(r"\[@[^\]]+\]", ch.text))
    if found >= need:
        return []
    return [
        Finding(
            "missing_citations",
            ch.id,
            "warning",
            f"The outline asks for at least {need} cited statement(s); this chapter has {found}.",
            None,
            "citations_min",
            {"required": need, "found": found},
        )
    ]


def check_outline(ch: ChapterIn, exclusions: list[str]) -> list[Finding]:
    out: list[Finding] = []
    if not ch.text.strip():
        return out
    have = {_norm(h) for h in headings(ch.text)}
    for title in ch.outline_sections:
        if _norm(title) and _norm(title) not in have:
            out.append(
                Finding(
                    "outline_mismatch",
                    ch.id,
                    "info",
                    f"The outline has a section “{title}”, but the chapter has no heading with that title.",
                    None,
                    f"section:{_norm(title)}",
                    {"rule": "missing_section"},
                )
            )
    n = len(words(prose(ch.text)))
    if ch.target_words and (n < ch.target_words * 0.5 or n > ch.target_words * 1.5):
        out.append(
            Finding(
                "outline_mismatch",
                ch.id,
                "info",
                f"The chapter has {n:,} words; the outline target is {ch.target_words:,}.",
                None,
                "target_words",
                {"rule": "length", "words": n, "target": ch.target_words},
            )
        )
    low = " ".join(prose(ch.text).lower().split())
    for ex in exclusions:
        term = " ".join(ex.lower().split())
        if len(term) >= 3 and re.search(rf"\b{re.escape(term)}\b", low):
            out.append(
                Finding(
                    "outline_mismatch",
                    ch.id,
                    "warning",
                    f"The brief says to leave out “{ex}”, but the chapter mentions it.",
                    None,
                    f"exclusion:{term}",
                    {"rule": "excluded_topic"},
                )
            )
    return out


def check_links(ch: ChapterIn, anchors: set[str]) -> list[Finding]:
    out: list[Finding] = []
    for m in _LINK.finditer(prose(ch.text)):
        label, href = m.group(1), m.group(2)
        problem = None
        if href.startswith("#"):
            if href[1:] not in anchors:
                problem = f"points to #{href[1:]}, which no heading or block in the book has."
        elif re.match(r"(?i)^https?:", href):
            if not re.match(r"(?i)^https?://[^/\s.]+\.[^/\s]+", href):
                problem = "is not a complete web address."
        elif not href:
            problem = "has no address."
        if problem:
            out.append(
                Finding(
                    "broken_link",
                    ch.id,
                    "warning",
                    f"The link “{label or href}” {problem} (Web links are not visited; only their form is checked.)",
                    _excerpt(m.group(0)),
                    f"link:{href}:{label}",
                )
            )
    for w in ch.warnings:
        if w.get("code") in ("unsafe_link", "unresolved_image", "external_image"):
            out.append(
                Finding(
                    "broken_link",
                    ch.id,
                    "warning",
                    str(w.get("message")),
                    None,
                    f"warn:{w.get('code')}:{w.get('line')}:{w.get('message')}",
                    {"line": w.get("line")},
                )
            )
    return out


def check_alt(ch: ChapterIn) -> list[Finding]:
    return [
        Finding(
            "missing_alt",
            ch.id,
            "warning",
            str(w.get("message")) + (f" (line {w['line']})" if w.get("line") else ""),
            None,
            f"alt:{w.get('line')}",
            {"line": w.get("line")},
        )
        for w in ch.warnings
        if w.get("code") == "missing_alt"
    ]


def check_terms(chs: list[ChapterIn]) -> list[Finding]:
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    first: dict[str, str] = {}
    for ch in chs:
        text = prose(ch.text)
        for w in _WORD.findall(_CITE.sub(" ", text)):
            if "-" in w.strip("-"):
                key = w.replace("-", "").lower()
                spellings[key][w.lower()] += 1
                first.setdefault(key, ch.id)
        for a, b in re.findall(r"\b([A-Za-z]{2,})[ ]([A-Za-z]{2,})\b", text):
            key = (a + b).lower()
            if key in spellings:
                spellings[key][f"{a} {b}".lower()] += 1
    for ch in chs:
        for w in _WORD.findall(_CITE.sub(" ", prose(ch.text))):
            key = w.lower()
            if key in spellings and "-" not in w:
                spellings[key][key] += 1
    out: list[Finding] = []
    for key, forms in spellings.items():
        if len(forms) < 2:
            continue
        listed = ", ".join(f"“{f}” ({n}×)" for f, n in forms.most_common())
        out.append(
            Finding(
                "inconsistent_term",
                first.get(key),
                "info",
                f"This term is spelled more than one way: {listed}. Pick one.",
                None,
                f"term:{key}",
                {"forms": dict(forms)},
            )
        )
    return out


def check_acronyms(chs: list[ChapterIn], known: set[str]) -> list[Finding]:
    full = "\n".join(prose(c.text) for c in sorted(chs, key=lambda c: c.order))
    defined = set(re.findall(r"\(([A-Z][A-Z0-9]{1,5})s?\)", full))
    defined |= set(re.findall(r"\b([A-Z][A-Z0-9]{1,5})s? \((?:[A-Za-z][\w'-]*\s?){2,}\)", full))
    defined |= {k.upper() for k in known}
    out: list[Finding] = []
    seen: set[str] = set()
    for ch in sorted(chs, key=lambda c: c.order):
        for para in paragraphs(ch.text):
            for m in _ACRONYM.finditer(para):
                acr = m.group(1)
                if acr in seen or acr in defined or acr in _ACRONYM_OK or _ROMAN.match(acr) or acr.isdigit():
                    continue
                if not any(c.isalpha() for c in acr):
                    continue
                seen.add(acr)
                out.append(
                    Finding(
                        "undefined_acronym",
                        ch.id,
                        "info",
                        f"“{acr}” is used but never spelled out (for example “Full Name ({acr})”).",
                        _excerpt(para),
                        f"acronym:{acr}",
                    )
                )
    return out


def _year(text: str | None) -> int | None:
    m = re.search(r"\b(\d{3,4})\b", text or "")
    return int(m.group(1)) if m else None


def check_continuity(book: BookIn) -> list[Finding]:
    out: list[Finding] = []
    live = [f for f in book.facts if f.status != "rejected"]
    groups: dict[tuple[str, str, str], list[FactIn]] = defaultdict(list)
    for f in live:
        if f.attribute and f.kind in ("character", "location", "relationship", "term", "other"):
            groups[(f.kind, f.name.lower(), f.attribute.lower())].append(f)
    for (kind, name, attr), facts in groups.items():
        values = {" ".join(f.value.lower().split()) for f in facts}
        if len(values) > 1:
            listed = "; ".join(
                f"“{f.value}” ({'confirmed' if f.status == 'confirmed' else 'from a draft'})" for f in facts
            )
            out.append(
                Finding(
                    "continuity",
                    facts[-1].chapter_id,
                    "warning",
                    f"{facts[0].name}: “{facts[0].attribute}” has different values: {listed}.",
                    None,
                    f"conflict:{kind}:{name}:{attr}",
                    {"rule": "conflicting_fact", "fact_ids": [f.id for f in facts]},
                )
            )
    events = sorted((f for f in live if f.kind == "event" and _year(f.story_time)), key=lambda f: f.chapter_order)
    latest: FactIn | None = None
    for ev in events:
        if latest is not None and (_year(ev.story_time) or 0) < (_year(latest.story_time) or 0):
            out.append(
                Finding(
                    "continuity",
                    ev.chapter_id,
                    "info",
                    f"Possible chronology issue: “{ev.name}” ({ev.story_time}) comes after “{latest.name}” "
                    f"({latest.story_time}) in the book. Fine if it is a flashback.",
                    None,
                    f"chronology:{ev.id}",
                    {"rule": "chronology"},
                )
            )
        if latest is None or (_year(ev.story_time) or 0) >= (_year(latest.story_time) or 0):
            latest = ev
    for f in live:
        if f.kind == "thread" and f.status in ("proposed", "confirmed"):
            out.append(
                Finding(
                    "continuity",
                    f.chapter_id,
                    "info",
                    f"Open story thread: {f.name}: {f.value}. Resolve it or mark it resolved in the story bible.",
                    None,
                    f"thread:{f.id}",
                    {"rule": "unresolved_thread"},
                )
            )
    return out


def check_code(ch: ChapterIn) -> list[Finding]:
    out: list[Finding] = []
    for i, m in enumerate(_FENCE.finditer(ch.text)):
        lang = (m.group(2) or "").strip().split()[0].lower().strip("{.") if (m.group(2) or "").strip() else ""
        body = m.group(3)
        err = None
        if lang in ("python", "py"):
            try:
                ast.parse(body)  # parse only: the code is never executed
            except SyntaxError as exc:
                err = f"Python syntax error on line {exc.lineno}: {exc.msg}."
        elif lang == "json":
            try:
                json.loads(body)
            except ValueError as exc:
                err = f"JSON does not parse: {exc}."
        else:
            continue
        if err:
            out.append(
                Finding(
                    "code_syntax",
                    ch.id,
                    "warning",
                    err + " (Checked by parsing only; the code was not run.)",
                    _excerpt(body, 160),
                    f"code:{i}:{hashlib.sha256(body.encode()).hexdigest()[:12]}",
                    {"language": lang},
                )
            )
    return out


def run(book: BookIn, checks: set[str] | None = None) -> tuple[list[Finding], list[str]]:
    """Run the chosen checks. Returns findings and the checks that actually ran."""
    wanted = set(checks or CHECKS)
    if book.fiction:
        wanted -= NONFICTION_ONLY
    else:
        wanted -= FICTION_ONLY
    if not book.code_check:
        wanted.discard("code_syntax")
    anchors: set[str] = set()
    for ch in book.chapters:
        anchors |= ch.anchors
    out: list[Finding] = []
    for ch in book.chapters:
        if "style" in wanted:
            out += check_style(ch)
        if "repeated_phrase" in wanted:
            out += check_repeated_phrases(ch)
        if "unsupported_claim" in wanted:
            out += check_unsupported(ch)
        if "missing_citations" in wanted:
            out += check_citations_required(ch)
        if "outline_mismatch" in wanted:
            out += check_outline(ch, book.exclusions)
        if "broken_link" in wanted:
            out += check_links(ch, anchors)
        if "missing_alt" in wanted:
            out += check_alt(ch)
        if "code_syntax" in wanted:
            out += check_code(ch)
    if "duplicate_paragraph" in wanted:
        out += check_duplicates(book.chapters)
    if "inconsistent_term" in wanted:
        out += check_terms(book.chapters)
    if "undefined_acronym" in wanted:
        out += check_acronyms(book.chapters, book.known_terms)
    if "continuity" in wanted:
        out += check_continuity(book)
    # One finding per fingerprint (the same sentence can trip two rules).
    unique: dict[str, Finding] = {}
    for f in out:
        unique.setdefault(f.fingerprint, f)
    return list(unique.values()), sorted(wanted)
