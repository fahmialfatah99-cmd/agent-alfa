"""Durable Task Runtime — checkpoint turn agar statusnya tidak hilang.

Tabel SQLite aditif ``durable_tasks`` menyimpan status setiap giliran agent
(prompt, chat, langkah tool terakhir, error, percobaan) sehingga:
- giliran yang terputus (restart/cancel/crash) bisa diidentifikasi,
- pengguna bisa melihat daftar tugas dan melanjutkan yang terputus,
- observability punya jejak durasi/attempt tanpa mengubah kontrak API lama.

Mode diatur ``ALFA_DURABLE_TASKS``:

- ``off``    — tidak mencatat apa pun.
- ``shadow`` — mencatat status/checkpoint, TIDAK mengizinkan resume (default).
- ``on``     — mencatat status/checkpoint dan mengizinkan resume eksplisit.

Semua fungsi fail-soft: kegagalan pencatatan tidak pernah mengganggu giliran.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from alfa.core.config import env_int, env_str
from alfa.core.db.connection import get_sync_db
from alfa.core.runtime_ctx import redact_sensitive

logger = logging.getLogger("DB.DurableTasks")

_TABLE = "durable_tasks"

#: Status yang boleh dilanjutkan secara eksplisit.
_RESUMABLE = frozenset({"interrupted", "failed", "paused"})

#: Panjang prompt/error yang disimpan agar baris tidak membengkak.
_PROMPT_LIMIT = 8_000
_ERROR_LIMIT = 500

#: Retensi default: 30 hari / 5.000 baris. 0 = nonaktif.
_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_MAX_ROWS = 5_000
_PRUNE_EVERY_WRITES = 100

_write_count = 0
_write_lock = threading.Lock()

_SQL_CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS {t} (
            task_id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL DEFAULT '',
            user_id INTEGER NOT NULL DEFAULT 0,
            chat_id INTEGER NOT NULL DEFAULT 0,
            kind TEXT NOT NULL DEFAULT 'turn',
            status TEXT NOT NULL DEFAULT 'running',
            prompt TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            step_index INTEGER NOT NULL DEFAULT 0,
            steps_total INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            payload TEXT NOT NULL DEFAULT '{{}}',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT ''
        )
        """
_SQL_CREATE_STATUS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_durable_status "
    "ON {t} (status, updated_at DESC)"
)
_SQL_CREATE_CHAT_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_durable_chat "
    "ON {t} (chat_id, created_at DESC)"
)
_SQL_CREATE_TURN_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_durable_turn ON {t} (turn_id)"
)
_SQL_INSERT = """
            INSERT OR IGNORE INTO {t}
                (task_id, turn_id, user_id, chat_id, kind, status, prompt,
                 model, step_index, steps_total, attempts, max_attempts,
                 payload, error, created_at, updated_at, finished_at)
            VALUES (?, ?, ?, ?, ?, 'running', ?, ?, 0, ?, 0, ?, ?, '', ?, ?, '')
            """
_SQL_GET = "SELECT * FROM {t} WHERE task_id = ?"
_SQL_LIST_ALL = "SELECT * FROM {t} ORDER BY created_at DESC LIMIT ?"
_SQL_LIST_STATUS = (
    "SELECT * FROM {t} WHERE status = ? ORDER BY created_at DESC LIMIT ?"
)
_SQL_LIST_USER = (
    "SELECT * FROM {t} WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
)
_SQL_LIST_USER_STATUS = (
    "SELECT * FROM {t} WHERE user_id = ? AND status = ? "
    "ORDER BY created_at DESC LIMIT ?"
)
_SQL_LIST_CHAT = (
    "SELECT * FROM {t} WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?"
)
_SQL_LIST_RESUMABLE = (
    "SELECT * FROM {t} WHERE status IN ('interrupted', 'failed', 'paused') "
    "AND attempts < max_attempts AND user_id = ? "
    "ORDER BY updated_at DESC LIMIT ?"
)
_SQL_LIST_RESUMABLE_ANY = (
    "SELECT * FROM {t} WHERE status IN ('interrupted', 'failed', 'paused') "
    "AND attempts < max_attempts ORDER BY updated_at DESC LIMIT ?"
)
_SQL_RECOVER_STALE = (
    "UPDATE {t} SET status = 'interrupted', updated_at = ?, "
    "finished_at = ?, error = CASE WHEN error = '' THEN ? ELSE error END "
    "WHERE status = 'running' AND updated_at < ?"
)
_SQL_COUNT = "SELECT COUNT(*) AS n FROM {t}"
_SQL_DELETE_OLD = "DELETE FROM {t} WHERE created_at < ?"
_SQL_DELETE_EXCESS = (
    "DELETE FROM {t} WHERE task_id NOT IN "
    "(SELECT task_id FROM {t} ORDER BY created_at DESC LIMIT ?)"
)

#: Error realistis untuk operasi durable task.
_DURABLE_ERR = (
    sqlite3.Error,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    RuntimeError,
    UnicodeError,
    json.JSONDecodeError,
)


def _sql(template: str) -> str:
    """Ganti penampung {t} dengan nama tabel (konstanta modul, literal)."""
    return template.replace("{t}", _TABLE)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_sql(_SQL_CREATE_TABLE))
    conn.execute(_sql(_SQL_CREATE_STATUS_INDEX))
    conn.execute(_sql(_SQL_CREATE_CHAT_INDEX))
    conn.execute(_sql(_SQL_CREATE_TURN_INDEX))


def durable_mode() -> str:
    """Mode runtime aktif: ``off`` | ``shadow`` | ``on``."""
    raw = env_str("ALFA_DURABLE_TASKS", "shadow").strip().lower()
    if raw in {"1", "true", "yes"}:
        return "on"
    if raw in {"0", "false", "no"}:
        return "off"
    if raw in {"off", "shadow", "on"}:
        return raw
    return "shadow"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        payload = json.loads(str(data.get("payload") or "{}"))
        data["payload"] = payload if isinstance(payload, dict) else {}
    except (ValueError, TypeError, json.JSONDecodeError):
        data["payload"] = {}
    return data


def _retention_settings() -> tuple[int, int]:
    return (
        env_int(
            "ALFA_DURABLE_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS, minimum=0
        ),
        env_int("ALFA_DURABLE_MAX_ROWS", _DEFAULT_MAX_ROWS, minimum=0),
    )


def _prune_with_conn(
    conn: sqlite3.Connection, days: int, max_rows: int
) -> dict[str, int]:
    deleted_old = 0
    deleted_excess = 0
    if days > 0:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds")
        deleted_old = max(
            0, conn.execute(_sql(_SQL_DELETE_OLD), (cutoff,)).rowcount or 0
        )
    if max_rows > 0:
        deleted_excess = max(
            0,
            conn.execute(_sql(_SQL_DELETE_EXCESS), (max_rows,)).rowcount or 0,
        )
    return {"deleted_old": deleted_old, "deleted_excess": deleted_excess}


def _maybe_prune(conn: sqlite3.Connection) -> None:
    global _write_count
    try:
        with _write_lock:
            _write_count += 1
            due = _write_count % _PRUNE_EVERY_WRITES == 0
        if not due:
            return
        days, max_rows = _retention_settings()
        if days <= 0 and max_rows <= 0:
            return
        _prune_with_conn(conn, days, max_rows)
    except _DURABLE_ERR as exc:
        logger.debug("Auto-prune durable task gagal: %s", exc)


def create_task_sync(
    task_id: str,
    *,
    turn_id: str = "",
    user_id: int = 0,
    chat_id: int = 0,
    kind: str = "turn",
    prompt: str = "",
    model: str = "",
    steps_total: int = 0,
    max_attempts: int = 2,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Buat/registrasikan satu tugas durabel. Fail-soft (None saat gagal)."""
    if durable_mode() == "off" or not str(task_id or "").strip():
        return None
    now = _now()
    task_id = str(task_id).strip()
    safe_prompt = str(prompt or "")[:_PROMPT_LIMIT]
    payload_json = json.dumps(payload or {}, ensure_ascii=False, default=str)
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.execute(
                _sql(_SQL_INSERT),
                (
                    task_id,
                    str(turn_id or task_id),
                    int(user_id or 0),
                    int(chat_id or 0),
                    str(kind or "turn"),
                    safe_prompt,
                    str(model or ""),
                    max(0, int(steps_total or 0)),
                    max(1, int(max_attempts or 1)),
                    payload_json,
                    now,
                    now,
                ),
            )
            _maybe_prune(conn)
            conn.commit()
        return get_task_sync(task_id)
    except _DURABLE_ERR as exc:
        logger.debug("Create durable task '%s' gagal: %s", task_id, exc)
        return None


def get_task_sync(task_id: str) -> dict[str, Any] | None:
    """Ambil satu tugas berdasarkan ``task_id``."""
    if not str(task_id or "").strip():
        return None
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                _sql(_SQL_GET), (str(task_id).strip(),)
            ).fetchone()
            return _row_to_dict(row) if row else None
    except _DURABLE_ERR as exc:
        logger.debug("Get durable task '%s' gagal: %s", task_id, exc)
        return None


def checkpoint_task_sync(
    task_id: str,
    *,
    step_index: int | None = None,
    status: str = "",
    payload: dict[str, Any] | None = None,
) -> bool:
    """Simpan progres langkah/tool. Payload lama di-merge, bukan ditimpa."""
    if durable_mode() == "off" or not str(task_id or "").strip():
        return False
    task_id = str(task_id).strip()
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            row = conn.execute(_sql(_SQL_GET), (task_id,)).fetchone()
            if row is None:
                return False
            current = _row_to_dict(row)
            merged = dict(current.get("payload") or {})
            if payload:
                merged.update(payload)
            conn.execute(
                "UPDATE durable_tasks SET updated_at = ?, payload = ?, "
                "step_index = COALESCE(?, step_index), "
                "status = COALESCE(?, status) WHERE task_id = ?",
                (
                    _now(),
                    json.dumps(merged, ensure_ascii=False, default=str),
                    None if step_index is None else max(0, int(step_index)),
                    str(status) if status else None,
                    task_id,
                ),
            )
            conn.commit()
    except _DURABLE_ERR as exc:
        logger.debug("Checkpoint durable task '%s' gagal: %s", task_id, exc)
        return False
    else:
        return True


def finish_task_sync(
    task_id: str,
    *,
    status: str = "completed",
    error: str = "",
    payload: dict[str, Any] | None = None,
) -> bool:
    """Tutup tugas dengan status akhir dan opsional payload tambahan."""
    if durable_mode() == "off" or not str(task_id or "").strip():
        return False
    task_id = str(task_id).strip()
    now = _now()
    safe_error = redact_sensitive(str(error or ""), limit=_ERROR_LIMIT)
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            row = conn.execute(_sql(_SQL_GET), (task_id,)).fetchone()
            if row is None:
                return False
            current = _row_to_dict(row)
            merged = dict(current.get("payload") or {})
            if payload:
                merged.update(payload)
            conn.execute(
                "UPDATE durable_tasks SET status = ?, error = ?, payload = ?, "
                "updated_at = ?, finished_at = ? WHERE task_id = ?",
                (
                    str(status or "completed"),
                    safe_error,
                    json.dumps(merged, ensure_ascii=False, default=str),
                    now,
                    now,
                    task_id,
                ),
            )
            conn.commit()
    except _DURABLE_ERR as exc:
        logger.debug("Finish durable task '%s' gagal: %s", task_id, exc)
        return False
    else:
        return True


def list_tasks_sync(
    *,
    status: str = "",
    user_id: int = 0,
    chat_id: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Daftar tugas terbaru (filter opsional status/user/chat)."""
    limit = max(1, min(int(limit), 200))
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            if chat_id:
                cursor = conn.execute(
                    _sql(_SQL_LIST_CHAT), (int(chat_id), limit)
                )
            elif user_id and status:
                cursor = conn.execute(
                    _sql(_SQL_LIST_USER_STATUS),
                    (int(user_id), status, limit),
                )
            elif user_id:
                cursor = conn.execute(
                    _sql(_SQL_LIST_USER), (int(user_id), limit)
                )
            elif status:
                cursor = conn.execute(
                    _sql(_SQL_LIST_STATUS), (status, limit)
                )
            else:
                cursor = conn.execute(_sql(_SQL_LIST_ALL), (limit,))
            return [_row_to_dict(row) for row in cursor.fetchall()]
    except _DURABLE_ERR as exc:
        logger.debug("List durable tasks gagal: %s", exc)
        return []


def list_resumable_tasks_sync(
    user_id: int = 0, limit: int = 10
) -> list[dict[str, Any]]:
    """Daftar tugas yang statusnya bisa dilanjutkan (attempt tersisa)."""
    limit = max(1, min(int(limit), 50))
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            if user_id:
                cursor = conn.execute(
                    _sql(_SQL_LIST_RESUMABLE), (int(user_id), limit)
                )
            else:
                cursor = conn.execute(
                    _sql(_SQL_LIST_RESUMABLE_ANY), (limit,)
                )
            return [_row_to_dict(row) for row in cursor.fetchall()]
    except _DURABLE_ERR as exc:
        logger.debug("List resumable durable tasks gagal: %s", exc)
        return []


def claim_task_for_resume_sync(
    task_id: str, user_id: int = 0
) -> dict[str, Any] | None:
    """Klaim tugas untuk dilanjutkan (atomik). Hanya mode ``on``.

    Mengembalikan row yang sudah dinaikkan ``attempts``-nya, atau None bila
    tugas tidak ada/tidak resumable/milik user lain/gagal diklaim.
    """
    if durable_mode() != "on" or not str(task_id or "").strip():
        return None
    task_id = str(task_id).strip()
    now = _now()
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(_sql(_SQL_GET), (task_id,)).fetchone()
            if row is None:
                conn.rollback()
                return None
            current = _row_to_dict(row)
            if str(current.get("status")) not in _RESUMABLE:
                conn.rollback()
                return None
            if user_id and int(current.get("user_id") or 0) != int(user_id):
                conn.rollback()
                return None
            attempts = int(current.get("attempts") or 0)
            max_attempts = int(current.get("max_attempts") or 1)
            if attempts >= max_attempts:
                conn.rollback()
                return None
            conn.execute(
                "UPDATE durable_tasks SET status = 'running', attempts = ?, "
                "error = '', updated_at = ?, finished_at = '' WHERE task_id = ?",
                (attempts + 1, now, task_id),
            )
            conn.commit()
            updated = conn.execute(_sql(_SQL_GET), (task_id,)).fetchone()
            return _row_to_dict(updated) if updated else None
    except _DURABLE_ERR as exc:
        logger.debug("Claim durable task '%s' gagal: %s", task_id, exc)
        return None


def recover_stale_tasks_sync(stale_minutes: int = 30) -> int:
    """Tandai tugas ``running`` yang basi sebagai ``interrupted``.

    Dipanggil saat startup bot/dashboard. TIDAK menjalankan ulang tugas;
    hanya mengklasifikasikan agar bisa dilanjutkan manual.
    """
    stale_minutes = max(1, int(stale_minutes))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    ).isoformat(timespec="seconds")
    now = _now()
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            cursor = conn.execute(
                _sql(_SQL_RECOVER_STALE),
                (
                    now,
                    now,
                    "Proses berhenti sebelum tugas selesai (startup recovery).",
                    cutoff,
                ),
            )
            conn.commit()
            return max(0, int(cursor.rowcount or 0))
    except _DURABLE_ERR as exc:
        logger.debug("Recovery durable tasks gagal: %s", exc)
        return 0


def prune_tasks_sync(
    days: int | None = None, max_rows: int | None = None
) -> dict[str, int | str]:
    """Bersihkan tugas lama/berlebih (retensi). Fail-soft."""
    env_days, env_max = _retention_settings()
    days = env_days if days is None else max(0, int(days))
    max_rows = env_max if max_rows is None else max(0, int(max_rows))
    result: dict[str, int | str] = {
        "status": "error",
        "deleted_old": 0,
        "deleted_excess": 0,
        "days": days,
        "max_rows": max_rows,
    }
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            deleted = _prune_with_conn(conn, days, max_rows)
            conn.commit()
        result = {"status": "ok", **deleted, "days": days, "max_rows": max_rows}
    except _DURABLE_ERR as exc:
        logger.debug("Prune durable tasks gagal: %s", exc)
    return result


def task_count_sync() -> int:
    """Jumlah baris (untuk dashboard/observability)."""
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            row = conn.execute(_sql(_SQL_COUNT)).fetchone()
            return int(row[0] or 0) if row else 0
    except _DURABLE_ERR as exc:
        logger.debug("Count durable tasks gagal: %s", exc)
        return 0


__all__ = [
    "checkpoint_task_sync",
    "claim_task_for_resume_sync",
    "create_task_sync",
    "durable_mode",
    "finish_task_sync",
    "get_task_sync",
    "list_resumable_tasks_sync",
    "list_tasks_sync",
    "prune_tasks_sync",
    "recover_stale_tasks_sync",
    "task_count_sync",
]
