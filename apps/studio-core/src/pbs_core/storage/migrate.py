"""Programmatic, safety-first schema migration (docs/DATA_MODEL.md section 5).

* DB older than the app -> integrity check, snapshot via SQLite online backup, upgrade.
* DB newer than the app -> refuse to open (never auto-downgrade).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer version of the app."""


class DatabaseIntegrityError(RuntimeError):
    """PRAGMA quick_check reported corruption."""


@dataclass(frozen=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str
    snapshot_path: Path | None

    @property
    def migrated(self) -> bool:
        return self.from_revision != self.to_revision


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:  # pragma: no cover - packaging error
        raise RuntimeError("no migrations found")
    return head


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def snapshot_database(db_path: Path, dest: Path) -> Path:
    """Consistent copy of a live SQLite DB using the online backup API."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def quick_check(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("PRAGMA quick_check").fetchall()
    finally:
        conn.close()
    if [r[0] for r in rows] != ["ok"]:
        raise DatabaseIntegrityError(f"database integrity check failed: {rows[:5]}")


def upgrade_to(engine: Engine, revision: str) -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)


def migrate(engine: Engine, db_path: Path, snapshot_dir: Path, timestamp: str) -> MigrationResult:
    script = ScriptDirectory.from_config(alembic_config())
    head = head_revision()
    current = current_revision(engine)
    if current == head:
        return MigrationResult(current, head, None)
    if current is not None:
        try:
            script.get_revision(current)
        except CommandError as exc:
            raise SchemaTooNewError(
                f"This workspace's database is at schema revision {current!r}, which this app "
                f"version does not know (latest known: {head!r}). It was probably written by a "
                "newer version of Personal Book Studio. Refusing to open it to avoid data loss."
            ) from exc

    snapshot: Path | None = None
    if current is not None:
        quick_check(db_path)
        safe_ts = timestamp.replace(":", "").replace("-", "").replace(".", "")
        snapshot = snapshot_database(db_path, snapshot_dir / f"studio-{current}-{safe_ts}.db")
    upgrade_to(engine, "head")
    return MigrationResult(current, head, snapshot)
