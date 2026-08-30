# 📦 Panduan Instalasi Lengkap — ALFA Sovereign AI

Dari nol sampai bot siap dipakai di Telegram. Ikuti berurutan, ±15 menit.

---

## Daftar Isi
1. [Prasyarat](#1-prasyarat)
2. [Buat Bot Telegram (BotFather)](#2-buat-bot-telegram)
3. [Ambil API Key Gemini](#3-ambil-api-key-gemini)
4. [Cari Telegram User ID kamu](#4-cari-telegram-user-id)
5. [Instal Bot](#5-instal-bot)
6. [Isi Konfigurasi .env](#6-isi-konfigurasi-env)
7. [Jalankan & Verifikasi Pertama](#7-jalankan--verifikasi-pertama)
8. [Mode Service 24/7 (systemd)](#8-mode-service-247)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prasyarat

| Perangkat | Versi | Wajib? | Cek dengan |
|---|---|---|---|
| Python | 3.10+ | ✅ Wajib | `python3 --version` |
| Git | any | ✅ Wajib | `git --version` |
| **Docker** | any | ⚠️ Sangat disarankan | `docker ps` |
| FFmpeg | any | Opsional (media/audio) | `ffmpeg -version` |
| LibreOffice | any | Opsional (konversi dokumen) | `libreoffice --version` |

> ⚠️ **PENTING — Docker:** Tanpa Docker, perintah bash/python dari AI tetap
> jalan tapi **langsung di komputermu tanpa isolasi**. Selalu instal Docker
> sebelum pakai bot untuk kerja serius:
> ```bash
> # Ubuntu/Debian
> sudo apt install docker.io && sudo usermod -aG docker $USER
> # logout-login sekali agar grup docker aktif
> ```

---

## 2. Buat Bot Telegram

1. Buka Telegram, cari **@BotFather** (verifikasi biru).
2. Kirim `/newbot`.
3. Ketik nama tampilan bot, mis. `ALFA Assistant`.
4. Ketik username unik yang diakhiri `bot`, mis. `alfa_assistant_kamu_bot`.
5. BotFather membalas dengan **token** seperti:
   ```
   123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   ```
   → Simpan. Ini `TELEGRAM_BOT_TOKEN` kamu.

---

## 3. Ambil API Key Gemini

1. Buka **https://aistudio.google.com/app/apikey** (login akun Google).
2. Klik **Create API key** → pilih/buat project.
3. Salin kunci seperti `AIzaSy...`
   → Ini `GEMINI_API_KEY` kamu.

> 💡 Free tier cukup untuk personal use, tapi ada batas request/hari.
> Kamu juga bisa menambahkan kunci provider lain (OpenRouter, NVIDIA, dll)
> lewat Web Dashboard nanti — bot mendukung multi-provider.

---

## 4. Cari Telegram User ID

1. Buka Telegram, cari **@userinfobot**.
2. Kirim pesan apa pun → dia membalas `Id: 123456789`.
3. Angka itu adalah `ALLOWED_USER_IDS` kamu.

> 🔒 **Kenapa wajib?** Bot ini bisa mengeksekusi bash/python, membaca file,
> dan mengontrol desktop. Tanpa whitelist, SIAPA PUN yang menemukan botmu
> bisa mengontrol komputermu. Kode bot punya fail-safe: whitelist kosong =
> semua akses ditolak.

---

## 5. Instal Bot

### Linux / macOS
```bash
git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git telegram-ai-bot
cd telegram-ai-bot
chmod +x setup.sh run.sh
./setup.sh        # wizard interaktif: venv + dependensi + salin .env
```

### Windows
```powershell
git clone https://github.com/fahmialfatah99-cmd/agent-alfa.git
cd agent-alfa
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # wizard interaktif Windows
```
Atau langsung jalankan peluncur otomatis:
```cmd
run.bat
```

---

## 6. Isi Konfigurasi .env

```bash
cp .env.example .env
nano .env         # atau editor apa pun
```

Wajib diisi (dari langkah 2–4):
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
GEMINI_API_KEY=AIzaSy...
ALLOWED_USER_IDS=123456789
OWNER_NAME=NamaKamu          # agar AI menyapa namamu
```

Sisanya boleh default dulu. Simpan file.

---

## 7. Jalankan & Verifikasi Pertama

```bash
./run.sh
# Windows: run.bat
```

**Checklist verifikasi (berurutan):**

- [ ] Terminal menampilkan `Application started` tanpa traceback
- [ ] Buka **http://localhost:8080** → dashboard tampil
- [ ] Di Telegram: kirim `/start` ke botmu → balasan selamat datang
- [ ] Kirim `halo` → AI membalas gaya santai
- [ ] Kirim `berapa RAM laptopku sekarang?` → jawaban data nyata (tool jalan)
- [ ] Kirim `/menu` → menu interaktif muncul

Semua centang? **Bot siap pakai.** 🎉

---

## 8. Mode Service 24/7

Agar bot hidup terus walau terminal ditutup (Linux, systemd user):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/*.service ~/.config/systemd/user/
# Sesuaikan path jika folder repo TIDAK bernama "telegram-ai-bot" di home:
#   nano ~/.config/systemd/user/telegram-ai-bot.service
systemctl --user daemon-reload
systemctl --user enable --now telegram-ai-bot.service alfa-dashboard.service

# Cek status & log
systemctl --user status telegram-ai-bot
journalctl --user -u telegram-ai-bot -f
```

---

## 9. Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| `Conflict: terminated by other getUpdates request` | Ada 2 instance bot jalan | Matikan satu: cek `ps aux \| grep bot.py` |
| `404 model ... not available` | Model di `.env` sudah pensiun | Ganti `GEMINI_MODEL` ke generasi aktif (mis. `gemini-3.6-flash`) |
| `429 RESOURCE_EXHAUSTED` | Kuota free-tier habis | Tunggu reset kuota / pakai kunci lain via dashboard; loop proaktif otomatis mundur 1 jam |
| `[PERINGATAN: dieksekusi di HOST]` | Docker tidak terdeteksi | Instal Docker + aktifkan integrasi WSL2 (Windows); atau jika sengaja tanpa Docker, set `ALFA_ALLOW_HOST_EXEC=true` di `.env` (Hanya untuk mesin pribadi tepercaya) |
| Bot tidak merespons apa pun | `ALLOWED_USER_IDS` kosong/salah | Isi ID kamu (langkah 4) lalu restart |
| `Temporary failure in name resolution` | Internet/DNS putus | Otomatis retry; periksa koneksi |
| Dashboard 401/403 | `DASHBOARD_AUTH_TOKEN` aktif | Login dengan password tersebut |
| DB makin besar sendiri | Indeks kode folder raksasa | Sudah diguard; vacuum manual: stop bot → `python3 -c "import sqlite3;c=sqlite3.connect('agent_data.db');c.execute('VACUUM')"` |

---

## 🔒 Catatan Keamanan Penting

1. **Jangan pernah share `.env`** — isinya token & kunci API.
2. **Whitelist ketat**: hanya ID kamu (dan keluarga) di `ALLOWED_USER_IDS`.
3. Dashboard default hanya bisa dibuka dari laptop itu (`127.0.0.1`).
4. Tool berbahaya (SSH, kontrol desktop, hapus proses) aktif di mesinmu —
   bot ini dirancang **personal assistant**, bukan bot publik multi-user
   dalam satu instance. Satu instance = satu pemilik = satu whitelist.
