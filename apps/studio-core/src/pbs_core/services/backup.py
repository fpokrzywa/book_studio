"""Project backup (ZIP, manifest/1) and restore-as-new-project.

Backup contents: every project-scoped row (JSONL per table), the project's images, and the preserved
originals of its imports and knowledge sources, each listed in manifest.json with SHA-256 and size.
Knowledge, evidence and interview rows: services/backup_knowledge.py.

Restore never overwrites anything. It validates the archive (size limits, safe names, manifest
schema, checksums, schema revision), then recreates the project under NEW IDs, remapping every
internal reference. Text references to images use content hashes, so manuscripts need no rewriting.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from typing import Any

from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from pbs_core import __version__
from pbs_core.context import AppContext
from pbs_core.contracts import BackupOut, RestoreOut, WarningOut
from pbs_core.domain.errors import NotFoundError, ValidationFailedError
from pbs_core.domain.ids import is_ulid
from pbs_core.security.archive import ArchiveLimits, UnsafeArchiveError, open_checked, read_capped
from pbs_core.services import activity, backup_knowledge, projects
from pbs_core.storage.backup_manifest import BackupManifest, ManifestFile
from pbs_core.storage.migrate import alembic_config
from pbs_core.storage.models import (
    ActivityEvent,
    Asset,
    BackupRun,
    Base,
    Chapter,
    ChapterDraft,
    ChapterRevision,
    ImportRun,
    OriginalFile,
    Project,
    RevisionTag,
)
from pbs_core.storage.paths import atomic_write_bytes, safe_join, sanitize_filename, slugify

BACKUP_LIMITS = ArchiveLimits(max_entries=50_000, max_total_bytes=8 * 1024**3, max_entry_bytes=2 * 1024**3)
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def _row(obj: Base) -> dict[str, Any]:
    return {c.key: getattr(obj, c.key) for c in sa_inspect(obj).mapper.column_attrs}


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")


# ---------------- backup ----------------


def create_backup(ctx: AppContext, project_id: str) -> BackupOut:
    with ctx.db.tx() as s:
        project = projects.require_project(s, project_id)
        pid = project.id
        chapter_rows = s.scalars(select(Chapter).where(Chapter.project_id == pid)).all()
        revision_rows = s.scalars(select(ChapterRevision).where(ChapterRevision.project_id == pid)).all()
        tag_rows = s.scalars(select(RevisionTag).where(RevisionTag.project_id == pid)).all()
        draft_rows = s.scalars(select(ChapterDraft).where(ChapterDraft.project_id == pid)).all()
        asset_rows = s.scalars(select(Asset).where(Asset.project_id == pid)).all()
        import_rows = s.scalars(select(ImportRun).where(ImportRun.project_id == pid)).all()
        original_rows = [o for o in (s.get(OriginalFile, r.original_file_id) for r in import_rows) if o is not None]
        activity_rows = s.scalars(select(ActivityEvent).where(ActivityEvent.project_id == pid)).all()
        knowledge_tables, knowledge_originals = backup_knowledge.collect(s, pid, _row)
        original_rows = original_rows + knowledge_originals
        tables: dict[str, list[dict[str, Any]]] = {
            "project": [_row(project)],
            "chapter": [_row(x) for x in chapter_rows],
            "chapter_revision": sorted(
                (_row(x) for x in revision_rows), key=lambda r: (r["chapter_id"], r["revision_no"])
            ),
            "revision_tag": [_row(x) for x in tag_rows],
            "chapter_draft": [_row(x) for x in draft_rows],
            "asset": [_row(x) for x in asset_rows],
            "import_run": [_row(x) for x in import_rows],
            "original_file": [_row(x) for x in {o.id: o for o in original_rows}.values()],
            "activity_event": [_row(x) for x in activity_rows],
            **knowledge_tables,
        }
        files: list[tuple[str, bytes]] = [(f"data/{name}.jsonl", _jsonl(rows)) for name, rows in tables.items()]
        for a in asset_rows:
            files.append(
                (
                    f"files/assets/{a.storage_path}",
                    safe_join(ctx.workspace.project_dir(pid), a.storage_path).read_bytes(),
                )
            )
        for o in tables["original_file"]:
            files.append((f"files/{o['storage_path']}", safe_join(ctx.workspace.root, o["storage_path"]).read_bytes()))
        manifest = BackupManifest(
            app_version=__version__,
            schema_revision=ctx.schema_revision,
            created_at=ctx.clock.iso(),
            project_id=pid,
            project_title=project.title,
            tables={k: len(v) for k, v in tables.items()},
            files=[ManifestFile(path=p, sha256=hashlib.sha256(d).hexdigest(), byte_size=len(d)) for p, d in files],
        )
        manifest_bytes = json.dumps(manifest.model_dump(by_alias=True), indent=2, ensure_ascii=False).encode("utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in [("manifest.json", manifest_bytes), *sorted(files)]:
                info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)
        data = buf.getvalue()
        stamp = ctx.clock.iso().replace(":", "").replace("-", "").replace(".", "")[:15]
        file_name = f"{sanitize_filename(slugify(project.title))}-{stamp}.pbsbak.zip"
        target = safe_join(ctx.workspace.backups_dir, file_name)
        atomic_write_bytes(target, data)
        run = BackupRun(
            id=ctx.ids.new(),
            project_id=pid,
            kind="manual",
            path=file_name,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            schema_revision=ctx.schema_revision,
            created_at=ctx.clock.iso(),
        )
        s.add(run)
        activity.record(s, ctx, kind="backup_created", summary=f"Backed up “{project.title}”", project_id=pid,
                        ref_type="backup_run", ref_id=run.id)  # fmt: skip
        s.flush()
        return _backup_out(run, len(data))


def _backup_out(run: BackupRun, size: int) -> BackupOut:
    return BackupOut(
        id=run.id,
        project_id=run.project_id or "",
        file_name=run.path,
        byte_size=size,
        manifest_sha256=run.manifest_sha256 or "",
        schema_revision=run.schema_revision,
        created_at=run.created_at,
        download_url=f"/api/backups/{run.id}/file",
    )


def list_backups(ctx: AppContext, project_id: str) -> list[BackupOut]:
    with ctx.db.tx() as s:
        projects.require_project(s, project_id)
        runs = s.scalars(
            select(BackupRun).where(BackupRun.project_id == project_id).order_by(BackupRun.created_at.desc())
        ).all()
        out = []
        for r in runs:
            path = safe_join(ctx.workspace.backups_dir, r.path)
            if path.is_file():
                out.append(_backup_out(r, path.stat().st_size))
        return out


def backup_file(ctx: AppContext, backup_id: str) -> tuple[Any, str]:
    with ctx.db.tx() as s:
        run = s.get(BackupRun, backup_id) if is_ulid(backup_id) else None
        if run is None:
            raise NotFoundError("Backup not found.")
        path = safe_join(ctx.workspace.backups_dir, run.path)
        if not path.is_file():
            raise NotFoundError("The backup file is missing from disk.")
        return path, run.path


# ---------------- restore ----------------


def _load_archive(data: bytes) -> tuple[BackupManifest, dict[str, bytes]]:
    try:
        zf = open_checked(data, BACKUP_LIMITS)
    except UnsafeArchiveError as exc:
        raise ValidationFailedError(f"The backup was rejected: {exc}") from exc
    names = set(zf.namelist())
    if "manifest.json" not in names:
        raise ValidationFailedError("This is not a Personal Book Studio backup (manifest.json is missing).")
    try:
        manifest = BackupManifest.model_validate(json.loads(read_capped(zf, "manifest.json", BACKUP_LIMITS)))
    except (ValueError, ValidationError) as exc:
        raise ValidationFailedError("The backup manifest is not valid (unknown version or damaged).") from exc
    listed = {f.path for f in manifest.files}
    extra = names - listed - {"manifest.json"} - {n for n in names if n.endswith("/")}
    if extra:
        raise ValidationFailedError(f"The backup contains files not listed in its manifest: {sorted(extra)[:3]}.")
    contents: dict[str, bytes] = {}
    for f in manifest.files:
        if f.path not in names:
            raise ValidationFailedError(f"The backup is incomplete: {f.path} is missing.")
        blob = read_capped(zf, f.path, BACKUP_LIMITS)
        if len(blob) != f.byte_size or hashlib.sha256(blob).hexdigest() != f.sha256:
            raise ValidationFailedError(f"Checksum mismatch for {f.path}: the backup is damaged or was modified.")
        contents[f.path] = blob
    return manifest, contents


def _check_schema(manifest: BackupManifest, current: str) -> None:
    script = ScriptDirectory.from_config(alembic_config())
    try:
        script.get_revision(manifest.schema_revision)
    except CommandError as exc:
        raise ValidationFailedError(
            f"This backup was made by a newer version of Personal Book Studio (schema {manifest.schema_revision}); "
            "update the app to restore it."
        ) from exc
    del current


def _rows(contents: dict[str, bytes], table: str) -> list[dict[str, Any]]:
    blob = contents.get(f"data/{table}.jsonl", b"")
    return [json.loads(line) for line in blob.decode("utf-8").splitlines() if line.strip()]


def _model_kwargs(model: type[Base], row: dict[str, Any]) -> dict[str, Any]:
    """Upcast: keep known columns, let defaults fill columns that older backups lack."""
    cols = {c.key for c in sa_inspect(model).column_attrs}
    return {k: v for k, v in row.items() if k in cols}


def restore_backup(ctx: AppContext, data: bytes) -> RestoreOut:
    manifest, contents = _load_archive(data)
    _check_schema(manifest, ctx.schema_revision)
    warnings: list[WarningOut] = []
    project_rows = _rows(contents, "project")
    if len(project_rows) != 1:
        raise ValidationFailedError("The backup does not contain exactly one project.")
    new = ctx.ids.new
    now = ctx.clock.iso()
    new_pid = new()
    project_dir = ctx.workspace.project_dir(new_pid)
    try:
        with ctx.db.tx() as s:
            src_project = project_rows[0]
            prow = _model_kwargs(Project, src_project)
            prow.update(
                id=new_pid, title=f"{src_project['title']} (restored)"[:300], status="active", archived_at=None,
                duplicated_from_id=None, created_at=now, updated_at=now,
            )  # fmt: skip
            s.add(Project(**prow))
            s.flush()

            original_map: dict[str, str] = {}
            for row in _rows(contents, "original_file"):
                existing = s.scalars(select(OriginalFile).where(OriginalFile.sha256 == row["sha256"])).one_or_none()
                if existing is not None:
                    original_map[row["id"]] = existing.id
                    continue
                blob = contents.get(f"files/{row['storage_path']}")
                if blob is None or hashlib.sha256(blob).hexdigest() != row["sha256"]:
                    warnings.append(
                        WarningOut(
                            code="original_missing", message=f"Original “{row['original_name']}” was not in the backup."
                        )
                    )
                    continue
                target = safe_join(ctx.workspace.root, row["storage_path"])
                if not target.exists():
                    atomic_write_bytes(target, blob)
                kw = _model_kwargs(OriginalFile, row)
                kw["id"] = original_map[row["id"]] = new()
                s.add(OriginalFile(**kw))
            s.flush()

            import_map: dict[str, str] = {}
            for row in _rows(contents, "import_run"):
                if row["original_file_id"] not in original_map:
                    continue
                kw = _model_kwargs(ImportRun, row)
                kw.update(id=new(), original_file_id=original_map[row["original_file_id"]], project_id=new_pid,
                          target_project_id=None)  # fmt: skip
                import_map[row["id"]] = kw["id"]
                s.add(ImportRun(**kw))
            s.flush()

            chapter_rows = _rows(contents, "chapter")
            chapter_map = {r["id"]: new() for r in chapter_rows}
            for row in chapter_rows:
                kw = _model_kwargs(Chapter, row)
                kw.update(id=chapter_map[row["id"]], project_id=new_pid, parent_id=None, head_revision_id=None)
                s.add(Chapter(**kw))
            s.flush()

            revision_map: dict[str, str] = {}
            proposal_map: dict[str, str] = {}
            revision_rows = sorted(
                _rows(contents, "chapter_revision"), key=lambda r: (r["chapter_id"], r["revision_no"])
            )
            for row in revision_rows:
                revision_map[row["id"]] = new()
            for row in revision_rows:
                if row["chapter_id"] not in chapter_map:
                    continue
                kw = _model_kwargs(ChapterRevision, row)
                bdm = json.loads(row["bdm_json"])
                bdm["chapter_id"] = chapter_map[row["chapter_id"]]
                kw.update(
                    id=revision_map[row["id"]],
                    project_id=new_pid,
                    chapter_id=chapter_map[row["chapter_id"]],
                    parent_revision_id=revision_map.get(row.get("parent_revision_id") or ""),
                    restored_from_revision_id=revision_map.get(row.get("restored_from_revision_id") or ""),
                    import_run_id=import_map.get(row.get("import_run_id") or ""),
                    # AI-origin revisions must name the proposal they came from, and each proposal can be
                    # applied once. Proposals and jobs are not part of a backup, so the copy gets a new,
                    # consistent reference instead of colliding with the original book's revision.
                    accepted_proposal_id=(
                        proposal_map.setdefault(row["accepted_proposal_id"], new())
                        if row.get("accepted_proposal_id")
                        else None
                    ),
                    bdm_json=json.dumps(bdm, ensure_ascii=False),
                )
                s.add(ChapterRevision(**kw))
                s.flush()
            for row in chapter_rows:
                ch = s.get(Chapter, chapter_map[row["id"]])
                if ch is None:  # pragma: no cover - inserted above in this transaction
                    continue
                ch.parent_id = chapter_map.get(row.get("parent_id") or "")
                ch.head_revision_id = revision_map.get(row.get("head_revision_id") or "")
            s.flush()

            for row in _rows(contents, "asset"):
                blob = contents.get(f"files/assets/{row['storage_path']}")
                if blob is None or hashlib.sha256(blob).hexdigest() != row["sha256"]:
                    warnings.append(
                        WarningOut(code="asset_missing", message=f"Image {row['short_hash']} was not in the backup.")
                    )
                    continue
                atomic_write_bytes(safe_join(project_dir, row["storage_path"]), blob)
                kw = _model_kwargs(Asset, row)
                kw.update(id=new(), project_id=new_pid, import_run_id=import_map.get(row.get("import_run_id") or ""))
                s.add(Asset(**kw))
            for row in _rows(contents, "revision_tag"):
                if row["revision_id"] in revision_map:
                    kw = _model_kwargs(RevisionTag, row)
                    kw.update(revision_id=revision_map[row["revision_id"]], project_id=new_pid)
                    s.add(RevisionTag(**kw))
            for row in _rows(contents, "chapter_draft"):
                if row["chapter_id"] in chapter_map:
                    kw = _model_kwargs(ChapterDraft, row)
                    kw.update(chapter_id=chapter_map[row["chapter_id"]], project_id=new_pid)
                    s.add(ChapterDraft(**kw))
            knowledge_counts = backup_knowledge.restore(
                s, ctx, lambda t: _rows(contents, t), _model_kwargs, new_pid=new_pid, original_map=original_map,
                chapter_map=chapter_map, revision_map=revision_map, warnings=warnings,
            )  # fmt: skip
            ref_map = {**chapter_map, **revision_map, **import_map, src_project["id"]: new_pid}
            for row in _rows(contents, "activity_event"):
                kw = _model_kwargs(ActivityEvent, row)
                kw.update(id=new(), project_id=new_pid, ref_id=ref_map.get(row.get("ref_id") or ""))
                s.add(ActivityEvent(**kw))
            s.flush()
            activity.record(
                s, ctx, kind="backup_restored",
                summary=f"Restored “{src_project['title']}” from a backup made {manifest.created_at[:10]}",
                project_id=new_pid, ref_type="project", ref_id=new_pid,
            )  # fmt: skip
            s.flush()
            out = projects._load_out(s, new_pid)
            counts = (len(chapter_rows), len(revision_map), len(_rows(contents, "asset")))
    except Exception:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    return RestoreOut(
        project=out,
        restored_from_project_id=manifest.project_id,
        chapters=counts[0],
        revisions=counts[1],
        assets=counts[2],
        sources=knowledge_counts["sources"],
        claims=knowledge_counts["claims"],
        warnings=warnings,
    )
