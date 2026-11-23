"""Operations helpers for the server's command line (docs/OPERATIONS.md).

* ``status``: what the studio holds and what the background worker is doing (job monitoring).
* ``check``: database integrity, schema, writable folders, free space; exit code 1 on a problem.
* ``verify_archive``: checks a whole-studio backup before it is trusted or restored, without
  touching the live data: safe member names, a readable database, integrity, schema and counts.

Nothing here prints manuscript text, keys or passwords.
"""

from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select, text

from pbs_core import __version__
from pbs_core.context import AppContext
from pbs_core.storage.ai_models import Job
from pbs_core.storage.auth_models import BackgroundTask, UserAccount
from pbs_core.storage.migrate import head_revision
from pbs_core.storage.models import Asset, Chapter, ChapterRevision, Project

GIB = 1024**3
STALE_QUEUE_SECONDS = 15 * 60


def _age_seconds(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    return int((now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds())


def worker_heartbeat_age(ctx: AppContext) -> int | None:
    from pbs_core.jobs.runner import HEARTBEAT_FILE

    try:
        return int(time.time() - (ctx.workspace.runtime_dir / HEARTBEAT_FILE).stat().st_mtime)
    except OSError:
        return None


def status(ctx: AppContext) -> dict[str, Any]:
    now = ctx.clock.now()
    with ctx.db.tx() as s:
        jobs = {k: int(v) for k, v in s.execute(select(Job.status, func.count()).group_by(Job.status)).all()}
        tasks = {
            k: int(v)
            for k, v in s.execute(select(BackgroundTask.status, func.count()).group_by(BackgroundTask.status)).all()
        }
        oldest_job = s.scalar(select(func.min(Job.created_at)).where(Job.status == "queued"))
        oldest_task = s.scalar(select(func.min(BackgroundTask.created_at)).where(BackgroundTask.status == "queued"))
        counts = {
            "books": int(s.scalar(select(func.count()).select_from(Project)) or 0),
            "chapters": int(s.scalar(select(func.count()).select_from(Chapter)) or 0),
            "revisions": int(s.scalar(select(func.count()).select_from(ChapterRevision)) or 0),
            "assets": int(s.scalar(select(func.count()).select_from(Asset)) or 0),
            "accounts": int(s.scalar(select(func.count()).select_from(UserAccount)) or 0),
        }
        schema = s.execute(text("select version_num from alembic_version")).scalar()
    usage = shutil.disk_usage(ctx.workspace.root)
    from pbs_core.providers import registry

    return {
        "app_version": __version__,
        "schema": schema,
        "schema_head": head_revision(),
        "deployment": ctx.settings.deployment,
        "privacy_mode": registry.privacy_mode(ctx),
        "cloud_allowed_by_operator": ctx.settings.allow_cloud,
        "private_model_hosts": sorted(ctx.settings.local_ai_hosts),
        "secret_store": ctx.secrets.name,
        "worker_heartbeat_age_s": worker_heartbeat_age(ctx),
        "jobs": jobs,
        "tasks": tasks,
        "oldest_queued_job_age_s": _age_seconds(oldest_job, now),
        "oldest_queued_task_age_s": _age_seconds(oldest_task, now),
        "content": counts,
        "disk_free_gib": round(usage.free / GIB, 1),
        "workspace": str(ctx.workspace.root),
    }


def check(ctx: AppContext) -> tuple[list[str], list[str]]:
    """(problems, warnings). Problems mean the studio is not healthy."""
    problems: list[str] = []
    warnings: list[str] = []
    con = sqlite3.connect(f"file:{ctx.workspace.db_path}?mode=ro", uri=True)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
        schema = con.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        con.close()
    if result != "ok":
        problems.append(f"database integrity check failed: {result}")
    if schema != head_revision():
        problems.append(f"database schema is {schema}, this version expects {head_revision()} (run migrate)")
    for d in (ctx.workspace.root, ctx.workspace.projects_dir, ctx.workspace.runtime_dir, ctx.workspace.logs_dir):
        probe = d / f".write-check-{ctx.ids.new()}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            problems.append(f"{d} is not writable ({type(exc).__name__})")
    free = shutil.disk_usage(ctx.workspace.root).free
    if free < 1 * GIB:
        problems.append(f"less than 1 GiB free on the data disk ({free / GIB:.2f} GiB)")
    elif free < 5 * GIB:
        warnings.append(f"only {free / GIB:.1f} GiB free on the data disk")
    st = status(ctx)
    age = st["worker_heartbeat_age_s"]
    if age is None or age > 60:
        warnings.append("no background worker has reported in during the last minute")
    for kind, oldest in (("AI job", st["oldest_queued_job_age_s"]), ("task", st["oldest_queued_task_age_s"])):
        if oldest is not None and oldest > STALE_QUEUE_SECONDS:
            warnings.append(f"the oldest queued {kind} has waited {oldest // 60} minutes")
    if st["content"]["accounts"] == 0:
        warnings.append("no account exists yet: open the studio and create it with the setup code")
    if not ctx.secrets.writable:
        warnings.append("no writable key store: provider keys can only come from environment variables")
    return problems, warnings


class ArchiveError(ValueError):
    pass


def _safe_name(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    parts = [x for x in p.parts if x not in (".", "")]
    if p.is_absolute() or ".." in parts or (parts and ":" in parts[0]):
        raise ArchiveError(f"unsafe path in archive: {name!r}")
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def verify_archive(path: Path) -> dict[str, Any]:
    """Check a whole-studio backup (tar.gz of the data folder) without extracting it over anything."""
    if not path.is_file():
        raise ArchiveError(f"{path} is not a file")
    members = files = 0
    db_member: tarfile.TarInfo | None = None
    sidecars: list[tarfile.TarInfo] = []  # studio.db-wal / -shm: committed data may still be in the WAL
    with tarfile.open(path, "r:*") as tar:
        for m in tar:
            members += 1
            rel = _safe_name(m.name)
            if m.issym() or m.islnk() or m.isdev() or m.isfifo():
                raise ArchiveError(f"links and device files are not allowed in a backup: {m.name!r}")
            if m.isfile():
                files += 1
                if str(rel) == "studio.db":
                    db_member = m
                elif str(rel) in ("studio.db-wal", "studio.db-shm"):
                    sidecars.append(m)
        if db_member is None:
            raise ArchiveError("the archive has no studio.db at its top level")
        with tempfile.TemporaryDirectory() as tmp:
            src = tar.extractfile(db_member)
            if src is None:
                raise ArchiveError("studio.db cannot be read from the archive")
            db = Path(tmp) / "studio.db"
            with db.open("wb") as out:
                shutil.copyfileobj(src, out)
            for side in sidecars:
                data = tar.extractfile(side)
                if data is not None:
                    with (Path(tmp) / _safe_name(side.name).name).open("wb") as out:
                        shutil.copyfileobj(data, out)
            try:
                con = sqlite3.connect(db)
            except sqlite3.Error as exc:
                raise ArchiveError(f"studio.db in the archive cannot be opened: {exc}") from exc
            try:
                integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
                schema = con.execute("select version_num from alembic_version").fetchone()[0]
                counts = {
                    t: int(con.execute(f"select count(*) from {t}").fetchone()[0])  # noqa: S608 - fixed names
                    for t in ("project", "chapter", "chapter_revision", "asset")
                }
            except sqlite3.Error as exc:
                raise ArchiveError(f"studio.db in the archive is not a usable database: {exc}") from exc
            finally:
                con.close()
    if integrity != "ok":
        raise ArchiveError(f"the database in the archive failed its integrity check: {integrity}")
    return {
        "archive": str(path),
        "bytes": path.stat().st_size,
        "members": members,
        "files": files,
        "schema": schema,
        "schema_head": head_revision(),
        "restorable_by_this_version": schema <= head_revision(),
        "integrity": integrity,
        "content": counts,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
