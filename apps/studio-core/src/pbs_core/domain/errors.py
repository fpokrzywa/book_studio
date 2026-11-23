"""Domain errors mapped to RFC 9457 problem responses by the API layer."""

from __future__ import annotations


class DomainError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, title: str, *, detail: str | None = None, extra: dict[str, object] | None = None) -> None:
        super().__init__(title)
        self.title = title
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(DomainError):
    status = 404
    code = "not_found"


class ConflictError(DomainError):
    status = 409
    code = "conflict"


class ArchivedError(DomainError):
    status = 409
    code = "project_archived"


class ValidationFailedError(DomainError):
    status = 422
    code = "validation_failed"
