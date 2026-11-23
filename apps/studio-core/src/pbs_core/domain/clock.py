"""UTC clock with ISO-8601 'Z' formatting."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime


class Clock:
    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self._now()

    def iso(self) -> str:
        return to_iso(self.now())


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
