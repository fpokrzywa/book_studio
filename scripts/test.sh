#!/usr/bin/env sh
# Run every check the phase gates require. Stops at the first failure.
# Usage: sh scripts/test.sh [--skip-e2e]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export UV_LINK_MODE=copy
PY="$ROOT/apps/studio-core/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/apps/studio-core/.venv/Scripts/python.exe"

step() { echo; echo "==> $1"; }

cd "$ROOT/apps/studio-core"
step "Core: ruff lint";          uv run ruff check src tests
step "Core: ruff format check";  uv run ruff format --check src tests
step "Core: mypy (strict)";      uv run mypy
step "Core: import contracts";   uv run lint-imports
step "Core: pytest";             uv run pytest -q -p no:logging

cd "$ROOT"
step "License gate";             "$PY" scripts/check_licenses.py
step "UI: eslint + prettier";    pnpm --filter studio-ui lint
step "UI: typecheck";            pnpm --filter studio-ui typecheck
step "UI: vitest";               pnpm --filter studio-ui test
step "UI: production build";     pnpm --filter studio-ui exec vite build
if [ "${1:-}" != "--skip-e2e" ]; then
  step "E2E: Playwright";        pnpm e2e
fi
echo
echo "All checks passed."
