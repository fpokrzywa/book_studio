"""Workspace layout, safe path joining, filename sanitization and atomic writes.

Every filesystem path Core touches is derived from IDs under the workspace root.
User-supplied names never become path components without `sanitize_filename`, and
any relative path read back from the database is re-validated with `safe_join`.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from pbs_core.domain.ids import is_ulid

_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DRIVE = re.compile(r"^[A-Za-z]:")


class UnsafePathError(ValueError):
    """A path component would escape or misuse the workspace."""


def _check_component(part: str) -> None:
    if part in ("", ".", ".."):
        raise UnsafePathError(f"illegal path component {part!r}")
    if "\x00" in part:
        raise UnsafePathError("NUL byte in path component")
    if ":" in part:  # drive letters and NTFS alternate data streams
        raise UnsafePathError(f"':' not allowed in path component {part!r}")
    if part != part.rstrip(" ."):
        raise UnsafePathError(f"trailing dot/space not allowed: {part!r}")
    stem = part.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise UnsafePathError(f"reserved device name: {part!r}")


def safe_join(base: Path, *parts: str) -> Path:
    """Join relative `parts` under `base`, rejecting anything that could escape it.

    Rejects absolute paths, drive letters, UNC paths, `..`, `:` (NTFS streams),
    Windows reserved device names, trailing dots/spaces and symlink/junction escapes.
    """
    base_resolved = base.resolve()
    components: list[str] = []
    for raw in parts:
        if not raw:
            raise UnsafePathError("empty path")
        if raw.startswith(("/", "\\")) or _DRIVE.match(raw):
            raise UnsafePathError(f"absolute path not allowed: {raw!r}")
        if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
            raise UnsafePathError(f"absolute path not allowed: {raw!r}")
        for piece in re.split(r"[\\/]+", raw):
            _check_component(piece)
            components.append(piece)
    candidate = base_resolved.joinpath(*components)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise UnsafePathError("path escapes the workspace")
    return candidate


def sanitize_filename(name: str, *, default: str = "untitled", max_len: int = 120) -> str:
    """Turn arbitrary text (e.g. a book title) into a safe, portable file name stem."""
    text = unicodedata.normalize("NFC", name or "")
    text = _INVALID_CHARS.sub("-", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip(" .-")
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .-")
    if not text:
        text = default
    if text.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        text = f"_{text}"
    return text


def slugify(text: str, *, max_len: int = 80) -> str:
    """ASCII slug for anchors and URLs (`Chapter One!` -> `chapter-one`)."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug[:max_len].strip("-") or "section"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via temp file + fsync + os.replace so readers never see a torn file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


@dataclass(frozen=True)
class Workspace:
    """On-disk layout (see docs/ARCHITECTURE.md section 3.1)."""

    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / "studio.db"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def legacy_token_path(self) -> Path:
        """Phase 00-08 wrote a per-launch token here for the Vite proxy; removed in Phase 09."""
        return self.runtime_dir / "session.token"

    @property
    def tmp_dir(self) -> Path:
        return self.runtime_dir / "tmp"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def db_backups_dir(self) -> Path:
        return self.root / "db-backups"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    def ensure(self) -> None:
        for d in (
            self.root,
            self.runtime_dir,
            self.tmp_dir,
            self.logs_dir,
            self.db_backups_dir,
            self.projects_dir,
            self.backups_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        if not is_ulid(project_id):
            raise UnsafePathError("project id is not a ULID")
        return safe_join(self.projects_dir, project_id)

    def project_subdir(self, project_id: str, *parts: str) -> Path:
        return safe_join(self.project_dir(project_id), *parts)
