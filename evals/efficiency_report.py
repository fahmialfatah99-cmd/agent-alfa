"""Generate docs/EFFICIENCY.md dari arsip hasil eval (storage/eval_runs/*.json).

Jalankan: python evals/efficiency_report.py [--runs-dir DIR] [--out PATH]
Tak butuh LLM/API — murni agregasi JSON yang sudah ada.
"""

import argparse
import glob
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RUNS = os.path.join(BASE_DIR, "storage", "eval_runs")
DEFAULT_OUT = os.path.join(BASE_DIR, "docs", "EFFICIENCY.md")


def load_runs(runs_dir: str) -> list[dict]:
    runs = []
    for path in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["_file"] = os.path.basename(path)
            runs.append(data)
        except Exception:
            continue
    return runs


def render(runs: list[dict]) -> str:
    lines = [
        "# ALFA Efficiency Report — biaya & latensi per task",
        "",
        "Digenerate otomatis: `python evals/efficiency_report.py`. "
        "Token live = delta tabel `api_token_usage` per skenario (real, bukan estimasi); "
        "biaya = token/1jt × harga per-juta token (default US$0.10, kasar, via "
        "`ALFA_EVAL_PRICE_PER_MTOK`). Offline = routing saja (0 token LLM).",
        "",
    ]
    if not runs:
        lines += [
            "Belum ada arsip hasil (`storage/eval_runs/*.json`). Jalankan:",
            "",
            "```bash",
            "python evals/run_evals.py --output-json storage/eval_runs/offline_x.json",
            "python evals/run_evals.py --live --output-json storage/eval_runs/live_x.json",
            "```",
            "",
        ]
        return "\n".join(lines)
    lines += [
        "| File | Mode | Lolos | Rata-rata ms/task | Total token | Estimasi US$ |",
        "|---|---|---|---|---|---|",
    ]
    for r in runs:
        mode = "live" if r.get("live") else "offline"
        lines.append(
            f"| `{r.get('_file')}` | {mode} | "
            f"{r.get('passed')}/{r.get('total')} | "
            f"{r.get('avg_duration_ms')} | {r.get('total_tokens')} | "
            f"{r.get('total_cost_usd_est')} |"
        )
    lines += [
        "",
        "## Per task (run terakhir)",
        "",
        "| Task | Mode | OK | ms | Token |",
        "|---|---|---|---|---|",
    ]
    for rec in runs[-1].get("records", []):
        lines.append(
            f"| `{rec.get('id')}` | {rec.get('mode')} | "
            f"{'ya' if rec.get('ok') else 'TIDAK'} | "
            f"{rec.get('duration_ms')} | {rec.get('tokens_total', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=DEFAULT_RUNS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    out = render(load_runs(args.runs_dir))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"EFFICIENCY.md ditulis ({len(out)} char) dari {args.runs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
