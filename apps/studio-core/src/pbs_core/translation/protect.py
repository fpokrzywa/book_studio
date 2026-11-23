"""Protect everything a translation must not change, and check what it may not lose.

Placeholders (restored byte for byte, as in Phase 06 editor actions) cover: code blocks and inline
code, math, citations ``[@key, p. 3]``, footnote markers ``[^n]`` and footnote labels, link and
image targets ``](…)``, attribute blocks ``{#id .class key="v"}`` (anchors, so cross-references keep
working) and raw HTML tags. Link text, image alt text, headings and prose are translated.

After translation the result is checked for: named entities that must stay as they are, the
author's term map, and the same structure (headings, list items, tables, paragraphs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pbs_core.writing.protect import Masked, mask

_EXTRA = [
    ("citation", re.compile(r"\[-?@[^\]\n]+\]")),
    ("footnote", re.compile(r"\[\^[^\]\n]+\]:?")),
    ("target", re.compile(r"(?<=\])\([^)\n]*\)")),
    ("attributes", re.compile(r"\{[#.][^}\n]*\}|\{[a-z][\w-]*=[^}\n]*\}")),
    ("html", re.compile(r"</?[A-Za-z][^>\n]*>")),
]


def mask_for_translation(text: str) -> Masked:
    m = mask(text)
    for kind, rx in _EXTRA:

        def sub(match: re.Match[str], kind: str = kind) -> str:
            token = f"⟦KEEP-{len(m.spans) + 1}⟧"
            m.spans[token] = match.group(0)
            m.kinds[kind] = m.kinds.get(kind, 0) + 1
            return token

        m.text = rx.sub(sub, m.text)
    return m


@dataclass
class Issue:
    kind: str  # name | terminology | structure | idiom | other
    message: str
    source: str = ""
    target: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "source": self.source,
            "target": self.target,
            "state": "open",
        }


def _count(rx: str, text: str) -> int:
    return len(re.findall(rx, text, re.MULTILINE))


def check(source: str, target: str, names: list[str], term_map: dict[str, str]) -> list[Issue]:
    out: list[Issue] = []
    for n in names:
        if re.search(rf"\b{re.escape(n)}\b", source) and not re.search(rf"\b{re.escape(n)}\b", target):
            out.append(
                Issue(
                    "name",
                    f"The name “{n}” is in the original but not in the translation. Names are kept as they are unless your term list says otherwise.",
                    n,
                )
            )
    for src, dst in term_map.items():
        if src.strip() and re.search(rf"\b{re.escape(src)}\b", source, re.IGNORECASE) and dst.strip() not in target:
            out.append(
                Issue(
                    "terminology",
                    f"“{src}” should be translated as “{dst}” (your term list), but that term is missing.",
                    src,
                    dst,
                )
            )
    for label, rx in (("headings", r"^#{1,6}\s"), ("list items", r"^\s*(?:[-*+]|\d+[.)])\s"), ("table rows", r"^\|")):
        a, b = _count(rx, source), _count(rx, target)
        if a != b:
            out.append(Issue("structure", f"The original has {a} {label}; the translation has {b}."))
    pa = len([p for p in re.split(r"\n\s*\n", source.strip()) if p.strip()])
    pb = len([p for p in re.split(r"\n\s*\n", target.strip()) if p.strip()])
    if abs(pa - pb) > max(1, pa // 10):
        out.append(Issue("structure", f"The original has {pa} paragraphs; the translation has {pb}."))
    return out
