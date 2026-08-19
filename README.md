# Telegram AI Agent Bot (Tier-Max Sovereign Autonomous Assistant)

Integrasi Bot Telegram Otonom tingkat lanjut berbasis Python dengan model AI Google Gemini, dilengkapi dengan eksekusi tools riil, OS-level computer use, browser stealth automation, subagent swarm delegator, proactive cron watchdogs, document generator, IoT hardware remote, dan audio meeting transcription.

## ✨ Fitur & Kemampuan Utama
- 🖥️ **OS-Level Computer Use:** Simulasi klik mouse koordinat pixel desktop (`desktop_click_coordinate`), pengetikan keyboard/hotkey (`desktop_type_keys`), dan peluncuran software GUI (`desktop_launch_app`).
- 🦊 **Camofox Browser Automation:** Membuka web, membaca struktur aksesibilitas, mengklik link/tombol, mengetik form, dan menangkap screenshot web otonom.
- 🤖 **Autonomous Subagent Swarm:** Agen pendelegasi mandiri yang menjalankan tugas riset/coding kompleks di latar belakang dan mengirimkan laporan lengkap begitu selesai.
- ⏰ **Proactive Cron & Watchdog Scheduler:** Penjadwalan tugas berulang otonom (monitor server, pantau kripto/saham, daily tech briefing) langsung ke chat.
- 📄 **Document & Report Generator:** Pembuatan laporan PDF bergaya modern (ReportLab), spreadsheet Excel berformat (OpenPyXL), dan presentasi PowerPoint (PPTX) yang otomatis terkirim sebagai lampiran berkas.
- 🎛️ **Linux Hardware & IoT Remote:** Kunci layar desktop, pengatur volume speaker & mute, kontrol media Spotify/YouTube, cek baterai detail, dan pemindai Wi-Fi/Bluetooth.
- 🎙️ **Long Audio Meeting Transcriber & Notulen:** Transkripsi rekaman suara/rapat (.mp3, .m4a, .wav) dan penyusunan notulen rapat lengkap dengan action items.
- 💬 **Percakapan Multi-turn & Memori Terisolasi:** Konteks riwayat chat dan fakta memori jangka panjang tersimpan persisten di SQLite (WAL Mode).
- 🐍 **Python Sandbox & Data Plotter:** Eksekusi skrip data analytics Python dan visualisasi grafik matplotlib yang otomatis dikirim ke chat Telegram.
- 🖥️ **Desktop Vision:** Tangkapan layar desktop instan (Wayland XDG Portal) dan kamera webcam hardware (`/dev/video0`).
- 🎙️ **Voice Notes Cerdas (Single Reply):** Menerima pesan suara dan otomatis memilih balasan suara/teks sesuai konteks konten.
- 🔒 **Security Whitelist:** Batasi akses bot hanya untuk akun Telegram Anda melalui `ALLOWED_USER_IDS`.

---

## 🚀 Panduan Cepat (Quick Start)

### 1. Setup & Konfigurasi
Jalankan setup script untuk membuat virtual environment dan menginstall dependensi:
```bash
cd /home/fahmial/telegram-ai-bot
./setup.sh
```

Buka dan sesuaikan file `.env`:
```env
TELEGRAM_BOT_TOKEN="TOKEN_DARI_BOTFATHER"
GEMINI_API_KEY="API_KEY_GEMINI_ANDA"
GEMINI_MODEL="gemini-3.5-flash-lite"
ALLOWED_USER_IDS="ID_TELEGRAM_ANDA"
SYSTEM_INSTRUCTION="Instruksi sistem kustom (opsional)"
```

### 2. Menjalankan Bot
Untuk menjalankan secara manual:
```bash
./run.sh
```

Atau kelola via systemd user service:
```bash
systemctl --user restart telegram-ai-bot.service
systemctl --user status telegram-ai-bot.service
```

---

## 📌 Daftar Perintah di Telegram
- `/start` - Menampilkan perkenalan & tombol cepat
- `/menu` - Membuka menu kontrol agen interaktif
- `/stats` - Memeriksa metrik CPU, RAM, Disk, Jaringan, dan Baterai
- `/cron` atau `/tasks` - Melihat daftar tugas berulang & watchdog aktif
- `/memory` - Melihat daftar fakta memori jangka panjang yang tersimpan
- `/voice` - Mengaktifkan / menonaktifkan respon suara otomatis
- `/clear` atau `/reset` - Mereset riwayat chat sesi saat ini
- `/id` - Menampilkan ID Telegram & Chat ID Anda
- `/help` - Menampilkan panduan dan contoh perintah AI
