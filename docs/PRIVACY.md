# Kebijakan Privasi Operasional — ALFA Sovereign AI

Dokumen ini menjelaskan data apa yang disimpan ALFA, untuk apa, berapa lama,
dan bagaimana menghapusnya. Ini adalah kebijakan operasional teknis, bukan
nasihat hukum. Untuk kewajiban regulasi tertentu, konsultasikan dengan hukum
yang berlaku.

## 1. Prinsip

- **Minimisasi**: hanya data yang dibutuhkan untuk menjalankan agent,
  riwayat percakapan, dan audit keamanan.
- **Lokal-first**: data utama tersimpan di SQLite `agent_data.db` pada host
  operator. Tidak ada telemetri produk ke pihak ketiga.
- **Rahasia tidak pernah dilatih**: API key disimpan terenkripsi (AES-GCM di
  vault), bukan di log atau prompt.
- **Dapat dihapus**: riwayat chat, thread, memori, dan user dashboard punya
  jalur penghapusan eksplisit.

## 2. Inventaris data

| Data | Lokasi | Tujuan | Retensi |
|---|---|---|---|
| Riwayat chat & thread | `chat_history`, `conversations` | Konteks percakapan | Sampai dihapus user/operator |
| Memori & knowledge graph | tabel memori/vektor | Recall jangka panjang | Sampai dihapus |
| User & sesi dashboard | `dashboard_users`, `dashboard_sessions` | Autentikasi | Sesi invalid/kedaluwarsa 30 hari |
| Audit izin tool | `permission_audit` | Keamanan & forensik | Mengikuti retensi DB/backup |
| Durable task & evidence | `durable_tasks`, evidence ledger | Ketahanan & audit eksekusi | 30 / 90 hari (env) |
| API key provider | vault terenkripsi | Memanggil LLM/tool | Sampai dihapus operator |
| Log service | journald | Operasional & debugging | Kebijakan journald host |
| Backup DB | `~/.alfa/backups` + offsite | Pemulihan bencana | 7 harian + 4 mingguan |

## 3. Data yang dikirim ke pihak ketiga

ALFA memanggil penyedia eksternal hanya bila fitur terkait dipakai:

- **LLM provider** (Gemini/Anthropic/OpenAI-compatible): prompt, riwayat
  percakapan yang relevan, dan hasil tool dapat dikirim ke provider sesuai
  konfigurasi model. Kebijakan retensi/pelatihan mengikuti provider tersebut.
- **Telegram / WhatsApp**: pesan dan media yang dikirim user diproses oleh
  platform masing-masing.
- **Web tools / scraping**: URL dan konten yang diminta dapat dilihat oleh
  situs tujuan.
- **Google Drive/Sheets**: hanya file/folder yang diotorisasi operator.

Operator bertanggung jawab memastikan provider yang dipakai sesuai kebijakan
data organisasi.

## 4. Rahasia dan kredensial

- Token bot, API key, dan kredensial lain dibaca dari environment/`.env` atau
  vault; nilai tidak pernah dicetak ke log aplikasi.
- Dashboard memakai hash password (PBKDF2/scrypt sesuai implementasi auth),
  session token di-hash sebelum disimpan.
- Backup offsite memakai rclone crypt; kunci recovery disimpan terpisah dari
  repo.
- CI memakai secret scanning (gitleaks) dan dependency audit.

## 5. Hak dan prosedur penghapusan

- **Hapus satu thread**: tombol hapus di panel riwayat dashboard; hanya thread
  tersebut yang dihapus.
- **Hapus seluruh riwayat user**: `clear_user_chat_history` (global) juga
  menghapus baris `conversations` milik user.
- **Hapus user dashboard**: endpoint admin `DELETE /api/auth/users/{id}`;
  sesi user di-invalidasi.
- **Hapus memori**: endpoint/tool memori yang tersedia untuk operator.
- **Backup**: penghapusan di DB produksi tidak otomatis menghapus salinan
  backup sampai retensi backup berakhir. Untuk permintaan penghapusan total,
  hapus juga arsip backup terkait dan salinan offsite.

## 6. Keamanan akses

- Dashboard fail-closed: `/api/*` butuh session/token; path publik dibatasi
  eksplisit (health/readiness/login).
- Endpoint admin (coding worktree, user management, audit) memakai
  `require_admin`.
- Rate limit login/registrasi dan generasi chat.
- CSP ketat, `X-Frame-Options: DENY`, `nosniff`, referrer policy.
- Setiap request punya `X-Request-ID` untuk korelasi insiden tanpa mencatat
  query string atau header sensitif.

## 7. Retensi dan pemulihan

- Pembersihan sesi dashboard berjalan saat startup dengan default 30 hari.
- Durable task/evidence dipangkas otomatis sesuai env retensi.
- Backup harian diverifikasi SHA-256 dan diuji restore (`restore-drill`).
- Bila terjadi insiden, prioritaskan preservasi bukti (log + backup) sebelum
  menghapus data.

## 8. Kontak

Pemilik operasional: Fahmi Alfatah. Untuk pertanyaan privasi/keamanan, gunakan
kanal internal yang sama dengan pengelolaan ALFA; jangan mengirim rahasia ke
issue publik.
