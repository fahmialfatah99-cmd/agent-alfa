# Auto-start ALFA Bot + Dashboard (aman dijalankan berulang)
$dir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $dir
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Test-Running($hint) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $hint } | Select-Object -First 1
}

if (-not (Test-Running 'bot\.py')) {
    Start-Process -FilePath "$dir\venv\Scripts\python.exe" -ArgumentList "bot.py" `
        -WorkingDirectory $dir -WindowStyle Hidden `
        -RedirectStandardOutput "$dir\bot_out.log" -RedirectStandardError "$dir\bot_err.log"
}

if (-not (Test-Running 'web_dashboard\.py')) {
    Start-Process -FilePath "$dir\venv\Scripts\python.exe" -ArgumentList "web_dashboard.py" `
        -WorkingDirectory $dir -WindowStyle Hidden `
        -RedirectStandardOutput "$dir\dash_out.log" -RedirectStandardError "$dir\dash_err.log"
}
