# ⚡ ALFA // Sovereign AI Agent Ecosystem & Command Center

<div align="center">

![ALFA Sovereign AI](https://img.shields.io/badge/ALFA-Sovereign%20AI%20v4.5-06B6D4?style=for-the-badge&logo=probot&logoColor=white)
![Cross Platform](https://img.shields.io/badge/OS-Linux%20%7C%20macOS%20%7C%20Windows-8B5CF6?style=for-the-badge&logo=linux&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google-Gemini%203.x-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API%20v21-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Dashboard-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-emerald?style=for-the-badge)

**Ekosistem AI Otonom Terpadu & Multi-Platform: Multi-Agent Swarm, Self-Evolution Plugins, Neural Vector Brain (Hybrid RAG), 112+ Sovereign Tools, Master Scraper, Passkey Vault, dan Web Command Center.**

[Fitur Unggulan](#-fitur-unggulan) • [Panduan Multi-OS](#-panduan-instalasi--menjalankan-multi-os) • [Konfigurasi .env](#-konfigurasi-environment-env) • [Perintah Telegram](#-daftar-perintah-telegram) • [Tools & Workbench](#-tools-catalog--interactive-workbench) • [Keamanan](#-keamanan--privasi)

</div>

---

## 🌟 Fitur Unggulan (Level 4.5 Sovereign AI)

### 1. 🤖 Multi-Agent Swarm & War Room (Dual Mode)
* **Mode 1 (Rapat Perencanaan Strategis):** 6 AI Agent spesialis (*Alpha Lead, Code Crafter, System Auditor, Researcher Prime, Strategic Planner, Laguna Co-Pilot*) berdiskusi otonom membedah masalah dan merumuskan Action Plan.
* **Mode 2 (Eksekusi Nyata Otonom):** Agen AI langsung mengeksekusi kode, scraping data, menulis skrip, dan membuat file deliverable (`CSV`, `JSON`, `Python`) yang otomatis tersimpan di `~/Dokumen/ALFA_SWARM_OUTPUTS` dan langsung dikirimkan ke chat Telegram.

### 2. 🧬 Self-Evolution & Dynamic Plugin Generator
* **Hot-Reloading Tanpa Restart:** Kemampuan ALFA untuk menciptakan alat Python baru secara otonom saat menghadapi tugas baru.
* **Sandbox Verification:** Kode plugin baru otomatis divalidasi via AST Parser, diuji di sandbox, dan langsung aktif di RAM tanpa perlu mematikan bot.

### 3. ⚡ Neural Vector Memory & Hybrid RAG (Super Second Brain)
* **Pencarian Semantik Kontekstual:** Menggunakan vector embedding (`gemini-embedding-001` + fallback lokal) dan cosine similarity ranking.
* **Sliding-Window Document Chunker:** Memecah dan mengindeks dokumen panjang (`.pdf`, `.txt`, `.md`, `.csv`, `.py`) ke dalam memori semantik permanen untuk pencarian berbasis makna.

### 4. 📁 Google Drive & Google Cloud Suite (Drive API v3)
* **Integrasi Resmi Google Cloud IAM:** Mendukung Service Account JSON Key dan OAuth2 untuk akses cloud sovereign tanpa batasan.
* **Auto-Upload & Cloud Backup:** Mengunggah file laporan (`.pdf`, `.xlsx`, `.docx`, gambar, zip) otomatis ke Google Drive dan mengembalikan tautan sharing publik.
* **1-Click Sync ke Second Brain:** Mengunduh dan mengindeks dokumen dari folder Google Drive langsung ke Neural Vector Brain untuk pencarian semantik instan.
* **Web Drive Explorer:** File manager interaktif di dashboard untuk membuat folder, mengunggah file langsung dari browser, dan mengelola izin berbagi.

### 5. 🛠️ 126+ Real Sovereign Tools & Interactive Workbench
* **Scraping & Modern Web Intelligence:**
  * 📄 **MarkItDown (Microsoft):** Konversi dokumen Word/PowerPoint/Excel, PDF, Audio, HTML ke Markdown LLM.
  * 🛡️ **Scrapling:** Stealth scraper anti-deteksi untuk bypass Cloudflare & Akamai.
  * 🕷️ **Scrapy & Parsel:** Ekstraksi dataset terstruktur berkecepatan tinggi via CSS/XPath.
  * 🌐 **Crawlee (Apify):** Crawler tangguh dengan request queueing dan deduplikasi otomatis.
  * 🤖 **Crawl4AI:** Web crawler khusus LLM dengan ekstraksi fit-markdown, link, dan media.
  * 🧭 **Browser-Use Agent:** Agen AI otonom untuk navigasi multi-step browser & pengisian form.
  * 🔥 **Firecrawl:** Scraper cerdas cloud + sovereign local engine fallback.
  * 📱 **Scrcpy & ADB:** Kontrol penuh smartphone Android (Screenshot, Touch Tap, Keyevents, Screen Mirroring).
* **System & Diagnostic:** Live telemetri CPU/RAM, storage vacuum, service manager.
* **Network & Security:** Speedtest benchmark CDN, WHOIS & SSL expiry inspector, audit port jaringan.
* **Marketplace & Finance:** Real-time crypto & forex ticker (CoinGecko + ExchangeRate API), generator QR Code resolusi tinggi.
* **Vision & Media:** Screenshot desktop, koordinat klik AI, Edge-TTS audio, konversi media FFmpeg.

### 6. 🌐 Web Command Center & Live Telemetry (Port 8080)
* **Light / Dark Mode:** Pilihan tema Obsidian Cyberpunk dan Clean SaaS Putih dengan penyimpanan preferensi otomatis (`localStorage`).
* **Settings Hub:** Pengaturan Bot Token, Gemini Key, Model AI, dan System Instruction langsung dari browser.
* **Passkey Biometric Vault:** Penyimpanan kredensial terenkripsi dengan proteksi WebAuthn / Passkey.
* **Google Drive Cloud Hub:** Manajemen kredensial Google Cloud, upload & download file, serta sinkronisasi memori RAG.

---

## 💻 Panduan Instalasi & Menjalankan (Multi-OS)

> 📖 **Baru pertama kali?** Ikuti tutorial lengkap dari nol sampai siap pakai:
> **[docs/INSTALL.md](docs/INSTALL.md)** — termasuk cara membuat bot BotFather,
> mengambil API key, whitelist keamanan, checklist verifikasi, dan troubleshooting.

### 🐧 1. Linux (Ubuntu, Debian, Arch, Fedora)
```bash
# Prasyarat: Python 3.10+, Git, dan Docker (untuk sandbox eksekusi aman)
sudo apt install docker.io && sudo usermod -aG docker $USER   # lalu logout-login

# Clone repository
git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git telegram-ai-bot
cd telegram-ai-bot

# Jalankan 1-Click Interactive Setup Wizard
chmod +x setup.sh run.sh
./setup.sh

# Jalankan langsung di terminal:
./run.sh

# Atau aktifkan service background 24/7 (Systemd):
mkdir -p ~/.config/systemd/user && cp deploy/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now telegram-ai-bot.service alfa-dashboard.service
```

---

### 🍏 2. macOS (MacBook, Mac Mini, iMac)
```bash
# Prasyarat: Python 3.10+, Git; Docker Desktop disarankan untuk sandbox
git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git telegram-ai-bot
cd telegram-ai-bot

# Beri izin eksekusi dan jalankan
chmod +x setup.sh run.sh
./run.sh
```
* Buka Web Dashboard di Safari/Chrome: **[http://localhost:8080](http://localhost:8080)**.
* Notifikasi desktop otomatis menggunakan **AppleScript Native macOS**.

---

### 🪟 3. Windows (Windows 10 / 11)
1. **Clone repository via Command Prompt / PowerShell / Git Bash:**
   ```cmd
   git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git telegram-ai-bot
   cd telegram-ai-bot
   ```
2. **Klik 2x file `run.bat`** (atau jalankan `run.bat` di terminal).
3. Script otomatis membuat virtual environment `venv`, menginstall dependensi, menyalin `.env`, dan meluncurkan Web Dashboard serta Telegram Bot secara bersamaan.
4. Notifikasi desktop otomatis menggunakan **PowerShell Windows Toast Notification**.

---

## ⚙️ Konfigurasi Environment (.env)

Salin `.env.example` menjadi `.env` dan isi token Anda:

```env
# Token dari @BotFather di Telegram (Wajib)
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"

# API Key Google Gemini (Wajib - Dapatkan gratis di https://aistudio.google.com)
GEMINI_API_KEY="AIzaSyYourGeminiApiKeyHere"

# Model Gemini default (pilih generasi aktif, mis. gemini-3.6-flash / gemini-3.5-flash-lite)
GEMINI_MODEL="gemini-3.6-flash"

# Telegram User ID yang diizinkan (WAJIB DIISI - fail-safe: kosong = semua akses ditolak.
# Jangan pernah jalankan bot ini publik tanpa whitelist karena bot bisa mengeksekusi
# perintah di mesin Anda!)
ALLOWED_USER_IDS="123456789"

# Nama Anda — AI akan menyapa & mempersonalisasi prompt dengan nama ini
OWNER_NAME="Nama Kamu"

# Persona / Karakter Utama AI
SYSTEM_INSTRUCTION="Kamu adalah ALFA Sovereign AI Assistant yang cerdas, solutif, proaktif, dan handal."
```

*(Atau Anda bisa mengaturnya langsung melalui menu **`⚙️ System Settings`** di browser [http://localhost:8080](http://localhost:8080))*

---

## 📌 Daftar Perintah Telegram

| Perintah | Deskripsi |
| :--- | :--- |
| `/start` | Membuka pesan selamat datang & status kesiapan agen |
| `/menu` | Membuka Menu Interaktif dengan tombol navigasi cepat |
| `/swarm <tugas>` | **Mode Eksekusi:** Menugaskan tim AI Swarm untuk langsung bekerja dan menghasilkan deliverable nyata |
| `/rapat <topik>` | **Mode Rapat:** Diskusi strategis antar 6 agen spesialis untuk merumuskan Action Plan |
| `/stats` | Menampilkan metrik performa CPU, RAM, Disk, Uptime, dan Baterai laptop |
| `/vault` | Membuka brankas Passkey Vault & melihat kredensial tersimpan |
| `/memory` | Menampilkan ingatan fakta jangka panjang (Second Brain) |
| `/clear` | Mereset riwayat chat percakapan saat ini |
| `/help` | Menampilkan panduan lengkap penggunaan seluruh fitur |

---

## 🧰 Tools Catalog & Interactive Workbench

Setiap tool di **Tools Catalog** ([http://localhost:8080](http://localhost:8080)) **100% interaktif dan dapat dieksekusi langsung**:
1. Klik kartu tool mana saja di web dashboard.
2. Form parameter akan otomatis digenerate sesuai signature fungsi Python.
3. Klik tombol **Eksekusi Tool Sekarang** untuk melihat output JSON dan durasi eksekusi dalam milidetik (ms).

---

## 🔒 Keamanan & Privasi

* **Whitelist Wajib:** Bot menolak semua akses bila `ALLOWED_USER_IDS` kosong (fail-safe). Satu instance = satu pemilik. JANGAN jalankan publik tanpa whitelist.
* **Sandbox Docker:** Eksekusi bash/python berjalan terisolasi dengan limit resource; tanpa Docker, eksekusi jatuh ke host tanpa isolasi (instal Docker!).
* **Zero Cloud Leak:** Database, memori vektor, dan log tersimpan 100% lokal di SQLite (`agent_data.db`).
* **Passkey Biometric Security:** Web Dashboard dilengkapi otentikasi biometrik WebAuthn (Fingerprint, Touch ID, Windows Hello).
* **Grounded ReAct Engine:** AI dilarang berasumsi atau berhalusinasi tanpa grounding fakta dari eksekusi tool nyata.

---

## 📄 Lisensi
Didistribusikan di bawah lisensi **MIT License**. Silakan gunakan, modifikasi, dan kembangkan untuk kebutuhan pribadi maupun komersial.
