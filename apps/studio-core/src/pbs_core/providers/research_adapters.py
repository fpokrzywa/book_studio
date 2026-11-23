"""Public-source research adapters. All traffic goes through the egress gate.

* ``openlibrary``: Open Library search API (https://openlibrary.org/dev/docs/api/search), checked
  2026-11-22: ``GET https://openlibrary.org/search.json?q=…&fields=…&limit=…`` returning
  ``{"docs": [{"key", "title", "author_name", "first_publish_year", "publisher", "edition_count",
  "subject"}]}``. Only bibliographic metadata is requested and kept. Open Library's own reading-log
  counts and ratings are deliberately not requested: they are not sales or demand data.
* ``mock``: a deterministic offline catalogue for tests and demos; every title says it is not real.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx2

from pbs_core.providers.egress import EgressBlockedError, EgressPermit, check, gated_client

OPENLIBRARY_URL = "https://openlibrary.org/search.json"
OPENLIBRARY_FIELDS = "key,title,author_name,first_publish_year,publisher,edition_count,subject"
USER_AGENT = "PersonalBookStudio/0.1 (local desktop app)"
LABELS = {
    "openlibrary": "Open Library (public book metadata)",
    "mock": "Built-in test catalogue (not real data)",
}


class ResearchError(RuntimeError):
    """Search could not be done. `code` is one of: not_configured, blocked, unavailable, bad_response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ResearchHit:
    title: str
    url: str | None
    authors: list[str] = field(default_factory=list)
    year: str | None = None
    publisher: str | None = None
    subjects: list[str] = field(default_factory=list)
    editions: int | None = None
    source_label: str = ""


class ResearchAdapter(Protocol):
    def search(self, query: str, *, limit: int) -> list[ResearchHit]: ...


class OpenLibraryAdapter:
    def __init__(self, permit: EgressPermit, transport: httpx2.BaseTransport | None = None) -> None:
        self.permit = permit
        self._http = gated_client(permit, transport=transport, timeout=20.0)

    def search(self, query: str, *, limit: int) -> list[ResearchHit]:
        try:
            check(OPENLIBRARY_URL, self.permit)
            resp = self._http.get(
                OPENLIBRARY_URL,
                params={"q": query, "fields": OPENLIBRARY_FIELDS, "limit": max(1, min(limit, 20))},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
        except EgressBlockedError as exc:
            raise ResearchError("blocked", str(exc)) from exc
        except httpx2.HTTPError as exc:
            cause = exc.__cause__
            if isinstance(cause, EgressBlockedError):
                raise ResearchError("blocked", str(cause)) from exc
            raise ResearchError("unavailable", "Open Library could not be reached. Nothing was added.") from exc
        if resp.status_code != 200:
            raise ResearchError(
                "unavailable", f"Open Library answered with an error ({resp.status_code}). Nothing was added."
            )
        try:
            docs = resp.json().get("docs", [])
        except ValueError as exc:
            raise ResearchError(
                "bad_response", "Open Library sent a reply that could not be read. Nothing was added."
            ) from exc
        hits = []
        for d in docs[:limit]:
            if not isinstance(d, dict) or not d.get("title"):
                continue
            key = str(d.get("key") or "")
            year = d.get("first_publish_year")
            editions = d.get("edition_count")
            hits.append(
                ResearchHit(
                    title=str(d["title"])[:300],
                    url=f"https://openlibrary.org{key}" if key.startswith("/works/") else None,
                    authors=[str(a)[:120] for a in (d.get("author_name") or [])][:10],
                    year=str(year) if isinstance(year, int) else None,
                    publisher=str((d.get("publisher") or [None])[0])[:200] if d.get("publisher") else None,
                    subjects=[str(x)[:80] for x in (d.get("subject") or [])][:8],
                    editions=editions if isinstance(editions, int) else None,
                    source_label=LABELS["openlibrary"],
                )
            )
        return hits


class MockResearchAdapter:
    """Deterministic, offline. `fail` in the query simulates an unreachable provider."""

    def search(self, query: str, *, limit: int) -> list[ResearchHit]:
        if "[[research:down]]" in query:
            raise ResearchError("unavailable", "The test catalogue is unavailable (simulated). Nothing was added.")
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:6]
        return [
            ResearchHit(
                title=f"Test title {i} about {query[:40]} (not a real book)",
                url=None,
                authors=[f"Test Author {i}"],
                year=None,
                publisher=None,
                subjects=["test data"],
                editions=None,
                source_label=f"{LABELS['mock']} #{key}",
            )
            for i in range(1, min(limit, 3) + 1)
        ]


def adapter_for(kind: str, *, permit: Any, transport: Any = None) -> ResearchAdapter:
    if kind == "openlibrary":
        return OpenLibraryAdapter(permit, transport)
    if kind == "mock":
        return MockResearchAdapter()
    raise ResearchError("not_configured", f"Unknown research provider {kind!r}.")
