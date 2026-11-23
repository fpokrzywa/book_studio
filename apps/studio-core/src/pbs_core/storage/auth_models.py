"""Phase 09 tables: the studio's account, its sign-in sessions, and durable background tasks.

* One studio = one author (docs/ADR/0010-web-deployment.md, decision P9-3). The account table can
  hold more rows later, but setup refuses a second account today.
* Passwords are stored only as scrypt hashes; session tokens only as SHA-256 hashes, so a copy of
  the database cannot be replayed as a login.
* Background tasks are non-AI work (publishing builds) that runs in the worker, not the request.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pbs_core.storage.models import Base, _in

TASK_STATUSES = ("queued", "running", "succeeded", "failed", "interrupted")


class UserAccount(Base):
    __tablename__ = "user_account"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="owner")
    disabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint(_in("role", ("owner",)), name="role"),)


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    __table_args__ = (Index("ix_auth_session_user", "user_id"),)


class BackgroundTask(Base):
    __tablename__ = "background_task"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status"),
        Index("ix_background_task_status", "status", "created_at"),
        Index("ix_background_task_project", "project_id", "created_at"),
    )
