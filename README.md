# ⚡ ALFA // Sovereign AI Agent Ecosystem & Command Center

<div align="center">

![ALFA Sovereign AI](https://img.shields.io/badge/ALFA-Sovereign%20AI%20v3.5-06B6D4?style=for-the-badge&logo=probot&logoColor=white)
[![CI](https://github.com/fahmialfatah99-cmd/agent-alfa/actions/workflows/ci.yml/badge.svg)](https://github.com/fahmialfatah99-cmd/agent-alfa/actions/workflows/ci.yml)
![Tests Passing](https://img.shields.io/badge/Tests-1366%20Passed%20%28100%25%29-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)
![Cross Platform](https://img.shields.io/badge/OS-Linux%20%7C%20macOS%20%7C%20Windows-8B5CF6?style=for-the-badge&logo=linux&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google-Gemini%203.x-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API%20v21-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![WhatsApp Web Automation](https://img.shields.io/badge/WhatsApp-Live%20Puppeteer-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Dashboard-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-emerald?style=for-the-badge)

**Ekosistem AI Otonom Berdaulat: Multi-Agent Swarm, Otomasi WhatsApp & Google Sheets 24/7, Pengolahan Dokumen Cerdas (Excel, PDF, Word, dll.), Neural Vector Brain, Self-Evolution Tools, Smart Permission Gate, dan Pemantauan RAM Otomatis.**

[Arsitektur Sistem](#-arsitektur-sistem) • [Fitur Unggulan](#-fitur-unggulan) • [Otomasi WhatsApp & Sheets](#-otomasi-whatsapp--google-sheets) • [Struktur Proyek](#-struktur-direktori-proyek) • [Panduan Multi-OS](#-panduan-instalasi--menjalankan-multi-os) • [Perintah Telegram](#-daftar-perintah-telegram)

</div>

---

## 🏛️ Arsitektur Sistem

ALFA dirancang sebagai arsitektur *sovereign multi-tier* terpadu yang menghubungkan interaksi chat Telegram, inferensi LLM cerdas, koordinasi multi-agen swarm, otomatisasi WhatsApp Web headless, serta pemrosesan dokumen lokal berkinerja tinggi.

```mermaid
flowchart TD
    subgraph Client["📱 User Interface & Clients"]
        TG["Telegram Client<br/>(Private Whitelist / Admin)"]
        CLI["CLI / Terminal Dashboard"]
    end

    subgraph Gateway["🛡️ Security & Access Layer"]
        AUTH{"Allowed User Whitelist"}
        PERM{"Permission Gate<br/>(Dangerous-Only Mode)"}
    end

    subgraph Core["⚡ ALFA Sovereign Engine (Python 3.10+)"]
        BRAIN["Core Brain<br/>(Gemini 3.5 / LLM Reasoning Engine)"]
        SWARM["Swarm Orchestrator<br/>(6 Specialized Autonomous Agents)"]
        CANCEL["Global Cancel Signal<br/>(Instant Session Abort)"]
        RAG["Neural Vector Brain<br/>(Hybrid RAG & Semantic Memory)"]
        DB[("SQLite WAL Database<br/>agent_data.db")]
    end

    subgraph Capabilities["🛠️ Execution & Sovereign Tools (80+ Tools)"]
        DOCS["Document Engine<br/>(Excel Consolidated, PDF, Word, CSV)"]
        WEB["Web & Scraping<br/>(Crawl4AI, Scrapling, Live Search)"]
        MEDIA["Media Suite<br/>(Images-to-PDF, FFmpeg, Edge-TTS)"]
        SYS["System Telemetry<br/>(RAM Monitor, Process Guardian)"]
    end

    subgraph Automation["🤖 WhatsApp & Sheets Automation (Port 3000)"]
        WABOT["wa-sheets-bot<br/>(Node.js / Express API)"]
        CHROME["Headless Chromium<br/>(Puppeteer Automation)"]
        WAWEB["WhatsApp Web Multi-Device"]
        GSUITE["Google Sheets & Drive Sync"]
    end

    TG --> AUTH --> PERM --> BRAIN
    CLI --> BRAIN
    BRAIN <--> SWARM
    SWARM -.-> CANCEL
    BRAIN <--> RAG <--> DB
    BRAIN --> DOCS
    BRAIN --> WEB
    BRAIN --> MEDIA
    BRAIN --> SYS
    BRAIN <==>|REST API / Seen / Sync| WABOT
    WABOT <--> CHROME <--> WAWEB
    WABOT --> GSUITE
    WABOT -.->|Permanent Archive & Deduplication| DB
```

---

## 🌟 Fitur Unggulan

> **Metrik Kualitas & Keandalan:** 83.000+ baris kode terstruktur, 80+ tools sovereign, **1.366 tes otomatis lolos 100%**, 48 perintah Telegram siap pakai, dan integritas database SQLite terverifikasi nol-korupsi.

### 1. 🤖 Multi-Agent Swarm & Rapat Otonom (Dengan Pembatalan Instan)
* **Mode Rapat Perencanaan (`/rapat`):** Tim agen AI spesialis (*Lead Coordinator, Code Crafter, Auditor, Researcher, Planner*) berdiskusi otonom merumuskan konsensus dan Action Plan.
* **Mode Eksekusi Nyata (`/swarm`):** Agen langsung bekerja di latar belakang: menulis kode, membaca file, scraping, membuat spreadsheet, dan menghasilkan deliverable nyata.
* **Pembatalan Seketika (`/batal`):** Dilengkapi sinyal `GLOBAL_SWARM_CANCEL` dan isolasi status per-sesi sehingga seluruh loop rapat dan eksekusi berhenti seketika saat diperintahkan, tanpa meninggalkan file sampah (*workspace hygiene*).

### 2. 📱 Otomasi WhatsApp, Google Sheets & Drive
* **Pencatatan Masuk Otomatis:** Merekam pesan WhatsApp dari grup proyek atau chat pribadi langsung ke Google Sheets secara real-time.
* **Unggah Lampiran Berbasis Aturan:** Media, berkas dokumen, nota, dan gambar lampiran otomatis diunggah ke Google Drive dan dirapikan ke subfolder sesuai aturan `media_rules.json`.
* **Pelacak Status Baca Permanen (`wa_read_messages`):** Mencegah pesan dibaca berulang-ulang saat pemilik mengecek pesan masuk baru (`/wamasuk baru` / `wa_get_incoming(only_unread=True)`).
* **Penyaringan Bersih Status & Saluran:** Membuang otomatis kiriman WhatsApp Status (`status@broadcast`) dan Saluran (`@newsletter`) di tingkat event, menjaga ring buffer tetap bersih dari spam.
* **Arsip SQLite Permanen (`wa_incoming_archive`):** Seluruh pesan masuk otomatis diarsipkan permanen di database lokal SQLite, memungkinkan pencarian riwayat kilat kapan saja tanpa batas buffer.
* **Keaslian Pesan 100% (*Verbatim*):** AI dilarang mengubah atau memparafrasekan teks WhatsApp; pesan ditampilkan persis seperti aslinya.
* **Dukungan Read Receipt (`POST /api/seen`):** Terhubung dengan WhatsApp Web untuk membersihkan unread badge jika diinginkan.

### 3. 📑 Pengolahan Dokumen Cerdas & Konsolidasi Excel (Excel, PDF, Word, dll.)

```mermaid
flowchart LR
    A["📄 Input Dokumen<br/>(Excel, PDF, Word, Teks)"] --> B["🔍 Universal Extractor<br/>(Teks, Tabel, Metadata)"]
    B --> C["🤖 AI Normalizer<br/>(Item, Kuantitas, Kategori)"]
    C --> D["📊 Formula Engine<br/>(Kalkulasi, Validasi Data)"]
    D --> E["📑 Single Consolidated Excel<br/>(Tab Terstruktur, Formula, 0 Duplikat)"]
    D --> F["📑 Rich PDF Report / Img2PDF<br/>(Format Rapi, Header, Watermark)"]
```

* **Ekstraksi & Analisis Rapi:** Ahli dalam membaca, merangkum, dan mengolah berbagai format dokumen (Excel `.xlsx/.csv`, PDF, Word `.docx`, teks). Rincian data, kuantitas item, atau pos inventaris diekstraksi secara presisi dengan format bersih: **Nama Dokumen ➔ Rincian Item/Data (Item : Qty Satuan) ➔ Rekap Total Ringkas**, tanpa narasi berbelit-belit.
* **Konsolidasi Excel 1-Klik:** Saat dikirimi beberapa dokumen sekaligus dan diminta rekap, seluruh data otomatis digabungkan menjadi **1 file Excel tunggal yang terstruktur rapi** dengan formula kalkulasi, bebas dari file output ganda yang membingungkan.
* **Generator Gambar ke PDF (`images_convert_to_pdf`):** Menggabungkan puluhan gambar lembar kerja, foto fisik, atau nota menjadi satu berkas PDF berkualitas tinggi dengan margin presisi.

### 4. 🧹 Pemantauan RAM & Pemeliharaan Otomatis
* **Diagnostik RAM Terpadu (`/ram` atau `/bersihkan`):** Menampilkan metrik pemakaian RAM sistem, proses ALFA Bot, dan Chrome/Node.js WA Sheets Bot, serta memicu pembersihan objek memori Python dan file sementara Chromium.
* **Batas Memori Aman:** Unit systemd dibatasi (`MemoryHigh=1.4G`, `MemoryMax=1.8G`, dan Node heap `--max-old-space-size=512`).
* **Timer Pemeliharaan Malam (03:30 WIB):** Unit `wa-sheets-bot-daily-recycle.timer` me-restart proses browser secara otomatis setiap malam untuk membuang akumulasi cache memori browser jangka panjang.

### 5. 🛡️ Kebijakan Izin Cerdas (*Smart Permission Gate*)
* **Filter Operasi Aman:** Mode `PERMISSION_GATE_DANGEROUS_ONLY` otomatis menyetujui pembacaan berkas lokal, penarikan data WhatsApp, dan diagnostik sistem tanpa pop-up konfirmasi berulang.
* **Proteksi Bahaya Tinggi:** Perintah berbahaya (`rm -rf`, eksekusi shell berisiko, modifikasi sistem kritis) tetap memerlukan persetujuan eksplisit pemilik melalui tombol inline interaktif Telegram.

### 6. 🧬 Self-Evolution & Dynamic Plugin Generator
* **Hot-Reloading Python:** Kemampuan ALFA untuk menciptakan alat baru secara otonom saat menghadapi tugas baru tanpa perlu me-restart bot.
* **Sandbox Verification:** Kode plugin baru otomatis divalidasi via AST Parser, diuji di sandbox, dan langsung aktif di memori.

### 7. ⚡ Neural Vector Memory & Hybrid RAG (Super Second Brain)
* **Pencarian Semantik Kontekstual:** Menggunakan vector embedding dan cosine similarity ranking di SQLite.
* **Sliding-Window Document Chunker:** Memecah dan mengindeks dokumen panjang (`.pdf`, `.txt`, `.md`, `.csv`, `.xlsx`, `.py`) ke dalam memori semantik permanen.

### 8. 🛠️ 80+ Real Sovereign Tools
* **Scraping & Web:** MarkItDown (Microsoft), Scrapling, Scrapy, Crawlee, Crawl4AI, Firecrawl, Live Web Search.
* **Perangkat Keras & OS:** Kontrol Android via Scrcpy & ADB, telemetri live CPU/RAM, inspeksi proses Linux.
* **Finansial & Media:** Ticker crypto & forex real-time, generator QR Code, konversi media FFmpeg, Edge-TTS audio sintetis.

---

## 📂 Struktur Direktori Proyek

```text
agent-alfa/
├── alfa/
│   ├── bot/                 # Telegram Bot handlers, menu, callback routers
│   │   ├── advanced_commands.py  # /wa, /ram, /sites, /vault, dsb.
│   │   ├── wa_menu.py            # Dashboard interaktif WhatsApp & tombol inline
│   │   └── pipeline/             # Tool filtering, RAG router, dan sanitasi prompt
│   ├── core/                # Core sovereign engine, database, dan security
│   │   ├── brain/                # Gemini multi-turn reasoning & agentic loops
│   │   ├── db/                   # SQLite WAL connection, migrations & wa_tracking
│   │   ├── memory/               # Vector embeddings & semantic memory store
│   │   └── perm/                 # Smart permission gate & risk classification
│   ├── swarm/               # Multi-agent coordination system
│   │   ├── engine.py             # Swarm meeting conductor & execution loops
│   │   ├── meeting_steps.py      # Turn-by-turn execution & cancel listener
│   │   └── workspace_hygiene.py  # Sandbox isolation & instant cancel cleanup
│   └── tools/               # 80+ Sovereign tools terintegrasi
│       ├── filesystem/           # Operasi berkas aman, search, universal extractor
│       ├── media/                # Image-to-PDF, PDF builder/editor, FFmpeg, player
│       ├── system/               # Telemetri RAM, process guardian, WhatsApp bridge
│       └── web/                  # Live web search, Crawl4AI, deep scrapers
├── docs/                    # Panduan instalasi dan deployment server
├── tests/                   # 1.366+ unit dan integration test suite
├── setup.sh / run.sh        # Skrip inisialisasi & startup runner otomatis
└── pyproject.toml           # Konfigurasi dependensi Python & linter
```

---

## 📱 Otomasi WhatsApp & Google Sheets

Diagram alur pertukaran data dua arah antara **ALFA Engine** dan **`wa-sheets-bot`** (berjalan pada port `3000` via Puppeteer):

```mermaid
sequenceDiagram
    autonumber
    actor Owner as 👤 Pemilik (Telegram)
    participant Alfa as ⚡ ALFA Bot
    participant WABot as 🤖 wa-sheets-bot (:3000)
    participant WWeb as 📱 WhatsApp Web
    participant Sheets as 📊 Google Sheets & Drive
    participant DB as 🗄️ SQLite (agent_data.db)

    Note over WWeb,WABot: Real-time Incoming Listener
    WWeb->>WABot: Pesan Masuk (Chat / Grup / Lampiran)
    WABot->>Sheets: Catat Laporan & Upload Media ke Drive
    WABot->>DB: Simpan ke wa_incoming_archive (Permanen)

    Owner->>Alfa: Kirim Perintah /wamasuk baru
    Alfa->>WABot: GET /api/incoming?unread=1
    Alfa->>DB: Cek & Catat ID ke wa_read_messages
    Alfa-->>Owner: Tampilkan Pesan Masuk (Verbatim, Anti-Duplikasi)

    Owner->>Alfa: Kirim Perintah /wakirim [tujuan] [pesan]
    Alfa->>WABot: POST /api/send {to, message}
    WABot->>WWeb: Kirim Pesan dengan Throttle Aman (Delay 3s)
    WABot-->>Alfa: Respon Status Sukses
    Alfa-->>Owner: ✅ Pesan Terkirim
```

---

## 💻 Panduan Instalasi & Menjalankan (Multi-OS)

> 📖 **Panduan Lengkap:**
> * Setup awal dari nol: **[docs/INSTALL.md](docs/INSTALL.md)** (BotFather, API key, whitelist, setup lokal).
> * Panduan server produksi: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** (Docker Compose, Systemd 24/7, Nginx/Caddy, WebSockets, SSL).

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

# Menjalankan manual:
./run.sh

# Atau aktifkan service background 24/7 (Systemd User Service):
systemctl --user enable --now telegram-ai-bot.service
systemctl --user enable --now wa-sheets-bot.service
systemctl --user enable --now wa-sheets-bot-daily-recycle.timer
```

### 🍏 2. macOS & 🪟 3. Windows
* **macOS:** Jalankan `./run.sh`. Notifikasi desktop otomatis via AppleScript native.
* **Windows:** Klik 2x `setup.bat` untuk inisialisasi, lalu klik 2x `run.bat` untuk menjalankan. Notifikasi via Windows Toast.

---

## ⚙️ Konfigurasi Environment (.env)

Salin `.env.example` menjadi `.env` dan isi token Anda:

```env
# Token dari @BotFather di Telegram (Wajib)
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"

# API Key Google Gemini (Wajib - Dapatkan di https://aistudio.google.com)
GEMINI_API_KEY="AIzaSyYourGeminiApiKeyHere"

# Model Gemini default
GEMINI_MODEL="gemini-3.5-flash"

# Telegram User ID yang diizinkan (Fail-safe: tanpa ini semua akses ditolak)
ALLOWED_USER_IDS="123456789"

# Nama Pemilik (AI menyapa & mempersonalisasi respon)
OWNER_NAME="Nama Kamu"

# Kebijakan Izin Cerdas (true = izin hanya diminta untuk perintah berisiko tinggi)
PERMISSION_GATE_DANGEROUS_ONLY="true"
```

---

## 📌 Daftar Perintah Telegram

### 🤖 Perintah Utama & Kontrol AI
| Perintah | Deskripsi |
| :--- | :--- |
| `/start` | Membuka pesan selamat datang & status kesiapan agen |
| `/menu` | Membuka Panel Menu Interaktif dengan tombol shortcut lengkap |
| `/swarm <tugas>` | **Mode Eksekusi Nyata:** Menugaskan tim AI Swarm untuk bekerja & menghasilkan deliverable |
| `/rapat <topik>` | **Mode Rapat:** Diskusi strategis antar 6 agen untuk merumuskan Action Plan |
| `/batal` | Membatalkan rapat atau misi Swarm yang sedang berjalan seketika |
| `/resume_swarm` | Melanjutkan kembali sesi Swarm yang sempat terjeda |
| `/mode <single\|swarm>` | Mengubah mode berpikir agen (Single cepat vs Swarm kolaboratif) |
| `/clear` | Mereset riwayat percakapan saat ini |
| `/help` | Menampilkan panduan lengkap penggunaan seluruh fitur |

### 📱 Perintah WhatsApp & Laporan
| Perintah | Deskripsi |
| :--- | :--- |
| `/wa` | **Dashboard WhatsApp Interaktif:** Menu tombol inline untuk cek chat, pesan masuk, format, dan kirim pesan |
| `/wamasuk [limit\|baru]` | Membaca pesan WA masuk terbaru (opsi `baru` = hanya yang belum dibaca) |
| `/wachat <nama/nomor>` | Membaca riwayat pesan chat personal atau grup WA |
| `/wakirim <tujuan> <pesan>` | Mengirim pesan WhatsApp ke kontak atau grup |
| `/wacari <kata kunci>` | Mencari kata kunci di pesan WhatsApp (arsip lokal SQLite + WA Web) |
| `/waringkas [format]` | Menghasilkan ringkasan cerdas laporan WhatsApp + sorotan AI |
| `/wareport [limit]` | Membaca catatan laporan WA yang tersinkronisasi ke Google Sheets |
| `/waformat` | Mengelola format kata kunci pencatatan otomatis WA ke Sheets |

<details>
<summary><b>⚙️ Klik untuk melihat Perintah Sistem, RAM & Utilitas Tingkat Lanjut</b></summary>

<br/>

| Perintah | Deskripsi |
| :--- | :--- |
| `/ram` atau `/bersihkan` | Laporan diagnostik RAM & pembersihan cache memori / GC otomatis |
| `/ram full` | Me-restart proses WA Sheets Bot secara instan untuk me-refresh RAM |
| `/stats` | Menampilkan metrik performa CPU, RAM, Disk, Baterai, dan Uptime |
| `/cekagen` | Audit integritas konfigurasi model AI & kunci API |
| `/vault` | Membuka brankas Passkey Vault & melihat kredensial tersimpan |
| `/memory` | Menampilkan ingatan fakta jangka panjang (Second Brain) |
| `/budget` | Memantau kuota dan pemakaian token API harian |
| `/sites` | Galeri website/proyek hasil agen (hidupkan/matikan dari bot) |
| `/cron` | Mengelola jadwal tugas otomatis berkala |
| `/voice` | Mengaktifkan/menonaktifkan balasan suara sintetis Edge-TTS |

</details>

---

## 🔒 Keamanan, Kontrol Izin & Manajemen RAM

* **Whitelist Akses Ketat:** Bot hanya merespons ID pengguna yang terdaftar di `ALLOWED_USER_IDS`. Akses dari pihak lain ditolak otomatis.
* **Smart Permission Gate:** Tool dengan tier `MEDIUM` dan `LOW` (baca dokumen, pembacaan WA, status sistem) dieksekusi tanpa pop-up persetujuan berulang. Hanya perintah `HIGH` dan `CRITICAL` yang memicu konfirmasi inline.
* **Penyimpanan Lokal Berdaulat:** Database SQLite (`agent_data.db`), arsip chat WA, dan memori vektor tersimpan 100% lokal di mesin pemilik.
* **Pengendalian Memori Proaktif:** Dilengkapi timer restart harian pada jam sepi (`03:30 WIB`), batas alokasi memori systemd, dan perintah manual `/ram` untuk mencegah penumpukan memori browser.

---

## 📄 Lisensi
Didistribusikan di bawah lisensi **MIT License**. Silakan gunakan, kembangkan, dan sesuaikan untuk kebutuhan operasional maupun riset Anda.
