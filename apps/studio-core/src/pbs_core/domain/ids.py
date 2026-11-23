"""ULID generation (time-sortable, 26-char Crockford base32)."""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_RAND_MAX = (1 << 80) - 1


def _encode(value: int) -> str:
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


class UlidFactory:
    """Monotonic ULID factory. The clock is injectable for deterministic tests."""

    def __init__(self, clock_ms: Callable[[], int] | None = None) -> None:
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._lock = threading.Lock()
        self._last_ms = -1
        self._last_rand = 0

    def new(self) -> str:
        with self._lock:
            ms = self._clock_ms()
            if ms <= self._last_ms:
                ms = self._last_ms
                rand = self._last_rand + 1
                if rand > _RAND_MAX:
                    ms += 1
                    rand = int.from_bytes(os.urandom(10), "big") >> 1
            else:
                rand = int.from_bytes(os.urandom(10), "big") >> 1  # headroom for increments
            self._last_ms, self._last_rand = ms, rand
        return _encode((ms << 80) | rand)


def is_ulid(value: str) -> bool:
    return bool(ULID_RE.match(value))
