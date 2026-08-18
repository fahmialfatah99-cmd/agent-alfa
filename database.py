"""
Database module for Telegram AI Bot.
Handles persistent chat history, long-term knowledge memory, reminders, and settings.
"""

import aiosqlite
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")


async def init_db():
    """Initialize SQLite database tables."""
    async with aiosqlite.connect(DB_PATH) as db:
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
        
        # User Settings (e.g. voice_mode, preferred_model)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                voice_reply INTEGER DEFAULT 0,
                system_prompt_override TEXT,
                model_name TEXT DEFAULT 'gemini-2.5-flash'
            )
        """)
        await db.commit()


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
async def save_memory_fact(user_id: int, key_topic: str, content: str, category: str = "general") -> str:
    """Save or update a persistent fact/memory."""
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
            (user_id, category, key_topic.strip().lower(), content.strip())
        )
        await db.commit()
        return f"Memori '{key_topic}' berhasil disimpan."


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
    """Search long-term memories matching query."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        search_pattern = f"%{query.strip().lower()}%"
        async with db.execute(
            """
            SELECT category, key_topic, content FROM knowledge_memory 
            WHERE user_id = ? AND (LOWER(key_topic) LIKE ? OR LOWER(content) LIKE ?)
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
