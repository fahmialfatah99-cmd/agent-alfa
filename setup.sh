#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=== Menyiapkan Lingkungan Telegram AI Bot ==="

# 1. Check Python3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 tidak ditemukan. Silakan pasang python3 terlebih dahulu."
    exit 1
fi

# 2. Setup virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Membuat virtual environment (venv)..."
    python3 -m venv venv
fi

# 3. Activate and install requirements
echo "📥 Menginstall dependensi (python-telegram-bot, google-genai, python-dotenv)..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Copy .env if not exists
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "📝 File .env baru telah dibuat dari .env.example."
    echo "👉 Silakan edit file .env dan masukkan TELEGRAM_BOT_TOKEN serta GEMINI_API_KEY Anda."
else
    echo "✅ File .env sudah ada."
fi

echo "==========================================="
echo "✅ Setup selesai!"
echo "Untuk menjalankan bot:"
echo "  ./run.sh"
echo "==========================================="
