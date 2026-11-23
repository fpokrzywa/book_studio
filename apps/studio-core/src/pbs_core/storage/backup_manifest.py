"""Backup archive data structure: `manifest/1` (docs/DATA_MODEL.md section 5.6).

Phase 01 defines and validates the structure; the ZIP writer/reader lands in Phase 02.

Archive layout::

    manifest.json              this model
    data/<table>.jsonl         project-scoped rows, one JSON object per line
    files/originals/...        immutable uploads (content-addressed)
    files/assets/...           images/media (content-addressed)
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from pbs_core.storage.paths import UnsafePathError, _check_component

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestFile(BaseModel):
    path: str = Field(description="POSIX path inside the archive, relative, e.g. data/project.jsonl")
    sha256: str
    byte_size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _safe_relative(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value:
            raise ValueError("archive paths must be relative POSIX paths")
        try:
            for part in value.split("/"):
                _check_component(part)
        except UnsafePathError as exc:
            raise ValueError(str(exc)) from exc
        if not value.startswith(("data/", "files/")):
            raise ValueError("archive paths must live under data/ or files/")
        return value

    @field_validator("sha256")
    @classmethod
    def _hex_digest(cls, value: str) -> str:
        if not _SHA256.match(value):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value


class BackupManifest(BaseModel):
    schema_: Literal["manifest/1"] = Field("manifest/1", alias="schema")
    app_version: str
    schema_revision: str = Field(description="Alembic revision of the source database")
    created_at: str
    project_id: str
    project_title: str
    tables: dict[str, int] = Field(description="row count per data/<table>.jsonl file")
    files: list[ManifestFile]

    model_config = {"populate_by_name": True}
