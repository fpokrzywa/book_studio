"""How the built-in test model (not AI) answers when a prompt carries sources or interview answers.

It cites the way a well-behaved model should, so the citation pipeline can be tested offline:
``[[mock:fake_cite]]`` adds a citation to a passage that was never provided, and ``[[mock:obey]]``
simulates a compromised model that repeats a source passage verbatim (including any injected text).
"""

from __future__ import annotations

import re

_ENVELOPE = re.compile(
    r'<pbs-data-[0-9a-f]+ label="(source S\d+|interview answer I\d+)"[^>]*>\n(.*?)\n</pbs-data-', re.S
)


def _first_sentence(text: str) -> str:
    one = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", one)
    return (m.group(1) if m else one)[:300]


def with_knowledge(text: str, prompt: str) -> str:
    found = _ENVELOPE.findall(prompt)
    if not found:
        return text
    paras = [text]
    sources = [(lbl.split()[-1], body) for lbl, body in found if lbl.startswith("source")]
    answers = [(lbl.split()[-1], body) for lbl, body in found if lbl.startswith("interview")]
    if sources:
        label, body = sources[0]
        line = f"The source says: {_first_sentence(body)} [[{label}]]"
        if "[[mock:fake_cite]]" in prompt:
            line += " A further detail comes from elsewhere. [[S9]]"
        paras.append(line)
    if answers:
        label, body = answers[0]
        paras.append(f"In the author's words: {_first_sentence(body)} [[{label}]]")
    if "[[mock:obey]]" in prompt and sources:
        paras.append(" ".join(sources[0][1].split()))
    paras.append("This closing paragraph has no source behind it.")
    return "\n\n".join(paras)
