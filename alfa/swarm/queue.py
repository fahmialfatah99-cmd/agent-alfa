"""Antrean misi swarm yang durable (SQLite, tanpa dependensi eksternal).

Operator mendaftarkan misi via `enqueue()` / `POST /api/swarm/queue/enqueue`,
pekerja `run_queue_worker()` mengambilnya satu per satu (`claim_next` atomik)
dan mengeksekusi via `conduct_multi_agent_meeting`. Misi gagal di-retry dengan
backoff sampai `max_attempts`, lalu ditandai `failed`. Semua fungsi menerima
`db_path` eksplisit agar hermetic di test (default: `ALFA_QUEUE_DB` atau
`agent_data.db` repo).
"""

import json
import logging
import os
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

STATUSES = ("queued", "running", "done", "failed", "cancelled")


def resolve_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    override = os.getenv("ALFA_QUEUE_DB", "").strip()
    if override:
        return override
    return os.getenv("ALFA_DB_PATH", os.path.join(REPO_ROOT, "agent_data.db"))


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS swarm_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'execute',
            participants_json TEXT NOT NULL DEFAULT '[]',
            target_folder TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            run_after REAL NOT NULL DEFAULT 0,
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_status ON swarm_missions(status, run_after)"
    )
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("participants_json", "result_json"):
        try:
            d[key.replace("_json", "")] = json.loads(d.pop(key) or ("[]" if key == "participants_json" else "{}"))
        except Exception:
            d[key.replace("_json", "")] = [] if key == "participants_json" else {}
    return d


def enqueue(
    topic: str,
    mode: str = "execute",
    participants: list[str] | None = None,
    target_folder: str = "",
    delay_s: float = 0,
    max_attempts: int = 0,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Daftarkan misi baru. Return dict misi."""
    if not (topic or "").strip():
        raise ValueError("topic wajib diisi")
    try:
        default_attempts = int(os.getenv("ALFA_QUEUE_MAX_ATTEMPTS", "3") or 3)
    except ValueError:
        default_attempts = 3
    now = time.time()
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO swarm_missions
               (topic, mode, participants_json, target_folder, status,
                attempts, max_attempts, run_after, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)""",
            (
                topic.strip(),
                mode or "execute",
                json.dumps(participants or []),
                target_folder or "",
                max(1, max_attempts or default_attempts),
                now + max(0.0, delay_s),
                now,
                now,
            ),
        )
        mid = cur.lastrowid or 0
        conn.commit()
        return get_mission(mid, conn=conn) or {"id": mid, "status": "queued"}
    finally:
        conn.close()


def get_mission(mid: int, db_path: str | None = None, conn=None) -> dict[str, Any] | None:
    own = conn is None
    conn = conn or _connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM swarm_missions WHERE id = ?", (mid,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        if own:
            conn.close()


def list_missions(
    status: str | None = None, limit: int = 50, db_path: str | None = None
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                "SELECT * FROM swarm_missions WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, max(1, limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM swarm_missions ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def cancel_mission(mid: int, db_path: str | None = None) -> bool:
    """Batalkan misi queued/running. Return True bila ada yang berubah."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE swarm_missions SET status = 'cancelled', updated_at = ? "
            "WHERE id = ? AND status IN ('queued', 'running')",
            (time.time(), mid),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def claim_next(db_path: str | None = None) -> dict[str, Any] | None:
    """Ambil misi queued tertua secara atomik → tandai running. None bila kosong."""
    conn = _connect(db_path)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM swarm_missions WHERE status = 'queued' "
                "AND run_after <= ? ORDER BY id ASC LIMIT 1",
                (time.time(),),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE swarm_missions SET status = 'running', "
                "attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (time.time(), row["id"]),
            )
            conn.execute("COMMIT")
            return get_mission(row["id"], conn=conn)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
    finally:
        conn.close()


def complete_mission(
    mid: int, result: dict[str, Any] | None = None, db_path: str | None = None
) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE swarm_missions SET status = 'done', result_json = ?, "
            "error = '', updated_at = ? WHERE id = ?",
            (json.dumps(result or {}, ensure_ascii=False), time.time(), mid),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def fail_mission(
    mid: int, error: str = "", db_path: str | None = None
) -> dict[str, Any] | None:
    """Gagalkan satu percobaan: retry backoff bila sisa kuota, else failed."""
    conn = _connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT attempts, max_attempts FROM swarm_missions WHERE id = ?", (mid,)
        ).fetchone()
        if not row:
            return None
        now = time.time()
        if row["attempts"] >= row["max_attempts"]:
            conn.execute(
                "UPDATE swarm_missions SET status = 'failed', error = ?, "
                "updated_at = ? WHERE id = ?",
                (error[:2000], now, mid),
            )
        else:
            backoff = 60.0 * max(1, row["attempts"])
            conn.execute(
                "UPDATE swarm_missions SET status = 'queued', error = ?, "
                "run_after = ?, updated_at = ? WHERE id = ?",
                (error[:2000], now + backoff, now, mid),
            )
        conn.commit()
        return get_mission(mid, conn=conn)
    finally:
        conn.close()


async def run_queue_worker(
    stop_after: int = 0,
    poll_interval: float = 0,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Loop pekerja: claim → eksekusi → complete/fail.

    `stop_after`: berhenti setelah N misi (0 = jalan terus). `poll_interval`:
    jeda detik saat antrean kosong (default env ALFA_QUEUE_POLL=5).
    """
    import asyncio

    try:
        raw_poll: str | float = poll_interval or os.getenv("ALFA_QUEUE_POLL") or "5"
        interval = float(raw_poll)
    except ValueError:
        interval = 5.0
    from alfa.swarm.engine import conduct_multi_agent_meeting

    done = 0
    failed = 0
    idle_slept = 0.0
    while True:
        mission = claim_next(db_path)
        if not mission:
            if stop_after and done + failed >= stop_after:
                break
            if stop_after:
                # Mode one-shot (test/CI): tunggu hingga ~interval detik, lalu keluar.
                if idle_slept >= interval:
                    break
                await asyncio.sleep(1.0)
                idle_slept += 1.0
                continue
            await asyncio.sleep(interval)
            continue
        idle_slept = 0.0
        try:
            result = await conduct_multi_agent_meeting(
                topic=mission["topic"],
                participant_names=mission.get("participants") or None,
                mode=mission.get("mode") or "execute",
                target_folder=mission.get("target_folder") or "",
            )
            complete_mission(mission["id"], result, db_path)
            done += 1
        except Exception as e:
            logger.warning(f"Misi #{mission['id']} gagal: {e}")
            fail_mission(mission["id"], str(e), db_path)
            failed += 1
        if stop_after and done + failed >= stop_after:
            break
    return {"done": done, "failed": failed}
