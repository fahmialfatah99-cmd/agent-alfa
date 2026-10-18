"""Metrik runtime proses (observability ringan tanpa dependensi eksternal).

Penghitung dipakai bersama oleh agent loop (`core.brain.tool_exec`) dan
rute dashboard (`/api/metrics`). Desainnya purpose-built supaya tidak
menambah import ruang (deps) baru, tetapi bentuk datanya opentelemetry-
compatible bila kelak ingin ditangkiskan: counter + histogram ringkas
(bucket durasi) per nama tool.

Semua fungsi thread-safe dan anti-throwing — metrik TIDAK boleh
mengganggu jalur eksekusi utama.
"""

import threading
import time
from collections import deque
from typing import Any

_MAX_TURNS_TRACED = 200
_DURATION_BUCKETS_MS = (50, 250, 1000, 5000, 15000)

_lock = threading.Lock()
_tool_calls: dict[str, int] = {}
_tool_errors: dict[str, int] = {}
_tool_durations_ms: dict[str, deque[float]] = {}
_duration_buckets: dict[str, dict[str, int]] = {}
_turns_started = 0
_turns_finished = 0
_turns_failed = 0
_recent_turns: deque[dict[str, Any]] = deque(maxlen=_MAX_TURNS_TRACED)
_started_at = time.time()


def note_tool_call(tool_name: str, ok: bool, duration_ms: float) -> None:
    """Catat satu pemanggilan tool (dipanggil setelah selesai/salah)."""
    try:
        with _lock:
            _tool_calls[tool_name] = _tool_calls.get(tool_name, 0) + 1
            if not ok:
                _tool_errors[tool_name] = _tool_errors.get(tool_name, 0) + 1
            dur = _tool_durations_ms.setdefault(
                tool_name, deque(maxlen=_MAX_TURNS_TRACED)
            )
            dur.append(float(duration_ms))
            buckets = _duration_buckets.setdefault(
                tool_name, {str(b): 0 for b in _DURATION_BUCKETS_MS}
            )
            buckets["+Inf"] = buckets.get("+Inf", 0) + 1
            for b in _DURATION_BUCKETS_MS:
                if duration_ms <= b:
                    buckets[str(b)] += 1
    except Exception:
        pass


def note_tool_missing(tool_name: str) -> None:
    """Tool dipinta model tapi tidak ada di registry (dihitung sebagai error)."""
    try:
        with _lock:
            _tool_errors[f"__missing__:{tool_name}"] = (
                _tool_errors.get(f"__missing__:{tool_name}", 0) + 1
            )
    except Exception:
        pass


def note_turn_started() -> None:
    global _turns_started
    try:
        with _lock:
            _turns_started += 1
            _recent_turns.append(
                {"event": "started", "ts": time.time()}
            )
    except Exception:
        pass


def note_turn_finished(ok: bool) -> None:
    global _turns_finished, _turns_failed
    try:
        with _lock:
            if ok:
                _turns_finished += 1
            else:
                _turns_failed += 1
            _recent_turns.append(
                {"event": "finished", "ok": ok, "ts": time.time()}
            )
    except Exception:
        pass


def snapshot() -> dict[str, Any]:
    """Ambil cuplikan penuh metrik untuk /api/metrics (salinan aman)."""
    try:
        with _lock:
            durations = {
                name: {
                    "count": len(items),
                    "p50_ms": _percentile(list(items), 50),
                    "p95_ms": _percentile(list(items), 95),
                }
                for name, items in _tool_durations_ms.items()
            }
            return {
                "uptime_seconds": round(time.time() - _started_at, 1),
                "turns": {
                    "started": _turns_started,
                    "finished": _turns_finished,
                    "failed": _turns_failed,
                },
                "tools": {
                    name: {
                        "calls": _tool_calls.get(name, 0),
                        "errors": _tool_errors.get(name, 0),
                        **durations.get(name, {}),
                        "buckets": dict(
                            _duration_buckets.get(name, {})
                        ),
                    }
                    for name in sorted(
                        set(_tool_calls) | set(_tool_errors)
                    )
                },
                "recent_turns": list(_recent_turns)[-50:],
            }
    except Exception:
        return {}


def _percentile(sorted_items: list[float], pct: float) -> float | None:
    if not sorted_items:
        return None
    items = sorted(sorted_items)
    idx = min(len(items) - 1, int((pct / 100) * len(items)))
    return round(items[idx], 1)
