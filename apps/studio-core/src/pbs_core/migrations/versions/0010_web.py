"""Phase 09: studio account, sign-in sessions, durable background tasks.

Adds tables only; no existing table or row is changed, so every book and revision is untouched.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-23 08:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default="owner", nullable=False),
        sa.Column("disabled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("password_changed_at", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('owner')", name=op.f("ck_user_account_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_account")),
        sa.UniqueConstraint("username", name=op.f("uq_user_account_username")),
    )
    op.create_table(
        "auth_session",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_account.id"], name=op.f("fk_auth_session_user_id_user_account"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_session_token_hash")),
    )
    with op.batch_alter_table("auth_session", schema=None) as batch_op:
        batch_op.create_index("ix_auth_session_user", ["user_id"], unique=False)

    op.create_table(
        "background_task",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted')",
            name=op.f("ck_background_task_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_task")),
    )
    with op.batch_alter_table("background_task", schema=None) as batch_op:
        batch_op.create_index("ix_background_task_project", ["project_id", "created_at"], unique=False)
        batch_op.create_index("ix_background_task_status", ["status", "created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("background_task", schema=None) as batch_op:
        batch_op.drop_index("ix_background_task_status")
        batch_op.drop_index("ix_background_task_project")
    op.drop_table("background_task")
    with op.batch_alter_table("auth_session", schema=None) as batch_op:
        batch_op.drop_index("ix_auth_session_user")
    op.drop_table("auth_session")
    op.drop_table("user_account")
