# Run every check the phase gates require. Stops at the first failure.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\test.ps1 [-SkipE2E]
param([switch]$SkipE2E)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:UV_LINK_MODE = "copy"

function Step([string]$Name, [scriptblock]$Block) {
    Write-Host ""
    Write-Host "==> $Name"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "FAILED: $Name (exit $LASTEXITCODE)" }
}

Push-Location (Join-Path $Root "apps\studio-core")
try {
    Step "Core: ruff lint" { uv run ruff check src tests }
    Step "Core: ruff format check" { uv run ruff format --check src tests }
    Step "Core: mypy (strict)" { uv run mypy }
    Step "Core: import contracts" { uv run lint-imports }
    Step "Core: pytest" { uv run pytest -q -p no:logging }
} finally { Pop-Location }

Push-Location $Root
try {
    Step "License gate" { & (Join-Path $Root "apps\studio-core\.venv\Scripts\python.exe") scripts\check_licenses.py }
    Step "UI: eslint + prettier" { pnpm --filter studio-ui lint }
    Step "UI: typecheck" { pnpm --filter studio-ui typecheck }
    Step "UI: vitest" { pnpm --filter studio-ui test }
    Step "UI: production build" { pnpm --filter studio-ui exec vite build }
    if (-not $SkipE2E) { Step "E2E: Playwright" { pnpm e2e } }
} finally { Pop-Location }

Write-Host ""
Write-Host "All checks passed."
