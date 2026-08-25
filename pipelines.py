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

Semantik:
- Step berjalan paralel per gelombang berdasarkan `depends_on` (opsional).
- Output step tersimpan sebagai variabel dengan nama id step-nya.
- Tipe step: "prompt" (otak utama), "tool" (eksekusi tool registry),
  "set" (set variabel literal), "template" (render teks ke variabel).

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
os.makedirs(PIPELINE_DIR, exist_ok=True)

try:
    MAX_STEPS = int(os.getenv("ALFA_PIPELINE_MAX_STEPS", "30"))
except ValueError:
    MAX_STEPS = 30

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def list_pipelines() -> List[Dict[str, Any]]:
    out = []
    for fn in sorted(os.listdir(PIPELINE_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(PIPELINE_DIR, fn), "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append({
                "id": data.get("id") or fn[:-5],
                "name": data.get("name", fn[:-5]),
                "description": data.get("description", ""),
                "steps": len(data.get("steps", [])),
            })
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


def _render(template: str, variables: Dict[str, Any], max_depth: int = 4) -> str:
    """Interpolasi {{var}} berulang (hasil tool bisa mengandung variabel lain)."""
    text = str(template)
    for _ in range(max_depth):
        def _sub(m):
            return str(variables.get(m.group(1), ""))
        new = _VAR_RE.sub(_sub, text)
        if new == text:
            break
        text = new
    return text


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


async def _run_step(step: Dict[str, Any], variables: Dict[str, Any]) -> Any:
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
            system_instruction=system or "Kamu adalah agent eksekutor langkah pipeline. Jawab padat dan langsung.",
            user_text=text,
            tools_schema=[],  # chat polos: tanpa tools supaya deterministik
            context=f"pipeline:{step.get('id', '')}",
        )
        return raw

    if stype == "tool":
        import main_brain as mb
        name = step.get("tool", "")
        args_json = json.dumps(
            {k: _render(v, variables) for k, v in (step.get("args") or {}).items()}
        )
        return await asyncio.to_thread(mb._execute_tool, name, args_json)

    raise ValueError(f"Tipe step '{stype}' tidak dikenal.")


async def run_pipeline(pid: str, overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
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
                *[_run_step(s, variables) for s in wave],
                return_exceptions=True,
            )
            for s, res in zip(wave, results):
                if isinstance(res, Exception):
                    step_outputs[s["id"]] = f"[ERROR] {res}"
                    trace.append({"step": s["id"], "status": "error", "detail": str(res)[:300]})
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

    return {
        "pipeline": pid,
        "status": status,
        "duration_ms": int((time.time() - started) * 1000),
        "error": error,
        "trace": trace,
        "outputs": {k: str(v)[:2000] for k, v in step_outputs.items()},
    }


# ── Contoh pipeline bawaan (dibuat sekali saat impor pertama) ──
_DEFAULT_PIPELINES = [
    {
        "id": "riset_dan_ringkas",
        "name": "Riset lalu Ringkas",
        "description": "Cari topik di web -> rangkum 3 poin -> simpan ke sandbox.",
        "vars": {"topik": "AI Indonesia", "out_dir": "/dev/shm/alfa_sandbox/pipeline_out"},
        "steps": [
            {"id": "cari", "type": "tool", "tool": "web_search",
             "args": {"query": "berita {{topik}} terbaru"}},
            {"id": "rangkum", "type": "prompt",
             "text": "Ringkas hasil pencarian ini menjadi 3 poin utama:\n{{cari}}",
             "depends_on": ["cari"]},
            {"id": "simpan", "type": "tool", "tool": "write_local_file",
             "args": {"file_path": "{{out_dir}}/ringkasan_{{topik}}.md",
                      "content": "# Ringkasan {{topik}}\n\n{{rangkum}}"},
             "depends_on": ["rangkum"]},
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
