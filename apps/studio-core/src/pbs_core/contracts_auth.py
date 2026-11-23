"""Sign-in, account and background-task contracts (Phase 09)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

USERNAME_PATTERN = r"^[A-Za-z0-9._@-]{1,64}$"


class AuthStateOut(BaseModel):
    setup_required: bool = Field(description="No account exists yet: the first visitor with the setup code creates it")
    signed_in: bool
    username: str | None = None
    csrf_token: str | None = Field(None, description="Send as X-PBS-CSRF on every POST, PUT, PATCH and DELETE")
    session_expires_at: str | None = None
    deployment: Literal["local", "server"]
    password_min_length: int


class SetupIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: SecretStr
    setup_code: SecretStr = Field(description="From runtime/setup-code.txt on the server; never logged")


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: SecretStr


class PasswordChangeIn(BaseModel):
    current_password: SecretStr
    new_password: SecretStr


class SessionsOut(BaseModel):
    signed_out: int


class TaskOut(BaseModel):
    id: str
    kind: str
    project_id: str | None
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempt: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
