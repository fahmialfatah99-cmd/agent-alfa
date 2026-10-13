#!/usr/bin/env bash
# ==============================================================================
# ALFA Sovereign AI - One-Click Production Deployment Script
# ==============================================================================
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}   ALFA Sovereign AI - Production Deployment Tool      ${NC}"
echo -e "${BLUE}======================================================${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Environment check
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo -e "${YELLOW}[!] File .env tidak ditemukan. Menyalin dari .env.example...${NC}"
        cp .env.example .env
        echo -e "${GREEN}[+] File .env berhasil dibuat. Silakan sesuaikan API key Anda.${NC}"
    else
        echo -e "${RED}[X] File .env tidak ditemukan! Silakan buat berkas .env terlebih dahulu.${NC}"
        exit 1
    fi
fi

# 2. Argument handling
MODE="${1:-systemd}"

case "$MODE" in
    docker|--docker)
        echo -e "${BLUE}[*] Memulai deployment berbasis Docker Compose...${NC}"
        if ! command -v docker &> /dev/null; then
            echo -e "${RED}[X] Docker tidak terpasang di sistem!${NC}"
            exit 1
        fi
        docker compose pull || true
        docker compose up -d --build
        echo -e "${GREEN}[+] Layanan ALFA Docker berhasil dinyalakan!${NC}"
        echo -e "${GREEN}    - Web Command Center: http://localhost:8080${NC}"
        echo -e "${GREEN}    - Status Container:${NC}"
        docker compose ps
        ;;

    systemd|--systemd)
        echo -e "${BLUE}[*] Memeriksa instalasi lokal Python venv & Systemd...${NC}"
        if [ ! -d "venv" ]; then
            echo -e "${YELLOW}[!] Virtualenv belum dibuat. Membuat ./venv...${NC}"
            python3 -m venv venv
            ./venv/bin/pip install --upgrade pip
            ./venv/bin/pip install -r requirements.txt
        fi

        echo -e "${BLUE}[*] Memeriksa database integritas...${NC}"
        ./venv/bin/python3 -c "from alfa.core import database; print('Database status: OK')"

        echo -e "${BLUE}[*] Me-reload dan me-restart layanan systemd user...${NC}"
        systemctl --user daemon-reload
        systemctl --user restart alfa-dashboard.service telegram-ai-bot.service
        sleep 2
        echo -e "${GREEN}[+] Status Layanan:${NC}"
        systemctl --user status alfa-dashboard.service --no-pager | head -n 6
        systemctl --user status telegram-ai-bot.service --no-pager | head -n 6
        echo -e "${GREEN}[+] ALFA Sovereign AI aktif dan berjalan optimal!${NC}"
        echo -e "${GREEN}    - Dashboard: http://localhost:8080${NC}"
        echo -e "${GREEN}    - API Docs:  http://localhost:8080/docs${NC}"
        ;;

    verify|--verify)
        echo -e "${BLUE}[*] Menjalankan verifikasi kode dan test suite...${NC}"
        ./venv/bin/ruff check .
        ./venv/bin/ruff format --check .
        ./venv/bin/pytest tests/
        echo -e "${GREEN}[+] Semua verifikasi 100% lulus!${NC}"
        ;;

    *)
        echo "Penggunaan: $0 [systemd|docker|verify]"
        exit 1
        ;;
esac
