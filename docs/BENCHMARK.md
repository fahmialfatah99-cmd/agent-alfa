# ALFA Benchmark — angka yang bisa dikutip

Metodologi: 20 skenario deklaratif di `evals/scenarios.json` (research, coding,
reasoning, memory, safety, system, media, agent). Dua mode:

- **Offline** (tanpa LLM, jalan di CI): validitas skenario + routing Tool-RAG
  harus mengenai minimal satu tool yang diharapkan (`expect_tools_any`).
- **Live** (pakai kuota Gemini): prompt dieksekusi via `bot.run_agent_turn`,
  dinilai `checks` (contains/regex/length/refusal).

## Hasil terakhir (2026-11-12, terverifikasi lokal)

- Offline: **20/20 PASS** (`python evals/run_evals.py`)
- Suite `alfa.eval`: ToolSelection 2 + MemoryRetrieval 1 + AgenticLoop 1 +
  ScenarioFile 20 skenario
- Unit/integrasi: **1.877 test passed** (`pytest`), coverage **63,9%**
  (gate repo 55%), `ruff` bersih, `mypy` 0 issue di 332 file,
  `bandit -ll` **0 Medium/High**, `pip-audit` bersih
- Gerbang Debt: budget TRY/BLE **505 instans** (dari 988 saat overhaul
  dimulai) & 0 handler `except Exception: pass` (gate CI)
- Rilis: **v2.15.0**

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
