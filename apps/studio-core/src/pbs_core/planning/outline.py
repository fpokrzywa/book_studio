"""Outline trees: validation, stable node IDs, locks, totals and estimated writing work.

A node is a plain dict::

    {"id": "n_<ULID>", "kind": "part|chapter|section|front_matter|back_matter", "title": str,
     "goal": str, "target_words": int | None, "locked": bool, "notes": str,
     "requirements": {...}, "children": [...]}

Rules (same shape as the manuscript tree): top level holds parts, chapters and front/back matter;
a part holds chapters; a chapter holds sections; a section holds nothing. IDs never change once
assigned, which is what lets an approved outline map onto chapters without touching their prose.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from pbs_core.domain.errors import ValidationFailedError

NODE_ID = re.compile(r"^n_[0-9A-HJKMNP-TV-Z]{26}$")
TOP_KINDS = frozenset({"part", "chapter", "front_matter", "back_matter"})
CHILD_KINDS = {
    "part": {"chapter"},
    "chapter": {"section"},
    "section": set(),
    "front_matter": set(),
    "back_matter": set(),
}
MAX_NODES = 500
FICTION_REQ = ("plot_points", "characters", "continuity")


def walk(
    nodes: list[dict[str, Any]], depth: int = 0, parent: str | None = None
) -> Iterator[tuple[dict[str, Any], int, str | None]]:
    for n in nodes:
        yield n, depth, parent
        yield from walk(n.get("children", []), depth + 1, n["id"])


def _clean_list(v: Any, limit: int = 30) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip()[:300] for x in v if str(x).strip()][:limit]


def _requirements(raw: Any, fiction: bool) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    if fiction:
        return {k: _clean_list(raw.get(k)) for k in FICTION_REQ}
    try:
        cmin = max(0, min(50, int(raw.get("citations_min") or 0)))
    except (TypeError, ValueError):
        cmin = 0
    return {
        "citations_min": cmin,
        "source_ids": _clean_list(raw.get("source_ids"), 50),
        "notes": _clean_list(raw.get("notes")),
    }


def normalise(nodes: Any, *, fiction: bool, new_id: Callable[[], str]) -> list[dict[str, Any]]:
    """Validate a tree from a client or a model; keep valid IDs, give new nodes new ones."""
    if not isinstance(nodes, list):
        raise ValidationFailedError("The outline must be a list of nodes.")
    seen: set[str] = set()
    count = 0

    def one(raw: Any, parent_kind: str | None) -> dict[str, Any]:
        nonlocal count
        count += 1
        if count > MAX_NODES:
            raise ValidationFailedError(f"An outline can have at most {MAX_NODES} entries.")
        if not isinstance(raw, dict):
            raise ValidationFailedError("Each outline entry must be an object.")
        kind = str(raw.get("kind") or ("section" if parent_kind == "chapter" else "chapter"))
        allowed = TOP_KINDS if parent_kind is None else CHILD_KINDS.get(parent_kind, set())
        if kind not in allowed:
            where = "at the top level" if parent_kind is None else f"inside a {parent_kind}"
            raise ValidationFailedError(f"A {kind} cannot be placed {where}.")
        nid = str(raw.get("id") or "")
        if not NODE_ID.match(nid) or nid in seen:
            nid = "n_" + new_id()
        seen.add(nid)
        title = " ".join(str(raw.get("title") or "").split())[:300] or "Untitled"
        tw = raw.get("target_words")
        try:
            target = int(tw) if tw not in (None, "") else None
        except (TypeError, ValueError):
            target = None
        if target is not None and not (0 <= target <= 1_000_000):
            target = None
        children = raw.get("children") or []
        if not isinstance(children, list):
            children = []
        return {
            "id": nid,
            "kind": kind,
            "title": title,
            "goal": str(raw.get("goal") or "").strip()[:2000],
            "target_words": target,
            "locked": bool(raw.get("locked")),
            "notes": str(raw.get("notes") or "").strip()[:4000],
            "requirements": _requirements(raw.get("requirements"), fiction),
            "children": [one(c, kind) for c in children],
        }

    return [one(n, None) for n in nodes]


def totals(nodes: list[dict[str, Any]], words_per_hour: int) -> dict[str, Any]:
    """Target words (sections roll up into chapters when a chapter has no own target)."""
    chapters = [n for n, _, _ in walk(nodes) if n["kind"] == "chapter"]

    def words(n: dict[str, Any]) -> int:
        own = n.get("target_words")
        if own:
            return int(own)
        return sum(words(c) for c in n.get("children", []))

    total = sum(words(c) for c in chapters)
    return {
        "chapters": len(chapters),
        "sections": sum(1 for n, _, _ in walk(nodes) if n["kind"] == "section"),
        "target_words": total,
        "estimated_writing_hours": round(total / max(1, words_per_hour), 1),
        "writing_hours_basis": f"Estimate: {words_per_hour} drafted words per hour (change it in the brief).",
    }


def keep_locked(new: list[dict[str, Any]], old: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """A fresh AI outline never replaces nodes the author locked: they are carried over as they were."""
    locked = [(i, n) for i, n in enumerate(old) if n.get("locked")]
    out = [n for n in new if n["id"] not in {x["id"] for _, x in locked}]
    for i, n in locked:
        out.insert(min(i, len(out)), n)
    return out, [n["title"] for _, n in locked]


def node_index(nodes: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], int, str | None]]:
    return {n["id"]: (n, d, p) for n, d, p in walk(nodes)}
