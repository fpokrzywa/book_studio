"""Fit a section prompt's context into an explicit token budget, and report what was kept.

Every part has a priority. Required parts (the brief, the local outline, targets and exclusions)
are always sent, trimmed only if they alone exceed the budget. Optional parts follow in priority
order: list-like parts (continuity facts, chapter summaries, source passages) are added item by item
until the budget is used; text parts are trimmed to what is left. The report says, per part, how
many tokens it used and whether it was included, trimmed or dropped. Token counts are estimates
(about four characters per token), and the report says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

CHARS_PER_TOKEN = 4
TRIM_MARK = "\n[… trimmed to fit the token budget …]\n"
MIN_USEFUL_TOKENS = 40


def tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


@dataclass
class Part:
    key: str
    label: str
    text: str = ""
    items: list[str] | None = None  # list-like part: kept item by item, in order
    required: bool = False
    keep: str = "start"  # which end to keep when a text part is trimmed: start | end


@dataclass
class Fitted:
    texts: dict[str, str] = field(default_factory=dict)
    kept_items: dict[str, int] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)


def _trim(text: str, budget_tokens: int, keep: str) -> str:
    limit = max(0, budget_tokens * CHARS_PER_TOKEN - len(TRIM_MARK))
    if len(text) <= budget_tokens * CHARS_PER_TOKEN:
        return text
    return (TRIM_MARK.lstrip("\n") + text[-limit:]) if keep == "end" else (text[:limit] + TRIM_MARK.rstrip("\n"))


def fit(parts: list[Part], budget: int) -> Fitted:
    """Parts are given in priority order (required ones first is not necessary)."""
    out = Fitted()
    rows: list[dict[str, Any]] = []
    used = 0
    required = [p for p in parts if p.required]
    optional = [p for p in parts if not p.required]
    req_total = sum(tokens(p.text) for p in required)
    for p in required:
        text = p.text
        if req_total > budget and text:
            # Share the budget among required parts in proportion to their size.
            share = max(MIN_USEFUL_TOKENS, int(budget * tokens(text) / max(1, req_total)))
            text = _trim(text, share, p.keep)
        out.texts[p.key] = text
        t = tokens(text)
        used += t
        rows.append(
            {
                "key": p.key,
                "label": p.label,
                "required": True,
                "tokens": t,
                "status": "empty" if not p.text else ("trimmed" if text != p.text else "included"),
            }
        )
    for p in optional:
        left = budget - used
        if p.items is not None:
            kept: list[str] = []
            for item in p.items:
                t = tokens(item)
                if t <= left:
                    kept.append(item)
                    left -= t
                else:
                    break
            out.kept_items[p.key] = len(kept)
            out.texts[p.key] = "\n".join(kept)
            t = sum(tokens(x) for x in kept)
            used += t
            total = len(p.items)
            status = (
                "empty" if total == 0 else ("included" if len(kept) == total else ("trimmed" if kept else "dropped"))
            )
            rows.append(
                {
                    "key": p.key,
                    "label": p.label,
                    "required": False,
                    "tokens": t,
                    "status": status,
                    "items_total": total,
                    "items_used": len(kept),
                }
            )
            continue
        if not p.text:
            out.texts[p.key] = ""
            rows.append({"key": p.key, "label": p.label, "required": False, "tokens": 0, "status": "empty"})
            continue
        if tokens(p.text) <= left:
            text, status = p.text, "included"
        elif left >= MIN_USEFUL_TOKENS:
            text, status = _trim(p.text, left, p.keep), "trimmed"
        else:
            text, status = "", "dropped"
        out.texts[p.key] = text
        t = tokens(text)
        used += t
        rows.append({"key": p.key, "label": p.label, "required": False, "tokens": t, "status": status})
    out.report = {
        "budget_tokens": budget,
        "used_tokens": used,
        "is_estimate": True,
        "basis": f"about {CHARS_PER_TOKEN} characters per token",
        "parts": rows,
    }
    return out
