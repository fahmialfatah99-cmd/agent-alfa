# ALFA Benchmark — angka yang bisa dikutip

Metodologi: 20 skenario deklaratif di `evals/scenarios.json` (research, coding,
reasoning, memory, safety, system, media, agent). Dua mode:

- **Offline** (tanpa LLM, jalan di CI): validitas skenario + routing Tool-RAG
  harus mengenai minimal satu tool yang diharapkan (`expect_tools_any`).
- **Live** (pakai kuota Gemini): prompt dieksekusi via `bot.run_agent_turn`,
  dinilai `checks` (contains/regex/length/refusal).

## Hasil terakhir (2026-11-16, terverifikasi lokal)

- Offline: **20/20 PASS** (`python evals/run_evals.py`)
- Suite `alfa.eval`: ToolSelection 2 + MemoryRetrieval 1 + AgenticLoop 1 +
  ScenarioFile 20 skenario
- Unit/integrasi: **2.000 test passed** (`pytest`), coverage **64,95%**
  (gate repo 55%), `ruff` bersih, `mypy` 0 issue di 347 file,
  `bandit -ll` **0 Medium/High**, `pip-audit` bersih
- Guard kepercayaan: klaim mutasi file diverifikasi (keberadaan, `mtime`,
  sheet Excel) sebelum balasan dikirim; turn per-chat diserialisasi; klaim
  atribusi tool/library di-grounding ke catatan eksekusi turn.
- Evidence ledger: setiap tool yang menyentuh artefak mencatat path, SHA-256,
  ukuran, status, dan `turn_id`; mode default `shadow`, retensi 90 hari /
  100.000 baris, dan API read-only `GET /api/v1/trust/*`.
- Edit Excel: `update_excel_sheet` menulis atomik (temp + replace), membuat
  backup, membuka ulang workbook, dan memverifikasi sheet/header/jumlah baris
  sebelum melaporkan sukses; `dry_run=True` memberi diff deterministik tanpa
  menulis, `keep_backup=True` + `restore_excel_backup` menyediakan undo.
- Context governor: kompaksi legacy dipertahankan; mode `on` menambah
  head+tail adaptif, hard budget, dan pemangkasan output tool baru. Statistik
  penghematan karakter/estimasi token tersedia via `/api/v1/trust/context`.
- Gerbang Debt: budget TRY/BLE **510 instans** (dari 988 saat overhaul
  dimulai) & 0 handler `except Exception: pass` (gate CI)
- Durable Task Runtime: status/checkpoint per giliran tersimpan di tabel
  `durable_tasks`; `/runs` + `/lanjut` (mode `ALFA_DURABLE_TASKS=on`) untuk
  melanjutkan tugas terputus. Default `shadow` (hanya mencatat).
- Skill Compiler: trajectory sukses (>= 2 tool, support >= 2) dikompilasi
  menjadi workflow reusable; default `shadow` (inactive), mode `on`
  mengaktifkan dan menyuntikkan panduan ke prompt.
- Capability Security: grant per chat/tool dengan TTL + batas pakai; default
  `shadow`, mode `on` menegakkan grant dan `ALFA_CAPABILITY_REQUIRED` menolak
  tool HIGH/CRITICAL tanpa grant.
- Trust Center UI: panel read-only di tab Guardian untuk evidence, context
  governor, capability, durable task, dan workflow terkompilasi.
- Rilis: **v2.20.0**

## Reproduksi

```bash
python evals/run_evals.py                 # offline
python evals/run_evals.py --live --output-json storage/eval_runs/x.json
venv/bin/python -m pytest -q
```

## Live terjadwal

Workflow `.github/workflows/eval-live.yml` jalan mingguan + manual bila
`GEMINI_API_KEY` tersedia; hasil JSON diarsipkan 30 hari sebagai artifact dan
dapat dibaca via `GET /api/evals/runs`. Tanpa secret, job dilewati otomatis.

## Batasan jujur

Offline menguji routing, bukan kualitas jawaban. Angka live bervariasi antar
run (LLM nondeterministik) — bandingkan tren mingguan, bukan angka tunggal.
Belum ada perbandingan versus framework lain; itu pekerjaan berikutnya.
