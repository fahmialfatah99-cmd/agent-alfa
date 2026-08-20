# Telegram AI Agent Bot (TIER-GOD MAX: Sovereign Autonomous Assistant)

Integrasi Bot Telegram Otonom tercanggih berbasis Python dengan model AI Google Gemini, dilengkapi dengan **65+ tools otonom**, Grounded Anti-Hallucination ReAct Engine, Vision Loop Computer Use, Self-Evolution Plugin System, Proactive 24/7 System & Focus Watchdogs, OS-level Linux automation, browser stealth automation, subagent swarm delegator, document generator, IoT hardware remote, dan audio meeting transcription.

## 🧠 Arsitektur Anti-Halusinasi & Logika Asli (Grounded ReAct Engine)
- **Zero-Assumption Directive:** AI dilarang menebak fakta, kondisi file, status sistem, atau data web tanpa grounding dari eksekusi tool nyata.
- **Deep Multi-Source Fact Checking (`deep_research_topic`):** Menggali dan menyintesis data dari berbagai domain web independen dengan sitasi resmi.
- **Autonomous Self-Diagnostic & Healing (`auto_diagnose_and_heal_system`):** Melakukan investigasi error log sistem secara jujur dan memperbaikinya secara otonom.

## ⚡ Kemampuan Unggulan Generasi Baru (Next-Gen Power Tools)
- 🌐 **Deep Multi-Source Web Research (`deep_research_topic`):** Crawling & ekstraksi 3-5 sumber web secara rekursif + sintesis laporan berbobot.
- 🩺 **Autonomous System Healing (`auto_diagnose_and_heal_system`):** Audit error log, unit gagal, dan auto-remediasi service Linux.
- 🎙️ **Media & Audio Studio (`text_to_audio_file`, `convert_media_format`, `extract_audio_from_video`):** Generate audio speech (.mp3) dari teks panjang via Edge-TTS, konversi media, dan ekstraksi audio dari video via ffmpeg.
- 📊 **Dataset Analyzer & Visualizer (`analyze_dataset_csv_json`):** Analisis statistik data CSV/JSON/Excel + plotting grafik otomatis terkirim ke Telegram.
- 🛡️ **Network Security & SSL Sentinel (`audit_network_security`):** Port scanner, socket inspector, UFW audit, dan validasi sertifikat SSL/TLS domain.
- 🧹 **Linux Storage Cleaner (`clean_system_storage`):** Pembersihan cache thumbnail, log vacuum, dan temp files dengan metrik MB ruang yang kembali.
- ⚙️ **Systemd & Crontab Power Manager (`manage_system_services`, `manage_crontab_jobs`):** Kontrol service Linux dan manajemen crontab OS nyata.
- 🧠 **Second Brain & Knowledge Graph (`extract_and_link_knowledge`, `export_knowledge_base`):** Struktur relasi semantik entitas dan export database pengetahuan ke Markdown/JSON.
- 🎯 **Pomodoro Focus Sessions (`start_focus_session`):** Pengatur timer sesi kerja produktif dengan notifikasi proaktif saat selesai.
- 🧩 **Modular Dynamic Plugin Engine (`plugins/`):** Self-evolution tools disimpan terisolasi di `plugins/*.py` dan dimuat dinamis tanpa risiko merusak kode inti.
- 🧿 **Vision-Guided Computer Use Loop (`vision_click_target`):** Mengambil screenshot desktop -> Gemini Vision deteksi koordinat UI -> Klik mouse -> Screenshot verifikasi.
- 🔄 **Self-Restart (`self_restart_service`):** Restart mandiri dalam 2 detik untuk menerapkan update/plugins baru.
- 🛡️ **24/7 Proactive System Guardian:** Daemon pemantau kesehatan CPU, RAM, Disk, dan Baterai secara nonstop + auto-kill proses boros RAM (>500MB).

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
