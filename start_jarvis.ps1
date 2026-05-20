Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Jarvis virtual environment is missing. Run .\\setup_jarvis.ps1 first."
}

& ".\.venv\Scripts\python.exe" ".\main.py"
