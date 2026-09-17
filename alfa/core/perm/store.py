"""Database persistence, trust scoring, and always-allow permissions store."""

import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

from alfa.core.perm.constants import DB_PATH, logger


def _get_db_path() -> str:
    mod = sys.modules.get("permission_gate") or sys.modules.get("alfa.core.permissions")
    if mod and hasattr(mod, "DB_PATH"):
        return getattr(mod, "DB_PATH")
    return os.getenv("ALFA_DB_PATH", DB_PATH)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS tool_permissions(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               permission_type TEXT DEFAULT 'always',
               created_at REAL,
               expires_at REAL,
               UNIQUE(chat_id, tool_name))""")
    # Add audit trail table
    conn.execute("""CREATE TABLE IF NOT EXISTS permission_audit(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               tier TEXT,
               decision TEXT,
               arguments_json TEXT,
               created_at REAL,
               response_time_sec REAL)""")
    # Add trust score table
    conn.execute("""CREATE TABLE IF NOT EXISTS user_trust_scores(
               chat_id INTEGER PRIMARY KEY,
               trust_score REAL DEFAULT 0.5,
               total_approvals INTEGER DEFAULT 0,
               safe_approvals INTEGER DEFAULT 0,
               risky_approvals INTEGER DEFAULT 0,
               last_updated REAL)""")
    return conn


def get_trust_score(chat_id: Optional[int]) -> float:
    """Get user's trust score (0.0 - 1.0)."""
    if chat_id is None:
        return 0.0
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT trust_score FROM user_trust_scores WHERE chat_id=?",
                (int(chat_id),),
            ).fetchone()
        return row[0] if row else 0.5
    except Exception as e:
        logger.warning(f"get trust score gagal: {e}")
        return 0.5


def update_trust_score(chat_id: int, was_safe: bool, response_time: float) -> None:
    """Update user's trust score based on their decision."""
    try:
        with _connect() as conn:
            # Get current stats
            row = conn.execute(
                "SELECT trust_score, total_approvals, safe_approvals, risky_approvals "
                "FROM user_trust_scores WHERE chat_id=?",
                (int(chat_id),),
            ).fetchone()

            if row:
                trust_score, total, safe, risky = row
            else:
                trust_score, total, safe, risky = 0.5, 0, 0, 0

            # Update counters
            total += 1
            if was_safe:
                safe += 1
            else:
                risky += 1

            # Calculate new trust score (simple heuristic)
            # More safe decisions = higher trust
            # Faster responses to risky tools = higher trust
            base_ratio = safe / total if total > 0 else 0.5
            speed_bonus = min(0.1, 30.0 / max(response_time, 30.0)) * 0.2
            new_trust = min(1.0, max(0.0, base_ratio + speed_bonus))

            conn.execute(
                """INSERT OR REPLACE INTO user_trust_scores 
                   (chat_id, trust_score, total_approvals, safe_approvals, risky_approvals, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (int(chat_id), new_trust, total, safe, risky, time.time()),
            )
    except Exception as e:
        logger.warning(f"update trust score gagal: {e}")


def log_permission_decision(
    chat_id: int,
    tool_name: str,
    tier: str,
    decision: str,
    args_json: str,
    response_time: float,
) -> None:
    """Log permission decision for audit trail."""
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO permission_audit 
                   (chat_id, tool_name, tier, decision, arguments_json, created_at, response_time_sec)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(chat_id),
                    tool_name,
                    tier,
                    decision,
                    args_json,
                    time.time(),
                    response_time,
                ),
            )
    except Exception as e:
        logger.warning(f"log audit trail gagal: {e}")


def is_always_allowed(chat_id: Optional[int], tool_name: str) -> bool:
    if chat_id is None:
        return False
    try:
        with _connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM tool_permissions 
                   WHERE chat_id=? AND tool_name=? 
                   AND (permission_type='always' OR (permission_type='session' AND expires_at > ?))""",
                (int(chat_id), tool_name, time.time()),
            ).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"cek tool_permissions gagal (lolos-aman): {e}")
        return False


def save_always_allow(
    chat_id: int, tool_name: str, perm_type: str = "always", duration_hours: int = 24
) -> None:
    """Save permission with type and optional expiration."""
    try:
        expires_at = (
            time.time() + (duration_hours * 3600) if perm_type == "session" else None
        )
        with _connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tool_permissions 
                   (chat_id, tool_name, permission_type, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (int(chat_id), tool_name, perm_type, time.time(), expires_at),
            )
    except Exception as e:
        logger.warning(f"simpan tool_permissions gagal: {e}")


def list_always_allowed(chat_id: int) -> List[str]:
    try:
        with _connect() as conn:
            return [
                r[0]
                for r in conn.execute(
                    """SELECT tool_name FROM tool_permissions 
                   WHERE chat_id=? AND (permission_type='always' 
                   OR (permission_type='session' AND expires_at > ?))
                   ORDER BY tool_name""",
                    (int(chat_id), time.time()),
                ).fetchall()
            ]
    except Exception:
        return []
