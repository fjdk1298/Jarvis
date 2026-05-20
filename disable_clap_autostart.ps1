Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

$envText = Get-Content ".env" -Raw
if ($envText -match "(?m)^CLAP_DETECTION_ENABLED=") {
    $envText = [System.Text.RegularExpressions.Regex]::Replace(
        $envText,
        "(?m)^CLAP_DETECTION_ENABLED=.*$",
        "CLAP_DETECTION_ENABLED=false"
    )
} else {
    $envText = $envText.TrimEnd() + "`r`nCLAP_DETECTION_ENABLED=false`r`n"
}
Set-Content ".env" $envText

& ".\.venv\Scripts\python.exe" ".\install_autostart.py"

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like '*jarvis_gpt*launcher.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "[INFO] Clap launcher is disabled."
