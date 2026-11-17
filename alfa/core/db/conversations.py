"""Dashboard conversation threads (additive, multi-thread chat history).

Threads are stored in ``conversations``; messages remain in ``chat_history``
with a nullable ``conversation_id`` so Telegram/WhatsApp history keeps working
unchanged (NULL = legacy/global channel history).

All functions are intentionally small and fail-safe; the dashboard degrades to
a single global thread if the additive schema cannot be created.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any

import aiosqlite

from alfa.core.db.connection import _get_db_path, get_sync_db

logger = logging.getLogger("DB.Conversations")

_SCHEMA_READY: set[str] = set()
_DEFAULT_TITLE = "Obrolan Baru"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_chat_schema_sync(force: bool = False) -> bool:
    """Create thread tables/columns if missing. Idempotent and cheap."""
    path = str(_get_db_path())
    if not force and path in _SCHEMA_READY:
        return True
    try:
        with get_sync_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT 'Obrolan Baru',
                    model TEXT DEFAULT '',
                    pinned INTEGER DEFAULT 0,
                    archived INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_user "
                "ON conversations(user_id, pinned DESC, updated_at DESC)"
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_history)")}
            if "conversation_id" not in cols:
                conn.execute("ALTER TABLE chat_history ADD COLUMN conversation_id TEXT")
            if "metadata" not in cols:
                conn.execute(
                    "ALTER TABLE chat_history ADD COLUMN metadata TEXT DEFAULT '{}'"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_history_conv "
                "ON chat_history(user_id, conversation_id, id)"
            )
            conn.commit()
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        logger.warning("Skema percakapan belum siap: %s", exc)
        return False
    _SCHEMA_READY.add(path)
    return True


def _clean_title(title: str | None, fallback: str = _DEFAULT_TITLE) -> str:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if not text:
        return fallback
    return text[:120]


def derive_title(prompt: str | None, max_len: int = 64) -> str:
    """Judul ringkas dari pesan pertama (bukan generate LLM; murah & deterministik)."""
    text = str(prompt or "")
    text = re.sub(r"^\[MODE SPESIALIS:[^\]]+\]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\[[^\]]{1,80}\]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return _DEFAULT_TITLE
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


async def create_conversation(
    user_id: int,
    title: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Create a thread and return its public dict."""
    ensure_chat_schema_sync()
    conv_id = uuid.uuid4().hex
    now = _now()
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            """
            INSERT INTO conversations
                (id, user_id, title, model, pinned, archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (conv_id, int(user_id), _clean_title(title), str(model or ""), now, now),
        )
        await db.commit()
    return {
        "id": conv_id,
        "user_id": int(user_id),
        "title": _clean_title(title),
        "model": str(model or ""),
        "pinned": 0,
        "archived": 0,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "last_message": "",
    }


async def list_conversations(
    user_id: int,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List non-archived threads, pinned first, newest activity first."""
    ensure_chat_schema_sync()
    limit = max(1, min(int(limit or 50), 200))
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    like = f"%{q}%"
    where = "c.user_id = ? AND c.archived = 0"
    params: list[Any] = [int(user_id)]
    if q:
        where += (
            " AND (c.title LIKE ? OR EXISTS ("
            "SELECT 1 FROM chat_history h WHERE h.conversation_id = c.id "
            "AND h.user_id = c.user_id AND h.content LIKE ?))"
        )
        params.extend([like, like])
    params.append(limit)
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT c.id, c.user_id, c.title, c.model, c.pinned, c.archived,
                   c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM chat_history h
                    WHERE h.conversation_id = c.id AND h.user_id = c.user_id)
                       AS message_count,
                   COALESCE((SELECT h.content FROM chat_history h
                    WHERE h.conversation_id = c.id AND h.user_id = c.user_id
                    ORDER BY h.id DESC LIMIT 1), '') AS last_message
            FROM conversations c
            WHERE {where}
            ORDER BY c.pinned DESC, c.updated_at DESC
            LIMIT ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "model": row["model"] or "",
            "pinned": int(row["pinned"] or 0),
            "archived": int(row["archived"] or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"] or 0),
            "last_message": str(row["last_message"] or "")[:180],
        }
        for row in rows
    ]


async def get_conversation(user_id: int, conversation_id: str) -> dict[str, Any] | None:
    ensure_chat_schema_sync()
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT c.id, c.user_id, c.title, c.model, c.pinned, c.archived,
                   c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM chat_history h
                    WHERE h.conversation_id = c.id AND h.user_id = c.user_id)
                       AS message_count
            FROM conversations c
            WHERE c.id = ? AND c.user_id = ?
            """,
            (str(conversation_id), int(user_id)),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "model": row["model"] or "",
        "pinned": int(row["pinned"] or 0),
        "archived": int(row["archived"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": int(row["message_count"] or 0),
    }


async def get_messages(
    user_id: int,
    conversation_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return messages in chronological order (oldest → newest)."""
    ensure_chat_schema_sync()
    limit = max(1, min(int(limit or 200), 1000))
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, role, content, timestamp, COALESCE(metadata, '{}') AS metadata
            FROM (
                SELECT id, role, content, timestamp, metadata
                FROM chat_history
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY id DESC LIMIT ?
            )
            ORDER BY id ASC
            """,
            (int(user_id), str(conversation_id), limit),
        ) as cursor:
            rows = await cursor.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = {}
        out.append(
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["timestamp"],
                "metadata": meta if isinstance(meta, dict) else {},
            }
        )
    return out


async def rename_conversation(
    user_id: int, conversation_id: str, title: str
) -> bool:
    ensure_chat_schema_sync()
    clean = _clean_title(title)
    async with aiosqlite.connect(_get_db_path()) as db:
        cur = await db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (clean, _now(), str(conversation_id), int(user_id)),
        )
        await db.commit()
        return bool(cur.rowcount)


async def set_pinned(user_id: int, conversation_id: str, pinned: bool) -> bool:
    ensure_chat_schema_sync()
    async with aiosqlite.connect(_get_db_path()) as db:
        cur = await db.execute(
            "UPDATE conversations SET pinned = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (1 if pinned else 0, _now(), str(conversation_id), int(user_id)),
        )
        await db.commit()
        return bool(cur.rowcount)


async def delete_conversation(user_id: int, conversation_id: str) -> bool:
    ensure_chat_schema_sync()
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            "DELETE FROM chat_history WHERE user_id = ? AND conversation_id = ?",
            (int(user_id), str(conversation_id)),
        )
        cur = await db.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (str(conversation_id), int(user_id)),
        )
        await db.commit()
        return bool(cur.rowcount)


async def get_last_user_message(
    user_id: int, conversation_id: str
) -> dict[str, Any] | None:
    ensure_chat_schema_sync()
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, role, content, timestamp
            FROM chat_history
            WHERE user_id = ? AND conversation_id = ? AND role = 'user'
            ORDER BY id DESC LIMIT 1
            """,
            (int(user_id), str(conversation_id)),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "timestamp": row["timestamp"],
    }


async def delete_messages_from(
    user_id: int, conversation_id: str, message_id: int
) -> int:
    """Delete a message and everything after it (edit/regenerate)."""
    ensure_chat_schema_sync()
    async with aiosqlite.connect(_get_db_path()) as db:
        cur = await db.execute(
            "DELETE FROM chat_history "
            "WHERE user_id = ? AND conversation_id = ? AND id >= ?",
            (int(user_id), str(conversation_id), int(message_id)),
        )
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
            (_now(), str(conversation_id), int(user_id)),
        )
        await db.commit()
        return int(cur.rowcount or 0)


async def update_message_metadata(
    user_id: int,
    conversation_id: str,
    metadata: dict[str, Any],
    message_id: int | None = None,
) -> bool:
    """Attach UI metadata (tools, artifacts, latency) to a message."""
    ensure_chat_schema_sync()
    try:
        payload = json.dumps(metadata or {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = "{}"
    async with aiosqlite.connect(_get_db_path()) as db:
        if message_id is None:
            cur = await db.execute(
                "UPDATE chat_history SET metadata = ? "
                "WHERE id = (SELECT MAX(id) FROM chat_history "
                "WHERE user_id = ? AND conversation_id = ?)",
                (payload, int(user_id), str(conversation_id)),
            )
        else:
            cur = await db.execute(
                "UPDATE chat_history SET metadata = ? "
                "WHERE id = ? AND user_id = ? AND conversation_id = ?",
                (payload, int(message_id), int(user_id), str(conversation_id)),
            )
        await db.commit()
        return bool(cur.rowcount)


async def touch_conversation(user_id: int, conversation_id: str) -> None:
    ensure_chat_schema_sync()
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
            (_now(), str(conversation_id), int(user_id)),
        )
        await db.commit()


__all__ = [
    "ensure_chat_schema_sync",
    "derive_title",
    "create_conversation",
    "list_conversations",
    "get_conversation",
    "get_messages",
    "rename_conversation",
    "set_pinned",
    "delete_conversation",
    "get_last_user_message",
    "delete_messages_from",
    "update_message_metadata",
    "touch_conversation",
]
