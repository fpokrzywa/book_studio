"""Alembic environment. Migrations run programmatically from pbs_core.storage.migrate."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from pbs_core.storage.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
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
