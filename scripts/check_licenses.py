"""License gate (docs/SECURITY.md section 7): fail if a shipped runtime dependency uses a banned license.

Banned without an ADR: AGPL, GPL (non-L), SSPL, and unknown licenses. External, user-installed tools
(Pandoc, Calibre) are not dependencies and are not checked here.

Usage: python scripts/check_licenses.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\b(AGPL|SSPL|(?<!L)GPL)\b|Affero|Server Side Public", re.IGNORECASE)
OWN_PACKAGES = {"pbs-core"}
# Dev-only tools that never ship in the app (checked by hand, recorded here with the reason).
ALLOWED_EXCEPTIONS: dict[str, str] = {}


def run(cmd: list[str], cwd: Path) -> str:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise SystemExit(f"license gate: '{cmd[0]}' not found on PATH")
    return subprocess.run(
        [exe, *cmd[1:]], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def python_runtime_deps() -> list[tuple[str, str]]:
    # Only the runtime dependency closure (no dev group) ships; read it from the lockfile.
    core = ROOT / "apps" / "studio-core"
    exported = run(["uv", "export", "--no-dev", "--no-hashes", "--format", "requirements-txt"], core)
    runtime = {
        re.split(r"[=<>;\[ ]", line, maxsplit=1)[0].lower().replace("_", "-")
        for line in exported.splitlines()
        if line and not line.startswith(("#", "-", " "))
    }
    out = run(["uv", "run", "pip-licenses", "--format=json"], core)
    return [
        (d["Name"], d["License"]) for d in json.loads(out) if d["Name"].lower().replace("_", "-") in runtime
    ]


def node_runtime_deps() -> list[tuple[str, str]]:
    out = run(["pnpm", "licenses", "list", "--prod", "--json"], ROOT)
    data = json.loads(out) if out.strip() else {}
    return [(pkg["name"], license_name) for license_name, pkgs in data.items() for pkg in pkgs]


def main() -> int:
    problems: list[str] = []
    checked = 0
    for ecosystem, deps in (("python", python_runtime_deps()), ("node", node_runtime_deps())):
        for name, license_name in deps:
            if name in OWN_PACKAGES or name in ALLOWED_EXCEPTIONS:
                continue
            checked += 1
            if BANNED.search(license_name) or license_name.strip().upper() in {"", "UNKNOWN"}:
                problems.append(f"{ecosystem}: {name} ({license_name or 'no license metadata'})")
    if problems:
        print("License gate FAILED. Banned or unknown licenses in runtime dependencies:")
        print("\n".join(f"  - {p}" for p in problems))
        return 1
    print(f"License gate passed: {checked} runtime dependencies checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
