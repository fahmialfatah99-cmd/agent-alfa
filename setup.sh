#!/usr/bin/env bash
# ==============================================================================
# ALFA SOVEREIGN AI AGENT & TELEGRAM BOT - 1-CLICK INTERACTIVE SETUP WIZARD
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Color constants
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
VIOLET='\033[0;35m'
NC='\033[0m' # No Color

clear
echo -e "${CYAN}"
echo "  █████╗ ██╗     ███████╗ █████╗     ███████╗██╗   ██╗██████╗ ███████╗██████╗ ██╗   ██╗██████╗ ███████╗"
echo " ██╔══██╗██║     ██╔════╝██╔══██╗    ██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║   ██║██╔══██╗██╔════╝"
echo " ███████║██║     █████╗  ███████║    ███████╗██║   ██║██████╔╝█████╗  ██████╔╝██║   ██║██████╔╝███████╗"
echo " ██╔══██║██║     ██╔══╝  ██╔══██║    ╚════██║██║   ██║██╔═══╝ ██╔══╝  ██╔══██╗██║   ██║██╔══██╗╚════██║"
echo " ██║  ██║███████╗██║     ██║  ██║    ███████║╚██████╔╝██║     ███████╗██║  ██║╚██████╔╝██████╔╝███████║"
echo " ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝  ╚═╝    ╚══════╝ ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝"
echo -e "${NC}"
echo -e "${VIOLET}==============================================================================${NC}"
echo -e "${GREEN}🚀 Memulai Panduan Instalasi & Konfigurasi Mandiri ALFA Sovereign AI Bot...${NC}"
echo -e "${VIOLET}==============================================================================${NC}"
echo ""

# 1. Check Python3 & pip
echo -e "${CYAN}[1/6] Memeriksa Lingkungan Sistem...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 tidak ditemukan. Pasang Python 3 (3.10+) terlebih dahulu:${NC}"
    echo "   sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi
PY_VER=$(python3 --version)
echo -e "   ${GREEN}✅ Ditemukan: ${PY_VER}${NC}"

# 2. Check Node.js for WhatsApp Service (Optional)
if command -v node &> /dev/null; then
    NODE_VER=$(node --version)
    echo -e "   ${GREEN}✅ Ditemukan Node.js: ${NODE_VER} (WhatsApp Sheets Bot Siap)${NC}"
else
    echo -e "   ${YELLOW}⚠️ Node.js belum terpasang (Opsional: dibutuhkan jika ingin menggunakan bot WhatsApp).${NC}"
fi

# 3. Create Virtual Environment
echo ""
echo -e "${CYAN}[2/6] Menyiapkan Virtual Environment Python (venv)...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "   ${GREEN}✅ Virtual environment 'venv' berhasil dibuat.${NC}"
else
    echo -e "   ${GREEN}✅ Virtual environment 'venv' sudah ada.${NC}"
fi

# 4. Install Dependencies
echo ""
echo -e "${CYAN}[3/6] Menginstall & Memperbarui Dependensi Python...${NC}"
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt --quiet
echo -e "   ${GREEN}✅ Seluruh dependensi python (Telegram, FastAPI, Gemini SDK, Tools) berhasil terpasang!${NC}"

# 5. Interactive Configuration Setup (.env)
echo ""
echo -e "${CYAN}[4/6] Konfigurasi Kredensial & Kunci API (.env)...${NC}"
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Auto-generate secure random keys if missing
if ! grep -q "^SESSION_SECRET=[a-zA-Z0-9]" .env 2>/dev/null; then
    SESS_SEC=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "alfa_session_secret_$(date +%s)")
    if grep -q "^SESSION_SECRET=" .env; then
        sed -i "s|^SESSION_SECRET=.*|SESSION_SECRET=$SESS_SEC|" .env
    else
        echo "SESSION_SECRET=$SESS_SEC" >> .env
    fi
fi

if ! grep -q "^ENCRYPTION_KEY=[a-zA-Z0-9]" .env 2>/dev/null; then
    ENC_KEY=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || openssl rand -hex 16 2>/dev/null || echo "alfa_enc_key_$(date +%s)")
    if grep -q "^ENCRYPTION_KEY=" .env; then
        sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENC_KEY|" .env
    else
        echo "ENCRYPTION_KEY=$ENC_KEY" >> .env
    fi
fi

# Ensure correct model format
sed -i "s|^GEMINI_MODEL=.*|GEMINI_MODEL=gemini-3.6-flash|" .env 2>/dev/null || true

# Read existing values if any
source .env 2>/dev/null || true

# Interactive Gemini Key
if [ -z "$GEMINI_API_KEY" ] || [ "$GEMINI_API_KEY" == "your_gemini_api_key_here" ]; then
    echo -e "${YELLOW}👉 Masukkan Google Gemini API Key Anda (gratis di https://aistudio.google.com):${NC}"
    read -rp "   GEMINI_API_KEY: " INPUT_GEMINI_KEY
    if [ -n "$INPUT_GEMINI_KEY" ]; then
        sed -i "s|GEMINI_API_KEY=.*|GEMINI_API_KEY=$INPUT_GEMINI_KEY|" .env
    fi
else
    echo -e "   ${GREEN}✅ GEMINI_API_KEY sudah terkonfigurasi.${NC}"
fi

# Interactive Bot Token
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" == "your_telegram_bot_token_here" ]; then
    echo -e "${YELLOW}👉 Masukkan Token Bot Telegram Anda dari @BotFather (opsional, tekan ENTER jika hanya mode web/CLI):${NC}"
    read -rp "   TELEGRAM_BOT_TOKEN: " INPUT_BOT_TOKEN
    if [ -n "$INPUT_BOT_TOKEN" ]; then
        sed -i "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$INPUT_BOT_TOKEN|" .env
    fi
else
    echo -e "   ${GREEN}✅ TELEGRAM_BOT_TOKEN sudah terkonfigurasi.${NC}"
fi

# Interactive Allowed User IDs
if [ -z "$ALLOWED_USER_IDS" ] && [ -n "$INPUT_BOT_TOKEN" ]; then
    echo -e "${YELLOW}👉 Masukkan Telegram User ID Anda (opsional, dapatkan dari @userinfobot):${NC}"
    read -rp "   ALLOWED_USER_IDS (kosongkan jika publik): " INPUT_ALLOWED_IDS
    if [ -n "$INPUT_ALLOWED_IDS" ]; then
        sed -i "s|ALLOWED_USER_IDS=.*|ALLOWED_USER_IDS=$INPUT_ALLOWED_IDS|" .env
    fi
fi

# 6. Setup Output Deliverable Directory
echo ""
echo -e "${CYAN}[5/6] Menyiapkan Direktori Output Deliverable Swarm...${NC}"
mkdir -p "$HOME/Dokumen/ALFA_SWARM_OUTPUTS"
echo -e "   ${GREEN}✅ Direktori siap: $HOME/Dokumen/ALFA_SWARM_OUTPUTS${NC}"

# 7. Optional Systemd Service Setup
echo ""
echo -e "${CYAN}[6/6] Opsi Menjalankan Otomatis di Background (Systemd Service)...${NC}"
USER_SERVICES_DIR="$HOME/.config/systemd/user"
mkdir -p "$USER_SERVICES_DIR"

cat <<EOF > "$USER_SERVICES_DIR/telegram-ai-bot.service"
[Unit]
Description=ALFA Sovereign AI Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python3 bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

cat <<EOF > "$USER_SERVICES_DIR/alfa-dashboard.service"
[Unit]
Description=ALFA Sovereign AI Web Management Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python3 web_dashboard.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload 2>/dev/null || true
echo -e "   ${GREEN}✅ File systemd user service berhasil digenerate di ~/.config/systemd/user/${NC}"

echo ""
echo -e "${VIOLET}==============================================================================${NC}"
echo -e "${GREEN}🎉 SETUP BERHASIL SELESAI DENGAN SEMPURNA!${NC}"
echo -e "${VIOLET}==============================================================================${NC}"
echo ""
echo -e "${CYAN}Cara Menjalankan Sistem:${NC}"
echo -e "  1. Jalankan langsung di terminal (Bot + Web Dashboard):"
echo -e "     ${YELLOW}./run.sh${NC}"
echo ""
echo -e "  2. ATAU jalankan 24/7 di background via Systemd:"
echo -e "     ${YELLOW}systemctl --user enable --now telegram-ai-bot.service alfa-dashboard.service${NC}"
echo ""
echo -e "  3. Akses Web Management Command Center:"
echo -e "     ${GREEN}http://localhost:8080${NC}"
echo ""
echo -e "${VIOLET}==============================================================================${NC}"

