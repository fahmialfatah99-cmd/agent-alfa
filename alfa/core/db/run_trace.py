"""Run-trace: jejak observability ringan untuk run multi-agen.

Sinkron, satu tabel SQLite (additive, tanpa mengubah schema lama), dan
SELALU gagal-lembut: kegagalan tracing TIDAK BOLEH pernah memengaruhi
jalur utama (zero-regression). Dibaca dashboard (GET /api/v1/trace/runs)
dan CLI langsung dari modul ini (``python -m alfa.core.db.run_trace``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("DB.RunTrace")

_TABLE = "run_traces"

# SQL berupa konstanta literal + {t} yang di-.replace() — mengikuti pola
# bandit-B608-safe milik wa_tracking (tanpa f-string SQL).
_SQL_CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS {t} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'swarm_meeting',
            status TEXT NOT NULL DEFAULT 'ok',
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            meta TEXT NOT NULL DEFAULT '{{}}',
            summary TEXT NOT NULL DEFAULT '{{}}'
        )
        """
_SQL_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_run_traces_started "
    "ON {t} (started_at DESC)"
)
_SQL_UPSERT = """
            INSERT INTO {t}
                (run_id, kind, status, started_at, finished_at, duration_ms,
                 meta, summary)
            VALUES (?, 'swarm_meeting', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status = excluded.status,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms,
                meta = excluded.meta,
                summary = excluded.summary
            """
_SQL_LIST_KIND = """
            SELECT * FROM {t} WHERE kind = ?
            ORDER BY started_at DESC LIMIT ?
            """
_SQL_LIST_ALL = "SELECT * FROM {t} ORDER BY started_at DESC LIMIT ?"
_SQL_GET_ONE = "SELECT * FROM {t} WHERE run_id = ?"


def _sql(template: str) -> str:
    """Ganti penampung {t} dengan nama tabel (konstanta modul, literal)."""
    return template.replace("{t}", _TABLE)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_sql(_SQL_CREATE_TABLE))
    conn.execute(_sql(_SQL_CREATE_INDEX))


def summarize_swarm_result(result: dict[str, Any] | None) -> dict[str, Any]:
    """Ringkasan post-hoc dari dict hasil impl — hanya baca, tak menulis.

    Isi respons run TIDAK disimpan (privacy-friendly): cukup angka ringkas.
    """
    if not isinstance(result, dict):
        return {}
    steps = result.get("execution_results")
    step_items: list[Any] = steps if isinstance(steps, list) else []
    tools_used = sum(
        1 for s in step_items if isinstance(s, dict) and s.get("tool_used")
    )
    deliverables = sum(
        1
        for s in step_items
        if isinstance(s, dict) and s.get("deliverable_file")
    )
    errors = sum(
        1
        for s in step_items
        if isinstance(s, dict)
        and str(s.get("execution_summary") or "").startswith("[EXCEPTION]")
    )
    dialogue = result.get("dialogue_transcript")
    return {
        "steps": len(step_items),
        "tools_used": tools_used,
        "deliverables": deliverables,
        "step_errors": errors,
        "dialogue_rounds": len(dialogue) if isinstance(dialogue, list) else 0,
        "has_vote_tally": bool(result.get("vote_tally")),
        "has_consensus": bool(str(result.get("consensus") or "").strip()),
    }


def record_swarm_meeting_sync(
    *,
    session_id: str,
    topic: str,
    mode: str,
    rounds: int,
    duration_ms: int,
    participants: list[str],
    result: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    """Catat satu run swarm (upsert per session_id). Pembaca tidak lain."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status = "error" if error else "ok"
    meta = {
        "topic": (topic or "")[:200],
        "mode": mode or "execute",
        "rounds": rounds,
        "participants": list(participants or []),
        "error": error,
    }
    summary = summarize_swarm_result(result)
    with get_sync_db() as conn:
        _ensure_table(conn)
        conn.execute(_sql(_SQL_UPSERT), (
            session_id,
            status,
            now,
            now,
            max(0, int(duration_ms)),
            json.dumps(meta),
            json.dumps(summary),
        ))
        conn.commit()


def list_runs_sync(limit: int = 25, kind: str = "") -> list[dict[str, Any]]:
    """Ambil jejak terakhir, terbaru dulu. Kolom meta/summary sudah diparse."""
    limit = max(1, min(int(limit), 200))
    with get_sync_db() as conn:
        _ensure_table(conn)
        conn.row_factory = sqlite3.Row
        if kind.strip():
            cursor = conn.execute(
                _sql(_SQL_LIST_KIND),
                (kind.strip(), limit),
            )
        else:
            cursor = conn.execute(_sql(_SQL_LIST_ALL), (limit,))
        rows = [dict(r) for r in cursor.fetchall()]
    for row in rows:
        for field in ("meta", "summary"):
            raw = row.get(field) or "{}"
            try:
                row[field] = dict(json.loads(raw))
            except (ValueError, TypeError):
                row[field] = {}
    return rows


def get_run_sync(run_id: str) -> dict[str, Any] | None:
    """Ambil satu jejak lengkap berdasarkan run_id."""
    with get_sync_db() as conn:
        _ensure_table(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            _sql(_SQL_GET_ONE), (run_id,)
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    for field in ("meta", "summary"):
        raw = data.get(field) or "{}"
        try:
            data[field] = dict(json.loads(raw))
        except (ValueError, TypeError):
            data[field] = {}
    return data


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Baca jejak run multi-agen (run_traces)."
    )
    parser.add_argument("--last", type=int, default=10, help="jumlah baris")
    parser.add_argument("--kind", default="", help="filter kind (mis. swarm_meeting)")
    parser.add_argument("--get", default="", help="tampilkan satu run_id")
    args = parser.parse_args()
    if args.get:
        run_row = get_run_sync(args.get)
        if run_row is None:
            print("run tidak ditemukan:", args.get)
        else:
            print(json.dumps(run_row, indent=2, ensure_ascii=False))
        return
    runs = list_runs_sync(limit=args.last, kind=args.kind)
    if not runs:
        print("(belum ada jejak run)")
        return
    for row in runs:
        meta = row.get("meta") or {}
        summary = row.get("summary") or {}
        print(
            f"{row['started_at']} | {str(row['status']):5s} | "
            f"{row['duration_ms']:>6d}ms | {str(meta.get('mode') or ''):8s} | "
            f"steps={summary.get('steps', 0)} "
            f"tools={summary.get('tools_used', 0)} "
            f"err={summary.get('step_errors', 0)} | "
            f"{str(meta.get('topic') or '')[:60]}"
        )


if __name__ == "__main__":
    _cli()
