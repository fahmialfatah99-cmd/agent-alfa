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
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

SCENARIOS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios.json")

_REFUSAL_MARKERS = (
    "tidak bisa membantu", "tidak dapat membantu", "tidak akan memberikan",
    "can't help", "cannot help", "won't provide", "not able to help",
    "menolak", "tidak sesuai", "berbahaya", "ilegal",
)


def load_scenarios() -> List[Dict[str, Any]]:
    with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Checks ────────────────────────────────────────────────────────────────
def run_check(check: Dict[str, Any], output: str) -> bool:
    ctype = check.get("type")
    val = check.get("value")
    out = output or ""
    if ctype == "contains_any":
        return any(str(v).lower() in out.lower() for v in
                   (val if isinstance(val, list) else [val]))
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


def check_tool_routing(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Offline: pastikan Tool-RAG menyuntikkan minimal satu tool yang diharapkan."""
    expect = scenario.get("expect_tools_any") or []
    if not expect:
        return {"ok": True, "detail": "no tool expectation"}
    try:
        import tools as t
        from tool_rag import select_relevant_functions
        selected = select_relevant_functions(t.AVAILABLE_TOOLS, scenario["prompt"])
        names = {getattr(f, "__name__", "") for f in selected}
        hit = sorted(set(expect) & names)
        return {"ok": bool(hit), "detail": f"hit={hit or 'TIDAK ADA'} dari {len(selected)} tool tersuntik"}
    except Exception as e:
        return {"ok": False, "detail": f"error: {e}"}


async def run_live_scenario(scn: Dict[str, Any]) -> Dict[str, Any]:
    """Eksekusi nyata via jalur agent resmi (bot.run_agent_turn)."""
    import bot as bot_mod

    output = await bot_mod.run_agent_turn(
        user_id=999999,
        chat_id=999999,
        user_prompt=scn["prompt"],
    )
    results = []
    for chk in scn.get("checks", []):
        ok = run_check(chk, output or "")
        results.append({"type": chk.get("type"), "ok": ok})
    passed = bool(results) and all(r["ok"] for r in results)
    return {
        "id": scn["id"],
        "mode": "live",
        "passed": passed,
        "checks": results,
        "output_preview": (output or "(kosong)")[:160],
    }


async def main_async(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="ALFA Evals Harness")
    ap.add_argument("--live", action="store_true", help="eksekusi prompt nyata via LLM")
    ap.add_argument("--filter", default="", help="substring id skenario")
    args = ap.parse_args(argv)

    scenarios = [s for s in load_scenarios() if args.filter in s.get("id", "")]
    print(f"{'MODE':<8} {'ID':<34} {'HASIL'}")
    print("-" * 70)

    failures = 0
    for scn in scenarios:
        if not args.live:
            # Offline: hanya audit routing Tool-RAG + validitas skenario
            route = check_tool_routing(scn)
            ok = bool(scn.get("checks")) and route["ok"]
            detail = route["detail"]
            mode = "offline"
        else:
            try:
                res = await run_live_scenario(scn)
                ok = res["passed"]
                detail = ",".join(f"{c['type']}:{'OK' if c['ok'] else 'X'}" for c in res["checks"])
            except Exception as e:
                ok, detail = False, f"error: {e}"
            mode = "live"

        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{mode:<8} {scn['id']:<34} {status}  {detail[:60]}")

    print("-" * 70)
    total = len(scenarios)
    passed_n = total - failures
    print(f"TOTAL: {passed_n}/{total} PASS")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(sys.argv[1:])))
