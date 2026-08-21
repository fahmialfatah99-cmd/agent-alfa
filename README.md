# ⚡ ALFA // Sovereign AI Agent Ecosystem & Command Center

<div align="center">

![ALFA Sovereign AI](https://img.shields.io/badge/ALFA-Sovereign%20AI-06B6D4?style=for-the-badge&logo=probot&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google-Gemini%202.5%20%26%203.5-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API%20v21-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Dashboard-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-emerald?style=for-the-badge)

**Ekosistem AI Otonom Terpadu: Multi-Agent Swarm, 102 Sovereign Tools, Real Scraper Pro, Affiliate Studio, Passkey Vault, dan Web Command Center.**

[Fitur Utama](#-fitur-unggulan) • [Panduan Instalasi](#-panduan-instalasi-dari-awal) • [Konfigurasi .env](#-konfigurasi-environment-env) • [Perintah Telegram](#-daftar-perintah-telegram) • [Deploy 24/7](#-menjalankan-247-di-background-systemd)

</div>

---

## 🌟 Fitur Unggulan

### 1. 🤖 Multi-Agent Swarm & War Room (Dual Mode)
* **Mode 1 (Rapat Perencanaan Strategis):** 6 AI Agent spesialis (*Alpha Lead, Code Crafter, System Auditor, Researcher Prime, Strategic Planner, Laguna Co-Pilot*) berdiskusi otonom untuk membedah masalah dan merumuskan Action Plan.
* **Mode 2 (Eksekusi Nyata Otonom):** Agen AI tidak hanya berwacana — mereka langsung mengeksekusi kode, scraping data, menulis skrip, dan membuat file deliverable (`CSV`, `JSON`, `Python`) yang otomatis tersimpan di `~/Dokumen/ALFA_SWARM_OUTPUTS` serta langsung dikirimkan ke chat Telegram.

### 2. 🛠️ 102 Sovereign OS & AI Tools
* **System Healing & Diagnostic:** Audit error log, cek status memory, perbaikan service otomatis.
* **Vision & Computer Use:** Screenshot layar desktop dan otomatisasi klik mouse berbasis koordinat AI.
* **Media & Audio Studio:** Text-to-Speech (Edge-TTS), ekstraksi audio video via FFmpeg.
* **Dataset & Statistical Engine:** Analisis otomatis CSV/Excel dan pembuatan chart grafik.

### 3. 🌐 Web Command Center & Live Telemetry (Port 8080)
* **Light / Dark Mode Switcher:** Pilihan tema Obsidian Cyberpunk dan Clean SaaS Putih dengan penyimpanan preferensi otomatis (`localStorage`).
* **Settings & Config Hub:** Pengaturan Bot Token, Gemini Key, Model AI, dan System Instruction langsung dari web browser.
* **Passkey Biometric Vault:** Penyimpanan kredensial dan API keys terenkripsi dengan proteksi WebAuthn / Passkey.

### 4. 🛒 Master Scraper Pro & Affiliate Sales Studio
* Ekstraksi produk dari Shopee, Tokopedia, TikTok Shop, dan web kustom dengan anti-bot stealth engine (Playwright & Camoufox).
* Generator script copywriting affiliate otomatis (Formula PAS, Hook-Story-Offer) dengan copy-to-clipboard instan.

---

## 📋 Prasyarat Sistem (Prerequisites)

* **Sistem Operasi:** Linux (Ubuntu 20.04+, Debian, Arch, Fedora) atau macOS / WSL2 di Windows.
* **Python:** Versi `3.10` atau yang lebih baru (`python3 --version`).
* **Git:** Terpasang pada sistem (`git --version`).
* **Node.js (Opsional):** Versi `18+` jika ingin menjalankan bot WhatsApp Sheets Sync.

---

## 🚀 Panduan Instalasi dari Awal (Step-by-Step)

### Langkah 1: Clone Repository dari GitHub
Buka terminal Anda dan clone repositori ini:
```bash
git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git
cd agent-alfa
```

---

### Langkah 2: Jalankan 1-Click Interactive Setup Wizard
Kami telah menyediakan script installer interaktif yang otomatis menyiapkan virtual environment, menginstall dependensi, menanyakan token, dan membuat service background:
```bash
chmod +x setup.sh run.sh
./setup.sh
```

Wizard instalasi akan memandu Anda:
1. Memeriksa ketersediaan Python 3 dan membuat virtual environment `venv/`.
2. Menginstall seluruh dependensi dari `requirements.txt`.
3. Meminta input **Token Bot Telegram** dan **Google Gemini API Key**.
4. Menyiapkan direktori penyimpanan artefak `~/Dokumen/ALFA_SWARM_OUTPUTS`.
5. Mengkonfigurasi service background systemd.

---

### Langkah 3: Konfigurasi Manual (Jika Tidak Memakai Wizard)
Jika Anda ingin mengatur file konfigurasi secara manual:
1. Salin template `.env.example` menjadi `.env`:
   ```bash
   cp .env.example .env
   ```
2. Buka file `.env` dengan text editor (misal: `nano .env`):
   ```env
   # Token dari @BotFather di Telegram (Wajib)
   TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"

   # API Key Google Gemini (Wajib - Dapatkan gratis di https://aistudio.google.com)
   GEMINI_API_KEY="AIzaSyYourGeminiApiKeyHere"

   # Model Gemini default (gemini-2.5-flash, gemini-2.5-pro, gemini-3.5-flash-lite)
   GEMINI_MODEL="gemini-2.5-flash"

   # Telegram User ID yang diizinkan (opsional, kosongkan jika publik)
   ALLOWED_USER_IDS="123456789"

   # Persona / Karakter Utama AI
   SYSTEM_INSTRUCTION="Kamu adalah ALFA Sovereign AI Assistant yang cerdas, solutif, proaktif, dan handal."
   ```

---

## 💻 Menjalankan Bot & Dashboard

### Opsi A: Jalankan Langsung di Terminal (Interactive Runner)
Untuk menjalankan Telegram Bot dan Web Dashboard secara bersamaan:
```bash
./run.sh
```
* **Telegram Bot:** Otomatis aktif dan merespons pesan di Telegram.
* **Web Dashboard:** Buka di browser: **[http://localhost:8080](http://localhost:8080)**

---

### Opsi B: Menjalankan 24/7 di Background (Systemd Service)
Agar bot dan web dashboard tetap berjalan nonstop bahkan setelah terminal ditutup atau komputer direstart:
```bash
# Aktifkan dan jalankan kedua service
systemctl --user enable --now telegram-ai-bot.service alfa-dashboard.service

# Cek status service
systemctl --user status telegram-ai-bot.service
systemctl --user status alfa-dashboard.service
```

Untuk me-restart atau menghentikan service:
```bash
systemctl --user restart telegram-ai-bot.service alfa-dashboard.service
systemctl --user stop telegram-ai-bot.service alfa-dashboard.service
```

---

## 📌 Daftar Perintah Telegram

| Perintah | Deskripsi |
| :--- | :--- |
| `/start` | Membuka pesan selamat datang & ringkasan kemampuan |
| `/menu` | Membuka Menu Interaktif dengan tombol aksi cepat |
| `/swarm <tugas>` | **Mode Eksekusi:** Menugaskan tim AI Swarm untuk langsung bekerja dan menghasilkan deliverable nyata |
| `/rapat <topik>` | **Mode Rapat:** Mengadakan diskusi strategis antar 6 agen untuk merumuskan Action Plan |
| `/stats` | Menampilkan metrik performa CPU, RAM, Disk, Uptime, dan Battery laptop |
| `/vault` | Membuka brankas Passkey Vault & melihat kredensial tersimpan |
| `/memory` | Menampilkan ingatan fakta jangka panjang (Second Brain) |
| `/clear` | Mereset riwayat chat percakapan saat ini |
| `/help` | Menampilkan panduan lengkap penggunaan seluruh fitur |

---

## ⚙️ Fitur Pengaturan Web (Web Settings Hub)

Anda dapat mengubah seluruh pengaturan sistem tanpa perlu menyentuh terminal:
1. Buka dashboard di **`http://localhost:8080`**.
2. Klik menu **`⚙️ System Settings`** di sidebar kiri.
3. Di sini Anda bisa:
   * Mengganti Token Bot Telegram & Gemini API Key.
   * Memilih model AI default (*Gemini 2.5 Flash, 2.5 Pro, 3.5 Flash Lite*).
   * Membatasi hak akses pengguna Telegram (*Allowed User IDs*).
   * Menyesuaikan instruksi sistem (*Persona Prompt*).
   * Mengganti tema Tampilan (*Dark Mode 🌙 / Light Mode ☀️*).
4. Klik tombol **Simpan Pengaturan** dan perubahan langsung diterapkan seketika!

---

## 🔒 Keamanan & Privasi

* **Zero Data Leak:** Kunci API dan kredensial disimpan terenkripsi secara lokal di SQLite (`agent_data.db`) dan tidak pernah dikirimkan ke server pihak ketiga.
* **Passkey Biometric Support:** Web Dashboard mendukung otentikasi biometrik (Fingerprint / Windows Hello / Touch ID) sebelum brankas data dibuka.
* **Grounded ReAct Engine:** AI dilarang berasumsi atau berhalusinasi tanpa grounding fakta dari eksekusi tool nyata.

---

## 📄 Lisensi
Didistribusikan di bawah lisensi **MIT License**. Silakan gunakan, modifikasi, dan kembangkan untuk kebutuhan pribadi maupun komersial.
