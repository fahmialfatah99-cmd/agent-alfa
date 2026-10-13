# ALFA Benchmark — angka yang bisa dikutip

Metodologi: 20 skenario deklaratif di `evals/scenarios.json` (research, coding,
reasoning, memory, safety, system, media, agent). Dua mode:

- **Offline** (tanpa LLM, jalan di CI): validitas skenario + routing Tool-RAG
  harus mengenai minimal satu tool yang diharapkan (`expect_tools_any`).
- **Live** (pakai kuota Gemini): prompt dieksekusi via `bot.run_agent_turn`,
  dinilai `checks` (contains/regex/length/refusal).

## Hasil terakhir (2026-10-14, terverifikasi lokal)

- Offline: **20/20 PASS** (`python evals/run_evals.py`)
- Suite `alfa.eval`: ToolSelection 2 + MemoryRetrieval 1 + AgenticLoop 1 +
  ScenarioFile 20 skenario
- Unit/integrasi: **780 passed** (`pytest`), ruff + bandit (`-ll`) + `pip-audit`
  bersih, mypy 1.8.0 = 7 ≤ budget 33

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
