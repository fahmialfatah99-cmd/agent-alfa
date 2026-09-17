# -*- coding: utf-8 -*-
"""
Cron, Reminders, Focus Sessions, Subagents, and API Token Telemetry Database Functions.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite

from alfa.core.db.connection import _get_db_path, get_sync_db

logger = logging.getLogger("DB.Tasks")


# --- Cron / Recurring Task Functions ---
def add_cron_job_sync(
    user_id: int,
    chat_id: int,
    title: str,
    prompt_instruction: str,
    interval_minutes: int,
) -> int:
    """Synchronously add a recurring cron job."""
    next_run = (datetime.now() + timedelta(minutes=interval_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_cron_jobs (user_id, chat_id, title, prompt_instruction, interval_minutes, next_run)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, title, prompt_instruction, interval_minutes, next_run),
        )
        conn.commit()
        return cursor.lastrowid


def list_cron_jobs_sync(user_id: int) -> List[Dict[str, Any]]:
    """List all recurring cron jobs for a user."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT id, title, prompt_instruction, interval_minutes, is_active, last_run, next_run 
            FROM scheduled_cron_jobs 
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def delete_cron_job_sync(user_id: int, job_id: int) -> bool:
    """Delete a recurring cron job."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            "DELETE FROM scheduled_cron_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


async def get_due_cron_jobs() -> List[Dict[str, Any]]:
    """Get all active recurring cron jobs whose next_run is due."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, title, prompt_instruction, interval_minutes 
            FROM scheduled_cron_jobs 
            WHERE is_active = 1 AND next_run <= ?
            """,
            (now_str,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def update_cron_job_after_run(job_id: int, interval_minutes: int):
    """Update last_run and advance next_run for a recurring cron job."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    next_run = (datetime.now() + timedelta(minutes=interval_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            "UPDATE scheduled_cron_jobs SET last_run = ?, next_run = ? WHERE id = ?",
            (now_str, next_run, job_id),
        )
        await db.commit()


# --- Subagent Task Storage ---
def save_subagent_task_sync(
    task_id: str, user_id: int, chat_id: int, role: str, description: str
):
    """Save initial subagent task."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO subagent_tasks (id, user_id, chat_id, role, task_description, status)
            VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (task_id, user_id, chat_id, role, description),
        )
        conn.commit()


def update_subagent_task_sync(task_id: str, status: str, result: str):
    """Update subagent completion result."""
    with get_sync_db() as conn:
        conn.execute(
            """
            UPDATE subagent_tasks 
            SET status = ?, result = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, result, task_id),
        )
        conn.commit()


def get_subagent_task_sync(task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve subagent task status."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT * FROM subagent_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_subagent_tasks_sync(limit: int = 20) -> List[Dict[str, Any]]:
    """List recent subagent autonomous background tasks."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM subagent_tasks 
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def log_agent_activity_sync(
    agent_id: Optional[int],
    agent_name: str,
    action_type: str,
    description: str,
    tool_name: Optional[str] = None,
    tool_input: Optional[str] = None,
    tool_output: Optional[str] = None,
    status: str = "success",
    duration_ms: float = 0.0,
) -> int:
    """Record an agent tool execution or real-time activity log."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_activity_logs (agent_id, agent_name, action_type, description, tool_name, tool_input, tool_output, status, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                agent_name,
                action_type,
                description,
                tool_name,
                tool_input,
                tool_output,
                status,
                duration_ms,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def list_agent_activities_sync(limit: int = 30) -> List[Dict[str, Any]]:
    """List recent agent activity logs and tool executions."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM agent_activity_logs 
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


# --- Reminders / Scheduled Tasks ---
def add_reminder_sync(
    user_id: int, chat_id: int, reminder_time_iso: str, message: str
) -> int:
    """Synchronously add a scheduled reminder (for tools)."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (user_id, chat_id, reminder_time, message)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, chat_id, reminder_time_iso, message),
        )
        conn.commit()
        return cursor.lastrowid


async def add_reminder(
    user_id: int, chat_id: int, reminder_time_iso: str, message: str
) -> int:
    """Add a scheduled reminder."""
    async with aiosqlite.connect(_get_db_path()) as db:
        cursor = await db.execute(
            """
            INSERT INTO reminders (user_id, chat_id, reminder_time, message)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, chat_id, reminder_time_iso, message),
        )
        await db.commit()
        return cursor.lastrowid


async def get_due_reminders() -> List[Dict[str, Any]]:
    """Get all pending reminders that are due now."""
    now_iso = datetime.now().isoformat()
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, message, reminder_time 
            FROM reminders 
            WHERE is_executed = 0 AND reminder_time <= ?
            """,
            (now_iso,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def mark_reminder_executed(reminder_id: int):
    """Mark reminder as completed."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            "UPDATE reminders SET is_executed = 1 WHERE id = ?", (reminder_id,)
        )
        await db.commit()


# --- Focus & Productivity Sessions (Pomodoro) ---
def start_focus_session_sync(
    user_id: int, chat_id: int, title: str, duration_minutes: int, notes: str = ""
) -> Dict[str, Any]:
    """Synchronously create and start a focus session."""
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    end_iso = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO focus_sessions (user_id, chat_id, title, duration_minutes, end_time, status, notes)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (user_id, chat_id, title, duration_minutes, end_iso, notes),
        )
        conn.commit()
        session_id = cursor.lastrowid

    return {
        "status": "success",
        "session_id": session_id,
        "title": title,
        "duration_minutes": duration_minutes,
        "end_time": end_iso,
    }


async def get_due_focus_sessions() -> List[Dict[str, Any]]:
    """Retrieve active focus sessions that have reached their end_time."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, title, duration_minutes, end_time, notes
            FROM focus_sessions
            WHERE status = 'active' AND is_notified = 0 AND end_time <= ?
            """,
            (now_iso,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def mark_focus_session_completed(session_id: int):
    """Mark a focus session as completed and notified."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            "UPDATE focus_sessions SET status = 'completed', is_notified = 1 WHERE id = ?",
            (session_id,),
        )
        await db.commit()


# --- API Token Usage Tracking (Realtime Dashboard) ---
def record_api_usage_sync(
    provider: str,
    model: str = "",
    key_id: int = None,
    key_label: str = "",
    context: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> bool:
    """Record one LLM call's token consumption. Never raises."""
    try:
        with get_sync_db() as conn:
            conn.execute(
                """
                INSERT INTO api_token_usage
                (provider, model, key_id, key_label, context, prompt_tokens, completion_tokens, total_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    model or "",
                    key_id,
                    key_label or "",
                    context or "",
                    max(0, int(prompt_tokens or 0)),
                    max(0, int(completion_tokens or 0)),
                    max(0, int((prompt_tokens or 0) + (completion_tokens or 0))),
                ),
            )
            conn.commit()
        return True
    except Exception:
        return False


def get_api_usage_summary_sync(hours: int = 24) -> Dict[str, Any]:
    """
    Aggregate token usage for the dashboard:
    - per key/provider totals within the window (and today separately)
    - hourly buckets for charting
    - grand totals + call counts
    """
    hours = max(1, min(int(hours or 24), 720))
    with get_sync_db() as conn:
        rows = conn.execute(
            """
            SELECT provider,
                   COALESCE(key_label, '') AS key_label,
                   key_id,
                   SUM(prompt_tokens)     AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens,
                   SUM(total_tokens)      AS total_tokens,
                   COUNT(*)               AS calls,
                   MAX(ts)                AS last_used
            FROM api_token_usage
            WHERE ts >= datetime('now', ?)
            GROUP BY provider, key_label, key_id
            ORDER BY total_tokens DESC
            """,
            (f"-{hours} hours",),
        ).fetchall()
        per_key = [dict(r) for r in rows]

        buckets = conn.execute(
            """
            SELECT strftime('%Y-%m-%d %H:00', ts) AS bucket,
                   SUM(total_tokens) AS tokens,
                   COUNT(*)          AS calls
            FROM api_token_usage
            WHERE ts >= datetime('now', ?)
            GROUP BY bucket ORDER BY bucket ASC
            """,
            (f"-{hours} hours",),
        ).fetchall()

        by_context = conn.execute(
            """
            SELECT COALESCE(NULLIF(context,''),'lainnya') AS ctx, SUM(total_tokens) AS tokens
            FROM api_token_usage WHERE ts >= datetime('now', ?)
            GROUP BY ctx ORDER BY tokens DESC
            """,
            (f"-{hours} hours",),
        ).fetchall()

        totals = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) FROM api_token_usage"
        ).fetchone()
        today = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0), COUNT(*) FROM api_token_usage WHERE date(ts) = date('now','localtime')"
        ).fetchone()

    return {
        "window_hours": hours,
        "per_key": per_key,
        "hourly": [dict(b) for b in buckets],
        "by_context": [dict(c) for c in by_context],
        "total_all_time": totals[0] if totals else 0,
        "tokens_today": today[0] if today else 0,
        "calls_today": today[1] if today else 0,
    }
