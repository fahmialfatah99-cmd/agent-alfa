"""Rate limiting and cost controls for ALFA."""

import logging
import os
import sqlite3
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("RateLimiter")

DEFAULT_TOKEN_LIMIT = int(os.getenv("ALFA_DAILY_TOKEN_LIMIT", "0"))
DEFAULT_CALL_LIMIT = int(os.getenv("ALFA_DAILY_CALL_LIMIT", "0"))


def init_budgets_table():
    """Initialize the user_budgets table."""
    try:
        with get_sync_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_budgets (
                    user_id INTEGER PRIMARY KEY,
                    daily_token_limit INTEGER NOT NULL,
                    daily_call_limit INTEGER NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    except (sqlite3.Error, OSError):
        logger.exception("Failed to init user_budgets")


# Call init on module load
init_budgets_table()


def check_rate_limit(user_id: int, provider: str = "") -> tuple[bool, str]:
    """Checks against configurable limits. Returns (allowed, reason)."""
    usage = get_user_usage_today(user_id)
    # Pembatasan token dinonaktifkan jika budget_limit <= 0 (unlimited)
    if usage["budget_limit"] > 0 and usage["total_tokens"] >= usage["budget_limit"]:
        return False, f"Daily token limit reached ({usage['total_tokens']}/{usage['budget_limit']})"
    if usage["call_limit"] > 0 and usage["total_calls"] >= usage["call_limit"]:
        return False, f"Daily call limit reached ({usage['total_calls']}/{usage['call_limit']})"
    return True, "OK"


def get_user_usage_today(user_id: int) -> dict[str, Any]:
    """Returns {total_tokens, total_calls, budget_remaining, budget_limit, call_limit}

    Pemakaian dihitung PER USER. Sebelum kolom `user_id` ada, seluruh pemakaian
    dijumlahkan global sehingga satu user menghabiskan kuota semua user lain.
    """
    budget_limit = DEFAULT_TOKEN_LIMIT
    call_limit = DEFAULT_CALL_LIMIT
    total_tokens = 0
    total_calls = 0

    try:
        with get_sync_db() as conn:
            row = conn.execute(
                "SELECT daily_token_limit, daily_call_limit FROM user_budgets WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row:
                budget_limit = row["daily_token_limit"]
                call_limit = row["daily_call_limit"]
    except (sqlite3.Error, OSError, ValueError, TypeError):
        logger.exception("Error getting usage")

    # Query usage dipisah dari query budget: tabel `user_budgets` yang belum
    # ada (mis. DB lama / test tanpa init) tidak boleh ikut menihilkan
    # pemakaian token — sebelumnya satu try block membuat seluruhnya 0.
    try:
        with get_sync_db() as conn:
            usage_row = conn.execute(
                "SELECT SUM(total_tokens) as total_tokens, COUNT(*) as total_calls "
                "FROM api_token_usage "
                "WHERE date(ts) = date('now') AND COALESCE(user_id, 0) = ?",
                (int(user_id or 0),),
            ).fetchone()
            if usage_row:
                total_tokens = usage_row["total_tokens"] or 0
                total_calls = usage_row["total_calls"] or 0
    except (sqlite3.Error, OSError, ValueError, TypeError):
        logger.exception("Error getting usage")

    budget_remaining = -1 if budget_limit <= 0 else max(0, budget_limit - total_tokens)
    return {
        "total_tokens": total_tokens,
        "total_calls": total_calls,
        "budget_limit": budget_limit,
        "call_limit": call_limit,
        "budget_remaining": budget_remaining,
    }


def set_user_budget(user_id: int, daily_token_limit: int, daily_call_limit: int):
    """Set per-user budget"""
    try:
        with get_sync_db() as conn:
            # Handle upsert via REPLACE or ON CONFLICT
            # Since user_id is PRIMARY KEY, we can use ON CONFLICT
            conn.execute(
                """
                INSERT INTO user_budgets (user_id, daily_token_limit, daily_call_limit, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    daily_token_limit = excluded.daily_token_limit,
                    daily_call_limit = excluded.daily_call_limit,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, daily_token_limit, daily_call_limit),
            )
            conn.commit()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        logger.exception("Error setting user budget")


def reset_user_usage_today(user_id: int | None = None) -> int:
    """Reset daily token usage records for today.

    If user_id is provided and > 0, resets for that specific user.
    If user_id is None or 0, resets all usage records for today.
    Returns the number of deleted records.
    """
    deleted_count = 0
    try:
        with get_sync_db() as conn:
            if user_id:
                cur = conn.execute(
                    "DELETE FROM api_token_usage WHERE date(ts) = date('now') AND COALESCE(user_id, 0) = ?",
                    (int(user_id),),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM api_token_usage WHERE date(ts) = date('now')"
                )
            deleted_count = cur.rowcount
            conn.commit()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        logger.exception("Error resetting user usage today")
    return deleted_count


def get_cost_estimate(prompt_text: str, model: str = "") -> dict[str, Any]:
    """Estimate token count and approximate cost before execution."""
    tokens = len(prompt_text) // 4  # rough estimate
    cost_per_1k = 0.0
    if "gpt-4" in model.lower():
        cost_per_1k = 0.03
    elif "gpt-3.5" in model.lower() or "flash" in model.lower():
        cost_per_1k = 0.001

    estimated_cost = (tokens / 1000.0) * cost_per_1k
    return {
        "estimated_tokens": tokens,
        "estimated_cost_usd": estimated_cost,
    }


def get_budget_report(user_id: int = 1) -> dict[str, Any]:
    """Laporan kuota hari ini: total, sisa, %, per-provider, status waspada.

    Fail-open: bila DB tidak bisa dibaca, kembalikan status 'unknown'
    agar tidak memblokir misi.
    """
    try:
        from alfa.core.db import get_api_usage_summary_sync

        usage = get_user_usage_today(user_id)
        try:
            summary = get_api_usage_summary_sync(hours=24)
        except (sqlite3.Error, OSError, ValueError, TypeError):
            summary = {}
        total = usage.get("total_tokens", 0) or 0
        limit = usage.get("budget_limit", 0) or 0
        pct = (total / limit) if limit else 0.0
        return {
            "status": "ok",
            "total_tokens": total,
            "total_calls": usage.get("total_calls", 0) or 0,
            "budget_limit": limit,
            "call_limit": usage.get("call_limit", 0) or 0,
            "remaining": usage.get("budget_remaining", 0) or 0,
            "pct": pct,
            "warn": pct >= 0.8,
            "exceeded": pct >= 1.0,
            "by_key": (summary or {}).get("per_key", []) or [],
            "by_context": (summary or {}).get("by_context", []) or [],
        }
    except (ImportError, sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"budget report gagal: {e}")
        return {"status": "unknown"}
