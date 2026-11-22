"""Side-by-side text comparison with word-level highlighting (pure, deterministic)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

_TOKEN = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


@dataclass
class Segment:
    text: str
    changed: bool


@dataclass
class Row:
    kind: str  # equal | replace | insert | delete
    left_no: int | None
    right_no: int | None
    left: list[Segment] = field(default_factory=list)
    right: list[Segment] = field(default_factory=list)


def _word_segments(a: str, b: str) -> tuple[list[Segment], list[Segment]]:
    ta, tb = _TOKEN.findall(a), _TOKEN.findall(b)
    sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
    left: list[Segment] = []
    right: list[Segment] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            left.append(Segment("".join(ta[i1:i2]), False))
            right.append(Segment("".join(tb[j1:j2]), False))
        else:
            if i2 > i1:
                left.append(Segment("".join(ta[i1:i2]), True))
            if j2 > j1:
                right.append(Segment("".join(tb[j1:j2]), True))
    return _merge(left), _merge(right)


def _merge(segs: list[Segment]) -> list[Segment]:
    out: list[Segment] = []
    for s in segs:
        if out and out[-1].changed == s.changed:
            out[-1] = Segment(out[-1].text + s.text, s.changed)
        elif s.text:
            out.append(s)
    return out


def side_by_side(old: str, new: str) -> list[Row]:
    a, b = old.split("\n"), new.split("\n")
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    rows: list[Row] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                rows.append(
                    Row("equal", i1 + k + 1, j1 + k + 1, [Segment(a[i1 + k], False)], [Segment(b[j1 + k], False)])
                )
        elif op == "delete":
            for k in range(i1, i2):
                rows.append(Row("delete", k + 1, None, [Segment(a[k], True)], []))
        elif op == "insert":
            for k in range(j1, j2):
                rows.append(Row("insert", None, k + 1, [], [Segment(b[k], True)]))
        else:  # replace: pair lines, then emit leftovers
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                li, rj = i1 + k, j1 + k
                if li < i2 and rj < j2:
                    left, right = _word_segments(a[li], b[rj])
                    rows.append(Row("replace", li + 1, rj + 1, left, right))
                elif li < i2:
                    rows.append(Row("delete", li + 1, None, [Segment(a[li], True)], []))
                else:
                    rows.append(Row("insert", None, rj + 1, [], [Segment(b[rj], True)]))
    return rows
