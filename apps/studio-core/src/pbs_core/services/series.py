"""Phase 08: series, shared canon (story bible), cross-book continuity review and manual resolution."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_advanced import (
    CanonFactIn,
    CanonFactOut,
    CanonFactPatch,
    CanonOut,
    EntityIn,
    EntityOut,
    EntityPatch,
    ImportNotesOut,
    IssueOut,
    RelationshipIn,
    RelationshipOut,
    RelationshipPatch,
    ResolveIn,
    ReviewIn,
    ReviewOut,
    SeriesBookIn,
    SeriesBookOut,
    SeriesIn,
    SeriesOut,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.series import continuity as cc
from pbs_core.services import activity
from pbs_core.services.chapters import active_chapters, tree_order
from pbs_core.services.projects import require_project
from pbs_core.storage.advanced_models import (
    CanonEntity,
    CanonFact,
    CanonRelationship,
    ContinuityIssue,
    Series,
    SeriesBook,
)
from pbs_core.storage.models import Chapter, ChapterRevision, Project
from pbs_core.storage.writing_models import ContinuityFact

REVIEW_NOTE = (
    "These are pattern checks against approved canon (eye and hair colour, age, a character canon says is dead, "
    "family relationships). They point at passages to look at; they do not decide what is true. Resolve each one."
)


def _require_series(s: Session, series_id: str) -> Series:
    x = s.get(Series, series_id) if is_ulid(series_id) else None
    if x is None:
        raise NotFoundError("Series not found.")
    return x


def series_of(s: Session, project_id: str) -> Series | None:
    sb = s.scalars(select(SeriesBook).where(SeriesBook.project_id == project_id)).first()
    return s.get(Series, sb.series_id) if sb else None


def _series_out(s: Session, x: Series) -> SeriesOut:
    books = []
    for sb in s.scalars(select(SeriesBook).where(SeriesBook.series_id == x.id).order_by(SeriesBook.position)):
        p = s.get(Project, sb.project_id)
        if p is not None:
            books.append(SeriesBookOut(project_id=p.id, title=p.title, position=sb.position, language=p.language))
    counts = {
        "entities": s.scalar(select(func.count()).select_from(CanonEntity).where(CanonEntity.series_id == x.id)) or 0,
        "suggested": s.scalar(select(func.count()).select_from(CanonFact).where(CanonFact.series_id == x.id, CanonFact.status == "suggested")) or 0,
        "open_issues": s.scalar(select(func.count()).select_from(ContinuityIssue).where(ContinuityIssue.series_id == x.id, ContinuityIssue.state == "open", ContinuityIssue.present == 1)) or 0,
    }  # fmt: skip
    return SeriesOut(
        id=x.id, title=x.title, description=x.description, books=books, counts=counts, updated_at=x.updated_at
    )


def list_series(ctx: AppContext) -> list[SeriesOut]:
    with ctx.db.tx() as s:
        return [_series_out(s, x) for x in s.scalars(select(Series).order_by(Series.title))]


def create_series(ctx: AppContext, data: SeriesIn) -> SeriesOut:
    with ctx.db.tx() as s:
        now = ctx.clock.iso()
        x = Series(id=ctx.ids.new(), title=data.title, description=data.description, created_at=now, updated_at=now)
        s.add(x)
        s.flush()
        return _series_out(s, x)


def series_for_project(ctx: AppContext, project_id: str) -> SeriesOut | None:
    with ctx.db.tx() as s:
        require_project(s, project_id)
        x = series_of(s, project_id)
        return _series_out(s, x) if x else None


def get_series(ctx: AppContext, series_id: str) -> SeriesOut:
    with ctx.db.tx() as s:
        return _series_out(s, _require_series(s, series_id))


def add_book(ctx: AppContext, series_id: str, data: SeriesBookIn) -> SeriesOut:
    with ctx.db.tx() as s:
        x = _require_series(s, series_id)
        require_project(s, data.project_id)
        other = s.scalars(select(SeriesBook).where(SeriesBook.project_id == data.project_id)).first()
        if other is not None and other.series_id != x.id:
            raise ConflictError("This book already belongs to another series. Remove it there first.")
        pos = (
            data.position
            or (s.scalar(select(func.max(SeriesBook.position)).where(SeriesBook.series_id == x.id)) or 0) + 1
        )
        if other is None:
            s.add(SeriesBook(series_id=x.id, project_id=data.project_id, position=pos))
        else:
            other.position = pos
        x.updated_at = ctx.clock.iso()
        s.flush()
        return _series_out(s, x)


def remove_book(ctx: AppContext, series_id: str, project_id: str) -> SeriesOut:
    with ctx.db.tx() as s:
        x = _require_series(s, series_id)
        sb = s.get(SeriesBook, (series_id, project_id))
        if sb is None:
            raise NotFoundError("That book is not in this series.")
        s.delete(sb)
        s.flush()
        return _series_out(s, x)


# ---------- canon ----------


def _fact_out(s: Session, f: CanonFact) -> CanonFactOut:
    p = s.get(Project, f.book_project_id) if f.book_project_id else None
    return CanonFactOut(
        id=f.id, entity_id=f.entity_id, attribute=f.attribute, value=f.value, story_time=f.story_time,
        book_project_id=f.book_project_id, book_title=p.title if p else None, status=f.status,
        origin=f.origin, provenance=json.loads(f.provenance_json), superseded_by=f.superseded_by, updated_at=f.updated_at,
    )  # fmt: skip


def _entity_out(s: Session, e: CanonEntity) -> EntityOut:
    facts = s.scalars(
        select(CanonFact).where(CanonFact.entity_id == e.id).order_by(CanonFact.attribute, CanonFact.created_at)
    ).all()
    return EntityOut(
        id=e.id, kind=e.kind, name=e.name, aliases=json.loads(e.aliases_json), summary=e.summary,
        status=e.status, origin=e.origin, provenance=json.loads(e.provenance_json),
        facts=[_fact_out(s, f) for f in facts], updated_at=e.updated_at,
    )  # fmt: skip


def _rel_out(r: CanonRelationship) -> RelationshipOut:
    return RelationshipOut(
        id=r.id, from_entity_id=r.from_entity_id, to_entity_id=r.to_entity_id, label=r.label,
        status=r.status, origin=r.origin, provenance=json.loads(r.provenance_json),
    )  # fmt: skip


def canon(ctx: AppContext, series_id: str) -> CanonOut:
    with ctx.db.tx() as s:
        _require_series(s, series_id)
        ents = s.scalars(
            select(CanonEntity).where(CanonEntity.series_id == series_id).order_by(CanonEntity.kind, CanonEntity.name)
        ).all()
        rels = s.scalars(select(CanonRelationship).where(CanonRelationship.series_id == series_id)).all()
        positions = {
            sb.project_id: sb.position for sb in s.scalars(select(SeriesBook).where(SeriesBook.series_id == series_id))
        }
        events = []
        rows = []
        for e in ents:
            if e.kind != "event" or e.status == "rejected":
                continue
            for f in s.scalars(
                select(CanonFact).where(
                    CanonFact.entity_id == e.id, CanonFact.status != "rejected", CanonFact.superseded_by.is_(None)
                )
            ):
                pos = positions.get(f.book_project_id or "", 0)
                events.append((e.id, e.name, pos, f.story_time))
                rows.append(
                    {
                        "entity_id": e.id,
                        "name": e.name,
                        "book_position": pos,
                        "story_time": f.story_time,
                        "status": f.status,
                    }
                )
        rows.sort(key=lambda r: (r["book_position"], r["story_time"] or ""))
        return CanonOut(
            entities=[_entity_out(s, e) for e in ents],
            relationships=[_rel_out(r) for r in rels],
            chronology=rows,
            chronology_warnings=cc.chronology(events),
        )


def _check_entity(s: Session, series_id: str, entity_id: str) -> CanonEntity:
    e = s.get(CanonEntity, entity_id) if is_ulid(entity_id) else None
    if e is None or e.series_id != series_id:
        raise NotFoundError("Canon entry not found in this series.")
    return e


def add_entity(ctx: AppContext, series_id: str, data: EntityIn) -> EntityOut:
    with ctx.db.tx() as s:
        _require_series(s, series_id)
        now = ctx.clock.iso()
        e = CanonEntity(
            id=ctx.ids.new(), series_id=series_id, kind=data.kind, name=data.name, aliases_json=json.dumps(data.aliases),
            summary=data.summary, status="canon", origin="author", provenance_json=json.dumps({"by": "author"}),
            created_at=now, updated_at=now,
        )  # fmt: skip
        s.add(e)
        s.flush()
        return _entity_out(s, e)


def patch_entity(ctx: AppContext, series_id: str, entity_id: str, data: EntityPatch) -> EntityOut:
    with ctx.db.tx() as s:
        e = _check_entity(s, series_id, entity_id)
        if data.name is not None:
            e.name = data.name
        if data.aliases is not None:
            e.aliases_json = json.dumps(data.aliases)
        if data.summary is not None:
            e.summary = data.summary
        if data.status is not None:
            e.status = data.status
        e.updated_at = ctx.clock.iso()
        s.flush()
        return _entity_out(s, e)


def add_fact(ctx: AppContext, series_id: str, data: CanonFactIn) -> CanonFactOut:
    with ctx.db.tx() as s:
        _check_entity(s, series_id, data.entity_id)
        if data.book_project_id and s.get(SeriesBook, (series_id, data.book_project_id)) is None:
            raise ValidationFailedError("That book is not in this series.")
        now = ctx.clock.iso()
        f = CanonFact(
            id=ctx.ids.new(), series_id=series_id, entity_id=data.entity_id, attribute=data.attribute, value=data.value,
            story_time=data.story_time, book_project_id=data.book_project_id, status="canon", origin="author",
            provenance_json=json.dumps({"by": "author"}), created_at=now, updated_at=now,
        )  # fmt: skip
        s.add(f)
        s.flush()
        return _fact_out(s, f)


def patch_fact(ctx: AppContext, series_id: str, fact_id: str, data: CanonFactPatch) -> CanonFactOut:
    with ctx.db.tx() as s:
        f = s.get(CanonFact, fact_id) if is_ulid(fact_id) else None
        if f is None or f.series_id != series_id:
            raise NotFoundError("Canon fact not found in this series.")
        changed = False
        if data.value is not None and data.value != f.value:
            # A changed value is a new canon entry; the old one is kept as superseded (history).
            now = ctx.clock.iso()
            new = CanonFact(
                id=ctx.ids.new(), series_id=series_id, entity_id=f.entity_id, attribute=f.attribute, value=data.value,
                story_time=data.story_time if data.story_time is not None else f.story_time, book_project_id=f.book_project_id,
                status="canon", origin="author", provenance_json=json.dumps({"by": "author", "replaces": f.id}),
                created_at=now, updated_at=now,
            )  # fmt: skip
            s.add(new)
            f.superseded_by, f.updated_at = new.id, now
            s.flush()
            return _fact_out(s, new)
        if data.story_time is not None:
            f.story_time, changed = data.story_time or None, True
        if data.status is not None:
            f.status, changed = data.status, True
        if changed:
            f.updated_at = ctx.clock.iso()
        s.flush()
        return _fact_out(s, f)


def add_relationship(ctx: AppContext, series_id: str, data: RelationshipIn) -> RelationshipOut:
    with ctx.db.tx() as s:
        _check_entity(s, series_id, data.from_entity_id)
        _check_entity(s, series_id, data.to_entity_id)
        if data.from_entity_id == data.to_entity_id:
            raise ValidationFailedError("A relationship needs two different entries.")
        now = ctx.clock.iso()
        r = CanonRelationship(
            id=ctx.ids.new(), series_id=series_id, from_entity_id=data.from_entity_id, to_entity_id=data.to_entity_id,
            label=data.label, status="canon", origin="author", provenance_json=json.dumps({"by": "author"}),
            created_at=now, updated_at=now,
        )  # fmt: skip
        s.add(r)
        s.flush()
        return _rel_out(r)


def patch_relationship(ctx: AppContext, series_id: str, rel_id: str, data: RelationshipPatch) -> RelationshipOut:
    with ctx.db.tx() as s:
        r = s.get(CanonRelationship, rel_id) if is_ulid(rel_id) else None
        if r is None or r.series_id != series_id:
            raise NotFoundError("Relationship not found in this series.")
        if data.label is not None:
            r.label = data.label
        if data.status is not None:
            r.status = data.status
        r.updated_at = ctx.clock.iso()
        s.flush()
        return _rel_out(r)


def import_book_notes(ctx: AppContext, series_id: str, project_id: str) -> ImportNotesOut:
    """A book's continuity notes become series suggestions (or canon, if the author confirmed them there)."""
    with ctx.db.tx() as s:
        _require_series(s, series_id)
        if s.get(SeriesBook, (series_id, project_id)) is None:
            raise ValidationFailedError("Add the book to the series first.")
        project = require_project(s, project_id)
        added_e = added_f = skipped = 0
        now = ctx.clock.iso()
        for n in s.scalars(
            select(ContinuityFact).where(ContinuityFact.project_id == project_id, ContinuityFact.status != "rejected")
        ):
            kind = {
                "character": "character",
                "location": "location",
                "thread": "thread",
                "event": "event",
                "term": "term",
            }.get(n.kind, "other")
            status = "canon" if n.status in ("confirmed", "resolved") else "suggested"
            origin = "book_note" if n.origin == "author" else "ai_suggested"
            prov = {"project_id": project_id, "book": project.title, "chapter_id": n.chapter_id, "note_id": n.id, "plan_id": n.plan_id,
                    "book_status": n.status, "book_origin": n.origin}  # fmt: skip
            e = s.scalars(
                select(CanonEntity).where(
                    CanonEntity.series_id == series_id,
                    CanonEntity.kind == kind,
                    func.lower(CanonEntity.name) == n.name.lower(),
                )
            ).first()
            if e is None:
                e = CanonEntity(id=ctx.ids.new(), series_id=series_id, kind=kind, name=n.name, status=status, origin=origin,
                                provenance_json=json.dumps(prov), created_at=now, updated_at=now)  # fmt: skip
                s.add(e)
                s.flush()
                added_e += 1
            attr = n.attribute or ("description" if kind != "event" else "what happens")
            dup = s.scalars(
                select(CanonFact).where(
                    CanonFact.entity_id == e.id, CanonFact.attribute == attr, CanonFact.value == n.value
                )
            ).first()
            if dup is not None:
                skipped += 1
                continue
            s.add(CanonFact(
                id=ctx.ids.new(), series_id=series_id, entity_id=e.id, attribute=attr, value=n.value, story_time=n.story_time,
                book_project_id=project_id, status=status, origin=origin, provenance_json=json.dumps(prov), created_at=now, updated_at=now,
            ))  # fmt: skip
            added_f += 1
        activity.record(s, ctx, kind="series_notes_imported", project_id=project_id, ref_type="series", ref_id=series_id,
                        summary=f"Imported {added_f} continuity note(s) from “{project.title}” into the series")  # fmt: skip
        return ImportNotesOut(entities_added=added_e, facts_added=added_f, skipped_existing=skipped)


# ---------- review ----------


def _canon_inputs(s: Session, series_id: str) -> tuple[list[cc.Entity], list[cc.Fact], list[cc.Relationship]]:
    ents = [
        cc.Entity(e.id, e.kind, e.name, json.loads(e.aliases_json))
        for e in s.scalars(select(CanonEntity).where(CanonEntity.series_id == series_id, CanonEntity.status == "canon"))
    ]
    ids = {e.id for e in ents}
    facts = [
        cc.Fact(f.id, f.entity_id, f.attribute, f.value, f.story_time)
        for f in s.scalars(
            select(CanonFact).where(
                CanonFact.series_id == series_id, CanonFact.status == "canon", CanonFact.superseded_by.is_(None)
            )
        )
        if f.entity_id in ids
    ]
    rels = [
        cc.Relationship(r.id, r.from_entity_id, r.to_entity_id, r.label)
        for r in s.scalars(
            select(CanonRelationship).where(
                CanonRelationship.series_id == series_id, CanonRelationship.status == "canon"
            )
        )
        if r.from_entity_id in ids and r.to_entity_id in ids
    ]
    return ents, facts, rels


def _issue_out(s: Session, i: ContinuityIssue) -> IssueOut:
    p = s.get(Project, i.project_id)
    ch = s.get(Chapter, i.chapter_id)
    return IssueOut(
        id=i.id, project_id=i.project_id, book_title=p.title if p else "?", chapter_id=i.chapter_id,
        chapter_title=ch.title if ch else "?", revision_no=i.revision_no, rule=i.rule, message=i.message, excerpt=i.excerpt,
        start=i.start, end=i.end, found_value=i.found_value, entity_id=i.entity_id, fact_id=i.fact_id,
        relationship_id=i.relationship_id, present=bool(i.present), state=i.state,
        resolution_note=i.resolution_note, link=f"/projects/{i.project_id}/chapters/{i.chapter_id}?select={i.start}-{i.end}",
        updated_at=i.updated_at,
    )  # fmt: skip


def list_issues(ctx: AppContext, series_id: str) -> list[IssueOut]:
    with ctx.db.tx() as s:
        _require_series(s, series_id)
        rows = s.scalars(
            select(ContinuityIssue)
            .where(ContinuityIssue.series_id == series_id)
            .order_by(ContinuityIssue.present.desc(), ContinuityIssue.created_at)
        ).all()
        return [_issue_out(s, i) for i in rows]


def review(ctx: AppContext, series_id: str, data: ReviewIn) -> ReviewOut:
    with ctx.db.tx() as s:
        _require_series(s, series_id)
        books = [
            sb.project_id
            for sb in s.scalars(
                select(SeriesBook).where(SeriesBook.series_id == series_id).order_by(SeriesBook.position)
            )
        ]
        if data.project_id:
            if data.project_id not in books:
                raise ValidationFailedError("That book is not in this series.")
            books = [data.project_id]
        ents, facts, rels = _canon_inputs(s, series_id)
        now = ctx.clock.iso()
        checked = new = 0
        seen: set[str] = set()
        scope_chapters: set[str] = set()
        for pid in books:
            for ch, _d in tree_order(active_chapters(s, pid)):
                if data.chapter_id and ch.id != data.chapter_id:
                    continue
                rev = s.get(ChapterRevision, ch.head_revision_id) if ch.head_revision_id else None
                if rev is None:
                    continue
                checked += 1
                scope_chapters.add(ch.id)
                for f in cc.check(rev.source_md, ents, facts, rels):
                    fp = f.fingerprint(ch.id)
                    seen.add(fp)
                    row = s.scalars(
                        select(ContinuityIssue).where(
                            ContinuityIssue.series_id == series_id, ContinuityIssue.fingerprint == fp
                        )
                    ).first()
                    if row is None:
                        s.add(ContinuityIssue(
                            id=ctx.ids.new(), series_id=series_id, project_id=pid, chapter_id=ch.id, revision_no=rev.revision_no,
                            entity_id=f.entity_id, fact_id=f.fact_id, relationship_id=f.relationship_id, rule=f.rule,
                            message=f.message, excerpt=f.excerpt[:1000], start=f.start, end=f.end, found_value=f.found_value,
                            fingerprint=fp, present=1, state="open", created_at=now, updated_at=now,
                        ))  # fmt: skip
                        new += 1
                    else:
                        row.present, row.revision_no, row.start, row.end, row.message = (
                            1,
                            rev.revision_no,
                            f.start,
                            f.end,
                            f.message,
                        )
                        row.updated_at = now
        for row in s.scalars(
            select(ContinuityIssue).where(
                ContinuityIssue.series_id == series_id, ContinuityIssue.chapter_id.in_(scope_chapters)
            )
        ):
            if row.fingerprint not in seen and row.present:
                row.present, row.updated_at = 0, now  # no longer found; the author's resolution is kept
        s.flush()
        rows = s.scalars(
            select(ContinuityIssue)
            .where(ContinuityIssue.series_id == series_id)
            .order_by(ContinuityIssue.present.desc(), ContinuityIssue.created_at)
        ).all()
        return ReviewOut(checked_chapters=checked, new=new, issues=[_issue_out(s, i) for i in rows], note=REVIEW_NOTE)


def resolve(ctx: AppContext, series_id: str, issue_id: str, data: ResolveIn) -> IssueOut:
    with ctx.db.tx() as s:
        i = s.get(ContinuityIssue, issue_id) if is_ulid(issue_id) else None
        if i is None or i.series_id != series_id:
            raise NotFoundError("Continuity issue not found in this series.")
        now = ctx.clock.iso()
        if data.action == "reopen":
            i.state, i.resolved_at = "open", None
        elif data.action == "update_canon":
            if not i.found_value:
                raise ConflictError("This finding has no value to take into canon; edit canon by hand instead.")
            prov = {
                "by": "author",
                "from_issue": i.id,
                "chapter_id": i.chapter_id,
                "revision_no": i.revision_no,
                "excerpt": i.excerpt[:300],
            }
            if i.fact_id:
                old = s.get(CanonFact, i.fact_id)
                if old is None:
                    raise NotFoundError("The canon fact no longer exists.")
                new_value = i.found_value if i.rule != "status" else "alive"
                new = CanonFact(
                    id=ctx.ids.new(), series_id=series_id, entity_id=old.entity_id, attribute=old.attribute, value=new_value,
                    story_time=old.story_time, book_project_id=i.project_id, status="canon", origin="author",
                    provenance_json=json.dumps({**prov, "replaces": old.id}), created_at=now, updated_at=now,
                )  # fmt: skip
                s.add(new)
                old.superseded_by, old.updated_at = new.id, now
            elif i.relationship_id:
                r = s.get(CanonRelationship, i.relationship_id)
                if r is None:
                    raise NotFoundError("The relationship no longer exists.")
                old_kin = cc._kin(r.label) or ""
                r.label = r.label.replace(old_kin, i.found_value) if old_kin else f"{i.found_value} of"
                r.provenance_json, r.updated_at = json.dumps({**prov, "previous_label": old_kin}), now
            i.state, i.resolved_at = "canon_updated", now
        else:
            i.state, i.resolved_at = data.action, now
        if data.note is not None:
            i.resolution_note = data.note or None
        i.updated_at = now
        activity.record(s, ctx, kind="continuity_resolved", project_id=i.project_id, ref_type="continuity_issue", ref_id=i.id,
                        summary=f"Resolved a continuity finding: {data.action.replace('_', ' ')}")  # fmt: skip
        s.flush()
        return _issue_out(s, i)


def canon_lines(s: Session, project_id: str) -> list[str]:
    """Approved series canon for prompts (Phase 06 drafting and AI review)."""
    x = series_of(s, project_id)
    if x is None:
        return []
    out = []
    names = {
        e.id: e
        for e in s.scalars(select(CanonEntity).where(CanonEntity.series_id == x.id, CanonEntity.status == "canon"))
    }
    for f in s.scalars(
        select(CanonFact).where(
            CanonFact.series_id == x.id, CanonFact.status == "canon", CanonFact.superseded_by.is_(None)
        )
    ):
        e = names.get(f.entity_id)
        if e:
            when = f" (story time: {f.story_time})" if f.story_time else ""
            out.append(f"[series canon] [{e.kind}] {e.name} {f.attribute}: {f.value}{when}")
    for r in s.scalars(
        select(CanonRelationship).where(CanonRelationship.series_id == x.id, CanonRelationship.status == "canon")
    ):
        a, b = names.get(r.from_entity_id), names.get(r.to_entity_id)
        if a and b:
            out.append(f"[series canon] {a.name} is {r.label} {b.name}")
    return out
