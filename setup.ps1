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
Write-Host "  █████╗ ██╗     ███████╗ █████╗     ███████╗██╗   ██╗██████╗ ███████╗" -ForegroundColor Yellow
Write-Host " ██╔══██╗██║     ██╔════╝██╔══██╗    ██╔════╝██║   ██║██╔══██╗██╔════╝" -ForegroundColor Yellow
Write-Host " ███████║██║     █████╗  ███████║    ███████╗██║   ██║██████╔╝█████╗  " -ForegroundColor Yellow
Write-Host " ██╔══██║██║     ██╔══╝  ██╔══██║    ╚════██║██║   ██║██╔═══╝ ██╔══╝  " -ForegroundColor Yellow
Write-Host " ██║  ██║███████╗██║     ██║  ██║    ███████║╚██████╔╝██║     ███████╗" -ForegroundColor Yellow
Write-Host " ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝  ╚═╝    ╚══════╝ ╚═════╝ ╚═╝     ╚══════╝" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  🚀 PANDUAN INSTALASI & SETUP 1-KLIK ALFA SOVEREIGN AI AGENT" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/6] Memeriksa Lingkungan Python..." -ForegroundColor Cyan
try {
    $pyVer = & python --version 2>&1
    Write-Host "   [OK] Ditemukan: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "   [ERR] Python tidak terdeteksi di PATH!" -ForegroundColor Red
    Write-Host "   Silakan unduh Python 3.10+ dari https://www.python.org dan pastikan centang 'Add Python to PATH'." -ForegroundColor Yellow
    exit 1
}

# 2. Check Node.js (Optional)
Write-Host ""
Write-Host "[2/6] Memeriksa Node.js (Opsional)..." -ForegroundColor Cyan
try {
    $nodeVer = & node --version 2>&1
    Write-Host "   [OK] Ditemukan Node.js: $nodeVer (WhatsApp Bot Siap)" -ForegroundColor Green
} catch {
    Write-Host "   [INFO] Node.js belum terpasang (Opsional: dibutuhkan jika ingin menggunakan bot WhatsApp)." -ForegroundColor DarkGray
}

# 3. Create Virtual Environment
Write-Host ""
Write-Host "[3/6] Menyiapkan Virtual Environment Python (venv)..." -ForegroundColor Cyan
if (-not (Test-Path "$dir\venv")) {
    Write-Host "   [*] Membuat virtual environment..." -ForegroundColor DarkGray
    & python -m venv venv
    Write-Host "   [OK] Virtual environment 'venv' berhasil dibuat." -ForegroundColor Green
} else {
    Write-Host "   [OK] Virtual environment 'venv' sudah siap." -ForegroundColor Green
}

# 4. Install Dependencies
Write-Host ""
Write-Host "[4/6] Memeriksa Dependensi Paket Python..." -ForegroundColor Cyan
Write-Host "   [*] Memperbarui pip & memasang dependensi (FastAPI, Gemini SDK, Telegram)..." -ForegroundColor DarkGray
& "$dir\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$dir\venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
Write-Host "   [OK] Seluruh dependensi berhasil terpasang!" -ForegroundColor Green

# 5. Interactive Configuration Setup (.env)
Write-Host ""
Write-Host "[5/6] Konfigurasi Pengaturan & Kunci API (.env)..." -ForegroundColor Cyan
$envPath = "$dir\.env"
if (-not (Test-Path $envPath)) {
    if (Test-Path "$dir\.env.example") {
        Copy-Item "$dir\.env.example" $envPath
    } else {
        Set-Content -Path $envPath -Value "" -Encoding UTF8
    }
}

$envContent = Get-Content $envPath -Raw

function Set-EnvVar([string]$Key, [string]$Value) {
    param($Key, $Value)
    $script:envContent = if ($script:envContent -match "(?m)^$Key=.*`$") {
        $script:envContent -replace "(?m)^$Key=.*`$", "$Key=$Value"
    } else {
        $script:envContent + "`n$Key=$Value"
    }
}

# Generate Secure Random Secret Keys if missing
function Get-SecureHex([int]$Length) {
    $bytes = New-Object byte[] $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return ($bytes | ForEach-Object { "{0:x2}" -f $_ }) -join ""
}

if ($envContent -notmatch "(?m)^SESSION_SECRET=\s*\S+") {
    $sessSecret = Get-SecureHex 32
    Set-EnvVar "SESSION_SECRET" $sessSecret
}
if ($envContent -notmatch "(?m)^ENCRYPTION_KEY=\s*\S+") {
    $encKey = Get-SecureHex 16
    Set-EnvVar "ENCRYPTION_KEY" $encKey
}
Set-EnvVar "GEMINI_MODEL" "gemini-3.6-flash"
Set-EnvVar "ALFA_ALLOW_HOST_EXEC" "true"
Set-EnvVar "DASHBOARD_HOST" "127.0.0.1"
Set-EnvVar "DASHBOARD_PORT" "8080"

Write-Host "   [?] Pilih Mode Setup yang Anda inginkan:" -ForegroundColor Yellow
Write-Host "       [1] Setup Lengkap (Bot Telegram + Web Dashboard + CLI) [Rekomendasi]" -ForegroundColor White
Write-Host "       [2] Setup Cepat / Mode Lokal (Hanya butuh Google Gemini API Key)" -ForegroundColor White
$modeChoice = Read-Host "   Pilihan Anda (1/2, default: 1)"
if (-not $modeChoice) { $modeChoice = "1" }

# Gemini Key
if ($envContent -notmatch "(?m)^GEMINI_API_KEY=\s*[A-Za-z0-9_\-\.]{15,}") {
    Write-Host ""
    Write-Host "👉 Masukkan Google Gemini API Key Anda (gratis di https://aistudio.google.com):" -ForegroundColor Yellow
    $geminiKey = Read-Host "   GEMINI_API_KEY"
    if ($geminiKey) { Set-EnvVar "GEMINI_API_KEY" $geminiKey.Trim() }
} else {
    Write-Host "   [OK] GEMINI_API_KEY sudah terpasang." -ForegroundColor Green
}

if ($modeChoice -eq "1") {
    # Telegram Bot Token
    if ($envContent -notmatch "(?m)^TELEGRAM_BOT_TOKEN=\s*\d{6,}:[A-Za-z0-9_\-]{20,}") {
        Write-Host ""
        Write-Host "👉 Masukkan Token Bot Telegram Anda dari @BotFather (misal: 123456:ABC...):" -ForegroundColor Yellow
        $botToken = Read-Host "   TELEGRAM_BOT_TOKEN"
        if ($botToken) { Set-EnvVar "TELEGRAM_BOT_TOKEN" $botToken.Trim() }
    } else {
        Write-Host "   [OK] TELEGRAM_BOT_TOKEN sudah terpasang." -ForegroundColor Green
    }

    # Telegram User ID
    if ($envContent -notmatch "(?m)^ALLOWED_USER_IDS=\s*\d+") {
        Write-Host ""
        Write-Host "👉 Masukkan Telegram User ID Anda (dapatkan dari bot @userinfobot):" -ForegroundColor Yellow
        $allowedIds = Read-Host "   ALLOWED_USER_IDS"
        if ($allowedIds) { Set-EnvVar "ALLOWED_USER_IDS" $allowedIds.Trim() }
    } else {
        Write-Host "   [OK] ALLOWED_USER_IDS sudah terpasang." -ForegroundColor Green
    }
} else {
    Write-Host "   [INFO] Mode Cepat Lokal dipilih. Bot Telegram dilewati (dapat diset nanti kapan saja)." -ForegroundColor DarkGray
}

# Save .env
Set-Content -Path $envPath -Value $envContent.Trim() -Encoding UTF8
Write-Host "   [OK] File konfigurasi .env berhasil disimpan." -ForegroundColor Green

# Master Vault Key
$vaultKeyPath = "$HOME\.alfa_vault_master.key"
if (-not (Test-Path $vaultKeyPath)) {
    $vaultKey = Get-SecureHex 32
    Set-Content -Path $vaultKeyPath -Value $vaultKey -Encoding UTF8
    Write-Host "   [OK] Master encryption key digenerate di $vaultKeyPath" -ForegroundColor Green
}

# 6. Deliverable Directory
Write-Host ""
Write-Host "[6/6] Menyiapkan Direktori Output Deliverable Swarm..." -ForegroundColor Cyan
$swarmOutputDir = "$HOME\Documents\ALFA_SWARM_OUTPUTS"
if (-not (Test-Path $swarmOutputDir)) {
    New-Item -ItemType Directory -Path $swarmOutputDir -Force | Out-Null
}
Write-Host "   [OK] Direktori output siap: $swarmOutputDir" -ForegroundColor Green

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "  🎉 SETUP SELESAI DENGAN SUKSES! ALFA SIAP DIGUNAKAN." -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Cara Menjalankan:" -ForegroundColor Yellow
Write-Host "  1. Buka File Explorer lalu Double-Click:"
Write-Host "     run.bat" -ForegroundColor White
Write-Host ""
Write-Host "  2. Dashboard Web dapat diakses di:"
Write-Host "     http://localhost:8080" -ForegroundColor Green
Write-Host ""

$launchNow = Read-Host "👉 Ingin langsung menjalankan ALFA sekarang? (Y/n)"
if ($launchNow -ne "n" -and $launchNow -ne "N") {
    Write-Host "[*] Meluncurkan ALFA Sovereign AI..." -ForegroundColor Green
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$dir\run.bat`"" -WorkingDirectory $dir
}
