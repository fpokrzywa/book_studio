"""Translation jobs: one chapter of an approved source revision into a linked edition.

The source revision is read, never written. Protected content is masked (translation/protect.py);
the model gets the masked text, the target language, names to keep and the author's term list, and
returns JSON {title, text, notes}. A reply that loses or alters a placeholder is invalid (retried).
The result is a *proposal* on the edition's chapter; the author accepts it like any suggestion.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy import select

from pbs_core.context import AppContext
from pbs_core.jobs.prompts import SYSTEM, BuiltPrompt, _envelope, neutralise
from pbs_core.jobs.runner import add_log
from pbs_core.jobs.writing_exec import Prepared, _usage
from pbs_core.providers.base import ProviderError, extract_json
from pbs_core.services import activity
from pbs_core.storage.advanced_models import ChapterTranslation, TranslationEdition
from pbs_core.storage.ai_models import Job, Proposal, ProviderConfig
from pbs_core.storage.models import Chapter, ChapterRevision, Project
from pbs_core.translation import protect as tp
from pbs_core.writing import protect as wprotect

KINDS = frozenset({"translate_chapter"})
TEMPLATE_VERSION = "2026-11-23.1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "text": {"type": "string"},
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["idiom", "terminology", "name", "other"]},
                    "source": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["kind", "source", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "text", "notes"],
    "additionalProperties": False,
}


def prepare(ctx: AppContext, job_id: str, inp: dict[str, Any]) -> Prepared:
    with ctx.db.tx() as s:
        rev = s.get(ChapterRevision, inp["source_revision_id"])
        src_ch = s.get(Chapter, inp["source_chapter_id"])
        if rev is None or src_ch is None:
            raise ProviderError("invalid_request", "The source revision no longer exists.")
        masked = tp.mask_for_translation(rev.source_md)
        tag = secrets.token_hex(6)
        names = list(inp.get("names") or [])
        terms = dict(inp.get("term_map") or {})
        lang = neutralise(inp["language"])
        blocks = [_envelope(tag, "chapter title", src_ch.title), _envelope(tag, "source text", masked.text)]
        if names:
            blocks.append(_envelope(tag, "names to keep unchanged", "\n".join(names)))
        if terms:
            blocks.append(
                _envelope(tag, "required term translations", "\n".join(f"{k} => {v}" for k, v in terms.items()))
            )
        user = (
            f"Target language: {lang}\n\n" + "\n\n".join(blocks) + "\n\n"
            f"Translate the chapter title and the source text into {lang}. Keep the Markdown structure (headings, lists, "
            "tables, paragraphs) exactly. Copy every placeholder like ⟦KEEP-1⟧ unchanged, once, in the right place: they "
            "stand for code, equations, citations, footnote markers, link targets and anchors. Keep the names listed as "
            "they are. Use the required term translations. Do not add, drop or summarise content. In 'notes', list idioms "
            "you could not translate literally and terminology choices the author should review. Reply with JSON only."
        )
        add_log(s, ctx, job_id, f"Translating revision {rev.revision_no} of “{src_ch.title}” into {inp['language']} "
                f"({len(masked.spans)} protected span(s)).")  # fmt: skip
        built = BuiltPrompt(SYSTEM.format(tag=tag), user, f"translate-chapter@{TEMPLATE_VERSION}", SCHEMA)
        return Prepared(built=built, extra={"masked": masked, "source": rev.source_md, "names": names, "terms": terms})


def parse(inp: dict[str, Any], payload: str, prep: Prepared) -> dict[str, Any]:
    try:
        data = extract_json(payload)
        title, text = str(data["title"]).strip(), str(data["text"])
        notes = [
            {
                "kind": str(n.get("kind", "other")),
                "source": str(n.get("source", ""))[:300],
                "note": str(n.get("note", ""))[:1000],
            }
            for n in (data.get("notes") or [])[:40]
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ProviderError("invalid_output", "The model did not return the requested structured answer.") from exc
    if not text.strip():
        raise ProviderError("invalid_output", "The translation is empty.")
    try:
        restored = wprotect.unmask(text, prep.extra["masked"])
    except wprotect.ProtectedContentChanged as exc:
        raise ProviderError(
            "invalid_output",
            f"The translation changed, dropped or repeated protected content ({len(exc.missing)} missing, "
            f"{len(exc.repeated)} repeated); it was discarded.",
        ) from exc
    issues = [i.as_dict() for i in tp.check(prep.extra["source"], restored, prep.extra["names"], prep.extra["terms"])]
    issues += [{"kind": n["kind"] if n["kind"] in ("idiom", "terminology", "name") else "other",
                "message": n["note"], "source": n["source"], "target": "", "state": "open"} for n in notes]  # fmt: skip
    return {"title": title[:300], "text": restored, "issues": issues}


def commit(ctx: AppContext, job_id: str, inp: dict[str, Any], parsed: dict[str, Any], prep: Prepared, result: Any,
           provider: ProviderConfig, snap: dict[str, Any]) -> None:  # fmt: skip
    with ctx.db.tx() as s:
        job = s.get(Job, job_id)
        if job is None or job.status != "running":
            return
        if job.cancel_requested:
            job.status, job.stage, job.finished_at, job.lease_owner = "cancelled", "cancelled", ctx.clock.iso(), None
            job.error_code, job.error_message = "cancelled", "Cancelled by the author. Nothing was saved."
            add_log(s, ctx, job_id, job.error_message)
            return
        _usage(s, ctx, job_id, snap["project_id"], provider, snap, result)
        now = ctx.clock.iso()
        target = s.get(Chapter, inp["target_chapter_id"])
        head = s.get(ChapterRevision, target.head_revision_id) if target and target.head_revision_id else None
        current = head.source_md if head else ""
        existing = s.scalars(select(Proposal).where(Proposal.job_id == job_id)).first()
        if existing is None and target is not None:
            p = Proposal(
                id=ctx.ids.new(), project_id=snap["project_id"], chapter_id=target.id, job_id=job_id,
                base_revision_id=head.id if head else None, base_revision_no=target.head_revision_no,
                mode="replace_selection" if current.strip() else "append",
                selection_start=0 if current.strip() else None, selection_end=len(current) if current.strip() else None,
                original_text=current if current.strip() else None, payload_md=parsed["text"].rstrip() + "\n", status="pending",
                provenance_json=json.dumps({
                    "provider_kind": snap["kind"], "provider_label": provider.label, "model": result.model or snap["model"],
                    "task": "translate", "template": prep.built.template, "generated_at": now,
                    "instruction": f"Translation into {inp['language']}",
                    "translation": {
                        "language": inp["language"], "source_project_id": inp["source_project_id"],
                        "source_chapter_id": inp["source_chapter_id"], "source_revision_no": inp["source_revision_no"],
                        "suggested_title": parsed["title"], "issues": parsed["issues"],
                        "protected": wprotect.summary(prep.extra["masked"]),
                    },
                }, ensure_ascii=False),
                created_at=now,
            )  # fmt: skip
            s.add(p)
            s.flush()
            ct = s.get(ChapterTranslation, inp["target_chapter_id"])
            if ct is not None:
                ct.status, ct.proposal_id, ct.suggested_title = "suggested", p.id, parsed["title"]
                ct.issues_json, ct.updated_at = json.dumps(parsed["issues"], ensure_ascii=False), now
        job.status, job.stage, job.finished_at, job.lease_owner, job.partial_output = (
            "succeeded",
            "ready_for_review",
            now,
            None,
            None,
        )
        add_log(
            s,
            ctx,
            job_id,
            f"Translation ready for review: {len(parsed['issues'])} item(s) to check. The source chapter was not changed.",
        )
        project = s.get(Project, snap["project_id"])
        ed = s.get(TranslationEdition, inp["edition_id"])
        activity.record(s, ctx, kind="translation_ready", project_id=snap["project_id"], ref_type="job", ref_id=job_id,
                        summary=f"Translation ready ({ed.language if ed else inp['language']}) in “{project.title if project else ''}”")  # fmt: skip
