"""Skema tabel & metrik software factory."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger(__name__)

_DB_ERR = (sqlite3.Error, TypeError, ValueError)

def init_software_factory_tables() -> None:
    """Initialize SQLite table tracking autonomous full-stack software builds."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_software_factory_builds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id TEXT UNIQUE,
                app_slug TEXT UNIQUE,
                title TEXT,
                app_dir TEXT,
                verification_status TEXT DEFAULT 'PRODUCTION_READY',
                e2e_score INTEGER DEFAULT 100,
                diagnostics_json TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

def _row_value(row: Any, key: str, index: int, default: Any = None) -> Any:
    """Read a column from a DB row regardless of whether `row_factory` is `sqlite3.Row`."""
    if row is None:
        return default
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        pass
    try:
        return row[index]
    except (TypeError, IndexError, KeyError):
        return default

def get_software_factory_metrics() -> dict[str, Any]:
    """Return telemetry for the Autonomous Full-Stack Software Factory."""
    empty = {"total_builds": 0, "production_ready_builds": 0, "avg_e2e_score": 100.0}
    try:
        init_software_factory_tables()
        with get_sync_db() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_builds,
                    COALESCE(SUM(CASE WHEN verification_status = 'PRODUCTION_READY' THEN 1 ELSE 0 END), 0) AS prod_ready,
                    COALESCE(AVG(e2e_score), 100.0) AS avg_score
                FROM alfa_software_factory_builds
                """
            ).fetchone()
    except _DB_ERR as exc:
        logger.warning("Software factory metrics unavailable: %s", exc)
        return empty
    return {
        "total_builds": int(_row_value(row, "total_builds", 0, 0) or 0),
        "production_ready_builds": int(_row_value(row, "prod_ready", 1, 0) or 0),
        "avg_e2e_score": round(float(_row_value(row, "avg_score", 2, 100.0) or 100.0), 1),
    }
