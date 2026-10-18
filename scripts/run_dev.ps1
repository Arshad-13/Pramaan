# Starts the API (port 8000) and the Vite dev server (port 5173) for local development.
# Usage:  .\scripts\run_dev.ps1
# First time? Run:  .\.venv\Scripts\python.exe scripts\gen_keys.py   and   cd frontend; npm install

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) { throw "No .venv found. Create it with: py -3.11 -m venv .venv" }
if (-not (Test-Path (Join-Path $root ".env"))) { throw "No .env found. Run: $python scripts\gen_keys.py" }

$api = Start-Process -FilePath $python -ArgumentList "-m uvicorn app.main:app --reload --port 8000" `
    -WorkingDirectory $root -PassThru
try {
    Push-Location (Join-Path $root "frontend")
    npm run dev
} finally {
    Pop-Location
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
