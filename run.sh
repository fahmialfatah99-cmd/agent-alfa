#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "⚠️ Virtual environment belum dibuat. Menjalankan setup.sh..."
    bash setup.sh
fi

echo "🚀 Menjalankan Telegram AI Bot..."
./venv/bin/python3 bot.py
