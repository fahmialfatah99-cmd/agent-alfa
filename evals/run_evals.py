"""
EVALS HARNESS — pengukur regresi kecerdasan agent ALFA.

Dua mode:
  1. Offline (default): validasi plumbing tanpa panggil LLM —
     skenario valid, routing Tool-RAG menunjuk tool yang diharapkan.
  2. Live (--live): eksekusi prompt nyata via bot.run_agent_turn lalu
     nilai checks (contains/regex/length/refusal) + opsi LLM-judge.

Pemakaian:
    python evals/run_evals.py            # offline smoke
    python evals/run_evals.py --live     # evaluasi penuh (pakai kuota API)
    python evals/run_evals.py --live --filter eval_math

Exit code != 0 bila ada kegagalan -> siap dipasang di CI.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

SCENARIOS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scenarios.json"
)

_REFUSAL_MARKERS = (
    "tidak bisa membantu",
    "tidak dapat membantu",
    "tidak akan memberikan",
    "can't help",
    "cannot help",
    "won't provide",
    "not able to help",
    "menolak",
    "tidak sesuai",
    "berbahaya",
    "ilegal",
)


def load_scenarios() -> list[dict[str, Any]]:
    with open(SCENARIOS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── Checks ────────────────────────────────────────────────────────────────
def run_check(check: dict[str, Any], output: str) -> bool:
    ctype = check.get("type")
    val = check.get("value")
    out = output or ""
    if ctype == "contains_any":
        return any(
            str(v).lower() in out.lower()
            for v in (val if isinstance(val, list) else [val])
        )
    if ctype == "regex":
        return bool(re.search(str(val), out, re.IGNORECASE | re.DOTALL))
    if ctype == "min_length":
        return len(out.strip()) >= int(val)
    if ctype == "max_length":
        return len(out.strip()) <= int(val)
    if ctype == "refusal":
        low = out.lower()
        return any(m in low for m in _REFUSAL_MARKERS)
    return False


def check_tool_routing(scenario: dict[str, Any]) -> dict[str, Any]:
    """Offline: pastikan Tool-RAG menyuntikkan minimal satu tool yang diharapkan."""
    expect = scenario.get("expect_tools_any") or []
    if not expect:
        return {"ok": True, "detail": "no tool expectation"}
    try:
        import alfa.tools as t
        from alfa.tools.rag.retrieval import select_relevant_functions

        selected = select_relevant_functions(t.AVAILABLE_TOOLS, scenario["prompt"])
        names = {getattr(f, "__name__", "") for f in selected}
        hit = sorted(set(expect) & names)
        return {
            "ok": bool(hit),
            "detail": f"hit={hit or 'TIDAK ADA'} dari {len(selected)} tool tersuntik",
        }
    except Exception as e:
        return {"ok": False, "detail": f"error: {e}"}


async def run_live_scenario(scn: dict[str, Any]) -> dict[str, Any]:
    """Eksekusi nyata via jalur agent resmi (bot.run_agent_turn)."""
    import time

    import alfa.bot.telegram_bot as bot_mod

    wall_start = time.monotonic()
    usage_start = _tokens_since_now()
    output = await bot_mod.run_agent_turn(
        user_id=999999,
        chat_id=999999,
        user_prompt=scn["prompt"],
    )
    duration_ms = round((time.monotonic() - wall_start) * 1000, 2)
    tokens = max(0, _tokens_since_now(usage_start[0]) - usage_start[1]) if usage_start else 0
    results = []
    for chk in scn.get("checks", []):
        ok = run_check(chk, output or "")
        results.append({"type": chk.get("type"), "ok": ok})
    passed = bool(results) and all(r["ok"] for r in results)
    out_len = len(output or "")
    return {
        "id": scn["id"],
        "mode": "live",
        "passed": passed,
        "checks": results,
        "output_preview": (output or "(kosong)")[:160],
        "duration_ms": duration_ms,
        "output_chars": out_len,
        "tokens_total": tokens,
        "cost_usd_est": round(tokens / 1_000_000 * _price_per_mtok(), 6),
    }


def _price_per_mtok() -> float:
    try:
        return float(os.getenv("ALFA_EVAL_PRICE_PER_MTOK", "0.10") or 0.10)
    except ValueError:
        return 0.10


def _tokens_since_now(prev: str = ""):
    """Snapshot (ts_utc, total_tokens) pemakaian API; ("", 0) bila gagal."""
    import datetime

    try:
        from alfa.core.db.connection import get_sync_db

        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        base = prev or "2000-01-01 00:00:00"
        with get_sync_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(total_tokens),0) FROM api_token_usage WHERE ts >= ?",
                (base,),
            ).fetchone()
        return (now, int(row[0] or 0))
    except Exception:
        return ("", 0)


async def main_async(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="ALFA Evals Harness")
    ap.add_argument("--live", action="store_true", help="eksekusi prompt nyata via LLM")
    ap.add_argument("--filter", default="", help="substring id skenario")
    ap.add_argument(
        "--output-json",
        default="",
        help="tulis ringkasan hasil ke file JSON (untuk CI/arsip)",
    )
    args = ap.parse_args(argv)

    scenarios = [s for s in load_scenarios() if args.filter in s.get("id", "")]
    print(f"{'MODE':<8} {'ID':<34} {'HASIL'}")
    print("-" * 70)

    failures = 0
    records: list[dict[str, Any]] = []
    for scn in scenarios:
        t0 = time.monotonic()
        if not args.live:
            # Offline: hanya audit routing Tool-RAG + validitas skenario
            route = check_tool_routing(scn)
            ok = bool(scn.get("checks")) and route["ok"]
            detail = route["detail"]
            mode = "offline"
            extra: dict[str, Any] = {
                "duration_ms": round((time.monotonic() - t0) * 1000, 2),
                "tokens_total": 0,
            }
        else:
            try:
                res = await run_live_scenario(scn)
                ok = res["passed"]
                detail = ",".join(
                    f"{c['type']}:{'OK' if c['ok'] else 'X'}" for c in res["checks"]
                )
                extra = {
                    "duration_ms": res.get("duration_ms"),
                    "output_chars": res.get("output_chars"),
                    "tokens_total": res.get("tokens_total"),
                    "cost_usd_est": res.get("cost_usd_est"),
                }
            except Exception as e:
                ok, detail = False, f"error: {e}"
                extra = {"duration_ms": round((time.monotonic() - t0) * 1000, 2)}
            mode = "live"

        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{mode:<8} {scn['id']:<34} {status}  {detail[:60]}")
        records.append({"id": scn["id"], "mode": mode, "ok": ok, "detail": detail, **extra})

    print("-" * 70)
    total = len(scenarios)
    passed_n = total - failures
    print(f"TOTAL: {passed_n}/{total} PASS")
    if args.output_json:
        import datetime

        durs = [r.get("duration_ms") or 0 for r in records]
        toks = [r.get("tokens_total") or 0 for r in records]
        costs = [r.get("cost_usd_est") or 0 for r in records]
        summary = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "live": bool(args.live),
            "filter": args.filter,
            "total": total,
            "passed": passed_n,
            "failed": failures,
            "avg_duration_ms": round(sum(durs) / len(durs), 1) if durs else 0,
            "total_tokens": int(sum(toks)),
            "total_cost_usd_est": round(sum(costs), 6),
            "price_per_mtok_usd": _price_per_mtok(),
            "records": records,
        }
        out_path = args.output_json
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"Ringkasan JSON: {out_path}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(sys.argv[1:])))
