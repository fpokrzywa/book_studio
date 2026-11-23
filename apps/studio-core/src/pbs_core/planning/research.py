"""Research: the market-metric guard and the public-source search adapters.

Personal Book Studio never claims sales rank, market size, demand, competition scores, bestseller
status or search volumes. No adapter here supplies such data, so:

* AI brainstorm text has every sentence that states such a figure removed (and the removal is
  recorded on the finding), and AI output cannot carry metrics at all (DB CHECK);
* text the author types is kept as written, but if it looks like an unsourced market figure the
  finding is flagged and shown as a heuristic note, never as evidence;
* provider results carry only bibliographic metadata the provider returned.

Search adapters run only when the author turns them on (AI settings) and cloud access is allowed;
they go through the egress gate. When one is off, blocked or failing, the request fails with an
explicit message and nothing is added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from pbs_core.providers.research_adapters import ResearchError, ResearchHit, adapter_for

log = structlog.get_logger(__name__)

_METRIC_PATTERNS = [
    r"\bsearch(?:es)?\s+(?:volume|per\s+month|a\s+month)\b",
    r"\b(?:monthly|weekly|daily)\s+searches\b",
    r"\b\d[\d,.]*\s*(?:k|thousand|million)?\s*(?:monthly\s+)?searches\b",
    r"\bBSR\b|\bbest[\s-]?sellers?\s+rank\b|\bsales\s+rank\b|\bamazon\s+rank(?:ing)?\b",
    r"\bbest[\s-]?sell(?:er|ers|ing)\b",
    r"\bmarket\s+(?:size|share|value|is\s+worth|worth)\b",
    r"[$€£]\s?\d[\d,.]*\s?(?:k|m|bn|million|billion)?\b",
    r"\b(?:competition|competitiveness|keyword\s+difficulty|difficulty)\s+(?:score|is\s+(?:low|high|medium))\b",
    r"\b(?:low|high|medium)\s+competition\b",
    r"\b(?:high|strong|growing|huge|low)\s+demand\b|\bdemand\s+(?:is|score)\b",
    r"\b\d[\d,.]*\s*(?:copies|units|sales|buyers)\b",
    r"\b(?:sells|selling|sold)\s+\d",
    r"\b(?:top|#)\s?\d+\s+(?:in|on)\s+(?:amazon|kindle|kdp)\b",
]
METRIC_RE = re.compile("|".join(_METRIC_PATTERNS), re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
FORBIDDEN_NOTE = (
    "Removed a statement about sales, rankings, demand, competition or search volume: no licensed data "
    "source is connected, so such figures cannot be supported."
)


def has_metric_claim(text: str) -> bool:
    return bool(METRIC_RE.search(text or ""))


@dataclass
class Sanitised:
    text: str
    removed: list[str] = field(default_factory=list)


def strip_metric_claims(text: str) -> Sanitised:
    """Drop every sentence that states an unsupported market figure (used on AI output)."""
    kept: list[str] = []
    removed: list[str] = []
    for sentence in _SENTENCE.split((text or "").strip()):
        (removed if has_metric_claim(sentence) else kept).append(sentence)
    return Sanitised(" ".join(kept).strip(), removed)


def provider_search(kind: str, query: str, *, permit: Any, transport: Any = None, limit: int = 10) -> list[ResearchHit]:
    """Raises ResearchError with a user-facing message on any failure. Never invents results."""
    adapter = adapter_for(kind, permit=permit, transport=transport)
    hits = adapter.search(query, limit=limit)
    log.info("research_search", provider=kind, results=len(hits))  # the query text itself is not logged
    return hits


__all__ = [
    "FORBIDDEN_NOTE",
    "ResearchError",
    "ResearchHit",
    "has_metric_claim",
    "provider_search",
    "strip_metric_claims",
]
