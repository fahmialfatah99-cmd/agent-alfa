"""
Database module for Telegram AI Bot.
Handles persistent chat history, long-term knowledge memory, reminders, and settings.
"""

import aiosqlite
import sqlite3
import os
import json
import contextlib
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")


def init_db_sync():
    """Synchronously ensure all SQLite tables and indices exist."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
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
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                api_key TEXT NOT NULL,
                base_url TEXT,
                default_model TEXT NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS custom_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL,
                persona TEXT NOT NULL,
                system_instruction TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'gemini',
                model TEXT NOT NULL DEFAULT 'gemini-2.5-flash',
                api_key_id INTEGER,
                avatar_emoji TEXT DEFAULT '🤖',
                color_theme TEXT DEFAULT 'cyan',
                is_enabled INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
            );
            CREATE TABLE IF NOT EXISTS agent_meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                participants TEXT NOT NULL,
                dialogue_transcript TEXT NOT NULL,
                consensus TEXT,
                action_plan TEXT,
                mode TEXT DEFAULT 'plan',
                execution_results TEXT DEFAULT '',
                status TEXT DEFAULT 'completed',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS agent_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER,
                agent_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                tool_name TEXT,
                tool_input TEXT,
                tool_output TEXT,
                status TEXT DEFAULT 'success',
                duration_ms REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS api_token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                provider TEXT NOT NULL,
                model TEXT DEFAULT '',
                key_id INTEGER,
                key_label TEXT DEFAULT '',
                context TEXT DEFAULT '',
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_atu_ts ON api_token_usage(ts);
            CREATE INDEX IF NOT EXISTS idx_atu_key ON api_token_usage(key_id);
        """)
        
        # Seed default API key from environment if empty
        row = conn.execute("SELECT COUNT(*) as count FROM api_keys").fetchone()
        if row and row[0] == 0:
            env_gemini_key = os.getenv("GEMINI_API_KEY", "")
            if env_gemini_key:
                conn.execute(
                    """
                    INSERT INTO api_keys (name, provider, api_key, default_model, is_active)
                    VALUES ('Default Gemini Key', 'gemini', ?, 'gemini-2.5-flash', 1)
                    """,
                    (env_gemini_key,)
                )

        # Seed default autonomous workforce agents if empty
        agent_count = conn.execute("SELECT COUNT(*) as count FROM custom_agents").fetchone()
        if agent_count and agent_count[0] == 0:
            default_agents = [
                (
                    "Alpha Lead",
                    "Chief Orchestrator & Project Director",
                    "Visioner, bijaksana, fokus pada tujuan akhir dan koordinasi tim.",
                    "Kamu adalah Alpha Lead, ketua tim AI otonom. Tugasmu memimpin rapat, membagi tugas ke spesialis lain, menyelaraskan perbedaan pendapat, dan merumuskan konsensus akhir yang solutif dan realistis.",
                    "gemini",
                    "gemini-2.5-flash",
                    "👑",
                    "cyan"
                ),
                (
                    "Code Crafter",
                    "Senior Software Architect & Fullstack Engineer",
                    "Presisi teknis tinggi, berorientasi kode efisien, arsitektur bersih.",
                    "Kamu adalah Code Crafter, ahli rekayasa perangkat lunak dan arsitektur kode. Tugasmu menganalisis aspek teknis, memilih algoritma/tools yang tepat, menyusun struktur modul, dan mengimplementasikan kode yang tangguh.",
                    "gemini",
                    "gemini-2.5-flash",
                    "⚡",
                    "emerald"
                ),
                (
                    "System Auditor",
                    "Security, Performance & Quality Critic",
                    "Kritis, teliti, mendeteksi celah keamanan, bug tersembunyi, dan bottleneck sistem.",
                    "Kamu adalah System Auditor, penguji kritis tim. Tugasmu menguji setiap ide yang diajukan, mencari potensi kelemahan, celah keamanan, skalabilitas, dan memastikan standar kualitas terbaik.",
                    "gemini",
                    "gemini-2.5-flash",
                    "🛡️",
                    "rose"
                ),
                (
                    "Researcher Prime",
                    "Deep Intel & Fact-Checking Specialist",
                    "Objektif, berbasis data dan riset literatur, up-to-date dengan teknologi modern.",
                    "Kamu adalah Researcher Prime, spesialis riset dan verifikasi data. Tugasmu menyajikan fakta ilmiah, tren teknologi terbaru, dokumentasi library resmi, dan benchmark empiris.",
                    "gemini",
                    "gemini-2.5-flash",
                    "🌐",
                    "violet"
                ),
                (
                    "Strategic Planner",
                    "Product Strategist & UX Visionary",
                    "Berorientasi pengguna, praktis, menyusun roadmap dan efisiensi alur kerja.",
                    "Kamu adalah Strategic Planner, perencana produk dan strategi alur kerja. Tugasmu memastikan solusi mudah digunakan oleh manusia, memiliki dampak bisnis yang jelas, dan membagi proyek menjadi tahapan aksi konkret.",
                    "gemini",
                    "gemini-2.5-flash",
                    "💡",
                    "amber"
                )
            ]
            for name, role, persona, sys_inst, prov, model, emoji, color in default_agents:
                conn.execute(
                    """
                    INSERT INTO custom_agents (name, role, persona, system_instruction, provider, model, avatar_emoji, color_theme, is_enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (name, role, persona, sys_inst, prov, model, emoji, color)
                )

        # Schema migrations for agent_meetings
        try:
            conn.execute("ALTER TABLE agent_meetings ADD COLUMN mode TEXT DEFAULT 'plan'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE agent_meetings ADD COLUMN execution_results TEXT DEFAULT ''")
        except Exception:
            pass

        conn.commit()
    finally:
        conn.close()


# Auto-initialize database tables synchronously on import
try:
    init_db_sync()
except Exception as _init_err:
    import logging
    logging.getLogger(__name__).error(
        f"init_db_sync failed on import: {_init_err}. "
        "Database may be missing tables - check disk space/permissions/corruption."
    )


def get_sync_db():
    """Get a synchronous SQLite connection wrapped so `with` blocks close it.

    sqlite3.Connection's own context manager only commits/rolls back the
    transaction; wrapping in contextlib.closing guarantees the connection
    (and its WAL file descriptors) are released when the block exits.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return contextlib.closing(conn)


async def init_db():
    """Initialize SQLite database tables and enable WAL mode (async wrapper).

    Delegates to the canonical sync schema so both paths always create the
    exact same tables, seeds, and migrations.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, init_db_sync)


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


def list_subagent_tasks_sync(limit: int = 20) -> List[Dict[str, Any]]:
    """List recent subagent autonomous background tasks."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM subagent_tasks 
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def log_agent_activity_sync(agent_id: Optional[int], agent_name: str, action_type: str, 
                            description: str, tool_name: Optional[str] = None, 
                            tool_input: Optional[str] = None, tool_output: Optional[str] = None, 
                            status: str = "success", duration_ms: float = 0.0) -> int:
    """Record an agent tool execution or real-time activity log."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_activity_logs (agent_id, agent_name, action_type, description, tool_name, tool_input, tool_output, status, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, agent_name, action_type, description, tool_name, tool_input, tool_output, status, duration_ms)
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
            (limit,)
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


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
    """Toggle voice reply setting on/off (atomic read-modify-write)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_settings (user_id, voice_reply)
            VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET voice_reply = 1 - voice_reply
            """,
            (user_id,)
        )
        await db.commit()
        cursor = await db.execute("SELECT voice_reply FROM user_settings WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
    return bool(row and row[0])


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


# --- API Key Multi-Provider Vault ---
def mask_key(k: str) -> str:
    if not k or len(k) <= 8:
        return "••••••••"
    return k[:4] + "••••••••" + k[-4:]


def list_api_keys_sync() -> List[Dict[str, Any]]:
    """List all configured API keys with masked key values."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT id, name, provider, api_key, base_url, default_model, is_active, created_at FROM api_keys ORDER BY id ASC")
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "name": r["name"],
                "provider": r["provider"],
                "masked_key": mask_key(r["api_key"]),
                "base_url": r["base_url"] or "",
                "default_model": r["default_model"],
                "is_active": bool(r["is_active"]),
                "created_at": str(r["created_at"])
            })
        return results


def add_api_key_sync(name: str, provider: str, api_key: str, default_model: str, base_url: str = "", set_active: bool = False) -> Dict[str, Any]:
    """Add a new API key to the vault."""
    provider_norm = provider.strip().lower()
    with get_sync_db() as conn:
        if set_active:
            conn.execute("UPDATE api_keys SET is_active = 0 WHERE provider = ?", (provider_norm,))
        cursor = conn.execute(
            """
            INSERT INTO api_keys (name, provider, api_key, base_url, default_model, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, provider_norm, api_key.strip(), base_url.strip() if base_url else None, default_model, 1 if set_active else 0)
        )
        conn.commit()
        key_id = cursor.lastrowid
    return {"status": "success", "id": key_id, "name": name, "provider": provider_norm}


def activate_api_key_sync(key_id: int) -> Dict[str, Any]:
    """Set an API key as active. The MOST RECENTLY activated key across any
    provider automatically becomes the MAIN BRAIN for the Telegram/Web agent."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT provider FROM api_keys WHERE id = ?", (key_id,))
        row = cursor.fetchone()
        if not row:
            return {"status": "error", "message": "Key not found"}
        prov = row["provider"]
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE provider = ?", (prov,))
        conn.execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
        # Mark this key as the main brain (works cross-provider)
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_key_id', ?)",
            (str(key_id),)
        )
        conn.commit()
    return {"status": "success", "message": f"API key #{key_id} activated & ditetapkan sebagai otak utama"}


def set_main_brain_model(model: str) -> None:
    """Simpan pilihan model eksplisit utk otak utama ('' = ikuti default kunci)."""
    with get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('main_brain_model', ?)",
            ((model or "").strip(),)
        )
        conn.commit()


def get_main_brain_model() -> str:
    """Model override otak utama ('' bila tidak disetel)."""
    try:
        with get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'main_brain_model'"
            ).fetchone()
            return (row[0] or "").strip() if row else ""
    except Exception:
        return ""


def get_main_brain_key_id() -> Optional[int]:
    """Return key id marked as main brain, if still valid."""
    try:
        with get_sync_db() as conn:
            row = conn.execute(
                """
                SELECT k.id FROM system_settings s
                JOIN api_keys k ON k.id = CAST(s.value AS INTEGER) AND k.is_active = 1
                WHERE s.key = 'main_brain_key_id'
                LIMIT 1
                """
            ).fetchone()
            return int(row[0]) if row else None
    except Exception:
        return None


def delete_api_key_sync(key_id: int) -> Dict[str, Any]:
    """Delete an API key from the vault."""
    with get_sync_db() as conn:
        cursor = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        # Detach agents referencing this key so they don't point at a ghost record
        conn.execute("UPDATE custom_agents SET api_key_id = NULL WHERE api_key_id = ?", (key_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"API key #{key_id} not found"}
    return {"status": "success", "message": f"API key #{key_id} deleted"}


def get_active_api_key_sync(provider: str = "gemini") -> Optional[Dict[str, Any]]:
    """Get active API key record for a given provider."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT * FROM api_keys WHERE provider = ? AND is_active = 1 LIMIT 1", (provider.lower(),))
        row = cursor.fetchone()
        if row:
            return dict(row)
        # Fallback to any other key for this provider (prefer active ones)
        cursor = conn.execute(
            "SELECT * FROM api_keys WHERE provider = ? ORDER BY is_active DESC, id ASC LIMIT 1",
            (provider.lower(),)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


# --- Custom Autonomous Agents (AI Workforce) ---
def list_custom_agents_sync() -> List[Dict[str, Any]]:
    """List all registered custom agents."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT a.id, a.name, a.role, a.persona, a.system_instruction, a.provider, a.model, 
                   a.api_key_id, a.avatar_emoji, a.color_theme, a.is_enabled, a.created_at,
                   k.name as key_name
            FROM custom_agents a
            LEFT JOIN api_keys k ON a.api_key_id = k.id
            ORDER BY a.id ASC
            """
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def add_custom_agent_sync(name: str, role: str, persona: str, system_instruction: str, 
                           provider: str = "gemini", model: str = "gemini-2.5-flash", 
                           api_key_id: Optional[int] = None, avatar_emoji: str = "🤖", 
                           color_theme: str = "cyan") -> Dict[str, Any]:
    """Create a new specialized AI agent in the workforce."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO custom_agents (name, role, persona, system_instruction, provider, model, api_key_id, avatar_emoji, color_theme, is_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (name, role, persona, system_instruction, provider, model, api_key_id, avatar_emoji, color_theme)
        )
        conn.commit()
        agent_id = cursor.lastrowid
    return {"status": "success", "id": agent_id, "name": name, "role": role}


def update_custom_agent_sync(agent_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update custom agent configuration."""
    allowed = ["name", "role", "persona", "system_instruction", "provider", "model", "api_key_id", "avatar_emoji", "color_theme", "is_enabled"]
    fields = []
    values = []
    for k, v in updates.items():
        if k in allowed:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        return {"status": "error", "message": "No valid fields to update"}
    values.append(agent_id)
    with get_sync_db() as conn:
        cursor = conn.execute(f"UPDATE custom_agents SET {', '.join(fields)} WHERE id = ?", tuple(values))
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"Agent #{agent_id} not found"}
    return {"status": "success", "message": f"Agent #{agent_id} updated"}


def delete_custom_agent_sync(agent_id: int) -> Dict[str, Any]:
    """Delete a custom agent."""
    with get_sync_db() as conn:
        cursor = conn.execute("DELETE FROM custom_agents WHERE id = ?", (agent_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return {"status": "error", "message": f"Agent #{agent_id} not found"}
    return {"status": "success", "message": f"Agent #{agent_id} deleted"}


def get_custom_agent_sync(name_or_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieve custom agent by name or id."""
    with get_sync_db() as conn:
        if isinstance(name_or_id, int) or (isinstance(name_or_id, str) and name_or_id.isdigit()):
            cursor = conn.execute("SELECT * FROM custom_agents WHERE id = ?", (int(name_or_id),))
        else:
            cursor = conn.execute("SELECT * FROM custom_agents WHERE LOWER(name) = LOWER(?)", (str(name_or_id).strip(),))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


# --- AI Round-Table Meetings (Konferensi & Rapat Antar Agent) ---
def create_agent_meeting_sync(title: str, topic: str, participants: List[str], 
                              dialogue_transcript: List[Dict[str, Any]], 
                              consensus: str, action_plan: str, 
                              mode: str = "plan",
                              execution_results: Any = "",
                              status: str = "completed") -> Dict[str, Any]:
    """Save a completed or active multi-agent meeting with mode and live execution results."""
    exec_str = execution_results if isinstance(execution_results, str) else json.dumps(execution_results, ensure_ascii=False)
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_meetings (title, topic, participants, dialogue_transcript, consensus, action_plan, mode, execution_results, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                topic,
                json.dumps(participants, ensure_ascii=False),
                json.dumps(dialogue_transcript, ensure_ascii=False),
                consensus,
                action_plan,
                mode,
                exec_str,
                status
            )
        )
        conn.commit()
        meeting_id = cursor.lastrowid
    return {"status": "success", "id": meeting_id, "title": title}


def list_agent_meetings_sync(limit: int = 50) -> List[Dict[str, Any]]:
    """List recent meetings with mode information."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            "SELECT id, title, topic, participants, consensus, action_plan, mode, execution_results, status, created_at FROM agent_meetings ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            parts = []
            try:
                parts = json.loads(r["participants"])
            except Exception:
                pass
            
            exec_res = []
            if r["execution_results"]:
                try:
                    exec_res = json.loads(r["execution_results"])
                except Exception:
                    exec_res = r["execution_results"]

            results.append({
                "id": r["id"],
                "title": r["title"],
                "topic": r["topic"],
                "participants": parts,
                "consensus": r["consensus"] or "",
                "action_plan": r["action_plan"] or "",
                "mode": r["mode"] or "plan",
                "execution_results": exec_res,
                "status": r["status"],
                "created_at": str(r["created_at"])
            })
        return results


def get_agent_meeting_sync(meeting_id: int) -> Optional[Dict[str, Any]]:
    """Get full details of a specific meeting including full dialogue transcript and execution results."""
    with get_sync_db() as conn:
        cursor = conn.execute("SELECT * FROM agent_meetings WHERE id = ?", (meeting_id,))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            try:
                d["participants"] = json.loads(d["participants"])
            except Exception:
                pass
            try:
                d["dialogue_transcript"] = json.loads(d["dialogue_transcript"])
            except Exception:
                pass
            if d.get("execution_results"):
                try:
                    d["execution_results"] = json.loads(d["execution_results"])
                except Exception:
                    pass
            return d
    return None





# --- API Token Usage Tracking (Realtime Dashboard) ---
def record_api_usage_sync(provider: str, model: str = "", key_id: int = None,
                          key_label: str = "", context: str = "",
                          prompt_tokens: int = 0, completion_tokens: int = 0) -> bool:
    """Record one LLM call's token consumption. Never raises."""
    try:
        with get_sync_db() as conn:
            conn.execute(
                """
                INSERT INTO api_token_usage
                (provider, model, key_id, key_label, context, prompt_tokens, completion_tokens, total_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (provider, model or "", key_id, key_label or "", context or "",
                 max(0, int(prompt_tokens or 0)), max(0, int(completion_tokens or 0)),
                 max(0, int((prompt_tokens or 0) + (completion_tokens or 0)))),
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

        totals = conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM api_token_usage").fetchone()
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
