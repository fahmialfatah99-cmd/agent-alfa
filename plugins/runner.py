"""Pekerja sandbox plugin — eksekusi plugin dinamis di subprocess terisolasi.

Protokol: payload JSON satu baris di stdin, hasil JSON satu baris di fd 1.

{
  "file":     "<abs path ke plugins/<name>.py>",
  "module":   "plugins.<name>",
  "function": "<tool_name>",
  "kwargs":   {...},
  "timeout":  120
}

→ {"ok": true, "result": <hasil serialisasi JSON>} | {"ok": false, "error": "..."}

Isolasi (Linux): resource limits (CPU/mem), stdout plugin dialihkan ke stderr
agar saluran hasil tetap bersih. Batas mem default 2048 MB via
``ALFA_PLUGIN_MAX_MEM_MB``. Mulai keluar process (exit) langsung dengan
``os._exit`` agar teardown thread-latar modul plugin tidak menggantung.
"""

import contextlib
import importlib.util
import json
import os
import resource
import sys

_BACKUP_FD = os.dup(1)


def _apply_limits() -> None:
    mem_mb = int(os.getenv("ALFA_PLUGIN_MAX_MEM_MB", "2048"))
    # Timeout dibaca dari payload (3s dari parent), margin CPU untuk import lib
    try:
        cpu_limit = int(os.getenv("ALFA_PLUGIN_CPU_SECONDS", "0")) or None
    except ValueError:
        cpu_limit = None

    def _lim(d: dict) -> None:
        try:
            resource.setrlimit(resource.RLIMIT_AS, d)
        except (ValueError, OSError):
            pass

    _lim((mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
    if cpu_limit:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 5))
        except (ValueError, OSError):
            pass


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"spec tidak valid untuk {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _emit(payload: dict) -> None:
    data = (json.dumps(payload, ensure_ascii=False, default=str) + "\n").encode(
        "utf-8", errors="replace"
    )
    os.write(_BACKUP_FD, data)


def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw.strip() or "{}")
    except json.JSONDecodeError as e:
        _emit({"ok": False, "error": f"payload tidak valid: {e}"})
        os._exit(2)

    path = req.get("file") or ""
    module_name = req.get("module") or "plugins.dynamic"
    function = req.get("function") or ""
    kwargs = req.get("kwargs") or {}
    timeout = int(req.get("timeout") or 120)
    os.environ["ALFA_PLUGIN_CPU_SECONDS"] = str(max(timeout + 10, 30))

    _apply_limits()

    # Jalur stdout modul plugin → stderr; fd 1 asli disimpan untuk hasil
    with contextlib.redirect_stdout(sys.stderr):
        try:
            if not path or not os.path.isfile(path):
                raise FileNotFoundError(f"file plugin tidak ada: {path}")
            module = _load_module(path, module_name)
            fn = getattr(module, function, None)
            if not callable(fn):
                raise AttributeError(f"fungsi '{function}' tidak ada di modul")
            result = fn(**kwargs)
        except BaseException as e:  # noqa: BLE001 — sandbox harus menangkap apa pun
            _emit({"ok": False, "error": f"{type(e).__name__}: {e}"})
            os._exit(1)

    try:
        _emit({"ok": True, "result": result})
        os._exit(0)
    except Exception as e:
        _emit({"ok": False, "error": f"hasil tidak serializable: {e}"})
        os._exit(3)


if __name__ == "__main__":
    main()
