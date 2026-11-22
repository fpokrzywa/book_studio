# Start Personal Book Studio for development: Core (127.0.0.1:8765) + UI (http://127.0.0.1:5173).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 [-Workspace <path>]
param(
    [string]$Workspace = (Join-Path $PSScriptRoot "..\.pbs-data"),
    [int]$CorePort = 8765,
    [int]$UiPort = 5173
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root "apps\studio-core\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Core environment not found. Run scripts\setup.ps1 first."
}

function Test-PortBusy([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}
foreach ($p in @($CorePort, $UiPort)) {
    if (Test-PortBusy $p) {
        Write-Error "Port $p is already in use. Stop the other process (or pass -CorePort/-UiPort) and try again."
    }
}

$Workspace = [System.IO.Path]::GetFullPath($Workspace)
$env:PBS_ENV = "dev"
$env:PBS_WORKSPACE = $Workspace
$env:PBS_PORT = "$CorePort"
$env:PBS_UI_PORT = "$UiPort"
$env:PBS_CORE_URL = "http://127.0.0.1:$CorePort"
$env:PBS_UI_ORIGINS = "[""http://127.0.0.1:$UiPort"",""http://localhost:$UiPort""]"

Write-Host "Workspace: $Workspace"
Write-Host "Starting Core on http://127.0.0.1:$CorePort ..."
$core = Start-Process -FilePath $Python -ArgumentList "-m", "pbs_core" -NoNewWindow -PassThru
try {
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$CorePort/healthz" -TimeoutSec 1
            if ($r.StatusCode -eq 200) { break }
        } catch { Start-Sleep -Milliseconds 300 }
        if ($core.HasExited) { throw "Core exited during startup (see messages above)." }
    }
    Write-Host "Open http://127.0.0.1:$UiPort in your browser. Press Ctrl+C to stop."
    Push-Location (Join-Path $Root "apps\studio-ui")
    try { pnpm dev } finally { Pop-Location }
} finally {
    if (-not $core.HasExited) {
        Write-Host "Stopping Core..."
        Stop-Process -Id $core.Id -Force
    }
}
