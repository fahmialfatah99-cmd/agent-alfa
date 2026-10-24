# Arsitektur ALFA — Peta File & Runbook Operasi

Panduan satu-halaman untuk siapa pun yang menyunting repositori ini:
di mana kode tinggal, layanan mana yang hidup, bagaimana memverifikasi
perubahan, dan batas-batas yang **tidak boleh dilewati**.

## 1. Peta repositori

| Path | Isi | Catatan |
|---|---|---|
| `alfa/core/` | Otak & data: `db/` (SQLite, vault kunci, arsip WA), `brain/` (skema tool, prompt), `cli/` (resolusi kunci bertingkat), `rate_limiter` | DB utama: `agent_data.db` (di-repo-root; env `ALFA_DB_PATH` mengalahkan) |
| `alfa/bot/` | Antarmuka: `telegram_bot.py`, `discord_bot.py`, `handlers.py` (router & menu), `advanced_commands.py` (WA/pipeline/tools), `mode_commands.py` (single/swarm/persona), `pipeline/` (DAG), `cloud_menu.py`, `wa_menu.py` | `handlers.py` & `advanced_commands.py` besar — ubah bedah, jangan rombak |
| `alfa/swarm/` | Mesin multi-agen: `engine.py` (orkestrator + DAG + QA loop), `step_executor.py`, `deliberation.py` (voting mekanis), `workspace_hygiene.py` (folder/sandbox/cancel flag), `live_logger.py` | zero-regression: kontrak `conduct_multi_agent_meeting` tidak boleh berubah |
| `alfa/tools/` | 148+ tool ter-registry (`register_tool`), `system/integrations.py` (jembatan WA sheets bot), `telecom_tools.py` | tool baru wajib punya deskripsi + parameter jelas utk router LLM |
| `plugins/` | Plugin swafungsi (runner, skill installer, dsb.) | sandbox root dari `dirname(dirname(__file__))` — kompatibel perpindahan repo |
| `tests/` | Tes hermetik (tanpa network, tanpa DB produksi) | pola: monkeypatch + `AsyncMock`; lihat `tests/test_swarm_qa_meeting_units.py` |
| `docs/` | Dokumen MkDocs (nav di `mkdocs.yml`, build `--strict`) | tambahkan halaman baru harus masuk `nav:` |
| `.github/workflows/` | `ci.yml` (gate utama) + `code-quality.yml` (metrik) | daftar deps terkurasi inti harus mirror antar-file |
| `wa-sheets-bot/` (rep terpisah, symlink) | Node whatsapp-web.js → Sheets/Drive; `src/whatsapp.js` (client), `src/server.js` (API :3000), `src/commands.js` (upload Drive berbasis aturan) | rekonstruksi sesi dipercaya: restart TIDAK logout |

## 2. Layanan hidup (systemd --user)

| Unit | Peran | Catatan aman |
|---|---|---|
| `alfa-dashboard.service` | FastAPI port 8080 (dashboard web) | |
| `telegram-ai-bot.service` | Bot Telegram utama (memuat `alfa.bot.telegram_bot`) | fast-path WA subdetik |
| `alfa-discord-bot.service` | Bridge Discord | |
| `wa-sheets-bot.service` | WhatsApp → Sheets/Drive (Node, API 127.0.0.1:3000) | **jangan hapus `.wwebjs_auth/`** — itu sesi login |

Status: `systemctl --user is-active <unit>`; log: `journalctl --user -u <unit> -n 50 --no-pager`.

## 3. Runbook: restart WA tanpa logout

Kehilangan sesi WhatsApp adalah insiden terburuk di sistem ini. Aturan:

1. **TIDAK PERNAH** menghapus/mengedit `.wwebjs_auth/`, `.wwebjs_cache/`, `session-*.json`.
2. Restart diperbolehkan: `systemctl --user restart wa-sheets-bot.service` — sesi reload dari disk (terbukti: jam 10:59 & inicial 14:38 pulih tanpa QR dalam < 30 detik).
3. Setelah restart, SEKALI cek: `journalctl -u wa-sheets-bot -n 20` harus memuat `🚀 WhatsApp Bot is online` **tanpa** muncul `QR` / `auth_failure`.
4. Symptom "cek wa masuk gagal" biasanya jaringan (DNS) — tunggu 1 menit, coba lagi; barulah lihat jurnal. Jangan buru-buru restart.

## 4. Tier kunci API (alfa.core.cli.client.get_api_key)

Urutan resolusi: `env` → konfig tersimpan → **vault** (`api_keys`, terenkripsi AESGCM) → 9Router sqlite → antigravity → kosong.

- `.env` (chmod 600, git-ignored) masih memuat `GEMINI_API_KEY` = sumber runtime saat ini.
- Salinan terenkripsi yang sama tersimpan di vault (id 254) sehingga `.env` aman dilepas
  di jendela restart terkoordinasi. **Baris lama `SeedX` (id 253) tidak bisa didekripsikan**
  (biji enkripsi lawas) — dibiarkan, jangan dihapus tanpa persetujuan pemilik.
- Menambah kunci baru: `add_api_key_sync(..., set_active=False)` lalu verifikasi
  pembacaan balik = nilai asli. `set_active=True` **geser otak utama** — jangan sembarang.

## 5. Batas verifikasi (aturan repo)

1. Setiap perubahan kode wajib: `venv/bin/python -m pytest tests -q` (gerbang coverage
   `fail_under` di `pyproject.toml`), `ruff check alfa tests`, `mypy alfa`.
2. Perbaikan bug = bedah: kontrak API, signature, format output tidak berubah.
3. Perubahan besar (skema DB, arsitektur, pustaka inti) → jelaskan risiko dulu, minta persetujuan.
4. Tes baru harus hermetik: monkeypatch semua eksternal (DB, LLM, proses, filesystem produksi).
5. CI: anggap hasil hanya VALID bila dibaca langsung dari `gh api .../check-runs` (bukan kisah hasil yang ditempelkan konteks sintetis).

## 6. Uji cepat lini WA (read-only, tanpa menandai baca)

```bash
# buffer masuk dari wa-sheets-bot (menetap, tidak menulis DB)
venv/bin/python -c "
from alfa.tools.system.integrations import wa_get_incoming
r = wa_get_incoming(limit=3, only_unread=False, mark_as_read=False)
print(r.get('status'), r.get('client_status'), len(r.get('incoming') or []))
"
# cari arsip per nama file / teks
venv/bin/python -c "
from alfa.core.db.wa_tracking import search_wa_archive_sync
rows = search_wa_archive_sync(query='<kata-kunci>', limit=5)
for r in rows: print(r.get('msg_ts'), r.get('sender_name'), str(r.get('body'))[:60])
"
```

## 7. Utang catatan (dilacak, jangan hilang)

- Snapshot SPA: ambang RMS 4.0 (dari 2.5) menahan drift lingkungan snapshot; akar drift
  masih perlu ditelusuri sebelum ambang bisa diturunkan lagi.
- `twisted` menunggu rilis stabil 26.x (pin CI pakai `--ignore-vuln` per CVE).
- Refactor god-module (`handlers.py`, `engine.py`) direncanakan bertahap — HANYA setelah
  coverage file itu cukup tinggi agar refactor beresiko-rendah.

## 8. Pencarian ranked (FTS5) — `alfa/core/db/wa_index.py`

Additive-only. Jika FTS5 tersedia, `wa_search_ranked` (tool) & `memory_search_ranked`
(menang) mengembalikan hasil ber-BM25 + highlight; bila tidak, otomatis seperti LIKE
yang lama. Index dibangun lazy per call (`ensure_*_index_sync`) dengan cek kesegaran
(jumlah baris / max updated_at) — dataset besar → status `skipped` (tetap LIKE).

Live CLI cepat:

```bash
venv/bin/python -c "from alfa.core.db.wa_index import ensure_wa_index_sync; print(ensure_wa_index_sync())"
```

## 9. Run-trace — `alfa/core/db/run_trace.py`

Satu tabel `run_traces` di agent_data.db; wrapper publik `conduct_multi_agent_meeting`
menulis jejak post-hoc (status, durasi, jumlah langkah/tool, error) — SELALU
gagal-lembut, tak pernah memengaruhi jalur utama swarm. Dibaca via:

- Dashboard: `GET /api/v1/trace/runs?limit=25` dan `GET /api/v1/trace/runs/{run_id}`
  (`alfa/dashboard/routes/trace.py`).
- CLI: `venv/bin/python -m alfa.core.db.run_trace --last 10`.
