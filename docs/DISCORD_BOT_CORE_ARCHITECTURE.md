# 🏛️ WAR ROOM RAPAT PLENO: ARSITEKTUR INTI BOT DISCORD CANGGIH ALFA
**ID Sesi**: `WAR-ROOM-DC-2026-001`  
**Koordinator**: Alpha Lead  
**Tanggal & Waktu**: 2026-10-15 16:56:00 WIB  
**Status**: 🚀 COMPLETED & RATIFIED  

---

## 🎯 1. Ringkasan Eksekutif & Latar Belakang
ALFA Swarm menggelar War Room tingkat tinggi untuk menetapkan dan memformalkan **Arsitektur Inti Bot Discord Canggih** (*Next-Generation AI Companion, Voice Jarvis, & Swarm Mission Control*).

Sistem Discord ini bukan sekadar bot chat biasa, melainkan antarmuka operasional penuh (*operational interface*) yang terhubung langsung ke inti otonom ALFA (Linux Host Execution, SQLite Sync, Swarm Collective, dan Realtime Voice Gateway).

---

## 👥 2. Matriks Keputusan War Room (Swarm Matrix)

| Unit Swarm | Peran dalam Sesi | Kontribusi Spesifik & Rekomendasi | Status |
|:---|:---|:---|:---:|
| **Alpha Lead** | Koordinator War Room | Mendefinisikan visi integrasi multi-modal, batas kewenangan Discord, alur delegasi swarm, dan ratifikasi standar operasional. | ✅ Disahkan |
| **Researcher Prime** | Spesialis Riset & Standar Discord API | Riset Discord API v10, integrasi Discord Gateway, slash command syncing, voice state handling, dan dynamic ephemeral replies. | ✅ Disahkan |
| **Strategic Planner** | Arsitek Fitur & UX | Pemetaan modul: Swarm Mission Control, Jarvis Voice Mode, Interactive Buttons/Modals, Real-time Alerts & Daily WA Digest. | ✅ Disahkan |
| **Code Crafter** | Lead Engineer & Blueprint Arsitektur | Desain modular sistem: `DiscordBridgeClient`, asynchronous event dispatching, Opus stream manager, thread pool offloading untuk Whisper & TTS. | ✅ Disahkan |
| **System Auditor** | Keamanan, Rate Limit & Fact-Check | Keamanan enkripsi token SQLite, RBAC (Role-Based Access Control) multi-level (Owner vs Server Member), proteksi limit 2000 chars, dan circuit breaker rate limit Discord API. | ✅ Disahkan |
| **Laguna Co-Pilot** | Triase Host & Health Monitoring | Validasi host Linux (RAM 3.8GB free, libopus, ffmpeg, yt-dlp) serta heartbeat watchdog. | ✅ Disahkan |

---

## 🏗️ 3. Arsitektur Inti Sistem Bot Discord ALFA

### 3.1 Diagram Topologi & Aliran Data
```
                    ┌────────────────────────────┐
                    │      Discord Client        │
                    │   (Text / Slash / Voice)   │
                    └─────────────┬──────────────┘
                                  │ (Gateway Events / Voice WebSocket)
                                  ▼
               ┌──────────────────────────────────────┐
               │         DISCORD CORE ENGINE          │
               │  (discord.py / pycord Async Client)  │
               └──────────┬────────────────┬──────────┘
                          │                │
            ┌─────────────┴──────┐         └─────────────┬──────────────┐
            ▼                    ▼                       ▼              ▼
     [Command Router]     [Voice Jarvis Hub]     [Mirror Listener]  [Digest Loop]
            │                    │                       │              │
     (Prefix / Slash)     (Opus + Whisper + TTS) (live_meeting) (Daily Cron)
            │                    │                       │              │
            └─────────────┬──────┴───────────────────────┴──────────────┘
                          │
                          ▼
             ┌────────────────────────┐
             │ ALFA TURN EXECUTOR     │
             │ & SWARM COLLECTIVE     │
             └───────────┬────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
[Host Linux Tools]  [Database / Memori]  [Media Engine]
 (Bash/Python/Web)   (SQLite Encrypted)  (FFmpeg/Opus)
```

### 3.2 Lapisan Arsitektur (Architectural Layers)

1. **Ingress & Gateway Layer (`discord_bot.py`)**:
   - Mendengarkan event Discord (`on_message`, `on_interaction`, `on_voice_state_update`).
   - Penanganan otomatis reconnection via Discord Gateway v10 dengan exponentially backed off retry.
   - Filtering intent: Message Content, Guild Voice States, Guild Messages, Direct Messages.

2. **Access Control & Security Layer**:
   - Multi-tier Permission:
     - **Tier 0 (Root Owner)**: Akses ke seluruh tool Linux Host (bash, python execution, file manipulation, live swarm).
     - **Tier 1 (Guild Admin)**: Akses ke monitoring server, digest, media player di VC publik.
     - **Tier 2 (General Member)**: Interaksi santai yang disanitasi (tanpa akses host).
   - Dynamic Token Fetching dari database SQLite ALFA via enkripsi master key (tidak pernah hardcoded di file).

3. **Multi-Modal Voice Jarvis Subsystem**:
   - **Voice Inbound**: Sink recording buffer memanfaatkan libopus untuk merekam stream suara dari channel.
   - **Speech-to-Text (STT)**: Model Whisper (`faster-whisper`) berjalan di worker thread asynchronous terisolasi tanpa memblokir event loop Discord.
   - **Response Generator**: Otak utama ALFA (`run_agent_turn`) memproses teks dengan prompt konteks suara Discord.
   - **Text-to-Speech (TTS)** & Audio Stream: Edge-TTS / OGG synthesis, diputar balik via `FFmpegPCMAudio` dengan anti-overlapping guard.

4. **Swarm War Room Mission Control (`!swarm` / `/swarm`)**:
   - Memungkinkan eksekusi kolektif 6 unit swarm langsung dari channel teks Discord.
   - Live stream status misi diposting bertahap (Thinking -> Decomposing -> Executing -> Ratified).
   - Sinkronisasi instan ke berkas `live_meeting_feed.jsonl` dan sistem reporting Telegram ALFA.

5. **Discord Mirror & Broadcast Engine**:
   - Continuous background loop memantau feed swarm dan file audit.
   - Auto-chunking text splitter (limit 1900-2000 karakter) dengan pemisah baris cerdas agar markdown tidak rusak.

---

## 🛡️ 4. Matriks Risiko & Mitigasi Keamanan

| Potensi Risiko | Tingkat | Solusi Mitigasi Arsitektur |
|:---|:---:|:---|
| **Discord API Rate Limit (429)** | Sedang | Message queuing asynchronous, batching output, split pesan bertahap dengan jeda waktu adaptif. |
| **Audio Stalling / Double Voice** | Rendah | Mutex guard pada VoiceClient; auto-stop audio lama sebelum streaming audio baru dimulai. |
| **Host Hijacking via Discord Chat** | Kritis | Strict Whitelist ID (`DEF_OWNER_ID` & `ALLOWED_USER_IDS`). Perintah host ditolak jika ID tidak lolos autentikasi. |
| **High Memory / Whisper Latency** | Sedang | Thread pool offload (`asyncio.to_thread`), model `base`/`tiny` int8 compute type di CPU. |

---

## 🚀 5. Roadmap Tahap Implementasi

1. **Sprint 1 (Fondasi & Stabilisasi Gateway)**:
   - Evaluasi dependency `py-cord`/`discord.py` dan kesiapan `libopus.so.0`.
   - Sinkronisasi token bot terenkripsi pada SQLite ALFA.
2. **Sprint 2 (Slash Commands & Interactive Views)**:
   - Migrasi perintah prefix (`!swarm`, `!play`, `!ss`) menjadi Discord Slash Commands modern (`/swarm`, `/jarvis`, `/status`).
   - Implementasi Discord Button & Select Menu untuk kendali musik dan swarm triage.
3. **Sprint 3 (Duplex Voice Channel Jarvis)**:
   - Penyempurnaan VAD (Voice Activity Detection) untuk transisi dari half-duplex (8 detik) menjadi fluid conversational turn.
4. **Sprint 4 (Cross-Platform Hub: Telegram-Discord Sync)**:
   - Sinkronisasi dua arah real-time antara War Room Telegram ALFA dan Mission Control Discord.

---
*Dokumen Keputusan Resmi War Room ALFA — Disetujui oleh Alpha Lead & Seluruh Swarm ALFA.*
