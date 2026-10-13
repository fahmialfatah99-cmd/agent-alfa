# Head-to-Head Pack — bandingkan ALFA vs framework lain secara adil

Paket ini berisi 10 task framework-agnostik + template hasil. Kami TIDAK
mengarang angka kompetitor: jalankan prompt yang sama di framework lain dengan
**model yang sama**, isi `results_template.md`, lalu bandingkan.

## Aturan adil

1. Model identik (mis. `gemini-3.6-flash` di semua kandidat).
2. Prompt disalin mentah dari `tasks.json` — tanpa tuning per framework.
3. Lolos = kriteria `pass_when` terpenuhi tanpa campur tangan manusia.
4. Catat wall-clock + token (atau estimasi) + biaya per task.

## Task (`tasks.json`)

Dibaca mesin maupun manusia: array `{id, prompt, pass_when, category}`.
10 task mewakili riset web, coding sandbox, tulis file, nalar, bahasa,
review kode, memori, keamanan (refusal), ringkas, dan tool-routing.

## Menjalankan di ALFA

```bash
python evals/run_evals.py --live --filter <id> --output-json storage/eval_runs/h2h.json
python evals/efficiency_report.py   # agregat ke docs/EFFICIENCY.md
```

## Menjalankan di framework lain (contoh)

- **CrewAI**: satu crew 2 agent (researcher + writer), tools Serper/Bash,
  prompt = task verbatim, catat iterasi dan token dari callback.
- **AutoGen**: `AssistantAgent` + `UserProxyAgent(code_execution_config)`,
  `max_consecutive_auto_reply` sama untuk semua task.
- **OpenHands**: task sebagai instruksi awal, ambil metric dari trajectory.

Isi hasilnya ke `results_template.md`, publikasikan metodenya. Klaim tanpa
metode = opini; paket ini ada agar klaim ALFA bisa dibantah secara terbuka.
