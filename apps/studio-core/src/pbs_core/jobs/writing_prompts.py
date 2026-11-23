"""Prompts for the writing pipeline (one section at a time) and the AI quality review.

All book material (brief, outline, earlier text, summaries, continuity notes, style guide, source
passages) goes in random-tag data envelopes, exactly like chapter prompts (jobs/prompts.py).
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from pbs_core.jobs.prompts import CITE_RULES, NO_PERSONAL_INVENTION, SYSTEM, BuiltPrompt, _envelope, neutralise
from pbs_core.knowledge.citations import Ref
from pbs_core.providers.base import extract_json
from pbs_core.storage.writing_models import FACT_KINDS

TEMPLATE_VERSION = "2026-11-22.1"
REVIEW_CHECKS = ("grammar", "clarity", "promise_mismatch", "unsupported_claim", "continuity", "other")

SECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "summary": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(FACT_KINDS)},
                    "name": {"type": "string"},
                    "attribute": {"type": "string"},
                    "value": {"type": "string"},
                    "story_time": {"type": "string"},
                },
                "required": ["kind", "name", "attribute", "value", "story_time"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["text", "summary", "facts"],
    "additionalProperties": False,
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check": {"type": "string", "enum": list(REVIEW_CHECKS)},
                    "quote": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["check", "quote", "message"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def section(
    *,
    book_title: str,
    chapter_title: str,
    section_title: str,
    section_no: int,
    section_count: int,
    goal: str,
    target_words: int | None,
    fiction: bool,
    texts: dict[str, str],
    sources: list[Ref],
    answers: list[Ref],
    exclusions: list[str],
) -> BuiltPrompt:
    tag = secrets.token_hex(6)
    blocks: list[str] = []
    for key, label in (
        ("brief", "book brief"),
        ("outline", "chapter outline (you are writing the marked section)"),
        ("so_far", "this chapter so far"),
        ("summaries", "summaries of earlier chapters"),
        ("continuity", "continuity notes"),
        ("style", "author style guide (style reference only)"),
    ):
        if texts.get(key):
            blocks.append(_envelope(tag, label, texts[key]))
    blocks += [_envelope(tag, f"source {r.label}", r.text, title=r.title, where=r.locator or "") for r in sources]
    blocks += [_envelope(tag, f"interview answer {r.label}", r.text, question=r.title) for r in answers]
    rules = [CITE_RULES] if sources else []
    rules.append(
        "Interview answers are the author's own words: use only experiences that appear in them."
        if answers
        else NO_PERSONAL_INVENTION
    )
    rules.append("Do not repeat or restate text that is already in 'this chapter so far'.")
    rules.append("Do not write the section heading; it is added for you.")
    if exclusions:
        rules.append("Leave out: " + "; ".join(neutralise(x) for x in exclusions) + ".")
    if fiction:
        rules.append(
            "Keep names, traits, places, relationships and the timeline consistent with the continuity notes. "
            "In 'facts', list characters, locations, relationships, events (with story_time when known) and open "
            "story threads that this section introduces or changes."
        )
    else:
        rules.append(
            "Only state facts you can support from the source passages, and cite them. If something needs a source "
            "you do not have, write [source needed] after it. In 'facts', list key terms this section defines "
            "(kind 'term', attribute 'definition')."
        )
    words = f" Aim for about {target_words} words." if target_words else ""
    user = (
        f"Book: {neutralise(book_title)}\nChapter: {neutralise(chapter_title)}\n"
        f"Section title: {neutralise(section_title)}\nSection {section_no} of {section_count}\n\n"
        + "\n\n".join(blocks)
        + f"\n\nWrite section {section_no} of {section_count} of this chapter."
        + (f" Section goal: {neutralise(goal)}." if goal else "")
        + words
        + "\n"
        + "\n".join(rules)
        + "\nReply with JSON only: 'text' is the section in Markdown, 'summary' is two or three sentences on what "
        "the section covers or what happens in it, 'facts' is the list described above (it may be empty)."
    )
    return BuiltPrompt(SYSTEM.format(tag=tag), user, f"section@{TEMPLATE_VERSION}", SECTION_SCHEMA)


def review(
    *,
    book_title: str,
    chapter_title: str,
    text: str,
    fiction: bool,
    brief: str,
    goal: str,
    continuity: str,
    instruction: str,
) -> BuiltPrompt:
    tag = secrets.token_hex(6)
    blocks = [_envelope(tag, "book brief", brief)] if brief else []
    if goal:
        blocks.append(_envelope(tag, "chapter goal from the outline", goal))
    if continuity:
        blocks.append(_envelope(tag, "continuity notes", continuity))
    blocks.append(_envelope(tag, "chapter text", text))
    focus = (
        "grammar, clarity, continuity (names, traits, places, relationships, timeline) and anything that does not "
        "fit the brief"
        if fiction
        else "grammar, clarity, statements of fact that have no citation, and anything that does not deliver the "
        "brief's promise to the reader"
    )
    user = (
        f"Book: {neutralise(book_title)}\nChapter: {neutralise(chapter_title)}\n\n"
        + "\n\n".join(blocks)
        + f"\n\nReview the chapter text as an editor. Look for {focus}. For each problem, copy the exact sentence or "
        "phrase from the chapter text into 'quote' (word for word, so it can be found), and explain the problem "
        "briefly in 'message'. Do not judge whether facts are true; flag what needs checking. Report at most 20 "
        "problems. Reply with JSON only."
        + (f"\nInstruction from the author: {neutralise(instruction)}" if instruction.strip() else "")
    )
    return BuiltPrompt(SYSTEM.format(tag=tag), user, f"review@{TEMPLATE_VERSION}", REVIEW_SCHEMA)


def parse_section(payload: str) -> dict[str, Any]:
    data = extract_json(payload)
    text = str(data["text"]).strip()
    if not text:
        raise ValueError("empty section")
    facts = []
    for f in data.get("facts") or []:
        kind = str(f.get("kind", "")).strip()
        name, value = str(f.get("name", "")).strip(), str(f.get("value", "")).strip()
        if kind in FACT_KINDS and name and value:
            facts.append(
                {
                    "kind": kind,
                    "name": name[:200],
                    "attribute": str(f.get("attribute", "")).strip()[:200],
                    "value": value[:1000],
                    "story_time": str(f.get("story_time", "")).strip()[:100] or None,
                }
            )
    return {"text": text, "summary": str(data.get("summary", "")).strip()[:2000], "facts": facts[:40]}


def parse_review(payload: str) -> list[dict[str, str]]:
    data = extract_json(payload)
    out = []
    for f in data["findings"][:40]:
        check = str(f.get("check", "other"))
        out.append(
            {
                "check": check if check in REVIEW_CHECKS else "other",
                "quote": str(f.get("quote", "")).strip(),
                "message": str(f.get("message", "")).strip()[:1000],
            }
        )
    return out


def dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False)
