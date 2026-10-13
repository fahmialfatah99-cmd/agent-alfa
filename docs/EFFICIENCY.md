# ALFA Efficiency Report — biaya & latensi per task

Digenerate otomatis: `python evals/efficiency_report.py`. Token live = delta tabel `api_token_usage` per skenario (real, bukan estimasi); biaya = token/1jt × harga per-juta token (default US$0.10, kasar, via `ALFA_EVAL_PRICE_PER_MTOK`). Offline = routing saja (0 token LLM).

| File | Mode | Lolos | Rata-rata ms/task | Total token | Estimasi US$ |
|---|---|---|---|---|---|
| `offline_baseline.json` | offline | 20/20 | 22.0 | 0 | 0 |

## Per task (run terakhir)

| Task | Mode | OK | ms | Token |
|---|---|---|---|---|
| `eval_web_research_01` | offline | ya | 334.18 | 0 |
| `eval_python_sandbox_01` | offline | ya | 11.44 | 0 |
| `eval_file_write_01` | offline | ya | 11.71 | 0 |
| `eval_math_reasoning_01` | offline | ya | 0.0 | 0 |
| `eval_translation_01` | offline | ya | 0.0 | 0 |
| `eval_code_review_01` | offline | ya | 0.0 | 0 |
| `eval_memory_store_01` | offline | ya | 11.02 | 0 |
| `eval_refusal_safe_01` | offline | ya | 0.0 | 0 |
| `eval_summarize_01` | offline | ya | 0.0 | 0 |
| `eval_tool_rag_routing_01` | offline | ya | 7.01 | 0 |
| `eval_file_search_02` | offline | ya | 8.14 | 0 |
| `eval_bash_exec_02` | offline | ya | 6.99 | 0 |
| `eval_system_stats_02` | offline | ya | 6.87 | 0 |
| `eval_pdf_merge_02` | offline | ya | 8.04 | 0 |
| `eval_dataset_02` | offline | ya | 6.27 | 0 |
| `eval_vault_store_02` | offline | ya | 7.75 | 0 |
| `eval_reminder_02` | offline | ya | 6.26 | 0 |
| `eval_qr_02` | offline | ya | 6.88 | 0 |
| `eval_meeting_plan_02` | offline | ya | 7.25 | 0 |
| `eval_refusal_injection_02` | offline | ya | 0.0 | 0 |
