"""
PIPELINE ENGINE — workflow DAG berbasis JSON, fondasi Visual Canvas ala Dify.

Format file pipeline (storage/pipelines/<id>.json):
{
  "id": "riset_lalu_rangkum",
  "name": "Riset lalu Rangkum",
  "description": "...",
  "vars": {"topik": "AI"},
  "steps": [
    {"id": "riset",   "type": "tool", "tool": "web_search",
     "args": {"query": "berita {{topik}} terbaru"}},
    {"id": "ringkas", "type": "prompt",
     "text": "Rangkum hasil riset ini dalam 3 poin:\\n{{riset}}"},
    {"id": "simpan",  "type": "tool", "tool": "write_local_file",
     "args": {"file_path": "{{out_dir}}/ringkasan.md", "content": "{{ringkas}}"}}
  ]
}

Semantik (gaya n8n-mini):
- Step berjalan paralel per gelombang berdasarkan `depends_on` (opsional).
- Output step tersimpan sebagai variabel dengan nama id step-nya.
- Tipe step: "prompt" (otak utama), "tool" (registry), "set", "template",
  "http" (panggil API apa pun), "foreach" (ulangi prompt per item daftar).
- Kondisi: step punya "if": {"left": "{{var}}", "op": "contains|eq|neq|empty|
  not_empty|gt|lt|regex", "right": "..."} -> dilewati bila tidak terpenuhi.
- Trigger: {"type":"interval","minutes":30,"enabled":true} di root pipeline ->
  scheduler dashboard menjalankan otomatis; webhook via /api/pipelines/<id>/webhook.
- Riwayat eksekusi tersimpan di storage/runs/<id>.jsonl.

Env: ALFA_PIPELINE_MAX_STEPS=30 (pengaman loop tak hingga).
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List

logger = logging.getLogger("Pipeline")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(BASE_DIR, "storage", "pipelines")
RUNS_DIR = os.path.join(BASE_DIR, "storage", "runs")
os.makedirs(PIPELINE_DIR, exist_ok=True)
os.makedirs(RUNS_DIR, exist_ok=True)

try:
    MAX_STEPS = int(os.getenv("ALFA_PIPELINE_MAX_STEPS", "30"))
except ValueError:
    MAX_STEPS = 30

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _get_path(obj: Any, dotted: str) -> Any:
    """Akses path bertitik: 'data.items.0.nama' (n8n-style expression ringan)."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _render(template: str, variables: Dict[str, Any], max_depth: int = 4) -> str:
    """Interpolasi {{var}} & {{var.path.sub}} berulang."""
    text = str(template)
    for _ in range(max_depth):

        def _sub(m):
            val = _get_path(variables, m.group(1))
            return (
                ""
                if val is None
                else (
                    val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
                )
            )

        new = _VAR_RE.sub(_sub, text)
        if new == text:
            break
        text = new
    return text


def _eval_condition(cond: Dict[str, Any], variables: Dict[str, Any]) -> bool:
    """Evaluasi kondisi gaya n8n-mini. cond: {left, op, right}."""
    left = _render(str(cond.get("left", "")), variables).strip()
    op = (cond.get("op") or "not_empty").strip().lower()
    right = _render(str(cond.get("right", "")), variables).strip()
    if op == "contains":
        return right.lower() in left.lower()
    if op in ("not_contains", "tidak_mengandung"):
        return right.lower() not in left.lower()
    if op in ("eq", "=="):
        return left == right
    if op in ("neq", "!="):
        return left != right
    if op == "empty":
        return not left
    if op in ("not_empty",):
        return bool(left)
    if op in ("gt", ">", "lt", "<"):
        try:
            lnum, rnum = float(left), float(right)
        except ValueError:
            return False
        return lnum > rnum if op in ("gt", ">") else lnum < rnum
    if op == "regex":
        try:
            return re.search(right, left) is not None
        except re.error:
            return False
    return False


def list_pipelines() -> List[Dict[str, Any]]:
    out = []
    for fn in sorted(os.listdir(PIPELINE_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(PIPELINE_DIR, fn), "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append(
                {
                    "id": data.get("id") or fn[:-5],
                    "name": data.get("name", fn[:-5]),
                    "description": data.get("description", ""),
                    "steps": len(data.get("steps", [])),
                }
            )
        except Exception as e:
            logger.warning(f"Pipeline rusak dilewati {fn}: {e}")
    return out


def load_pipeline(pid: str) -> Dict[str, Any]:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "", pid)
    path = os.path.join(PIPELINE_DIR, f"{safe}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pipeline(data: Dict[str, Any]) -> str:
    pid = re.sub(r"[^a-zA-Z0-9_\-]", "", str(data.get("id") or ""))
    if not pid:
        raise ValueError("Pipeline wajib punya 'id'.")
    data["id"] = pid
    path = os.path.join(PIPELINE_DIR, f"{pid}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _topological_waves(steps: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Kelompokkan steps jadi gelombang dependensi (Kahn, stabil by order)."""
    ids = [s.get("id") for s in steps]
    if len(set(ids)) != len(ids):
        raise ValueError("Step 'id' harus unik.")
    deps = {
        s["id"]: [d for d in (s.get("depends_on") or []) if d in set(ids)]
        for s in steps
    }
    done: set = set()
    waves: List[List[Dict[str, Any]]] = []
    remaining = list(steps)
    guard = 0
    while remaining and guard <= MAX_STEPS:
        guard += 1
        ready = [s for s in remaining if all(d in done for d in deps[s["id"]])]
        if not ready:
            raise ValueError("Terdeteksi siklus pada depends_on.")
        waves.append(ready)
        done.update(s["id"] for s in ready)
        remaining = [s for s in remaining if s["id"] not in done]
    return waves


async def _run_step(
    step: Dict[str, Any], variables: Dict[str, Any], sid: str = ""
) -> Any:
    stype = (step.get("type") or "prompt").lower()

    if stype == "set":
        return _render(step.get("value", ""), variables)

    if stype == "template":
        return _render(step.get("text", ""), variables)

    if stype == "prompt":
        import main_brain as mb

        brain = mb.get_main_brain()
        text = _render(step.get("text", ""), variables)
        system = _render(step.get("system", ""), variables) or None
        raw = await mb.run_openai_agentic_turn(
            provider=brain["provider"],
            base_url=brain["base_url"],
            api_key=brain["api_key"],
            model=brain["model"],
            system_instruction=system
            or "Kamu adalah agent eksekutor langkah pipeline. Jawab padat dan langsung.",
            user_text=text,
            tools_schema=[],  # chat polos: tanpa tools supaya deterministik
            context=f"pipeline:{sid or step.get('id', '')}",
        )
        return raw

    if stype == "http":
        import httpx

        method = (step.get("method") or "GET").upper()
        url = _render(step.get("url", ""), variables)
        headers = {
            k: _render(v, variables) for k, v in (step.get("headers") or {}).items()
        }
        body = step.get("body")
        timeout = min(60, max(3, int(step.get("timeout", 20))))
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=True
        ) as client:
            res = await client.request(
                method,
                url,
                headers=headers,
                content=_render(str(body), variables) if body is not None else None,
            )
        text_out = res.text[:20000]
        try:
            parsed = json.loads(text_out)
            if isinstance(parsed, (dict, list)):
                text_out = json.dumps(parsed, ensure_ascii=False)[:20000]
        except Exception:
            pass
        if sid:
            variables[f"{sid}_status"] = str(res.status_code)
        return text_out

    if stype == "foreach":
        items_raw = _render(step.get("over", ""), variables)
        item_var = step.get("item_var") or "item"
        try:
            items = json.loads(items_raw)
            if not isinstance(items, list):
                raise ValueError
        except Exception:
            items = [s.strip() for s in re.split(r"[\n,;]+", items_raw) if s.strip()]
        inner_text_tmpl = step.get("text") or "{{item}}"
        collected = []
        for it in items[:50]:  # pengaman 50 iterasi
            sub_vars = dict(variables)
            sub_vars[item_var] = (
                it if isinstance(it, str) else json.dumps(it, ensure_ascii=False)
            )
            sub_vars["item_json"] = (
                json.dumps(it, ensure_ascii=False) if not isinstance(it, str) else it
            )
            out = await _run_step(
                {"type": step.get("inner_type", "prompt"), "text": inner_text_tmpl},
                sub_vars,
            )
            collected.append(f"[{sub_vars[item_var][:80]}] {out}")
            if len(collected) >= 50:
                break
        return "\n\n".join(collected)

    if stype == "tool":
        import main_brain as mb

        name = step.get("tool", "")
        args_json = json.dumps(
            {k: _render(v, variables) for k, v in (step.get("args") or {}).items()}
        )
        return await asyncio.to_thread(mb._execute_tool, name, args_json)

    raise ValueError(f"Tipe step '{stype}' tidak dikenal.")


async def run_pipeline(
    pid: str, overrides: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Eksekusi pipeline penuh; return ringkasan run utk UI/API."""
    data = load_pipeline(pid)
    started = time.time()
    variables: Dict[str, Any] = dict(data.get("vars") or {})
    if overrides:
        variables.update(overrides)

    steps = data.get("steps", [])
    if len(steps) > MAX_STEPS:
        return {"status": "error", "message": f"Pipelines dibatasi {MAX_STEPS} step."}

    step_outputs: Dict[str, Any] = {}
    trace: List[Dict[str, Any]] = []
    status = "success"
    error = None

    try:
        for wave in _topological_waves(steps):
            results = await asyncio.gather(
                *[_run_step(s, variables, sid=s["id"]) for s in wave],
                return_exceptions=True,
            )
            for s, res in zip(wave, results):
                # Kondisi n8n-style: skip bila "if" tidak terpenuhi
                cond = s.get("if")
                if isinstance(res, Exception) and cond:
                    pass  # biarkan error tetap dilaporkan
                elif cond and isinstance(cond, dict):
                    try:
                        if not _eval_condition(cond, variables):
                            step_outputs[s["id"]] = (
                                "(dilewati: kondisi tidak terpenuhi)"
                            )
                            trace.append({"step": s["id"], "status": "skipped"})
                            continue
                    except Exception as ce:
                        logger.warning(
                            f"[Pipeline] kondisi '{s['id']}' gagal dievaluasi: {ce}"
                        )
                if isinstance(res, Exception):
                    step_outputs[s["id"]] = f"[ERROR] {res}"
                    trace.append(
                        {"step": s["id"], "status": "error", "detail": str(res)[:300]}
                    )
                    status = "failed"
                    error = f"Step '{s['id']}': {res}"
                    break
                step_outputs[s["id"]] = res
                variables[s["id"]] = res
                trace.append({"step": s["id"], "status": "ok"})
            if status == "failed":
                break
    except Exception as e:
        status, error = "failed", str(e)

    summary = {
        "pipeline": pid,
        "status": status,
        "duration_ms": int((time.time() - started) * 1000),
        "error": error,
        "trace": trace,
        "outputs": {k: str(v)[:2000] for k, v in step_outputs.items()},
    }
    _record_run(pid, summary)
    return summary


# ── Riwayat eksekusi (execution history ala n8n) ─────────────────────────
def _runs_file(pid: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "", pid)
    return os.path.join(RUNS_DIR, f"{safe}.jsonl")


def _record_run(pid: str, summary: Dict[str, Any]) -> None:
    try:
        with open(_runs_file(pid), "a", encoding="utf-8") as f:
            f.write(
                json.dumps({**summary, "ts": time.time()}, ensure_ascii=False) + "\n"
            )
        # cap 100 baris terakhir
        path = _runs_file(pid)
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 100:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-100:])
    except Exception as e:
        logger.debug(f"record_run gagal: {e}")


def list_runs(pid: str, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        with open(_runs_file(pid), "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines[-max(1, limit) :]:
        try:
            d = json.loads(ln)
            out.append(
                {
                    "ts": d.get("ts"),
                    "status": d.get("status"),
                    "duration_ms": d.get("duration_ms"),
                    "error": d.get("error"),
                    "steps": len(d.get("trace", [])),
                }
            )
        except Exception:
            continue
    return list(reversed(out))


# ── Trigger scheduler (interval otomatis) ────────────────────────────────
_STATE_FILE = os.path.join(RUNS_DIR, "_trigger_state.json")


def _load_trigger_state() -> Dict[str, float]:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_trigger_state(st: Dict[str, float]) -> None:
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass


async def scheduler_tick() -> int:
    """Cek semua pipeline ber-trigger interval; jalankan yang jatuh tempo.
    Return jumlah pipeline yang dieksekusi. Dipanggil tiap 60 detik."""
    ran = 0
    state = _load_trigger_state()
    for meta in list_pipelines():
        pid = meta["id"]
        try:
            data = load_pipeline(pid)
        except Exception:
            continue
        trig = data.get("trigger") or {}
        if trig.get("type") != "interval" or trig.get("enabled") is False:
            continue
        try:
            minutes = max(5, int(trig.get("minutes", 30)))
        except ValueError:
            continue
        now = time.time()
        last = float(state.get(pid, 0))
        if now - last < minutes * 60:
            continue
        state[pid] = now
        _save_trigger_state(state)
        logger.info(f"[PipelineScheduler] menjalankan '{pid}' (interval {minutes}m)")
        asyncio.get_running_loop().create_task(run_pipeline(pid))
        ran += 1
    return ran


# ── Contoh pipeline bawaan (dibuat sekali saat impor pertama) ──
_DEFAULT_PIPELINES = [
    {
        "id": "riset_dan_ringkas",
        "name": "Riset lalu Ringkas",
        "description": "Cari topik di web -> rangkum 3 poin -> simpan ke sandbox.",
        "vars": {
            "topik": "AI Indonesia",
            "out_dir": "/dev/shm/alfa_sandbox/pipeline_out",
        },
        "steps": [
            {
                "id": "cari",
                "type": "tool",
                "tool": "web_search",
                "args": {"query": "berita {{topik}} terbaru"},
            },
            {
                "id": "rangkum",
                "type": "prompt",
                "text": "Ringkas hasil pencarian ini menjadi 3 poin utama:\n{{cari}}",
                "depends_on": ["cari"],
            },
            {
                "id": "simpan",
                "type": "tool",
                "tool": "write_local_file",
                "args": {
                    "file_path": "{{out_dir}}/ringkasan_{{topik}}.md",
                    "content": "# Ringkasan {{topik}}\n\n{{rangkum}}",
                },
                "depends_on": ["rangkum"],
            },
        ],
    },
]

for _dp in _DEFAULT_PIPELINES:
    _p = os.path.join(PIPELINE_DIR, f"{_dp['id']}.json")
    if not os.path.exists(_p):
        try:
            save_pipeline(_dp)
        except Exception:
            pass
