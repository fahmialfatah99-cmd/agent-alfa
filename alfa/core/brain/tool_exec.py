"""Agentic tool-argument sanitizing and sandboxed sync execution."""

import json
import logging
import re
import time
from typing import Any

from alfa.core.brain.config import MAX_TOOL_OUTPUT, TOOL_EXEC_TIMEOUT
from alfa.core.brain.tool_schema import _find_tool

logger = logging.getLogger("MainBrain")


def _clean_json_args(raw_json: str) -> dict[str, Any]:
    """Parsing argumen JSON dari model dengan auto-sanitasi agresif bila ada karakter escape/markdown."""
    if not raw_json or not str(raw_json).strip():
        return {}
    if isinstance(raw_json, dict):
        return raw_json
    raw_str = str(raw_json).strip()
    try:
        _d = json.loads(raw_str)
        return _d if isinstance(_d, dict) else {}
    except ValueError:
        pass
    # Strip markdown codeblocks
    if raw_str.startswith("```"):
        lines = raw_str.splitlines()
        if len(lines) >= 2:
            raw_str = "\n".join(
                lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
            ).strip()
    try:
        _d = json.loads(raw_str)
        return _d if isinstance(_d, dict) else {}
    except ValueError:
        pass
    # Hapus trailing comma

    cleaned = re.sub(r",\s*([\]}])", r"\1", raw_str)
    try:
        _d = json.loads(cleaned)
        return _d if isinstance(_d, dict) else {}
    except ValueError:
        pass
    try:
        import ast

        val = ast.literal_eval(raw_str)
        if isinstance(val, dict):
            return val
    except (ValueError, SyntaxError, TypeError):
        pass
    raise ValueError("Argumen tool bukan JSON valid.")


def _execute_tool(name: str, arguments_json: str) -> str:
    fn = _find_tool(name)
    if fn is None:
        try:
            from alfa.core.metrics import note_tool_missing

            note_tool_missing(name)
        except (ImportError, AttributeError, TypeError):
            pass
        return f"[ERROR] Tool '{name}' tidak ditemukan. Silakan periksa daftar tool yang tersedia."
    try:
        args = _clean_json_args(arguments_json)
    except ValueError as err:
        return f"[ERROR format JSON] {err}. Pastikan argumen dalam format JSON valid."

    # Streaming aktivitas tool ke live feed rapat (jika sedang berjalan)
    try:
        from alfa.swarm import engine as _se

        if getattr(_se, "MEETING_RUNNING", False):
            arg_hint = (
                ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:2])
                or "-"
            )
            _se.log_tool_live(f"⚙️ menjalankan `{name}` ({arg_hint}) ...")
    except (ImportError, AttributeError, OSError, TypeError):
        pass

    try:
        from alfa.core import tracing as _tr

        _span = _tr.new_span(f"tool:{name}", tool=name)
    except (ImportError, AttributeError, TypeError):
        _span = None

    def _call():
        try:
            return fn(**args)
        except TypeError as te:
            # Model OpenAI-compatible sering mengirim keyword ekstra (misal: 'reason', 'delay', 'dummy')
            # Saring otomatis agar hanya parameter yang valid yang diteruskan ke fungsi tool.
            try:
                import inspect

                sig = inspect.signature(fn)
                has_var_kw = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if has_var_kw:
                    return fn(**args)
                valid_args = {k: v for k, v in args.items() if k in sig.parameters}
                return fn(**valid_args)
            except (ValueError, TypeError, KeyError):
                return f"[ERROR tool] {te}"
        except Exception as e:
            return f"[ERROR tool] {e}"

    try:
        # Jalankan di thread terpisah agar event loop tetap hidup
        import concurrent.futures

        _t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_call)
            raw = fut.result(timeout=TOOL_EXEC_TIMEOUT)
        _ok = not str(raw).startswith("[ERROR")
        try:
            from alfa.core.metrics import note_tool_call

            note_tool_call(
                name, _ok, (time.perf_counter() - _t0) * 1000
            )
        except (ImportError, AttributeError, TypeError):
            pass
    except Exception as e:
        try:
            from alfa.core.metrics import note_tool_call as _ntc

            _ntc(name, False, (time.perf_counter() - _t0) * 1000)
        except (ImportError, AttributeError, TypeError):
            pass
        if _span:
            _span.finish(status="error", error=str(e))
        return f"[ERROR eksekusi] {e}"

    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False, default=str)

    if _span:
        _status = "error" if raw.startswith("[ERROR") else "success"
        _span.finish(status=_status)

    # Laporkan hasil ke live feed juga
    try:
        from alfa.swarm import engine as _se

        if getattr(_se, "MEETING_RUNNING", False):
            _se.log_tool_live(f"✅ `{name}` selesai -> {raw[:90]}")
    except (ImportError, AttributeError, OSError, TypeError):
        pass

    return str(raw)[:MAX_TOOL_OUTPUT]


# ── Kompaksi konteks agentic loop ────────────────────────────────────────────
