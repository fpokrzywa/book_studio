# Regenerate the API contract (OpenAPI JSON) and the TypeScript client types from Core's Pydantic models.
# Run after changing anything in apps/studio-core/src/pbs_core/contracts.py or api/routes.py.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:UV_LINK_MODE = "copy"
$out = Join-Path $Root "apps\studio-ui\src\api\openapi.json"
Push-Location (Join-Path $Root "apps\studio-core")
try {
    uv run python -m pbs_core.openapi_export $out
    if ($LASTEXITCODE -ne 0) { throw "OpenAPI export failed" }
} finally { Pop-Location }
pnpm --filter studio-ui gen:api
