"""Safe handling of ZIP-based files (DOCX uploads, backup archives).

Checks run on the central directory *before* anything is extracted or parsed:
entry count, declared sizes, compression ratio, unsafe names, symlinks and encryption.
Reads are size-capped while streaming, so a lying header cannot bypass the limits.
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
from dataclasses import dataclass

from pbs_core.storage.paths import UnsafePathError, _check_component


class UnsafeArchiveError(ValueError):
    """The archive is malformed, too large, or tries to escape its extraction directory."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int = 10_000
    max_total_bytes: int = 2 * 1024**3
    max_entry_bytes: int = 512 * 1024**2
    max_ratio: float = 100.0


DEFAULT_LIMITS = ArchiveLimits()
_DTD = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)


def check_name(name: str) -> None:
    if not name or name.startswith(("/", "\\")) or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchiveError(f"unsafe path in archive: {name!r}")
    parts = name.rstrip("/").split("/")
    try:
        for part in parts:
            _check_component(part)
    except UnsafePathError as exc:
        raise UnsafeArchiveError(f"unsafe path in archive: {name!r}") from exc


def open_checked(data: bytes, limits: ArchiveLimits = DEFAULT_LIMITS) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsafeArchiveError("The file is not a valid ZIP-based document or is damaged.") from exc
    infos = zf.infolist()
    if len(infos) > limits.max_entries:
        raise UnsafeArchiveError(f"Archive has too many entries ({len(infos)}).")
    total = 0
    for info in infos:
        check_name(info.filename)
        if info.flag_bits & 0x1:
            raise UnsafeArchiveError("The file is encrypted or password-protected.")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise UnsafeArchiveError(f"Archive contains a symbolic link: {info.filename!r}")
        if info.file_size > limits.max_entry_bytes:
            raise UnsafeArchiveError(f"Archive entry {info.filename!r} is too large.")
        if (
            info.compress_size > 0
            and info.file_size / info.compress_size > limits.max_ratio
            and info.file_size > 1_000_000
        ):
            raise UnsafeArchiveError("Archive compression ratio is suspicious (possible zip bomb).")
        total += info.file_size
        if total > limits.max_total_bytes:
            raise UnsafeArchiveError("Archive expands to more data than allowed.")
    return zf


def read_capped(zf: zipfile.ZipFile, name: str, limits: ArchiveLimits = DEFAULT_LIMITS) -> bytes:
    """Read one entry, enforcing the size cap on the actual decompressed stream."""
    with zf.open(name) as fh:
        data = fh.read(limits.max_entry_bytes + 1)
    if len(data) > limits.max_entry_bytes:
        raise UnsafeArchiveError(f"Archive entry {name!r} is larger than declared.")
    return data


def reject_xml_dtd(zf: zipfile.ZipFile, limits: ArchiveLimits = DEFAULT_LIMITS) -> None:
    """Office XML never needs DTDs; their presence signals an XXE / entity-expansion attempt."""
    for info in zf.infolist():
        if info.filename.endswith((".xml", ".rels")) and _DTD.search(read_capped(zf, info.filename, limits)):
            raise UnsafeArchiveError(f"Document part {info.filename!r} contains a DTD or entity declaration.")
