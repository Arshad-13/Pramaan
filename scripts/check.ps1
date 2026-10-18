# Runs the same static checks CI runs (formatting, lint, security scan) plus the fast test suites.
# Run before every push:   .\scripts\check.ps1
# Add -Full to include the whole backend test suite (about 4 minutes).

param([switch]$Full)
$ErrorActionPreference = "Continue"  # native tools write progress to stderr; we check exit codes instead
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
Set-Location $root

function Step($name, $cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    & $cmd[0] $cmd[1..($cmd.Length - 1)]
    if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $name" -ForegroundColor Red; exit 1 }
}

Step "black --check" @($py, "-m", "black", "--check", ".")
Step "ruff" @($py, "-m", "ruff", "check", ".")
Step "bandit (medium+)" @($py, "-m", "bandit", "-q", "-r", "app", "scripts", "-ll")
if ($Full) { Step "pytest (backend)" @($py, "-m", "pytest", "-q") }
else { Step "pytest (fast subset)" @($py, "-m", "pytest", "-q", "tests/test_canonical.py", "tests/test_crypto.py", "tests/test_drugs.py", "tests/test_qr.py", "tests/test_payload_pdf.py") }

Push-Location (Join-Path $root "frontend")
try {
    $env:NODE_USE_SYSTEM_CA = "1"
    Step "frontend lint" @("npm", "run", "lint", "--silent")
    Step "frontend build" @("npm", "run", "build", "--silent")
    Step "frontend tests" @("npm", "test", "--silent")
} finally { Pop-Location }
Write-Host "All checks passed." -ForegroundColor Green
