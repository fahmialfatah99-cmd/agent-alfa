#!/usr/bin/env bash
# ==============================================================================
# ALFA Sovereign Command Center - Auto Browser Opener on Internet Connection
# ==============================================================================

LOG_FILE="/tmp/alfa_dashboard_auto_open.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALFA Auto-Opener started." > "$LOG_FILE"

# 1. Give GUI session 3 seconds to stabilize
sleep 3

# 2. Wait for local dashboard server (http://localhost:8080) to be ready
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Menunggu server dashboard lokal (port 8080)..." >> "$LOG_FILE"
SERVER_READY=0
for i in $(seq 1 45); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://localhost:8080/ 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
        SERVER_READY=1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dashboard lokal aktif (HTTP $HTTP_CODE) pada detik ke-$((i*2))" >> "$LOG_FILE"
        break
    fi
    sleep 2
done

# If server still not ready, try starting via systemctl user or python
if [ "$SERVER_READY" -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Memulai ulang alfa-dashboard.service via systemctl --user..." >> "$LOG_FILE"
    systemctl --user start alfa-dashboard.service 2>/dev/null || true
    sleep 4
fi

# 3. Wait for active Internet Connection (ping/http check)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Menunggu koneksi internet aktif..." >> "$LOG_FILE"
INTERNET_READY=0
for i in $(seq 1 60); do
    if ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1 || ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1 || curl -s --connect-timeout 2 http://connectivitycheck.gstatic.com/generate_204 >/dev/null 2>&1; then
        INTERNET_READY=1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Internet terkoneksi aktif pada percobaan ke-$i." >> "$LOG_FILE"
        break
    fi
    sleep 2
done

if [ "$INTERNET_READY" -eq 1 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Membuka dashboard http://localhost:8080 di browser..." >> "$LOG_FILE"
    
    # Send desktop notification if notify-send exists
    if which notify-send >/dev/null 2>&1; then
        notify-send "ALFA Command Center" "🌐 Internet Terhubung! Membuka Dashboard (http://localhost:8080)..." -i preferences-system-network -t 4000 2>/dev/null || true
    fi

    # Open browser with localhost:8080
    if which xdg-open >/dev/null 2>&1; then
        xdg-open "http://localhost:8080" >/dev/null 2>&1 &
    elif which google-chrome >/dev/null 2>&1; then
        google-chrome "http://localhost:8080" >/dev/null 2>&1 &
    elif which firefox >/dev/null 2>&1; then
        firefox "http://localhost:8080" >/dev/null 2>&1 &
    elif which x-www-browser >/dev/null 2>&1; then
        x-www-browser "http://localhost:8080" >/dev/null 2>&1 &
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Selesai! Browser berhasil diluncurkan." >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Timeout menunggu koneksi internet (120 detik). Membuka dashboard lokal..." >> "$LOG_FILE"
    xdg-open "http://localhost:8080" >/dev/null 2>&1 &
fi
