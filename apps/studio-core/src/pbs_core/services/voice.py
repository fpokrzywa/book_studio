"""Author voice profiles: the author's own writing in, an editable style guide out.

Samples require an explicit rights confirmation (own writing, or writing they have the rights to
use; enforced by the API and a DB CHECK). Analysis is local and deterministic. The generated guide
is a draft: once the author edits it, re-analysis never overwrites it.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts_knowledge import (
    AuthorProfileCreate,
    AuthorProfileOut,
    AuthorProfilePatch,
    CorrectionOut,
    VoiceSampleIn,
    VoiceSampleOut,
)
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.importers import detect_format
from pbs_core.importers.base import ImportError_
from pbs_core.knowledge import extract as ex
from pbs_core.knowledge import voice as analysis
from pbs_core.services import activity
from pbs_core.services.imports import _store_original
from pbs_core.storage.knowledge_models import AuthorProfile, VoiceSample

MAX_SAMPLE_CHARS = 400_000


def _out(s: Session, p: AuthorProfile) -> AuthorProfileOut:
    samples = s.scalars(
        select(VoiceSample).where(VoiceSample.profile_id == p.id).order_by(VoiceSample.created_at)
    ).all()
    metrics = json.loads(p.metrics_json or "{}")
    return AuthorProfileOut(
        id=p.id,
        name=p.name,
        kind=p.kind,
        style_guide_md=p.style_guide_md,
        guide_edited=bool(p.guide_edited),
        metrics=metrics.get("metrics", {}),
        labels=metrics.get("labels", {}),
        examples=json.loads(p.examples_json or "[]"),
        corrections=[CorrectionOut(**c) for c in json.loads(p.corrections_json or "[]")],
        samples=[
            VoiceSampleOut(
                id=x.id,
                title=x.title,
                word_count=x.word_count,
                rights_basis=x.rights_basis,
                excerpt=x.text[:240],
                created_at=x.created_at,
            )
            for x in samples
        ],
        analysis_note=metrics.get("message"),
        analyzed_at=p.analyzed_at,
        created_at=p.created_at,
    )


def _require(s: Session, profile_id: str) -> AuthorProfile:
    p = s.get(AuthorProfile, profile_id) if is_ulid(profile_id) else None
    if p is None:
        raise NotFoundError("Author profile not found.")
    return p


def list_profiles(ctx: AppContext) -> list[AuthorProfileOut]:
    with ctx.db.tx() as s:
        return [_out(s, p) for p in s.scalars(select(AuthorProfile).order_by(AuthorProfile.name)).all()]


def get_profile(ctx: AppContext, profile_id: str) -> AuthorProfileOut:
    with ctx.db.tx() as s:
        return _out(s, _require(s, profile_id))


def create_profile(ctx: AppContext, data: AuthorProfileCreate) -> AuthorProfileOut:
    now = ctx.clock.iso()
    with ctx.db.tx() as s:
        p = AuthorProfile(id=ctx.ids.new(), name=data.name, kind=data.kind, created_at=now, updated_at=now)
        s.add(p)
        s.flush()
        return _out(s, p)


def patch_profile(ctx: AppContext, profile_id: str, data: AuthorProfilePatch) -> AuthorProfileOut:
    with ctx.db.tx() as s:
        p = _require(s, profile_id)
        if data.name is not None:
            p.name = data.name
        if data.style_guide_md is not None and data.style_guide_md != p.style_guide_md:
            p.style_guide_md, p.guide_edited = data.style_guide_md, 1
        if data.corrections is not None:
            p.corrections_json = json.dumps([c.model_dump() for c in data.corrections])
        p.updated_at = ctx.clock.iso()
        s.flush()
        return _out(s, p)


def _reanalyze(s: Session, ctx: AppContext, p: AuthorProfile) -> None:
    samples = s.scalars(
        select(VoiceSample).where(VoiceSample.profile_id == p.id).order_by(VoiceSample.created_at)
    ).all()
    result = analysis.analyze([(x.title, x.text) for x in samples])
    if result.get("enough"):
        p.metrics_json = json.dumps({"metrics": result["metrics"], "labels": result["labels"]})
        p.examples_json = json.dumps(result["examples"])
        if not p.guide_edited:
            p.style_guide_md = result["guide"]
    else:
        p.metrics_json = json.dumps({"message": result.get("message")})
        p.examples_json = "[]"
    p.analyzed_at = p.updated_at = ctx.clock.iso()


def _add(
    s: Session, ctx: AppContext, p: AuthorProfile, title: str, text: str, basis: str, original_id: str | None
) -> None:
    text = text.strip()
    if not text:
        raise ValidationFailedError("The sample is empty.")
    digest = hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
    if s.scalars(select(VoiceSample).where(VoiceSample.profile_id == p.id, VoiceSample.text_sha256 == digest)).first():
        raise ConflictError("This sample is already in the profile.", extra={"reason": "duplicate"})
    s.add(
        VoiceSample(
            id=ctx.ids.new(),
            profile_id=p.id,
            title=title[:200],
            original_file_id=original_id,
            text=text[:MAX_SAMPLE_CHARS],
            text_sha256=digest,
            word_count=len(text.split()),
            rights_confirmed=1,
            rights_basis=basis,
            created_at=ctx.clock.iso(),
        )
    )
    s.flush()
    _reanalyze(s, ctx, p)
    activity.record(s, ctx, kind="voice_sample_added", summary=f"Added a writing sample to “{p.name}”")


def add_sample(ctx: AppContext, profile_id: str, data: VoiceSampleIn) -> AuthorProfileOut:
    if not data.rights_confirmed:
        raise ValidationFailedError("Confirm that this is your own writing or that you have the rights to use it.")
    with ctx.db.tx() as s:
        p = _require(s, profile_id)
        _add(s, ctx, p, data.title, data.text, data.rights_basis, None)
        s.flush()
        return _out(s, p)


def add_sample_file(
    ctx: AppContext, profile_id: str, filename: str, data: bytes, *, rights_confirmed: bool, rights_basis: str
) -> AuthorProfileOut:
    if not rights_confirmed:
        raise ValidationFailedError("Confirm that this is your own writing or that you have the rights to use it.")
    if rights_basis not in ("own_writing", "licensed"):
        raise ValidationFailedError("Choose own writing or licensed.")
    try:
        fmt = detect_format(filename, data)
        parsed = ex.extract(fmt, filename, data)
    except ImportError_ as exc:
        raise ValidationFailedError(str(exc)) from exc
    text = "\n\n".join(u.text for u in parsed.units)
    with ctx.db.tx() as s:
        p = _require(s, profile_id)
        original, _ = _store_original(s, ctx, filename, data, fmt)
        _add(s, ctx, p, parsed.title, text, rights_basis, original.id)
        s.flush()
        return _out(s, p)


def remove_sample(ctx: AppContext, profile_id: str, sample_id: str) -> AuthorProfileOut:
    with ctx.db.tx() as s:
        p = _require(s, profile_id)
        row = s.get(VoiceSample, sample_id)
        if row is None or row.profile_id != p.id:
            raise NotFoundError("Sample not found.")
        s.delete(row)
        s.flush()
        _reanalyze(s, ctx, p)
        s.flush()
        return _out(s, p)


def for_prompt(ctx: AppContext, profile_id: str) -> dict[str, object] | None:
    """What a style rewrite may use: the author's guide, exact example sentences and corrections."""
    with ctx.db.tx() as s:
        p = s.get(AuthorProfile, profile_id) if is_ulid(profile_id) else None
        if p is None:
            return None
        return {
            "name": p.name,
            "guide": p.style_guide_md,
            "examples": [e["text"] for e in json.loads(p.examples_json or "[]")][:5],
            "corrections": json.loads(p.corrections_json or "[]")[:10],
        }
