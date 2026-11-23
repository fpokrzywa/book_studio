"""Import workflow: upload -> original preserved -> preview (chapters, warnings, duplicates) -> commit or cancel.

The original upload is stored byte-for-byte, content-addressed, before any parsing, and is never
modified or deleted (DB trigger + read-only file). A failed or cancelled import keeps the original.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.context import AppContext
from pbs_core.contracts import (
    ImportChapterOut,
    ImportCommitIn,
    ImportCommitOut,
    ImportPreviewOut,
    ProjectCreate,
    WarningOut,
)
from pbs_core.document import bookmd
from pbs_core.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.importers import ImportError_, detect_format, run_importer
from pbs_core.services import activity, assets, chapters, projects
from pbs_core.storage.models import Chapter, ChapterRevision, ImportRun, OriginalFile
from pbs_core.storage.paths import atomic_write_bytes, safe_join, sanitize_filename

PREVIEW_CHARS = 600


def _store_original(s: Session, ctx: AppContext, name: str, data: bytes, fmt: str) -> tuple[OriginalFile, str | None]:
    digest = hashlib.sha256(data).hexdigest()
    existing = s.scalars(select(OriginalFile).where(OriginalFile.sha256 == digest)).one_or_none()
    if existing is not None:
        return existing, existing.received_at
    ext = os.path.splitext(name)[1].lower()[:10] or ".bin"
    rel = f"originals/sha256/{digest[:2]}/{digest}{ext}"
    target = safe_join(ctx.workspace.root, rel)
    if not target.exists():
        atomic_write_bytes(target, data)
        with contextlib.suppress(OSError):
            os.chmod(target, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)  # read-only on disk too
    original = OriginalFile(
        id=ctx.ids.new(),
        sha256=digest,
        original_name=sanitize_filename(name, default="upload")[:255],
        detected_format=fmt,
        byte_size=len(data),
        storage_path=rel,
        received_at=ctx.clock.iso(),
    )
    s.add(original)
    s.flush()
    return original, None


def _read_original(ctx: AppContext, original: OriginalFile) -> bytes:
    data = safe_join(ctx.workspace.root, original.storage_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != original.sha256:
        raise ConflictError("The preserved original file no longer matches its checksum; it may have been altered.")
    return data


def _duplicates(s: Session, project_id: str | None, chapters_in: list[dict[str, Any]]) -> None:
    if project_id is None:
        return
    existing = s.execute(
        select(Chapter.id, Chapter.title, ChapterRevision.content_hash)
        .outerjoin(ChapterRevision, ChapterRevision.id == Chapter.head_revision_id)
        .where(Chapter.project_id == project_id, Chapter.archived_at.is_(None))
    ).all()
    by_hash = {h: cid for cid, _, h in existing if h}
    by_title = {t.casefold(): cid for cid, t, _ in existing}
    for ch in chapters_in:
        h = bookmd.content_hash(ch["source_md"])
        if ch["source_md"].strip() and h in by_hash:
            ch["duplicate_of_chapter_id"], ch["duplicate_reason"] = by_hash[h], "same text as an existing chapter"
        elif ch["title"].casefold() in by_title:
            ch["duplicate_of_chapter_id"], ch["duplicate_reason"] = (
                by_title[ch["title"].casefold()],
                "same title as an existing chapter",
            )


def _preview_out(run: ImportRun, original: OriginalFile) -> ImportPreviewOut:
    preview = json.loads(run.preview_json)
    report = json.loads(run.report_json)
    return ImportPreviewOut(
        id=run.id,
        status=run.status,
        importer=run.importer,
        original_name=original.original_name,
        sha256=original.sha256,
        byte_size=original.byte_size,
        lossy=bool(run.lossy),
        target_project_id=run.target_project_id,
        project_id=run.project_id,
        suggested_title=preview.get("suggested_title", original.original_name),
        chapters=[
            ImportChapterOut(
                index=i,
                title=c["title"],
                word_count=c["word_count"],
                block_count=c["block_count"],
                image_count=c["image_count"],
                preview_source=c["source_md"][:PREVIEW_CHARS],
                duplicate_of_chapter_id=c.get("duplicate_of_chapter_id"),
                duplicate_reason=c.get("duplicate_reason"),
            )
            for i, c in enumerate(preview.get("chapters", []))
        ],
        warnings=[WarningOut(code=w["code"], message=w["message"]) for w in report.get("warnings", [])],
        previously_imported_at=report.get("previously_imported_at"),
        created_at=run.created_at,
    )


def create_import(ctx: AppContext, filename: str, data: bytes, target_project_id: str | None) -> ImportPreviewOut:
    if not data:
        raise ValidationFailedError("The uploaded file is empty.")
    with ctx.db.tx() as s:
        if target_project_id is not None:
            projects.require_active(s, target_project_id)
        try:
            fmt = detect_format(filename, data)
        except ImportError_ as exc:
            fmt = "text"
            failure: str | None = str(exc)
        else:
            failure = None
        original, previously = _store_original(s, ctx, filename, data, fmt)
        report: dict[str, Any] = {"warnings": [], "previously_imported_at": previously}
        preview: dict[str, Any] = {"suggested_title": os.path.splitext(original.original_name)[0], "chapters": []}
        status, lossy = "preview_ready", False
        if previously:
            report["warnings"].append(
                {"code": "duplicate_file", "message": f"This exact file was uploaded before ({previously[:10]})."}
            )
        if failure is None:
            try:
                result = run_importer(fmt, filename, data)
                preview["chapters"] = [
                    {"title": c.title, "source_md": c.source_md, "word_count": c.word_count,
                     "block_count": c.block_count, "image_count": c.image_count}
                    for c in result.chapters
                ]  # fmt: skip
                if len(result.chapters) == 1:
                    preview["suggested_title"] = result.chapters[0].title
                report["warnings"].extend(result.warnings)
                lossy = result.lossy
                _duplicates(s, target_project_id, preview["chapters"])
            except ImportError_ as exc:
                failure = str(exc)
        if failure is not None:
            status = "failed"
            report["error"] = failure
            report["warnings"].insert(0, {"code": "import_failed", "message": failure})
        run = ImportRun(
            id=ctx.ids.new(),
            original_file_id=original.id,
            target_project_id=target_project_id,
            importer=fmt,
            status=status,
            lossy=1 if lossy else 0,
            preview_json=json.dumps(preview, ensure_ascii=False),
            report_json=json.dumps(report, ensure_ascii=False),
            created_at=ctx.clock.iso(),
            finished_at=ctx.clock.iso() if status == "failed" else None,
        )
        s.add(run)
        verb = "could not be imported" if status == "failed" else "is ready to review"
        activity.record(s, ctx, kind="import_previewed", summary=f"Upload “{original.original_name}” {verb}",
                        project_id=target_project_id, ref_type="import_run", ref_id=run.id)  # fmt: skip
        s.flush()
        return _preview_out(run, original)


def _require_run(s: Session, import_id: str) -> tuple[ImportRun, OriginalFile]:
    run = s.get(ImportRun, import_id) if is_ulid(import_id) else None
    if run is None:
        raise NotFoundError("Import not found.")
    original = s.get(OriginalFile, run.original_file_id)
    if original is None:  # pragma: no cover - prevented by the foreign key
        raise NotFoundError("The original upload for this import is missing.")
    return run, original


def get_import(ctx: AppContext, import_id: str) -> ImportPreviewOut:
    with ctx.db.tx() as s:
        run, original = _require_run(s, import_id)
        return _preview_out(run, original)


def cancel_import(ctx: AppContext, import_id: str) -> ImportPreviewOut:
    with ctx.db.tx() as s:
        run, original = _require_run(s, import_id)
        if run.status == "preview_ready":
            run.status, run.finished_at = "cancelled", ctx.clock.iso()
        s.flush()
        return _preview_out(run, original)


def commit_import(ctx: AppContext, import_id: str, data: ImportCommitIn) -> ImportCommitOut:
    with ctx.db.tx() as s:
        run, original = _require_run(s, import_id)
        if run.status != "preview_ready":
            raise ConflictError(f"This import is {run.status.replace('_', ' ')} and cannot be committed.")
        preview = json.loads(run.preview_json)
        chosen = data.include if data.include is not None else list(range(len(preview["chapters"])))
        if not chosen or any(i >= len(preview["chapters"]) for i in chosen):
            raise ValidationFailedError("Choose at least one of the detected chapters to import.")
        # Re-run the deterministic importer for embedded images (they are not kept in the preview).
        result = run_importer(run.importer, original.original_name, _read_original(ctx, original))
        if [c.source_md for c in result.chapters] != [c["source_md"] for c in preview["chapters"]]:
            raise ConflictError("The importer produced different output than the preview. Upload the file again.")

        if data.mode == "existing_project":
            project_id = data.project_id or run.target_project_id
            if project_id is None:
                raise ValidationFailedError("Choose the book to import into.")
            project = projects.require_active(s, project_id)
        else:
            title = data.project_title or preview.get("suggested_title") or "Imported book"
            project = projects.insert_project(s, ctx, ProjectCreate(title=title[:300], project_type=data.project_type))
            project_id = project.id

        needed = set()
        for i in chosen:
            needed |= {h for h in result.images if f"asset:{h}" in preview["chapters"][i]["source_md"]}
        for h in sorted(needed):
            img, name = result.images[h]
            assets.store(s, ctx, project_id, img, original_name=name, import_run_id=run.id)

        chapter_ids: list[str] = []
        for i in chosen:
            proposed = preview["chapters"][i]
            chapter = chapters.append_chapter(s, ctx, project_id, proposed["title"])
            chapters.append_revision(
                s, ctx, chapter, bookmd.normalize_source(proposed["source_md"]), origin="imported",
                import_run_id=run.id, note=f"Imported from {original.original_name}",
            )  # fmt: skip
            chapter_ids.append(chapter.id)
        run.status, run.project_id, run.finished_at = "committed", project_id, ctx.clock.iso()
        project.updated_at = ctx.clock.iso()
        summary = f"Imported {len(chapter_ids)} chapter(s) from “{original.original_name}”"
        activity.record(s, ctx, kind="import_committed", summary=summary, project_id=project_id,
                        ref_type="import_run", ref_id=run.id)  # fmt: skip
        s.flush()
        return ImportCommitOut(project_id=project_id, chapter_ids=chapter_ids, import_run=_preview_out(run, original))


def original_file(ctx: AppContext, import_id: str) -> tuple[Any, str]:
    with ctx.db.tx() as s:
        _, original = _require_run(s, import_id)
        return safe_join(ctx.workspace.root, original.storage_path), original.original_name


def list_imports(ctx: AppContext, project_id: str) -> list[ImportPreviewOut]:
    with ctx.db.tx() as s:
        projects.require_project(s, project_id)
        runs = s.scalars(
            select(ImportRun)
            .where((ImportRun.project_id == project_id) | (ImportRun.target_project_id == project_id))
            .order_by(ImportRun.created_at.desc())
        ).all()
        out = []
        for run in runs:
            original = s.get(OriginalFile, run.original_file_id)
            if original is not None:
                out.append(_preview_out(run, original))
        return out
