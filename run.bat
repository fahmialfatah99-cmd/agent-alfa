@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title ALFA Sovereign AI - Universal Service Launcher
color 0b

echo ===================================================
echo   ALFA SOVEREIGN AI AGENT (Windows Launcher)
echo ===================================================
echo.

:: 1. Cek Virtual Environment & .env
if not exist venv (
    echo [!] Lingkungan belum disetup. Menjalankan Setup Wizard otomatis...
    echo.
    call "%~dp0setup.bat"
    exit /b
)

if not exist .env (
    echo [!] File .env belum ditemukan. Menjalankan Setup Wizard otomatis...
    echo.
    call "%~dp0setup.bat"
    exit /b
)

call venv\Scripts\activate.bat

:: 2. Jalankan Web Dashboard
echo [*] Meluncurkan Web Command Center di background...
start "ALFA Web Dashboard" cmd /c "python web_dashboard.py"

:: Tunggu 2 detik agar server siap
timeout /t 2 /nobreak >nul

:: 3. Cek apakah Token Telegram sudah diisi
set BOT_TOKEN=
for /f "tokens=1,2 delims==" %%A in (.env) do (
    if "%%A"=="TELEGRAM_BOT_TOKEN" set BOT_TOKEN=%%B
)

if "%BOT_TOKEN%"=="" goto NO_BOT
if "%BOT_TOKEN%"=="your_telegram_bot_token_here" goto NO_BOT

echo [*] Token Telegram ditemukan. Menjalankan Bot Telegram...
echo [OK] ALFA Sovereign AI aktif sepenuhnya! (Web Dashboard: http://localhost:8080)
echo.
python bot.py
goto END

:NO_BOT
echo.
echo ================================================================
echo [INFO] Berjalan dalam Mode Web Dashboard ^& CLI Lokal
echo        (Token Telegram belum disetel - bot Telegram dilewati)
echo.
echo 👉 Web Management Command Center: http://localhost:8080
echo 👉 Membuka antarmuka CLI Interaktif...
echo ================================================================
echo.
start http://localhost:8080
python cli.py

:END
pause
