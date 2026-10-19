# 🚀 Panduan Deployment Produksi — ALFA Sovereign AI

Panduan resmi untuk men-deploy **ALFA Sovereign AI** (Dashboard Web, Telegram Bot, WA Sheets Bot, dan Multi-Agent Swarm) di lingkungan server produksi (VPS Linux, Docker Container, atau Dedicated Server).

---

## 📑 Daftar Isi
1. [Arsitektur Deployment](#1-arsitektur-deployment)
2. [Metode A: Deployment Kontainer Docker Compose (Rekomendasi Cepat)](#2-metode-a-deployment-kontainer-docker-compose)
3. [Metode B: Baremetal Linux VPS dengan Systemd (24/7 Service)](#3-metode-b-baremetal-linux-vps-dengan-systemd)
4. [Konfigurasi Reverse Proxy & WebSocket (Caddy / Nginx)](#4-konfigurasi-reverse-proxy-websocket)
5. [Manajemen Keamanan & Lingkungan Produksi](#5-manajemen-keamanan-lingkungan-produksi)
6. [Health Check, Monitoring & Pemeliharaan Database](#6-health-check-monitoring-pemeliharaan-database)

---

## 1. Arsitektur Deployment

ALFA dirancang modular dengan komponen terpisah yang dapat berjalan bersamaan:

```text
               +-----------------------------------------+
               |        Internet (Klien & Webhooks)       |
               +-----------------------------------------+
                                    |
                    HTTPS (Port 443) / WSS (WebSocket)
                                    v
               +-----------------------------------------+
               |    Reverse Proxy (Caddy / Nginx / SSL)  |
               +-----------------------------------------+
                                    |
                    HTTP / WS Internal (127.0.0.1:8080)
                                    v
+--------------------------------------------------------------------------+
| ALFA APPLICATION LAYER                                                   |
|                                                                          |
|  [FastAPI Web Dashboard] <======> [SQLite: agent_data.db]               |
|      - REST API: /api/*                  - Memory Store                  |
|      - WebSockets: /ws/*                 - Vault API Keys (AES-GCM)      |
|      - Glassmorphic UI                   - Custom Workforce Agents       |
|                                                                          |
|  [Telegram AI Bot Service]               [WhatsApp Sheets Bot Service]   |
|      - Turn Executor                         - Baileys / Multi-Device    |
|      - Multi-Provider LLM Fallback           - Dynamic Formatter         |
|      - 130+ Native Autonomous Tools          - Google Drive Sync         |
|                                                                          |
|  [Isolated Docker Sandbox (/dev/shm/alfa_sandbox)]                       |
|      - Eksekusi kode aman & mandiri tanpa merusak OS host                |
+--------------------------------------------------------------------------+
```

---

## 2. Metode A: Deployment Kontainer Docker Compose

Metode ini mengemas seluruh dependensi sistem (Python, FFmpeg, SQLite, libgl) dalam kontainer terisolasi.

### Langkah-langkah:

1. **Clone Repositori & Persiapan Direktori:**
   ```bash
   git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git
   cd agent-alfa
   ```

2. **Siapkan Konfigurasi `.env`:**
   Salin dari template dan sesuaikan token API Anda:
   ```bash
   cp .env.example .env
   nano .env
   ```
   *Pastikan minimal mengisi:*
   - `GEMINI_API_KEY`: API Key dari Google AI Studio.
   - `TELEGRAM_BOT_TOKEN`: Token bot dari @BotFather.
   - `ALLOWED_USER_IDS`: ID numerik akun Telegram Anda.
   - `DASHBOARD_AUTH_TOKEN`: Token rahasia otentikasi dashboard.
   - `SESSION_SECRET`: Kunci acak hex 32-byte untuk enkripsi cookie sesi.

3. **Build & Jalankan Multi-Container Stack:**
   ```bash
   docker compose up -d --build
   ```

4. **Periksa Status & Log:**
   ```bash
   docker compose ps
   docker compose logs -f alfa-dashboard
   docker compose logs -f alfa-bot
   ```

5. **Akses Dashboard Web:**
   Buka peramban di `http://IP_SERVER:8080` atau via domain yang telah dikonfigurasi reverse proxy.

---

## 3. Metode B: Baremetal Linux VPS dengan Systemd

Jika menginginkan efisiensi performa maksimal dengan konsumsi RAM di bawah 200 MB, jalankan langsung di Linux Host menggunakan `systemd` user services.

### Langkah-langkah:

1. **Instalasi Prasyarat Sistem (Ubuntu/Debian):**
   ```bash
   sudo apt update && sudo apt install -y python3 python3-venv git curl ffmpeg sqlite3
   ```

2. **Buat Virtual Environment & Pasang Dependensi:**
   ```bash
   cd ~/agent-alfa
   python3 -m venv venv
   ./venv/bin/pip install --upgrade pip setuptools wheel
   ./venv/bin/pip install -r requirements.txt
   ```

3. **Konfigurasi Systemd User Services:**
   Pastikan direktori service ada:
   ```bash
   mkdir -p ~/.config/systemd/user
   ```

   **File 1: Telegram Bot Service (`~/.config/systemd/user/telegram-ai-bot.service`)**
   ```ini
   [Unit]
   Description=ALFA Sovereign Telegram AI Bot
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=%h/agent-alfa
   ExecStart=%h/agent-alfa/venv/bin/python bot.py
   Restart=always
   RestartSec=5
   MemoryMax=2G
   StandardOutput=journal
   StandardError=journal

   [Install]
   WantedBy=default.target
   ```

   **File 2: Web Command Center Service (`~/.config/systemd/user/alfa-dashboard.service`)**
   ```ini
   [Unit]
   Description=ALFA Sovereign Web Command Center Dashboard
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=%h/agent-alfa
   ExecStart=%h/agent-alfa/venv/bin/python web_dashboard.py
   Restart=always
   RestartSec=5
   MemoryMax=1G
   StandardOutput=journal
   StandardError=journal

   [Install]
   WantedBy=default.target
   ```

4. **Aktifkan & Jalankan Service:**
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now telegram-ai-bot.service
   systemctl --user enable --now alfa-dashboard.service
   ```

5. **Aktifkan Lingering (Agar service tetap berjalan saat logout dari SSH):**
   ```bash
   loginctl enable-linger $USER
   ```

---

## 4. Konfigurasi Reverse Proxy & WebSocket

ALFA Dashboard menggunakan WebSocket untuk **Live Telemetry (`/ws/broadcast`)**, **Log Streaming (`/ws/logs`)**, dan **Web Terminal (`/ws/terminal`)**.

### Opsi 1: Caddy (Sangat Direkomendasikan — Otomatis SSL/TLS)

Caddy secara otomatis menangani sertifikat SSL Let's Encrypt dan mendukung WebSocket secara native.

Buat file `/etc/caddy/Caddyfile`:
```caddy
alfa.domainkamu.com {
    reverse_proxy 127.0.0.1:8080 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```
Muat ulang Caddy:
```bash
sudo systemctl reload caddy
```

---

### Opsi 2: Nginx + Certbot

Jika menggunakan Nginx, pastikan upgrade header WebSocket terpasang dengan benar.

Buat file `/etc/nginx/sites-available/alfa`:
```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    server_name alfa.domainkamu.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;

        # WebSocket headers
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```
Aktifkan dan pasang SSL via Certbot:
```bash
sudo ln -s /etc/nginx/sites-available/alfa /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d alfa.domainkamu.com
```

---

## 5. Manajemen Keamanan & Lingkungan Produksi

1. **Vault Enkripsi Kunci API:**
   - Semua kunci provider cadangan (Groq, OpenRouter, Perplexity, Cerebras) yang ditambahkan melalui Dashboard disimpan terenkripsi menggunakan AES-256-GCM.
   - Salt enkripsi terikat pada hardware ID mesin host untuk mencegah pencurian database.

2. **Proteksi Akses Dashboard:**
   - Selalu tetapkan `DASHBOARD_AUTH_TOKEN` yang kuat di `.env`.
   - Gunakan fitur WebAuthn (Passkey / Biometrik Sidik Jari) di menu Security Dashboard untuk login tanpa password yang kebal phishing.

3. **Pembatasan Pengguna Telegram (`ALLOWED_USER_IDS`):**
   - Bot tidak akan merespons siapa pun di luar ID numerik yang terdaftar di `ALLOWED_USER_IDS`.

---

## 6. Health Check, Monitoring & Pemeliharaan Database

### Endpoint Pemantauan Otomatis:
- `GET /health`: Mengembalikan status HTTP 200 `{ "status": "healthy", "service": "alfa-command-center" }`.
- `GET /metrics`: Metrik internal (CPU, Memory, Swarm Execution Steps, Active Sessions).

### Backup Database SQLite Otomatis:
Jalankan backup berkala `agent_data.db` via cron:
```bash
# Tambahkan di crontab (crontab -e):
0 3 * * * sqlite3 ~/agent-alfa/agent_data.db ".backup '/home/fahmial/backups/alfa_db_$(date +\%F).db'"
```

Dengan konfigurasi ini, server ALFA Sovereign AI Anda beroperasi 24/7 dengan keandalan enterprise, waktu henti minimal, dan keamanan tingkat tinggi.
