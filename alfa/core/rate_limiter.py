"""Rate limiting and cost controls for ALFA."""

import logging
import os
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("RateLimiter")

DEFAULT_TOKEN_LIMIT = int(os.getenv("ALFA_DAILY_TOKEN_LIMIT", "500000"))
DEFAULT_CALL_LIMIT = int(os.getenv("ALFA_DAILY_CALL_LIMIT", "200"))


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
    except Exception as e:
        logger.error(f"Failed to init user_budgets: {e}")


# Call init on module load
init_budgets_table()


def check_rate_limit(user_id: int, provider: str = "") -> tuple[bool, str]:
    """Checks against configurable limits. Returns (allowed, reason)."""
    usage = get_user_usage_today(user_id)
    if usage["total_tokens"] >= usage["budget_limit"]:
        return False, f"Daily token limit reached ({usage['total_tokens']}/{usage['budget_limit']})"
    if usage["total_calls"] >= usage["call_limit"]:
        return False, f"Daily call limit reached ({usage['total_calls']}/{usage['call_limit']})"
    return True, "OK"


def get_user_usage_today(user_id: int) -> dict[str, Any]:
    """Returns {total_tokens, total_calls, budget_remaining, budget_limit, call_limit}"""
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

            # Note: api_token_usage doesn't have user_id, so we sum globally for today
            usage_row = conn.execute(
                "SELECT SUM(total_tokens) as total_tokens, COUNT(*) as total_calls "
                "FROM api_token_usage WHERE date(ts) = date('now')"
            ).fetchone()

            if usage_row:
                total_tokens = usage_row["total_tokens"] or 0
                total_calls = usage_row["total_calls"] or 0

    except Exception as e:
        logger.error(f"Error getting usage: {e}")

    return {
        "total_tokens": total_tokens,
        "total_calls": total_calls,
        "budget_limit": budget_limit,
        "call_limit": call_limit,
        "budget_remaining": max(0, budget_limit - total_tokens),
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
    except Exception as e:
        logger.error(f"Error setting user budget: {e}")


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
