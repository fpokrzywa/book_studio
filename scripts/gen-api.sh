#!/usr/bin/env sh
# Regenerate the API contract (OpenAPI JSON) and the TypeScript client types from Core's Pydantic models.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export UV_LINK_MODE=copy
(cd "$ROOT/apps/studio-core" && uv run python -m pbs_core.openapi_export "$ROOT/apps/studio-ui/src/api/openapi.json")
cd "$ROOT" && pnpm --filter studio-ui gen:api
