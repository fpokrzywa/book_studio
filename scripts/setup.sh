#!/usr/bin/env sh
# One-time developer setup for Personal Book Studio (macOS / Linux).
# Usage: sh scripts/setup.sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)

need() { command -v "$1" >/dev/null 2>&1 || { echo "'$1' was not found. $2" >&2; exit 1; }; }
need uv "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
need node "Install Node.js 22 or newer: https://nodejs.org/"
need pnpm "Install pnpm 10: https://pnpm.io/installation (or: corepack enable)"

NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
[ "$NODE_MAJOR" -ge 22 ] || { echo "Node.js 22+ is required (found $(node --version))." >&2; exit 1; }

export UV_LINK_MODE=copy
echo "Installing Python 3.12 (if needed) and Core dependencies..."
(cd "$ROOT/apps/studio-core" && uv python install 3.12 && uv sync)

echo "Installing UI and test dependencies..."
(cd "$ROOT" && pnpm install && pnpm exec playwright install chromium)

echo
echo "Setup complete. Start the app with:  sh scripts/dev.sh"
