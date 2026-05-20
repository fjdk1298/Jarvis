Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    try {
        py -3.12 -m venv .venv
    } catch {
        python -m venv .venv
    }
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[INFO] Created .env from .env.example"
}

Write-Host "[INFO] Jarvis setup is complete."
Write-Host "[INFO] Edit .env if needed, then run .\\enable_clap_autostart.ps1 and .\\start_jarvis.ps1"
