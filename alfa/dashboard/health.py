"""Readiness probe dan snapshot operasional dashboard (aditif).

``/healthz`` tetap menjadi liveness check yang sudah dipakai Docker/systemd.
``/readyz`` menambahkan pemeriksaan dependensi nyata (DB, disk, antrean) agar
orchestrator tidak mengirim trafik ke proses yang belum siap. Semua error
dikembalikan sebagai status terstruktur, tidak pernah melempar ke pemanggil.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Any

from alfa import __version__


def _check_database() -> dict[str, Any]:
    """SELECT 1 + hitung tabel; False bila pool/DB tidak sehat."""
    try:
        from alfa.core import database as db

        pool = db.get_connection_pool()
        conn = pool.acquire()
        try:
            conn.execute("SELECT 1").fetchone()
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
            tables = int(row[0]) if row else 0
        finally:
            pool.release(conn)
    except (sqlite3.Error, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    else:
        return {"ok": True, "tables": tables}


def _check_disk() -> dict[str, Any]:
    """Pastikan direktori DB ada dan bisa ditulis (bukan hanya bebas ruang)."""
    try:
        from alfa.core import database as db

        db_path = os.path.abspath(str(db.DB_PATH))
        directory = os.path.dirname(db_path) or "."
        usage = shutil.disk_usage(directory)
        writable = os.access(directory, os.W_OK)
    except (OSError, ValueError, TypeError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    else:
        return {
            "ok": writable,
            "free_mb": round(usage.free / (1024 * 1024), 2),
            "writable": writable,
        }


def _check_queue() -> dict[str, Any]:
    """Statistik antrean durable; kegagalan antrean tidak menggagalkan readiness."""
    try:
        from alfa.swarm.queue import queue_stats

        stats = queue_stats()
    except (sqlite3.Error, OSError, RuntimeError, ValueError, TypeError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    else:
        return {"ok": True, **stats}


def _active_turns() -> int:
    try:
        from alfa.dashboard.routes.chat import active_turn_count

        return int(active_turn_count())
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return 0


def readiness_snapshot() -> dict[str, Any]:
    """Snapshot siap-trafik: DB + disk adalah gate, antrean hanya informasi."""
    database = _check_database()
    disk = _check_disk()
    queue = _check_queue()
    ready = bool(database.get("ok")) and bool(disk.get("ok"))
    return {
        "status": "ready" if ready else "not_ready",
        "service": "alfa-sovereign-ai",
        "version": __version__,
        "checks": {
            "database": database,
            "disk": disk,
            "queue": queue,
        },
        "active_chat_turns": _active_turns(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def operational_snapshot() -> dict[str, Any]:
    """Metrik ringan untuk /api/metrics (ukuran DB, antrean, turn aktif)."""
    try:
        from alfa.core import database as db

        db_path = os.path.abspath(str(db.DB_PATH))
    except (ImportError, AttributeError, TypeError, ValueError):
        db_path = ""

    def _size_mb(path: str) -> float:
        try:
            return round(os.path.getsize(path) / (1024 * 1024), 2)
        except OSError:
            return 0.0

    queue = _check_queue()
    return {
        "db_size_mb": _size_mb(db_path),
        "db_wal_size_mb": _size_mb(f"{db_path}-wal"),
        "queue": queue,
        "active_chat_turns": _active_turns(),
    }


__all__ = ["operational_snapshot", "readiness_snapshot"]
