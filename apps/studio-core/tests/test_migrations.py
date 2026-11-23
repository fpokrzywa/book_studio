"""Schema migration safety (T-P7): fresh -> head, upgrade with data + snapshot, newer DB refused, no drift."""

import sqlite3
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from pbs_core.context import build_context
from pbs_core.storage.db import create_sqlite_engine
from pbs_core.storage.migrate import SchemaTooNewError, head_revision, upgrade_to
from pbs_core.storage.models import Base
from tests.conftest import make_settings


def test_fresh_workspace_migrates_to_head_without_snapshot(workspace: Path) -> None:
    ctx = build_context(make_settings(workspace))
    try:
        assert ctx.migration.from_revision is None
        assert ctx.schema_revision == head_revision() == "0009"
        assert ctx.migration.snapshot_path is None
    finally:
        ctx.close()


def test_restart_on_head_is_a_no_op(workspace: Path) -> None:
    build_context(make_settings(workspace)).close()
    ctx = build_context(make_settings(workspace))
    try:
        assert not ctx.migration.migrated
        assert list(ctx.workspace.db_backups_dir.iterdir()) == []
    finally:
        ctx.close()


def test_upgrade_from_0001_preserves_content_and_snapshots(workspace: Path) -> None:
    workspace.mkdir(parents=True)
    db_path = workspace / "studio.db"
    engine = create_sqlite_engine(db_path)
    upgrade_to(engine, "0001")
    engine.dispose()
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO project (id, title, project_type, language, publication_formats, status, is_demo,"
            " created_at, updated_at) VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FAV', 'Old Book', 'fiction', 'en', '[\"ebook\"]',"
            " 'active', 0, '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')"
        )
        conn.execute(
            "INSERT INTO chapter (id, project_id, kind, position, title, slug, status, locked, head_revision_no,"
            " created_at, updated_at) VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FAW', '01ARZ3NDEKTSV4RRFFQ69G5FAV', 'chapter', 'V',"
            " 'One', 'one', 'draft', 0, 0, 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO chapter_revision (id, project_id, chapter_id, revision_no, origin, source_md, bdm_json,"
            " parser_version, content_hash, word_count, created_at) VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FAX',"
            " '01ARZ3NDEKTSV4RRFFQ69G5FAV', '01ARZ3NDEKTSV4RRFFQ69G5FAW', 1, 'human', 'Words from the past.\n', '{}',"
            " 'bookmd-0.1', 'h', 4, 'now')"
        )
        conn.execute(
            "UPDATE chapter SET head_revision_id='01ARZ3NDEKTSV4RRFFQ69G5FAX', head_revision_no=1"
            " WHERE id='01ARZ3NDEKTSV4RRFFQ69G5FAW'"
        )
    conn.close()

    ctx = build_context(make_settings(workspace))
    try:
        assert ctx.migration.from_revision == "0001" and ctx.schema_revision == "0009"
        snap = ctx.migration.snapshot_path
        assert snap is not None and snap.exists()
        with sqlite3.connect(snap) as s:  # snapshot holds the pre-migration data
            assert s.execute("SELECT count(*) FROM chapter_revision").fetchone() == (1,)
        from pbs_core.services import chapters

        content = chapters.get_content(ctx, "01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FAW")
        assert content.source_md == "Words from the past.\n"
        with ctx.db.tx() as s:
            assert s.connection().exec_driver_sql("SELECT count(*) FROM backup_run").scalar() == 0
    finally:
        ctx.close()


def test_newer_database_is_refused(workspace: Path) -> None:
    build_context(make_settings(workspace)).close()
    with sqlite3.connect(workspace / "studio.db") as conn:
        conn.execute("UPDATE alembic_version SET version_num = '9999_future'")
    with pytest.raises(SchemaTooNewError, match="newer version"):
        build_context(make_settings(workspace))


def test_models_match_migrations(workspace: Path) -> None:
    ctx = build_context(make_settings(workspace))
    try:
        with ctx.db.engine.connect() as conn:
            # The FTS5 virtual table and its shadow tables are managed by raw SQL, not the ORM.
            opts = {"include_name": lambda name, type_, parent: not str(name).startswith("source_chunk_fts")}
            diff = compare_metadata(MigrationContext.configure(conn, opts=opts), Base.metadata)
        assert diff == [], diff
    finally:
        ctx.close()
