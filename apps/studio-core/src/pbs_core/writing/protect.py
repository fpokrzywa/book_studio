"""Keep code blocks and math exactly as written when AI edits a passage.

Before a passage is sent for an editor action, every fenced code block, inline code span and math
span is replaced by a numbered placeholder the model cannot alter meaningfully. Afterwards each
placeholder must appear exactly once; the originals are put back byte for byte. A reply that drops,
repeats or invents a placeholder is rejected as invalid output (and retried), so a suggestion can
never silently change an equation or a code listing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\1[ \t]*$", re.MULTILINE)
_DISPLAY_MATH = re.compile(r"\$\$[\s\S]+?\$\$")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_INLINE_MATH = re.compile(r"(?<![\\$\w])\$(?![\s$])[^$\n]+?(?<![\s\\])\$(?![\w$])")
_PLACEHOLDER = re.compile(r"⟦KEEP-(\d+)⟧")


@dataclass
class Masked:
    text: str
    spans: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, int] = field(default_factory=dict)


class ProtectedContentChanged(Exception):
    def __init__(self, missing: list[str], repeated: list[str], unknown: list[str]) -> None:
        self.missing, self.repeated, self.unknown = missing, repeated, unknown
        super().__init__("protected content changed")


def mask(text: str) -> Masked:
    out = Masked(text=text)
    for kind, rx in (("code_block", _FENCE), ("math", _DISPLAY_MATH), ("code", _INLINE_CODE), ("math", _INLINE_MATH)):

        def sub(m: re.Match[str], kind: str = kind) -> str:
            token = f"⟦KEEP-{len(out.spans) + 1}⟧"
            out.spans[token] = m.group(0)
            out.kinds[kind] = out.kinds.get(kind, 0) + 1
            return token

        out.text = rx.sub(sub, out.text)
    return out


def unmask(text: str, masked: Masked) -> str:
    seen = [f"⟦KEEP-{m.group(1)}⟧" for m in _PLACEHOLDER.finditer(text)]
    missing = [t for t in masked.spans if t not in seen]
    repeated = sorted({t for t in seen if seen.count(t) > 1})
    unknown = sorted({t for t in seen if t not in masked.spans})
    if missing or repeated or unknown:
        raise ProtectedContentChanged(missing, repeated, unknown)
    return _PLACEHOLDER.sub(lambda m: masked.spans[f"⟦KEEP-{m.group(1)}⟧"], text)


def summary(masked: Masked) -> dict[str, int]:
    return {"protected_spans": len(masked.spans), **masked.kinds}
