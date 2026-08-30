# ==============================================================================
# ALFA SOVEREIGN AI AGENT & TELEGRAM BOT - 1-CLICK WINDOWS SETUP WIZARD
# ==============================================================================
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$dir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $dir

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Clear-Host
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  ALFA SOVEREIGN AI AGENT (Windows Setup Wizard)" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/6] Memeriksa Lingkungan Python..." -ForegroundColor Cyan
try {
    $pyVer = & python --version 2>&1
    Write-Host "   [OK] Ditemukan: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "   [ERR] Python tidak terdeteksi di PATH! Silakan unduh Python 3.10+ dari python.org dan centang 'Add Python to PATH'." -ForegroundColor Red
    exit 1
}

# 2. Check Node.js (Optional)
Write-Host ""
Write-Host "[2/6] Memeriksa Node.js (Opsional)..." -ForegroundColor Cyan
try {
    $nodeVer = & node --version 2>&1
    Write-Host "   [OK] Ditemukan Node.js: $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "   [INFO] Node.js belum terpasang (Opsional: dibutuhkan jika ingin menggunakan bot WhatsApp)." -ForegroundColor Yellow
}

# 3. Create Virtual Environment
Write-Host ""
Write-Host "[3/6] Menyiapkan Virtual Environment Python (venv)..." -ForegroundColor Cyan
if (-not (Test-Path "$dir\venv")) {
    & python -m venv venv
    Write-Host "   [OK] Virtual environment 'venv' berhasil dibuat." -ForegroundColor Green
} else {
    Write-Host "   [OK] Virtual environment 'venv' sudah ada." -ForegroundColor Green
}

# 4. Install Dependencies
Write-Host ""
Write-Host "[4/6] Menginstall & Memperbarui Dependensi Python..." -ForegroundColor Cyan
& "$dir\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$dir\venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
Write-Host "   [OK] Seluruh dependensi python (Telegram, FastAPI, Gemini SDK, Tools) berhasil terpasang!" -ForegroundColor Green

# 5. Interactive Configuration Setup (.env)
Write-Host ""
Write-Host "[5/6] Konfigurasi Kredensial & Kunci API (.env)..." -ForegroundColor Cyan
$envPath = "$dir\.env"
if (-not (Test-Path $envPath)) {
    if (Test-Path "$dir\.env.example") {
        Copy-Item "$dir\.env.example" $envPath
    } else {
        Set-Content -Path $envPath -Value "" -Encoding UTF8
    }
}

$envContent = Get-Content $envPath -Raw

# Helper to update key in .env
function Set-EnvVar([string]$Key, [string]$Value) {
    param($Key, $Value)
    $script:envContent = if ($script:envContent -match "(?m)^$Key=.*`$") {
        $script:envContent -replace "(?m)^$Key=.*`$", "$Key=$Value"
    } else {
        $script:envContent + "`n$Key=$Value"
    }
}

# Interactive Bot Token
if ($envContent -notmatch "(?m)^TELEGRAM_BOT_TOKEN=\s*\S+") {
    Write-Host "👉 Masukkan Token Bot Telegram Anda dari @BotFather:" -ForegroundColor Yellow
    $botToken = Read-Host "   TELEGRAM_BOT_TOKEN"
    if ($botToken) { Set-EnvVar "TELEGRAM_BOT_TOKEN" $botToken.Trim() }
} else {
    Write-Host "   [OK] TELEGRAM_BOT_TOKEN sudah terkonfigurasi." -ForegroundColor Green
}

# Interactive Gemini Key
if ($envContent -notmatch "(?m)^GEMINI_API_KEY=\s*\S+") {
    Write-Host "👉 Masukkan Google Gemini API Key Anda (gratis di https://aistudio.google.com):" -ForegroundColor Yellow
    $geminiKey = Read-Host "   GEMINI_API_KEY"
    if ($geminiKey) { Set-EnvVar "GEMINI_API_KEY" $geminiKey.Trim() }
} else {
    Write-Host "   [OK] GEMINI_API_KEY sudah terkonfigurasi." -ForegroundColor Green
}

# Interactive Allowed User IDs
if ($envContent -notmatch "(?m)^ALLOWED_USER_IDS=\s*\S+") {
    Write-Host "👉 Masukkan Telegram User ID Anda (opsional, dapatkan dari @userinfobot):" -ForegroundColor Yellow
    $allowedIds = Read-Host "   ALLOWED_USER_IDS (kosongkan jika publik)"
    if ($allowedIds) { Set-EnvVar "ALLOWED_USER_IDS" $allowedIds.Trim() }
}

# Set Default Model to gemini-3.6-flash if invalid/missing
if ($envContent -match "(?m)^GEMINI_MODEL=.*(Gemini|gemini-2\.5).*`$") {
    Set-EnvVar "GEMINI_MODEL" "gemini-3.6-flash"
}

# Save .env
Set-Content -Path $envPath -Value $envContent.Trim() -Encoding UTF8

# Setup Vault Master Key if missing
$vaultKeyPath = "$HOME\.alfa_vault_master.key"
if (-not (Test-Path $vaultKeyPath)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $hexKey = ($bytes | ForEach-Object { "{0:x2}" -f $_ }) -join ""
    Set-Content -Path $vaultKeyPath -Value $hexKey -Encoding UTF8
    Write-Host "   [OK] Master encryption key digenerate di $vaultKeyPath" -ForegroundColor Green
}

# 6. Setup Output Deliverable Directory
Write-Host ""
Write-Host "[6/6] Menyiapkan Direktori Output Deliverable Swarm..." -ForegroundColor Cyan
$swarmOutputDir = "$HOME\Documents\ALFA_SWARM_OUTPUTS"
if (-not (Test-Path $swarmOutputDir)) {
    New-Item -ItemType Directory -Path $swarmOutputDir -Force | Out-Null
}
Write-Host "   [OK] Direktori siap: $swarmOutputDir" -ForegroundColor Green

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  SETUP BERHASIL SELESAI DENGAN SEMPURNA!" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Cara Menjalankan Sistem:" -ForegroundColor Yellow
Write-Host "  1. Jalankan langsung via batch launcher (Bot + Web Dashboard):"
Write-Host "     .\run.bat" -ForegroundColor White
Write-Host ""
Write-Host "  2. ATAU jalankan di background via PowerShell:"
Write-Host "     powershell -ExecutionPolicy Bypass -File .\start_alfa.ps1" -ForegroundColor White
Write-Host ""
Write-Host "  3. Akses Web Management Command Center:"
Write-Host "     http://localhost:8080" -ForegroundColor Green
Write-Host ""
