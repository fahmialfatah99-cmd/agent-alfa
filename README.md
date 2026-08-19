# Telegram AI Agent Bot (GOD MODE: Sovereign Autonomous Assistant)

Integrasi Bot Telegram Otonom tercanggih berbasis Python dengan model AI Google Gemini, dilengkapi dengan 52+ tools otonom, Vision Loop Computer Use, Self-Evolution Engine, Proactive System Guardian 24/7, OS-level automation, browser stealth automation, subagent swarm delegator, proactive cron watchdogs, document generator, IoT hardware remote, dan audio meeting transcription.

## ⚡ Kemampuan God Mode
- 🧿 **Vision-Guided Autonomous Computer Use (`vision_click_target`):** Loop otonom berbasis penglihatan — mengambil screenshot desktop, menganalisis elemen UI via Gemini Vision, mengklik target secara akurat, lalu mengambil screenshot verifikasi.
- 🧬 **Self-Evolution Engine (`self_add_new_tool`):** Bot mampu menulis, memvalidasi sintaksis, menginjeksi, dan mendaftarkan *tool baru ke dalam basis kodenya sendiri* tanpa perlu diedit manual oleh manusia.
- 🔄 **Self-Restart (`self_restart_service`):** Memulai ulang systemd servicenya secara mandiri dalam hitungan detik setelah menerapkan pembaruan atau tool baru.
- 🛡️ **24/7 Proactive System Guardian (`proactive_system_guardian_config`):** Daemon latar belakang yang memantau kesehatan CPU, RAM, Disk, dan Baterai secara terus-menerus serta mengeksekusi tindakan protektif mandiri (seperti mematikan proses boros RAM & mengirimkan alert instan).

## ✨ Fitur & Kemampuan Utama Lainnya
- 🖥️ **OS-Level Computer Use:** Simulasi klik mouse koordinat pixel desktop, pengetikan keyboard/hotkey, dan peluncuran software GUI.
- 📦 **File & Folder Operations:** ZIP seluruh direktori (`compress_folder_to_zip`), unduh URL (`download_file_from_url`), dan kirim berkas apa saja ke chat (`send_file_to_chat`).
- 🎬 **Screen Recorder:** Perekaman video layar desktop (.mp4) langsung ke Telegram (`record_desktop_screen`).
- 📋 **System Clipboard & Notifikasi:** Baca/tulis clipboard Wayland/X11 serta kirim notifikasi pop-up fisik ke layar monitor (`show_desktop_notification`).
- 🌐 **DevOps & Remote:** Eksekusi SSH ke server remote (`ssh_execute_command`), operasi Git langsung dari chat (`git_operations`), query basis data SQLite (`query_database`), dan pengirim email SMTP (`send_email`).
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
