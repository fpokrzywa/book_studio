#!/usr/bin/env sh
# Start Personal Book Studio for development: Core (127.0.0.1:8765) + UI (http://127.0.0.1:5173).
# Usage: sh scripts/dev.sh            (optional env: PBS_WORKSPACE, PBS_PORT, PBS_UI_PORT)
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/apps/studio-core/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/apps/studio-core/.venv/Scripts/python.exe"
[ -x "$PY" ] || { echo "Core environment not found. Run scripts/setup.sh first." >&2; exit 1; }

export PBS_ENV=dev
export PBS_WORKSPACE="${PBS_WORKSPACE:-$ROOT/.pbs-data}"
export PBS_PORT="${PBS_PORT:-8765}"
export PBS_UI_PORT="${PBS_UI_PORT:-5173}"
export PBS_CORE_URL="http://127.0.0.1:$PBS_PORT"
export PBS_UI_ORIGINS="[\"http://127.0.0.1:$PBS_UI_PORT\",\"http://localhost:$PBS_UI_PORT\"]"

echo "Workspace: $PBS_WORKSPACE"
"$PY" -m pbs_core &
CORE_PID=$!
trap 'echo "Stopping Core..."; kill "$CORE_PID" 2>/dev/null || true' EXIT INT TERM

i=0
until curl -fs "http://127.0.0.1:$PBS_PORT/healthz" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 100 ]; then echo "Core did not start." >&2; exit 1; fi
  kill -0 "$CORE_PID" 2>/dev/null || { echo "Core exited during startup." >&2; exit 1; }
  sleep 0.3
done
echo "Open http://127.0.0.1:$PBS_UI_PORT in your browser. Press Ctrl+C to stop."
cd "$ROOT/apps/studio-ui" && pnpm dev
