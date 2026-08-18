# Telegram AI Agent Bot (Google Gemini / Antigravity Assistant)

Integrasi Bot Telegram berbasis Python dengan model AI Google Gemini.

## ✨ Fitur Utama
- 💬 **Percakapan Multi-turn:** Bot mengingat konteks chat sebelumnya.
- ⚡ **Google Gemini 2.5:** Respon cepat dan cerdas.
- 🔒 **Security Whitelist:** Batasi akses bot hanya untuk akun Telegram Anda (opsional).
- 🧹 **Manajemen Sesi:** Perintah `/clear` untuk mereset riwayat percakapan.
- 📝 **Markdown Safe Formatting & Auto Chunking:** Mendukung snippet kode tanpa terpotong limit 4096 karakter Telegram.
- ⏳ **Real-time Typing Status:** Indikator mengetik saat AI sedang berpikir/menjawab.

---

## 🚀 Panduan Cepat (Quick Start)

### 1. Dapatkan Token Telegram Bot
1. Buka aplikasi Telegram dan cari **`@BotFather`**.
2. Kirim pesan `/newbot`.
3. Masukkan nama bot dan username bot (harus berakhiran `_bot`, contoh: `FahmiAIAssistant_bot`).
4. Salin token API yang diberikan oleh BotFather (contoh: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

### 2. Dapatkan Google Gemini API Key
1. Buka [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Klik **Create API Key** dan salin kunci API Anda.

### 3. Setup & Konfigurasi
Jalankan setup script untuk membuat virtual environment dan menginstall dependensi:
```bash
cd /home/fahmial/telegram-ai-bot
./setup.sh
```

Buka dan isi file `.env`:
```bash
nano .env
```
Isi parameter:
```env
TELEGRAM_BOT_TOKEN="TOKEN_DARI_BOTFATHER"
GEMINI_API_KEY="API_KEY_GEMINI_ANDA"
GEMINI_MODEL="gemini-2.5-flash"
ALLOWED_USER_IDS=""
```
*(Opsional: Isi `ALLOWED_USER_IDS` dengan ID Telegram Anda untuk membatasi akses).*

### 4. Jalankan Bot
```bash
./run.sh
```

---

## 📌 Daftar Perintah di Telegram
- `/start` - Memulai interaksi & melihat info bot
- `/id` - Menampilkan ID Telegram Anda
- `/clear` atau `/reset` - Menghapus memori riwayat chat sesi saat ini
- `/status` - Memeriksa status dan model bot yang aktif
- `/help` - Menampilkan bantuan penggunaan
