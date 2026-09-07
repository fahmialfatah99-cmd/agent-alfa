# Auto-start ALFA Bot + Dashboard + 9Router (aman dijalankan berulang)
$dir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $dir
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$pyExe = if (Test-Path "$dir\venv\Scripts\python.exe") { 
    "$dir\venv\Scripts\python.exe" 
} elseif (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") { 
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" 
} else { 
    "python.exe" 
}

function Test-Running($hint) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $hint } | Select-Object -First 1
}

function Test-PortListening($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# 1. Start 9Router Gateway jika belum aktif di port 20128
if (-not (Test-PortListening 20128)) {
    try {
        $env:PORT = "20128"
        $env:HOSTNAME = "0.0.0.0"
        $routerApp = "$env:APPDATA\npm\node_modules\9router\app\server.js"
        if (Test-Path $routerApp) {
            Start-Process node -ArgumentList $routerApp -WorkingDirectory (Split-Path $routerApp) -WindowStyle Hidden -ErrorAction SilentlyContinue
        } else {
            Start-Process -FilePath "9router.cmd" -ArgumentList "-t", "-n", "-p", "20128" `
                -WindowStyle Hidden -ErrorAction SilentlyContinue
        }
    } catch {}
}

# 2. Start Web Management Dashboard
if (-not (Test-Running 'web_dashboard\.py')) {
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "`"$pyExe`" web_dashboard.py"
        CurrentDirectory = $dir
    } | Out-Null
}

# 3. Start Telegram Bot Core
if (-not (Test-Running 'bot\.py')) {
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "`"$pyExe`" bot.py"
        CurrentDirectory = $dir
    } | Out-Null
}

