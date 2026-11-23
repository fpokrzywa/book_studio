"""Alembic environment. Migrations run programmatically from pbs_core.storage.migrate."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from pbs_core.storage.models import Base

config = context.config
target_metadata = Base.metadata


def _include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """The FTS5 index (migration 0005) is raw SQL with shadow tables; autogenerate must not touch it."""
    return not (name or "").startswith("source_chunk_fts")


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is None:  # pragma: no cover - CLI usage for authoring migrations only
    from sqlalchemy import create_engine

    engine = create_engine(config.get_main_option("sqlalchemy.url") or "sqlite://")
    with engine.begin() as conn:
        _run(conn)
else:
    _run(connection)
