"""Word counting for prose (code blocks excluded by callers)."""

from __future__ import annotations

import re

_WORD = re.compile(r"[\w][\w'\u2019\-]*", re.UNICODE)


def count_words(text: str) -> int:
    return len(_WORD.findall(text))
