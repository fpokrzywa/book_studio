"""Turn an approved outline into the book's chapter skeleton without ever touching prose.

* A chapter is matched to its outline node by `chapter.outline_node_id` (stable node IDs).
* Matched chapters get the node's title, kind, place and target, unless the author locked or
  approved the chapter: those are reported and left exactly as they are.
* New nodes become empty "planned" chapters. Sections stay inside their chapter (they become its
  headings when it is drafted), so only parts, chapters and front/back matter become chapters here.
* A chapter whose node left the outline is archived only if it is empty (no saved revision, no
  autosaved draft); a chapter with prose is kept and reported. Archiving is reversible: if the
  node comes back, the chapter is restored.
* Chapters the author created by hand (no node) are kept and reported.
* Revisions and drafts are never read for content, changed or deleted here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.domain.position import key_between
from pbs_core.planning.outline import walk
from pbs_core.services import chapters as ch
from pbs_core.storage.models import Chapter, ChapterDraft


def _has_prose(s: Session, c: Chapter) -> bool:
    return c.head_revision_no > 0 or s.get(ChapterDraft, c.id) is not None


def _frozen(c: Chapter) -> bool:
    return bool(c.locked) or c.status == "approved"


def apply(s: Session, ctx: AppContext, project_id: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    now = ctx.clock.iso()
    all_chapters = s.scalars(select(Chapter).where(Chapter.project_id == project_id)).all()
    by_node = {c.outline_node_id: c for c in all_chapters if c.outline_node_id}
    report: dict[str, Any] = {
        "created": [],
        "updated": [],
        "restored": [],
        "unchanged": 0,
        "skipped_locked": [],
        "kept_not_in_outline": [],
        "archived_empty": [],
        "manual_kept": [],
    }
    node_to_chapter: dict[str, str] = {}
    last_key: dict[str | None, str | None] = {}

    for node, _depth, parent_node in walk(nodes):
        if node["kind"] == "section":
            continue  # sections are headings inside their chapter, not separate chapters
        parent_id = node_to_chapter.get(parent_node) if parent_node else None
        c = by_node.get(node["id"])
        if c is not None and _frozen(c):
            node_to_chapter[node["id"]] = c.id
            report["skipped_locked"].append(c.title)
            last_key[c.parent_id] = max(filter(None, [last_key.get(c.parent_id), c.position]), default=None)
            continue
        position = key_between(last_key.get(parent_id), None)
        last_key[parent_id] = position
        if c is None:
            c = Chapter(
                id=ctx.ids.new(),
                project_id=project_id,
                parent_id=parent_id,
                kind=node["kind"],
                position=position,
                title=node["title"],
                slug=ch._unique_slug(s, project_id, node["title"]),
                status="planned",
                locked=0,
                target_word_count=node.get("target_words"),
                head_revision_no=0,
                outline_node_id=node["id"],
                created_at=now,
                updated_at=now,
            )
            s.add(c)
            s.flush()
            report["created"].append(c.title)
        else:
            before = (c.title, c.kind, c.parent_id, c.target_word_count, c.archived_at is None)
            if c.archived_at is not None:
                c.archived_at = None
                report["restored"].append(node["title"])
            c.title, c.kind, c.parent_id = node["title"], node["kind"], parent_id
            c.target_word_count = node.get("target_words")
            moved = c.position != position
            c.position = position
            after = (c.title, c.kind, c.parent_id, c.target_word_count, True)
            if before != after or moved:
                c.updated_at = now
                report["updated"].append(c.title)
            else:
                report["unchanged"] += 1
        node_to_chapter[node["id"]] = c.id
    s.flush()

    in_outline = set(node_to_chapter.values())
    # Remove only what is empty, deepest first, and never a parent that still has live children.
    leftovers = [c for c in all_chapters if c.id not in in_outline and c.archived_at is None]
    for c in sorted(leftovers, key=lambda x: 0 if x.kind == "section" else (1 if x.kind == "chapter" else 2)):
        if not c.outline_node_id:
            report["manual_kept"].append(c.title)
            continue
        live_children = [x for x in all_chapters if x.parent_id == c.id and x.archived_at is None and x.id != c.id]
        if _frozen(c) or _has_prose(s, c) or live_children:
            report["kept_not_in_outline"].append(c.title)
            continue
        c.archived_at = c.updated_at = now
        report["archived_empty"].append(c.title)
    s.flush()
    return report
