"""
Long-Term Knowledge Memory, Semantic Knowledge Graph, Chat History & Settings.
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

import aiosqlite

from alfa.core.db.connection import _get_db_path, get_sync_db
from alfa.core.db.conversations import derive_title, ensure_chat_schema_sync
from alfa.core.runtime_ctx import get_current_conversation_id

logger = logging.getLogger("DB.Memory")


# --- Chat History Functions ---
async def save_chat_message(
    user_id: int,
    role: str,
    content: str,
    conversation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    """Save a chat message to history.

    ``conversation_id`` mengisolasi thread dashboard. Bila tidak diberikan,
    nilai diambil dari runtime context; kanal Telegram/WhatsApp tidak pernah
    mensetnya sehingga tetap memakai riwayat global (NULL).
    """
    ensure_chat_schema_sync()
    raw_cid = (
        conversation_id if conversation_id is not None else get_current_conversation_id()
    )
    cid: str | None = str(raw_cid or "").strip() or None
    try:
        meta_json = json.dumps(metadata or {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        meta_json = "{}"

    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(_get_db_path()) as db:
        if cid:
            # Pastikan thread ada (mis. pesan pertama setelah reload/restart).
            title = derive_title(content) if role == "user" else "Obrolan Baru"
            await db.execute(
                "INSERT OR IGNORE INTO conversations "
                "(id, user_id, title, model, pinned, archived, created_at, updated_at) "
                "VALUES (?, ?, ?, '', 0, 0, ?, ?)",
                (cid, user_id, title, now_local, now_local),
            )
        cursor = await db.execute(
            "INSERT INTO chat_history (user_id, role, content, conversation_id, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, cid, meta_json),
        )
        if cid:
            await db.execute(
                "UPDATE conversations SET updated_at = ?, "
                "title = CASE WHEN ? = 'user' AND (title = '' OR title = 'Obrolan Baru') "
                "THEN ? ELSE title END WHERE id = ? AND user_id = ?",
                (now_local, role, derive_title(content), cid, user_id),
            )
        await db.commit()
        return int(cursor.lastrowid or 0) or None


async def get_recent_chat_history(
    user_id: int,
    limit: int = 15,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get the most recent messages for a user/thread in chronological order."""
    ensure_chat_schema_sync()
    cid = conversation_id if conversation_id is not None else get_current_conversation_id()
    cid = str(cid or "").strip()
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        if cid:
            sql = (
                "SELECT id, role, content, timestamp, "
                "COALESCE(metadata, '{}') AS metadata FROM chat_history "
                "WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY id DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (user_id, cid, limit)
        else:
            # Riwayat kanal global. Pesan dashboard ber-conversation_id tidak
            # boleh bocor ke konteks Telegram/WhatsApp.
            sql = (
                "SELECT id, role, content, timestamp, "
                "COALESCE(metadata, '{}') AS metadata FROM chat_history "
                "WHERE user_id = ? AND conversation_id IS NULL "
                "ORDER BY id DESC LIMIT ?"
            )
            params = (user_id, limit)
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in reversed(list(rows)):
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


async def clear_user_chat_history(
    user_id: int, conversation_id: str | None = None
) -> None:
    """Clear chat history for a user, or only one dashboard thread."""
    ensure_chat_schema_sync()
    cid = conversation_id if conversation_id is not None else get_current_conversation_id()
    cid = str(cid or "").strip()
    async with aiosqlite.connect(_get_db_path()) as db:
        if cid:
            await db.execute(
                "DELETE FROM chat_history WHERE user_id = ? AND conversation_id = ?",
                (user_id, cid),
            )
        else:
            await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
            try:
                # Thread dashboard hanya berisi pesan yang baru saja dihapus;
                # hapus juga metadatanya supaya tidak tersisa thread kosong.
                await db.execute(
                    "DELETE FROM conversations WHERE user_id = ?", (user_id,)
                )
            except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
                logger.debug("conversations tidak dihapus untuk user %s: %s", user_id, e)
            try:
                await db.execute(
                    "DELETE FROM chat_compactions WHERE user_id = ?", (user_id,)
                )
            except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
                logger.debug("chat_compactions tidak dihapus untuk user %s: %s", user_id, e)
        await db.commit()


# --- Long-Term Knowledge Memory Functions ---
def save_memory_fact_sync(
    user_id: int, key_topic: str, content: str, category: str = "general"
) -> str:
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
            (
                user_id,
                category.strip().lower(),
                key_topic.strip().lower(),
                content.strip(),
            ),
        )
        conn.commit()
    return f"Memori '{key_topic}' berhasil disimpan dalam kategori '{category}'."


async def save_memory_fact(
    user_id: int, key_topic: str, content: str, category: str = "general"
) -> str:
    """Async save or update a persistent fact/memory."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            """
            INSERT INTO knowledge_memory (user_id, category, key_topic, content, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, key_topic) DO UPDATE SET
                content = excluded.content,
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                category.strip().lower(),
                key_topic.strip().lower(),
                content.strip(),
            ),
        )
        await db.commit()
        return f"Memori '{key_topic}' berhasil disimpan."


def search_memories_sync(user_id: int, query: str) -> list[dict[str, Any]]:
    """Synchronously search memories for a specific user."""
    with get_sync_db() as conn:
        pattern = f"%{query.strip().lower()}%"
        cursor = conn.execute(
            """
            SELECT category, key_topic, content, updated_at FROM knowledge_memory
            WHERE user_id = ? AND (LOWER(key_topic) LIKE ? OR LOWER(content) LIKE ?)
            ORDER BY updated_at DESC
            """,
            (user_id, pattern, pattern),
        )
        rows = cursor.fetchall()
        return [
            {
                "category": r["category"],
                "key_topic": r["key_topic"],
                "content": r["content"],
            }
            for r in rows
        ]


async def get_all_memories(user_id: int) -> list[dict[str, Any]]:
    """Retrieve all long-term memories for a user."""
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT category, key_topic, content, updated_at FROM knowledge_memory WHERE user_id = ? ORDER BY category, key_topic",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def search_memories(user_id: int, query: str) -> list[dict[str, Any]]:
    """Search long-term memories matching query for a user."""
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        search_pattern = f"%{query.strip().lower()}%"
        async with db.execute(
            """
            SELECT category, key_topic, content FROM knowledge_memory
            WHERE user_id = ? AND (LOWER(key_topic) LIKE ? OR LOWER(content) LIKE ?)
            ORDER BY updated_at DESC
            """,
            (user_id, search_pattern, search_pattern),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def delete_memory(user_id: int, key_topic: str) -> bool:
    """Delete a specific memory."""
    async with aiosqlite.connect(_get_db_path()) as db:
        cursor = await db.execute(
            "DELETE FROM knowledge_memory WHERE user_id = ? AND LOWER(key_topic) = ?",
            (user_id, key_topic.strip().lower()),
        )
        await db.commit()
        return bool(cursor.rowcount and cursor.rowcount > 0)


# --- Knowledge Graph (Semantic Relations & Second Brain) ---
def add_knowledge_relation_sync(
    user_id: int,
    entity: str,
    relation: str,
    target_value: str,
    category: str = "general",
    tags: str = "",
) -> dict[str, Any]:
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
            (user_id, entity, relation, target_value, category, tags),
        )
        conn.commit()
    return {
        "status": "success",
        "entity": entity,
        "relation": relation,
        "target_value": target_value,
        "category": category,
        "tags": tags,
    }


def search_knowledge_graph_sync(user_id: int, query: str) -> list[dict[str, Any]]:
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
            (user_id, pattern, pattern, pattern, pattern),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def get_all_knowledge_graph_sync(user_id: int) -> list[dict[str, Any]]:
    """Retrieve all semantic relations in user's knowledge graph."""
    with get_sync_db() as conn:
        cursor = conn.execute(
            """
            SELECT entity, relation, target_value, category, tags, created_at
            FROM knowledge_graph
            WHERE user_id = ?
            ORDER BY category, entity
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def export_full_second_brain_sync(user_id: int) -> dict[str, Any]:
    """Export complete user knowledge base: facts + semantic knowledge graph."""
    with get_sync_db() as conn:
        c1 = conn.execute(
            "SELECT category, key_topic, content, updated_at FROM knowledge_memory WHERE user_id = ?",
            (user_id,),
        )
        facts = [dict(r) for r in c1.fetchall()]
        c2 = conn.execute(
            "SELECT entity, relation, target_value, category, tags, created_at FROM knowledge_graph WHERE user_id = ?",
            (user_id,),
        )
        relations = [dict(r) for r in c2.fetchall()]

        return {
            "user_id": user_id,
            "exported_at": datetime.now().isoformat(),
            "total_facts": len(facts),
            "total_relations": len(relations),
            "facts": facts,
            "knowledge_graph": relations,
        }


# --- User Settings ---
async def get_user_settings(user_id: int) -> dict[str, Any]:
    """Get settings for a user."""
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT voice_reply, system_prompt_override, model_name FROM user_settings WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {
                "voice_reply": 0,
                "system_prompt_override": None,
                "model_name": "gemini-3.5-flash",
            }


async def toggle_voice_setting(user_id: int) -> bool:
    """Toggle voice reply setting on/off (atomic read-modify-write)."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await db.execute(
            """
            INSERT INTO user_settings (user_id, voice_reply)
            VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET voice_reply = 1 - voice_reply
            """,
            (user_id,),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT voice_reply FROM user_settings WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
    return bool(row and row[0])
