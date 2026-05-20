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
        "CLAP_DETECTION_ENABLED=true"
    )
} else {
    $envText = $envText.TrimEnd() + "`r`nCLAP_DETECTION_ENABLED=true`r`n"
}

if ($envText -match "(?m)^CLAP_TRIGGER_COUNT=") {
    $envText = [System.Text.RegularExpressions.Regex]::Replace(
        $envText,
        "(?m)^CLAP_TRIGGER_COUNT=.*$",
        "CLAP_TRIGGER_COUNT=3"
    )
} else {
    $envText = $envText.TrimEnd() + "`r`nCLAP_TRIGGER_COUNT=3`r`n"
}

Set-Content ".env" $envText

& ".\.venv\Scripts\python.exe" ".\install_autostart.py"

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like '*jarvis_gpt*launcher.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList ".\launcher.py" -WorkingDirectory $projectRoot -WindowStyle Hidden
Write-Host "[INFO] Clap launcher is enabled."
