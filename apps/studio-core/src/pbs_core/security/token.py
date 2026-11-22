"""Per-launch session token shared between Core and the UI host (dev proxy / Tauri shell)."""

from __future__ import annotations

import hmac
import os
import secrets
import subprocess
import sys
from pathlib import Path

import structlog

from pbs_core.storage.paths import atomic_write_bytes

log = structlog.get_logger(__name__)


def generate_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def tokens_equal(a: str | None, b: str) -> bool:
    if a is None:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _current_user_sid() -> str | None:
    try:
        out = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    # "domain\user","S-1-..."
    parts = [p.strip('"') for p in out.split(",")]
    return parts[-1] if parts and parts[-1].startswith("S-1-") else None


def restrict_directory(path: Path) -> bool:
    """Limit a directory to the current user. Returns False if it could not be enforced."""
    if sys.platform == "win32":
        sid = _current_user_sid()
        if sid is None:
            return False
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
                capture_output=True,
                timeout=15,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return True
    try:
        os.chmod(path, 0o700)
    except OSError:
        return False
    return True


def write_token(runtime_dir: Path, token_path: Path, token: str) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if not restrict_directory(runtime_dir):
        log.warning("runtime_dir_acl_not_restricted", path=str(runtime_dir))
    atomic_write_bytes(token_path, token.encode("ascii"))
    if sys.platform != "win32":
        os.chmod(token_path, 0o600)
