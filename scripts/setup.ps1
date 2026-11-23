# One-time developer setup for Personal Book Studio (Windows PowerShell 5.1+ or PowerShell 7).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

function Require([string]$Cmd, [string]$Hint) {
    if (-not (Get-Command $Cmd -ErrorAction SilentlyContinue)) {
        Write-Error "'$Cmd' was not found. $Hint"
    }
}
Require "uv" "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
Require "node" "Install Node.js 22 or newer: https://nodejs.org/"
Require "pnpm" "Install pnpm 10: https://pnpm.io/installation (or: corepack enable)"

$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 22) { Write-Error "Node.js 22+ is required (found $(node --version))." }

# Copy instead of hard-linking from uv's cache: hard links fail across drives / cloud-synced folders.
$env:UV_LINK_MODE = "copy"

Write-Host "Installing Python 3.12 (if needed) and Core dependencies..."
Push-Location (Join-Path $Root "apps\studio-core")
try {
    uv python install 3.12
    uv sync
} finally { Pop-Location }

Write-Host "Installing UI and test dependencies..."
Push-Location $Root
try {
    pnpm install
    pnpm exec playwright install chromium
} finally { Pop-Location }

Write-Host ""
Write-Host "Setup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1"
