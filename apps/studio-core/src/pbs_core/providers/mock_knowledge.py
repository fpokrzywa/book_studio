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


# ---------- planning answers (outline, research brainstorm) ----------

_FOCUS = [
    "Foundations",
    "First Steps",
    "Tools",
    "Common Mistakes",
    "Practice",
    "Troubleshooting",
    "Going Further",
    "Case Study",
    "Review",
    "Next Steps",
    "Reference",
    "Afterword",
]


def _field(prompt: str, label: str) -> str:
    m = re.search(rf"{label}:\s*(.+)", prompt)
    return m.group(1).strip() if m else ""


def planning_answer(schema: dict[str, object], prompt: str) -> str | None:
    """Deterministic outline or research items when the schema asks for them; None otherwise.

    ``[[mock:metrics]]`` makes the brainstorm claim fabricated market figures, so the guard that removes
    unsupported metrics can be tested.
    """
    import json

    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return None
    fiction = "Kind of book: fiction" in prompt
    if "chapters" in props:
        try:
            n = int(_field(prompt, "Desired number of chapters").split()[0])
        except (ValueError, IndexError):
            n = 5
        n = max(1, min(n, 40))
        try:
            total = int(_field(prompt, "Target length").split()[0])
        except (ValueError, IndexError):
            total = 30000
        promise = _field(prompt, "Core promise") or "the book's promise"
        chapters = []
        for k in range(1, n + 1):
            focus = _FOCUS[(k - 1) % len(_FOCUS)]
            sections = (
                [
                    {"title": "Opening scene", "goal": "Set the place and the pressure."},
                    {"title": "Turn", "goal": "Something changes for the main character."},
                ]
                if fiction
                else [
                    {"title": f"Why {focus.lower()} matters", "goal": "Show the reader the problem."},
                    {"title": f"How to approach {focus.lower()}", "goal": "Give steps the reader can follow."},
                ]
            )
            chapters.append(
                {
                    "title": f"{focus}",
                    "goal": f"[Test model output, not AI] Move the reader toward: {promise[:120]} (part {k} of {n}).",
                    "target_words": max(500, total // n),
                    "sections": sections,
                    "requirements": ["Introduce the main character"]
                    if fiction
                    else ["Back each factual claim with a source"],
                }
            )
        return json.dumps({"chapters": chapters})
    if "items" in props:
        what = "keyword" if "KDP keyword" in prompt else ("query" if "search queries" in prompt else "topic")
        items = []
        for i in range(1, 4):
            rationale = f"[Test model output, not AI] Reason {i} for this {what}."
            if "[[mock:metrics]]" in prompt:
                rationale += (
                    " This phrase gets 12,000 monthly searches with low competition. Top books have a BSR under 5,000."
                )
            items.append({"text": f"Test {what} {i}", "rationale": rationale})
        if "[[mock:metrics]]" in prompt:
            items.append({"text": "A bestseller niche worth $2 million a year", "rationale": "High demand."})
        return json.dumps({"items": items})
    return None
