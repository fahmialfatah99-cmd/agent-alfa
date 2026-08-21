@echo off
title ALFA Sovereign AI Agent - Dual Service Runner
color 0b

echo ===================================================
echo   ALFA SOVEREIGN AI AGENT (Windows Launcher)
echo ===================================================
echo.

if not exist venv (
    echo [!] Virtual environment belum ditemukan.
    echo [*] Membuat virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo [*] Menginstall dependensi...
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

if not exist .env (
    if exist .env.example (
        copy .env.example .env
        echo [!] File .env telah dibuat dari .env.example.
        echo [!] Silakan edit .env dan masukkan TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY.
    )
)

echo [*] Menjalankan Web Dashboard pada http://localhost:8080...
start "ALFA Web Dashboard" cmd /k "python web_dashboard.py"

echo [*] Menjalankan Telegram Bot Core...
python bot.py

pause
