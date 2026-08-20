"""
Database module for Telegram AI Bot.
Handles persistent chat history, long-term knowledge memory, reminders, and settings.
"""

import aiosqlite
import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")


def init_db_sync():
    """Synchronously ensure all SQLite tables and indices exist."""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS knowledge_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT DEFAULT 'general',
                key_topic TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key_topic)
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                reminder_time TEXT NOT NULL,
                message TEXT NOT NULL,
                is_executed INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS scheduled_cron_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                prompt_instruction TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                is_active INTEGER DEFAULT 1,
                last_run DATETIME,
                next_run DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subagent_tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                result TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                voice_reply INTEGER DEFAULT 0,
                system_prompt_override TEXT,
                model_name TEXT DEFAULT 'gemini-3.5-flash-lite'
            );
            CREATE TABLE IF NOT EXISTS knowledge_graph (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, entity, relation)
            );
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME NOT NULL,
                status TEXT DEFAULT 'active',
                notes TEXT,
                is_notified INTEGER DEFAULT 0
            );
        """)
        conn.commit()


# Auto-initialize database tables synchronously on import
try:
    init_db_sync()
except Exception:
    pass


def get_sync_db():
    """Get a standard synchronous SQLite connection with Row factory and WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


async def init_db():
    """Initialize SQLite database tables and enable WAL mode."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        
        # Chat History
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Long-Term Knowledge Memory
        await db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT DEFAULT 'general',
                key_topic TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key_topic)
            )
        """)
        
        # Reminders / Scheduled Tasks
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                reminder_time TEXT NOT NULL,
                message TEXT NOT NULL,
                is_executed INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Scheduled Recurring Cron Tasks / Watchdog
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_cron_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                prompt_instruction TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                is_active INTEGER DEFAULT 1,
                last_run DATETIME,
                next_run DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Subagent Background Tasks
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subagent_tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                result TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME
            )
        """)

        # User Settings (e.g. voice_mode, preferred_model, prompt)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                voice_reply INTEGER DEFAULT 0,
                system_prompt_override TEXT,
                model_name TEXT DEFAULT 'gemini-3.5-flash-lite'
            )
        """)

        # Semantic Knowledge Graph
        await db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_graph (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, entity, relation)
            )
        """)

        # Focus & Productivity Sessions (Pomodoro)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME NOT NULL,
                status TEXT DEFAULT 'active',
                notes TEXT,
                is_notified INTEGER DEFAULT 0
            )
        """)
        await db.commit()


# --- Cron / Recurring Task Functions ---
def add_cron_job_sync(user_id: int, chat_id: int, title: str, prompt_instruction: str, interval_minutes: int) -> int:
    """Synchronously add a recurring cron job."""
    from datetime import datetime, timedelta
    next_run = (datetime.now() + timedelta(minutes=interval_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_cron_jobs (user_id, chat_id, title, prompt_instruction, interval_minutes, next_run)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, title, prompt_instruction, interval_minutes, next_run)
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
            (user_id,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def delete_cron_job_sync(user_id: int, job_id: int) -> bool:
    """Delete a recurring cron job."""
    with get_sync_db() as conn:
        cursor = conn.execute("DELETE FROM scheduled_cron_jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
        conn.commit()
        return cursor.rowcount > 0


async def get_due_cron_jobs() -> List[Dict[str, Any]]:
    """Get all active recurring cron jobs whose next_run is due."""
    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, title, prompt_instruction, interval_minutes 
            FROM scheduled_cron_jobs 
            WHERE is_active = 1 AND next_run <= ?
            """,
            (now_str,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def update_cron_job_after_run(job_id: int, interval_minutes: int):
    """Update last_run and advance next_run for a recurring cron job."""
    from datetime import datetime, timedelta
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    next_run = (datetime.now() + timedelta(minutes=interval_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE scheduled_cron_jobs SET last_run = ?, next_run = ? WHERE id = ?",
            (now_str, next_run, job_id)
        )
        await db.commit()


# --- Subagent Task Storage ---
def save_subagent_task_sync(task_id: str, user_id: int, chat_id: int, role: str, description: str):
    """Save initial subagent task."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO subagent_tasks (id, user_id, chat_id, role, task_description, status)
            VALUES (?, ?, ?, ?, ?, 'running')
            """,
            (task_id, user_id, chat_id, role, description)
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
            (status, result, task_id)
        )
        conn.commit()


def get_subagent_task_sync(task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve subagent task status."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT * FROM subagent_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


# --- Chat History Functions ---
async def save_chat_message(user_id: int, role: str, content: str):
    """Save a chat message to history."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        await db.commit()


async def get_recent_chat_history(user_id: int, limit: int = 15) -> List[Dict[str, str]]:
    """Get the most recent messages for a user in chronological order."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT role, content FROM chat_history 
            WHERE user_id = ? 
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            # Reverse so it's in chronological order
            history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
            return history


async def clear_user_chat_history(user_id: int):
    """Clear chat history for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await db.commit()


# --- Long-Term Knowledge Memory Functions ---
def save_memory_fact_sync(user_id: int, key_topic: str, content: str, category: str = "general") -> str:
    """Synchronously save or update a persistent memory fact (for tools)."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_memory (user_id, category, key_topic, content, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, key_topic) DO UPDATE SET
                content = excluded.content,
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, category.strip().lower(), key_topic.strip().lower(), content.strip())
        )
        conn.commit()
    return f"Memori '{key_topic}' berhasil disimpan dalam kategori '{category}'."


async def save_memory_fact(user_id: int, key_topic: str, content: str, category: str = "general") -> str:
    """Async save or update a persistent fact/memory."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO knowledge_memory (user_id, category, key_topic, content, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, key_topic) DO UPDATE SET
                content = excluded.content,
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, category.strip().lower(), key_topic.strip().lower(), content.strip())
        )
        await db.commit()
        return f"Memori '{key_topic}' berhasil disimpan."


def search_memories_sync(user_id: int, query: str) -> List[Dict[str, Any]]:
    """Synchronously search memories for a specific user."""
    with get_sync_db() as conn:
        pattern = f"%{query.strip().lower()}%"
        cursor = conn.execute(
            """
            SELECT category, key_topic, content, updated_at FROM knowledge_memory 
            WHERE user_id = ? AND (LOWER(key_topic) LIKE ? OR LOWER(content) LIKE ?)
            ORDER BY updated_at DESC
            """,
            (user_id, pattern, pattern)
        )
        rows = cursor.fetchall()
        return [{"category": r["category"], "key_topic": r["key_topic"], "content": r["content"]} for r in rows]


async def get_all_memories(user_id: int) -> List[Dict[str, Any]]:
    """Retrieve all long-term memories for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT category, key_topic, content, updated_at FROM knowledge_memory WHERE user_id = ? ORDER BY category, key_topic",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def search_memories(user_id: int, query: str) -> List[Dict[str, Any]]:
    """Search long-term memories matching query for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        search_pattern = f"%{query.strip().lower()}%"
        async with db.execute(
            """
            SELECT category, key_topic, content FROM knowledge_memory 
            WHERE user_id = ? AND (LOWER(key_topic) LIKE ? OR LOWER(content) LIKE ?)
            ORDER BY updated_at DESC
            """,
            (user_id, search_pattern, search_pattern)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def delete_memory(user_id: int, key_topic: str) -> bool:
    """Delete a specific memory."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM knowledge_memory WHERE user_id = ? AND LOWER(key_topic) = ?",
            (user_id, key_topic.strip().lower())
        )
        await db.commit()
        return cursor.rowcount > 0


# --- Reminders / Scheduled Tasks ---
def add_reminder_sync(user_id: int, chat_id: int, reminder_time_iso: str, message: str) -> int:
    """Synchronously add a scheduled reminder (for tools)."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (user_id, chat_id, reminder_time, message)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, chat_id, reminder_time_iso, message)
        )
        conn.commit()
        return cursor.lastrowid


async def add_reminder(user_id: int, chat_id: int, reminder_time_iso: str, message: str) -> int:
    """Add a scheduled reminder."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO reminders (user_id, chat_id, reminder_time, message)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, chat_id, reminder_time_iso, message)
        )
        await db.commit()
        return cursor.lastrowid


async def get_due_reminders() -> List[Dict[str, Any]]:
    """Get all pending reminders that are due now."""
    now_iso = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, message, reminder_time 
            FROM reminders 
            WHERE is_executed = 0 AND reminder_time <= ?
            """,
            (now_iso,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def mark_reminder_executed(reminder_id: int):
    """Mark reminder as completed."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET is_executed = 1 WHERE id = ?", (reminder_id,))
        await db.commit()


# --- User Settings ---
async def get_user_settings(user_id: int) -> Dict[str, Any]:
    """Get settings for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT voice_reply, system_prompt_override, model_name FROM user_settings WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {"voice_reply": 0, "system_prompt_override": None, "model_name": "gemini-2.5-flash"}


async def toggle_voice_setting(user_id: int) -> bool:
    """Toggle voice reply setting on/off."""
    current = await get_user_settings(user_id)
    new_val = 0 if current.get("voice_reply", 0) == 1 else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_settings (user_id, voice_reply)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET voice_reply = excluded.voice_reply
            """,
            (user_id, new_val)
        )
        await db.commit()
    return bool(new_val)


# --- Knowledge Graph (Semantic Relations & Second Brain) ---
def add_knowledge_relation_sync(user_id: int, entity: str, relation: str, target_value: str, category: str = "general", tags: str = "") -> Dict[str, Any]:
    """Synchronously insert or update a semantic relation in the knowledge graph."""
    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_graph (user_id, entity, relation, target_value, category, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, entity, relation) DO UPDATE SET 
                target_value = excluded.target_value,
                category = excluded.category,
                tags = excluded.tags,
                created_at = CURRENT_TIMESTAMP
            """,
            (user_id, entity, relation, target_value, category, tags)
        )
        conn.commit()
    return {
        "status": "success",
        "entity": entity,
        "relation": relation,
        "target_value": target_value,
        "category": category,
        "tags": tags
    }


def search_knowledge_graph_sync(user_id: int, query: str) -> List[Dict[str, Any]]:
    """Synchronously search the knowledge graph by entity, relation, target, or tags."""
    pattern = f"%{query}%"
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT entity, relation, target_value, category, tags, created_at
            FROM knowledge_graph
            WHERE user_id = ? AND (entity LIKE ? OR relation LIKE ? OR target_value LIKE ? OR tags LIKE ?)
            ORDER BY created_at DESC LIMIT 25
            """,
            (user_id, pattern, pattern, pattern, pattern)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def get_all_knowledge_graph_sync(user_id: int) -> List[Dict[str, Any]]:
    """Retrieve all semantic relations in user's knowledge graph."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT entity, relation, target_value, category, tags, created_at
            FROM knowledge_graph
            WHERE user_id = ?
            ORDER BY category, entity
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def export_full_second_brain_sync(user_id: int) -> Dict[str, Any]:
    """Export complete user knowledge base: facts + semantic knowledge graph."""
    with get_sync_db() as conn:
        # Facts
        c1 = conn.execute("SELECT category, key_topic, content, updated_at FROM knowledge_memory WHERE user_id = ?", (user_id,))
        facts = [dict(r) for r in c1.fetchall()]
        # Relations
        c2 = conn.execute("SELECT entity, relation, target_value, category, tags, created_at FROM knowledge_graph WHERE user_id = ?", (user_id,))
        relations = [dict(r) for r in c2.fetchall()]
        
        return {
            "user_id": user_id,
            "exported_at": datetime.now().isoformat(),
            "total_facts": len(facts),
            "total_relations": len(relations),
            "facts": facts,
            "knowledge_graph": relations
        }


# --- Focus & Productivity Sessions (Pomodoro) ---
def start_focus_session_sync(user_id: int, chat_id: int, title: str, duration_minutes: int, notes: str = "") -> Dict[str, Any]:
    """Synchronously create and start a focus session."""
    from datetime import datetime, timedelta
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    end_iso = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO focus_sessions (user_id, chat_id, title, duration_minutes, end_time, status, notes)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (user_id, chat_id, title, duration_minutes, end_iso, notes)
        )
        conn.commit()
        session_id = cursor.lastrowid
        
    return {
        "status": "success",
        "session_id": session_id,
        "title": title,
        "duration_minutes": duration_minutes,
        "end_time": end_iso
    }


async def get_due_focus_sessions() -> List[Dict[str, Any]]:
    """Retrieve active focus sessions that have reached their end_time."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, title, duration_minutes, end_time, notes
            FROM focus_sessions
            WHERE status = 'active' AND is_notified = 0 AND end_time <= ?
            """,
            (now_iso,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def mark_focus_session_completed(session_id: int):
    """Mark a focus session as completed and notified."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE focus_sessions SET status = 'completed', is_notified = 1 WHERE id = ?",
            (session_id,)
        )
        await db.commit()


