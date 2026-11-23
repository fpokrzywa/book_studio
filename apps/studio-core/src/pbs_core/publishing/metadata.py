"""Publishing metadata for the KDP handoff: checks, JSON and a copy-paste text version.

Categories are only suggestions until the author checks them in KDP's own category picker, and
keywords are the author's. PBS adds no claims (sales rank, "bestseller", prices, reviews).
"""

from __future__ import annotations

import re
from typing import Any

from pbs_core.publishing import kdp_rules

AI_CHOICES = {"none": "No AI was used", "assisted": "AI-assisted only", "generated": "Contains AI-generated content"}


def defaults(title: str, subtitle: str | None, author: str | None, language: str) -> dict[str, Any]:
    return {
        "description": "",
        "keywords": [""] * kdp_rules.KEYWORD_SLOTS,
        "categories": [],
        "age_min": None,
        "age_max": None,
        "language": language,
        "formats": ["paperback", "ebook"],
        "ai_disclosure": {"text": "", "images": "", "translation": ""},
        "contributors": [],
    }


def check(
    meta: dict[str, Any], title: str, subtitle: str | None, author: str | None, ai_evidence: dict[str, Any]
) -> list[dict[str, str]]:
    a = "Metadata"
    out: list[dict[str, str]] = []

    def it(check_: str, status: str, detail: str) -> None:
        out.append({"area": a, "check": check_, "status": status, "detail": detail})

    full = title + (f": {subtitle}" if subtitle else "")
    it("Title and subtitle length", "pass" if len(full) <= kdp_rules.TITLE_SUBTITLE_MAX else "fail",
       f"{len(full)} characters together (KDP: fewer than 200).")  # fmt: skip
    bad = [w for w in kdp_rules.METADATA_FORBIDDEN if re.search(rf"\b{re.escape(w)}\b", full.lower())]
    if bad:
        it("Title wording", "fail", "KDP does not allow these in titles: " + ", ".join(bad))
    it("Author", "pass" if author else "fail", f"Author: {author}" if author else "No author name.")
    desc = (meta.get("description") or "").strip()
    if not desc:
        it("Description", "warn", "No description yet.")
    else:
        flags = []
        if re.search(r"https?://|www\.", desc):
            flags.append("a web address")
        if re.search(r"[\w.+-]+@[\w-]+\.\w+", desc):
            flags.append("an email address")
        if re.search(r"\+?\d[\d\s().-]{7,}\d", desc):
            flags.append("what looks like a phone number")
        flags += [f"“{w}”" for w in kdp_rules.METADATA_FORBIDDEN if re.search(rf"\b{re.escape(w)}\b", desc.lower())]
        it(
            "Description",
            "fail" if flags else "pass",
            ("KDP does not allow " + ", ".join(flags) + " in descriptions.") if flags else f"{len(desc)} characters.",
        )
    kws = [k.strip() for k in meta.get("keywords") or [] if k and k.strip()]
    if len(kws) > kdp_rules.KEYWORD_SLOTS:
        it("Keywords", "fail", f"{len(kws)} keywords; KDP takes up to {kdp_rules.KEYWORD_SLOTS}.")
    else:
        issues = []
        for k in kws:
            low = k.lower()
            if any(re.search(rf"\b{re.escape(w)}\b", low) for w in kdp_rules.METADATA_FORBIDDEN):
                issues.append(f"“{k}” makes a sales or promotional claim")
            if '"' in k or "<" in k:
                issues.append(f"“{k}” has quotes or HTML")
            if low in full.lower() or (author and low in author.lower()):
                issues.append(f"“{k}” repeats the title or author (wasted slot)")
        it("Keywords", "warn" if issues or not kws else "pass",
           ("; ".join(issues)) if issues else (f"{len(kws)} of {kdp_rules.KEYWORD_SLOTS} keyword slots used." if kws else "No keywords yet."))  # fmt: skip
    cats = meta.get("categories") or []
    if len(cats) > kdp_rules.CATEGORY_MAX:
        it("Categories", "fail", f"{len(cats)} categories; KDP lets you choose up to {kdp_rules.CATEGORY_MAX}.")
    else:
        it(
            "Categories",
            "manual",
            f"{len(cats)} suggestion(s), unverified: choose them in KDP's category picker, which lists what exists today.",
        )
    lo, hi = meta.get("age_min"), meta.get("age_max")
    if lo is not None and hi is not None and lo > hi:
        it("Age range", "fail", "The youngest age is above the oldest.")
    ai = meta.get("ai_disclosure") or {}
    unanswered = [k for k in ("text", "images", "translation") if not ai.get(k)]
    detail = (
        "Answer the AI questions for text, images and translations. " if unanswered else "Answered. "
    ) + kdp_rules.AI_DEFINITIONS["ai_generated"]
    if ai_evidence.get("ai_revisions"):
        detail += (
            f" PBS recorded {ai_evidence['ai_revisions']} chapter revision(s) made from AI suggestions you accepted."
        )
    if ai.get("text") == "none" and ai_evidence.get("ai_revisions"):
        it("AI disclosure", "warn", detail + " You answered that no AI was used for text; check that answer.")
    else:
        it("AI disclosure", "warn" if unanswered else "pass", detail)
    return out


def as_text(meta: dict[str, Any], title: str, subtitle: str | None, author: str | None) -> str:
    kws = [k for k in meta.get("keywords") or [] if k and k.strip()]
    ai = meta.get("ai_disclosure") or {}
    lines = [
        f"Title: {title}",
        f"Subtitle: {subtitle or ''}",
        f"Author: {author or ''}",
        f"Language: {meta.get('language') or ''}",
        f"Formats: {', '.join(meta.get('formats') or [])}",
        "",
        "Description:",
        (meta.get("description") or "").strip() or "(none yet)",
        "",
        "Keywords (one per KDP box):",
        *[f"  {i + 1}. {k}" for i, k in enumerate(kws)],
        "",
        "Category suggestions (UNVERIFIED: choose real categories in KDP's picker):",
        *[f"  - {c.get('text') if isinstance(c, dict) else c}" for c in meta.get("categories") or []],
        "",
        f"Reading age: {meta.get('age_min') or '-'} to {meta.get('age_max') or '-'}",
        "",
        "AI disclosure (KDP asks about text, images and translations):",
        f"  Text: {AI_CHOICES.get(ai.get('text') or '', 'not answered')}",
        f"  Images: {AI_CHOICES.get(ai.get('images') or '', 'not answered')}",
        f"  Translations: {AI_CHOICES.get(ai.get('translation') or '', 'not answered')}",
        "",
        "AI-generated: " + kdp_rules.AI_DEFINITIONS["ai_generated"],
        "AI-assisted: " + kdp_rules.AI_DEFINITIONS["ai_assisted"],
        f"Source: {kdp_rules.SOURCES['content_guidelines_ai']} (checked {kdp_rules.CHECKED_ON})",
    ]
    return "\n".join(lines) + "\n"
