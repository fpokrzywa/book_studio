"""Compare chapter text with series canon. Deterministic, local, explainable.

Only author-approved canon is compared (status "canon", not superseded). Each finding points at the
exact sentence (character offsets in the chapter revision) and says which canon entry it disagrees
with. These are prompts for the author, not verdicts: a flashback, a lie or a disguise can be
intended, and the author resolves each finding by hand.

Rules:
* colour traits: eye/hair colour in a sentence that names the character;
* age: "<n> years old" next to the character's name;
* status: a character canon says is dead speaking or acting;
* family relationships: "<A>'s <kin> <B>" against the canon relationship between A and B.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

COLOURS = (
    "amber", "black", "blond", "blonde", "blue", "brown", "chestnut", "copper", "dark", "golden", "green",
    "grey", "gray", "hazel", "auburn", "red", "silver", "violet", "white", "fair", "ginger",
)  # fmt: skip
KIN = (
    "brother", "sister", "father", "mother", "son", "daughter", "wife", "husband", "cousin", "aunt", "uncle",
    "grandfather", "grandmother", "niece", "nephew", "twin",
)  # fmt: skip
ACTION_VERBS = ("said", "says", "asked", "asks", "smiled", "smiles", "walked", "walks", "ran", "runs", "laughed",
                "replied", "nodded", "entered", "whispered", "shouted", "answered", "looked")  # fmt: skip
DEAD = ("dead", "deceased", "died", "killed")
_SENT = re.compile(r"[^.!?\n]+[.!?]*")


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    aliases: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [n for n in [self.name, *self.aliases] if n.strip()]


@dataclass
class Fact:
    id: str
    entity_id: str
    attribute: str
    value: str
    story_time: str | None = None


@dataclass
class Relationship:
    id: str
    from_id: str
    to_id: str
    label: str


@dataclass
class Finding:
    rule: str
    message: str
    excerpt: str
    start: int
    end: int
    entity_id: str | None = None
    fact_id: str | None = None
    relationship_id: str | None = None
    found_value: str | None = None

    def fingerprint(self, chapter_id: str) -> str:
        ref = self.fact_id or self.relationship_id or self.entity_id or ""
        norm = " ".join(self.excerpt.lower().split())
        return hashlib.sha256(f"{self.rule}|{ref}|{chapter_id}|{norm}".encode()).hexdigest()[:24]


def _name_rx(e: Entity) -> re.Pattern[str]:
    alts = "|".join(re.escape(n) for n in sorted(e.names, key=len, reverse=True))
    return re.compile(rf"\b(?:{alts})(?:'s|’s)?\b")


def sentences(text: str) -> list[tuple[int, int, str]]:
    """(start, end, sentence) with offsets trimmed to the sentence itself, so a link selects just it."""
    out = []
    for m in _SENT.finditer(text):
        raw = m.group(0)
        if not raw.strip():
            continue
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw) - len(raw.rstrip())
        out.append((m.start() + lead, m.end() - trail, raw.strip()))
    return out


def _kin(label: str) -> str | None:
    low = label.lower()
    return next((k for k in sorted(KIN, key=len, reverse=True) if re.search(rf"\b{k}\b", low)), None)


def check(text: str, entities: list[Entity], facts: list[Fact], relationships: list[Relationship]) -> list[Finding]:
    out: list[Finding] = []
    by_id = {e.id: e for e in entities}
    sents = sentences(text)
    for f in facts:
        e = by_id.get(f.entity_id)
        if e is None or e.kind != "character":
            continue
        rx = _name_rx(e)
        attr = f.attribute.lower()
        val = f.value.lower().strip()
        for s0, s1, sent in sents:
            if not rx.search(sent):
                continue
            low = sent.lower()
            if ("eye" in attr or "hair" in attr) and any(c in val.split() for c in COLOURS):
                noun = "eye" if "eye" in attr else "hair"
                for m in re.finditer(rf"\b({'|'.join(COLOURS)})[\s-]+{noun}", low):
                    if m.group(1) not in val.split():
                        out.append(Finding(
                            "trait", f"{e.name}: canon says {f.attribute} is “{f.value}”, but this sentence says “{m.group(1)}”.",
                            sent.strip(), s0, s1, e.id, f.id, None, m.group(1),
                        ))  # fmt: skip
            elif attr == "age" and val.isdigit():
                for m in re.finditer(r"\b(\d{1,3})[\s-]+years?[\s-]+old\b", low):
                    if m.group(1) != val:
                        out.append(Finding(
                            "age", f"{e.name}: canon age is {f.value}, but this sentence says {m.group(1)}"
                            " (fine if time has passed since the canon entry).",
                            sent.strip(), s0, s1, e.id, f.id, None, m.group(1),
                        ))  # fmt: skip
            elif attr in ("status", "alive") and any(d in val for d in DEAD):
                m2 = re.search(rf"\b({'|'.join(ACTION_VERBS)})\b", low)
                if m2:
                    out.append(Finding(
                        "status", f"{e.name}: canon says “{f.value}”, but here {e.name} {m2.group(1)} (fine in a flashback or memory).",
                        sent.strip(), s0, s1, e.id, f.id, None, "alive",
                    ))  # fmt: skip
    for r in relationships:
        a, b = by_id.get(r.from_id), by_id.get(r.to_id)  # canon: a is b's <kin>
        canon_kin = _kin(r.label)
        if a is None or b is None or canon_kin is None:
            continue
        a_alt = "|".join(re.escape(n) for n in a.names)
        b_alt = "|".join(re.escape(n) for n in b.names)
        pat = re.compile(rf"\b(?:{b_alt})(?:'s|’s)\s+({'|'.join(KIN)})\s*,?\s+(?:{a_alt})\b", re.IGNORECASE)
        for s0, s1, sent in sents:
            for m in pat.finditer(sent):
                if m.group(1).lower() != canon_kin:
                    out.append(Finding(
                        "relationship", f"Canon: {a.name} is {b.name}'s {canon_kin}. This sentence calls {a.name} {b.name}'s {m.group(1).lower()}.",
                        sent.strip(), s0, s1, a.id, None, r.id, m.group(1).lower(),
                    ))  # fmt: skip
    return out


def chronology(events: list[tuple[str, str, int, str | None]]) -> list[dict[str, str]]:
    """events: (entity id, name, book position, story time). Year-like story times out of book order."""
    out: list[dict[str, str]] = []
    dated = []
    for eid, name, pos, when in events:
        m = re.search(r"\b(\d{3,4})\b", when or "")
        if m:
            dated.append((pos, int(m.group(1)), eid, name, when or ""))
    dated.sort(key=lambda x: x[0])
    latest: tuple[int, int, str, str, str] | None = None
    for ev in dated:
        if latest is not None and ev[0] > latest[0] and ev[1] < latest[1]:
            out.append({
                "entity_id": ev[2],
                "message": f"“{ev[3]}” ({ev[4]}, book {ev[0]}) is set before “{latest[3]}” ({latest[4]}, book {latest[0]}). Fine if intended.",
            })  # fmt: skip
        if latest is None or ev[1] >= latest[1]:
            latest = ev
    return out
