#!/usr/bin/env bash
# ==============================================================================
# ALFA SOVEREIGN AI AGENT & DASHBOARD RUNNER
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "⚠️ Virtual environment belum dibuat. Menjalankan setup.sh..."
    bash setup.sh
fi

echo "========================================================"
echo "🚀 MENJALANKAN ALFA SOVEREIGN AI ECOSYSTEM..."
echo "  👉 Telegram AI Bot     : Aktif"
echo "  👉 Web Command Center  : http://localhost:8080"
echo "========================================================"

# Trap SIGINT / SIGTERM to kill all background child processes
cleanup() {
    echo ""
    echo "🛑 Menghentikan seluruh service..."
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Read .env for token check
source .env 2>/dev/null || true

# Start Web Dashboard in background
./venv/bin/python3 web_dashboard.py &
DASH_PID=$!

if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ "$TELEGRAM_BOT_TOKEN" != "your_telegram_bot_token_here" ]; then
    echo "  👉 Telegram AI Bot     : Aktif"
    ./venv/bin/python3 bot.py &
    BOT_PID=$!
    wait $DASH_PID $BOT_PID
else
    echo "  👉 Telegram AI Bot     : Dinonaktifkan (Token belum disetel)"
    echo "  👉 Masuk ke mode Web Dashboard & CLI Interaktif..."
    ./venv/bin/python3 cli.py
fi

