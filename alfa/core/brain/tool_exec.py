"""Agentic tool-argument sanitizing and sandboxed sync execution."""

import concurrent.futures
import inspect
import json
import logging
import os
import re
import threading
import time
from typing import Any

from alfa.core.brain.config import MAX_TOOL_OUTPUT, TOOL_EXEC_TIMEOUT
from alfa.core.brain.tool_schema import _find_tool
from alfa.core.tuning import truncate_middle

logger = logging.getLogger("MainBrain")

# Pool eksekusi tool yang dipakai ulang antar-panggilan.
#
# Sebelumnya tiap tool call membuat `ThreadPoolExecutor` baru di dalam blok
# `with`, dan `__exit__` memanggil `shutdown(wait=True)` — sehingga timeout
# TIDAK membatalkan tool: pemanggil tetap terblokir sampai worker selesai
# (300 detik × 24 iterasi = 2 jam untuk satu turn). Pool modul-level +
# `shutdown(wait=False)` membuat pemanggil kembali tepat waktu.
_EXEC_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_EXEC_POOL_LOCK = threading.Lock()


def _get_exec_pool() -> concurrent.futures.ThreadPoolExecutor:
    """Pool thread eksekusi tool (dibuat sekali, dipakai ulang)."""
    global _EXEC_POOL
    with _EXEC_POOL_LOCK:
        if _EXEC_POOL is None:
            workers = max(8, min(32, int(os.getenv("ALFA_TOOL_POOL_WORKERS", "16"))))
            _EXEC_POOL = concurrent.futures.ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="alfa-tool"
            )
        return _EXEC_POOL


def shutdown_exec_pool(wait: bool = False) -> None:
    """Tutup pool eksekusi tool (dipanggil saat shutdown aplikasi)."""
    global _EXEC_POOL
    with _EXEC_POOL_LOCK:
        pool, _EXEC_POOL = _EXEC_POOL, None
    if pool is not None:
        pool.shutdown(wait=wait, cancel_futures=True)


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
        from alfa.swarm import live_logger as _ll
        from alfa.swarm import workspace_hygiene as _wh

        if _wh.any_session_running():
            arg_hint = (
                ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:2])
                or "-"
            )
            _ll.log_tool_live(f"⚙️ menjalankan `{name}` ({arg_hint}) ...")
    except (ImportError, AttributeError, OSError, TypeError):
        pass

    try:
        from alfa.core import tracing as _tr

        _span = _tr.new_span(f"tool:{name}", tool=name)
    except (ImportError, AttributeError, TypeError):
        _span = None

    def _call():
        # Panggil tool dengan argumen yang sudah tervalidasi terhadap
        # signature-nya. Pemeriksaan dilakukan SEBELUM pemanggilan supaya
        # tool TIDAK pernah dieksekusi dua kali: sebelumnya `except TypeError`
        # tidak bisa membedakan "signature mismatch" dari "TypeError di dalam
        # body tool", sehingga tool dengan efek samping (write file, kirim
        # email) berjalan dua kali.
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            sig = None

        call_args = args
        if sig is not None:
            has_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not has_var_kw:
                try:
                    sig.bind(**args)
                except TypeError:
                    # Buang hanya keyword yang tidak dikenal.
                    call_args = {k: v for k, v in args.items() if k in sig.parameters}
                    try:
                        sig.bind(**call_args)
                    except TypeError as bind_err:
                        return f"[ERROR tool] argumen tidak cocok: {bind_err}"
        try:
            return fn(**call_args)
        except Exception as e:
            hint = ""
            try:
                from alfa.tools.system.constants import generate_self_heal_hint

                h = generate_self_heal_hint(name, str(e))
                if h:
                    hint = f"\n{h}"
            except Exception:
                pass
            return f"[ERROR tool] {e}{hint}"

    _t0 = time.perf_counter()
    try:
        # Jalankan di thread terpisah agar event loop tetap hidup.
        pool = _get_exec_pool()
        fut = pool.submit(_call)
        try:
            raw = fut.result(timeout=TOOL_EXEC_TIMEOUT)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            logger.warning(
                "[ToolTimeout] %s melewati batas %ss — pemanggil dilepas, "
                "worker mungkin masih berjalan.",
                name,
                TOOL_EXEC_TIMEOUT,
            )
            return (
                f"[ERROR timeout] Tool '{name}' melebihi batas waktu eksekusi "
                f"({TOOL_EXEC_TIMEOUT} detik) dan dibatalkan."
            )
        _ok = not str(raw).startswith("[ERROR")
        if _ok:
            try:
                from alfa.core.runtime_ctx import (
                    record_executed_tool,
                    record_turn_artifact,
                )
                record_executed_tool(name)
                if isinstance(raw, dict):
                    for k in ("file_path", "output_path", "zip_path", "target_path", "image_path", "pdf_path"):
                        v = raw.get(k)
                        if isinstance(v, str) and os.path.exists(v):
                            record_turn_artifact(v)
            except Exception:
                pass
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

    if raw.startswith("[ERROR") and "[SELF_HEAL_HINT]" not in raw:
        try:
            from alfa.tools.system.constants import generate_self_heal_hint

            h = generate_self_heal_hint(name, raw)
            if h:
                raw = f"{raw}\n{h}"
        except Exception:
            pass

    if _span:
        _status = "error" if raw.startswith("[ERROR") else "success"
        _span.finish(status=_status)

    # Laporkan hasil ke live feed juga
    try:
        from alfa.swarm import live_logger as _ll
        from alfa.swarm import workspace_hygiene as _wh

        if _wh.any_session_running():
            _ll.log_tool_live(f"✅ `{name}` selesai -> {raw[:90]}")
    except (ImportError, AttributeError, OSError, TypeError):
        pass

    return truncate_middle(str(raw), MAX_TOOL_OUTPUT)


# ── Kompaksi konteks agentic loop ────────────────────────────────────────────
