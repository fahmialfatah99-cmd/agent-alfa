# Operations Runbook — ALFA Sovereign AI

Runbook ini untuk operator single-node (SQLite + systemd user services).
Semua perintah dijalankan sebagai user `fahmial` dari direktori repo.

## 1. Aturan mutlak

- **JANGAN** restart, stop, logout, reset, atau menghapus folder session
  `wa-sheets-bot.service`. Login WhatsApp mahal dan rawan QR.
- Restart rutin setelah update **hanya**:
  `telegram-ai-bot.service` dan `alfa-dashboard.service`.
- `alfa-queue-worker.service` boleh direstart bila antrean macet dan tidak ada
  misi berstatus `running`; periksa dulu dengan `queue_stats`.
- Jangan pernah mencetak token/API key/hash session ke log atau chat.

## 2. Peta service

| Unit | Fungsi | Port / probe |
|---|---|---|
| `alfa-dashboard.service` | FastAPI dashboard + API | `127.0.0.1:8080` |
| `telegram-ai-bot.service` | Bot Telegram, turn executor, tools | polling Telegram |
| `alfa-queue-worker.service` | Worker misi swarm durable | SQLite `swarm_missions` |
| `alfa-db-backup.timer` | Backup harian 03:00 | `~/.alfa/backups` |
| `wa-sheets-bot.service` | WhatsApp → Sheets (JANGAN disentuh) | `127.0.0.1:3000` |

## 3. Health, readiness, dan metrics

```bash
# Liveness (selalu 200 bila proses hidup)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/healthz

# Readiness (200 siap trafik, 503 bila DB/disk tidak sehat)
curl -s -i http://127.0.0.1:8080/readyz | head -20

# Metrics (butuh auth token/session)
curl -s -H "Authorization: Bearer $DASHBOARD_AUTH_TOKEN" \
  http://127.0.0.1:8080/api/metrics | python3 -m json.tool
```

`/readyz` memeriksa `SELECT 1`, jumlah tabel, direktori DB yang writable, dan
statistik antrean. `/healthz` tidak berubah agar probe lama tetap kompatibel.
`/api/metrics` memuat `operational`: ukuran DB/WAL, antrean per status, dan
jumlah turn chat aktif.

## 4. Request tracing dan rate limit

- Setiap response dashboard membawa `X-Request-ID`. Nilai dari klien hanya
  diterima bila cocok `[A-Za-z0-9._-]{8,64}`; selain itu dibuat baru.
- Log akses memuat method, path tanpa query string, status, durasi, dan
  request-id. Header `Authorization`/cookie tidak dicatat.
- Endpoint generasi chat dibatasi default **20 permintaan/60 detik/IP**
  (`ALFA_CHAT_RATE_LIMIT`, `ALFA_CHAT_RATE_WINDOW_SEC`; `0` = nonaktif).
  Respons 429 membawa `Retry-After`.

## 5. Graceful shutdown

Unit dashboard memakai `TimeoutStopSec=30`. Saat stop/restart, lifespan:

1. membatalkan scheduler pipeline dan malloc-trim loop;
2. membatalkan seluruh turn chat aktif dan membersihkan registry;
3. menutup connection pool SQLite.

Turn yang sedang streaming akan menerima status `stopped`/koneksi terputus,
bukan menggantung sampai timeout systemd.

## 6. Retensi data

| Data | Default | Pengaturan |
|---|---|---|
| Sesi dashboard invalid/kedaluwarsa | 30 hari | `ALFA_DASHBOARD_SESSION_RETENTION_DAYS` (`0` = nonaktif) |
| Durable tasks | 30 hari | `ALFA_DURABLE_RETENTION_DAYS` |
| Evidence ledger | 90 hari | `ALFA_EVIDENCE_RETENTION_DAYS` |
| Backup lokal | 7 harian + 4 mingguan | `scripts/backup_db.py` |
| Riwayat chat | Tidak dihapus otomatis | hapus manual per thread / global |

Pembersihan sesi dashboard berjalan saat startup. Untuk menerapkan retensi
baru, restart **hanya** dashboard (bukan WhatsApp).

## 7. Backup dan restore

```bash
venv/bin/python scripts/backup_db.py run
venv/bin/python scripts/backup_db.py verify <archive>
venv/bin/python scripts/backup_db.py restore-drill
systemctl --user status alfa-db-backup.timer
```

Backup memakai snapshot SQLite hot-safe, manifest SHA-256, dan sinkron offsite
rclone yang fail-soft. Jangan jalankan restore ke DB produksi saat service
hidup; ikuti prosedur di `DEPLOYMENT.md`.

## 8. Playbook insiden

### Dashboard 503 / `readyz` not_ready
1. Cek `journalctl --user -u alfa-dashboard.service -n 100 --no-pager`.
2. Cek disk (`df -h`) dan izin direktori DB.
3. Jangan hapus `agent_data.db-wal`/`-shm` saat service hidup.
4. Restart hanya dashboard setelah penyebab jelas.

### Bot Telegram tidak merespons
1. `systemctl --user is-active telegram-ai-bot.service`
2. `journalctl --user -u telegram-ai-bot.service -n 100 --no-pager`
3. Cek koneksi ke `api.telegram.org` dan konflik polling (dua instance).
4. Restart hanya bot bila tidak ada proses lain memakai token yang sama.

### Antrean swarm menumpuk
1. `queue_stats` / `GET /api/swarm/queue` (admin).
2. Pastikan worker aktif dan tidak ada misi `running` macet.
3. Restart worker hanya bila aman; misi `queued` tetap tersimpan di SQLite.

### WhatsApp stuck / QR
Ikuti aturan §1: **jangan restart**. Catat `MainPID`, `NRestarts`, dan log
`journalctl --user -u wa-sheets-bot.service`. Serahkan keputusan ke Fahmi;
session folder tidak boleh dihapus.

## 9. Deploy dan verifikasi

```bash
cd ~/telegram-ai-bot
git pull --ff-only
systemctl --user restart telegram-ai-bot.service alfa-dashboard.service
sleep 5
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/healthz
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/coding/worktrees
systemctl --user show wa-sheets-bot.service -p MainPID -p NRestarts -p ActiveEnterTimestamp
```

Catat `MainPID` WhatsApp sebelum dan sesudah deploy; nilainya **harus sama**.

## 10. Postur keamanan

- Auth dashboard fail-closed; `/api/*` butuh session/token kecuali path publik
  yang eksplisit.
- CSP ketat + nonce, `X-Frame-Options: DENY`, `nosniff`, referrer policy.
- Rate limit auth dan generasi chat.
- Audit permission tersimpan di `permission_audit`; endpoint audit admin-only.
- Dependency check CI memindai `requirements-lock.txt`; SBOM CycloneDX
  dihasilkan setiap run Code Quality.
