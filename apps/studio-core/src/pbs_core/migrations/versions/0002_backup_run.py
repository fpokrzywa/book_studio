"""Add backup_run bookkeeping table (backup manifest/1 data structure).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_run",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.Text(), nullable=True),
        sa.Column("schema_revision", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('manual', 'pre_migration', 'pre_restore')",
            name=op.f("ck_backup_run_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_backup_run_project_id_project"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_run")),
    )


def downgrade() -> None:
    op.drop_table("backup_run")
