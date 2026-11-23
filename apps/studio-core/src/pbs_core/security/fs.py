"""File-system permissions for the runtime folder (setup code, encrypted keys, worker lock)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
