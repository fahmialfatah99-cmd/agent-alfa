"""
WhatsApp Read-State Tracking and Deduplication Module.

Manages persistent tracking of messages read/seen by ALFA to prevent
repeated reporting of already-processed WhatsApp messages.
"""

from __future__ import annotations

import logging
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("DB.WATracking")

LAST_READ_TS_KEY = "wa_last_read_ts"


def record_wa_messages_read_sync(messages: list[dict[str, Any]]) -> int:
    """
    Simpan daftar pesan WA ke tabel wa_read_messages agar tidak dibaca/dilaporkan ulang.
    Return jumlah pesan baru yang berhasil dicatat.
    """
    if not messages:
        return 0

    inserted = 0
    max_ts = 0
    with get_sync_db() as conn:
        for m in messages:
            if not isinstance(m, dict):
                continue
            msg_id = str(m.get("msg_id") or m.get("id") or "").strip()
            if not msg_id:
                continue
            chat_id = str(m.get("chat") or m.get("chat_id") or "").strip()
            sender = str(m.get("sender_name") or m.get("sender") or m.get("author") or "").strip()
            msg_ts = int(m.get("msg_ts") or m.get("ts") or 0)
            if msg_ts > max_ts:
                max_ts = msg_ts

            try:
                res = conn.execute(
                    """
                    INSERT OR IGNORE INTO wa_read_messages (msg_id, chat_id, sender, msg_ts, read_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (msg_id, chat_id, sender, msg_ts),
                )
                if res.rowcount > 0:
                    inserted += 1
            except Exception as e:
                logger.debug("Failed to record wa_read_messages for %s: %s", msg_id, e)

        if max_ts > 0:
            try:
                conn.execute(
                    """
                    INSERT INTO system_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = MAX(CAST(value AS INTEGER), CAST(excluded.value AS INTEGER))
                    """,
                    (LAST_READ_TS_KEY, str(max_ts)),
                )
            except Exception:
                pass

        conn.commit()
    return inserted


def get_read_wa_msg_ids_sync(msg_ids: list[str]) -> set[str]:
    """
    Cek ID pesan mana saja yang sudah pernah tercatat sebagai dibaca.
    """
    clean_ids = [str(i).strip() for i in msg_ids if str(i).strip()]
    if not clean_ids:
        return set()

    read_set: set[str] = set()
    with get_sync_db() as conn:
        chunk_size = 50
        for i in range(0, len(clean_ids), chunk_size):
            chunk = clean_ids[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT msg_id FROM wa_read_messages WHERE msg_id IN ({placeholders})",
                chunk,
            ).fetchall()
            for r in rows:
                read_set.add(str(r[0]))
    return read_set


def is_wa_message_read_sync(msg_id: str) -> bool:
    """Cek apakah pesan tertentu sudah dibaca."""
    mid = str(msg_id or "").strip()
    if not mid:
        return False
    with get_sync_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM wa_read_messages WHERE msg_id = ? LIMIT 1", (mid,)
        ).fetchone()
        return row is not None


def mark_chat_read_sync(chat_id: str) -> int:
    """Tandai semua pesan dari chat tertentu yang ada di incoming sebagai dibaca."""
    cid = str(chat_id or "").strip()
    if not cid:
        return 0
    with get_sync_db() as conn:
        res = conn.execute(
            "UPDATE wa_read_messages SET read_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (cid,),
        )
        conn.commit()
        return res.rowcount


def get_last_read_wa_ts_sync() -> int:
    """Ambil timestamp pesan WA terakhir yang sudah dibaca."""
    try:
        with get_sync_db() as conn:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?", (LAST_READ_TS_KEY,)
            ).fetchone()
            if row and row[0]:
                return int(row[0])
    except Exception:
        pass
    return 0


def set_last_read_wa_ts_sync(ts: int) -> None:
    """Set timestamp pesan WA terakhir yang sudah dibaca."""
    try:
        with get_sync_db() as conn:
            conn.execute(
                """
                INSERT INTO system_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (LAST_READ_TS_KEY, str(ts)),
            )
            conn.commit()
    except Exception as e:
        logger.debug("Failed to set last_read_wa_ts: %s", e)


def archive_wa_messages_sync(messages: list[dict[str, Any]]) -> int:
    """
    Arsipkan pesan WhatsApp masuk ke tabel SQLite wa_incoming_archive secara permanen.
    Pesan tidak akan pernah hilang meskipun ring buffer 250 terlewati.
    """
    if not messages:
        return 0

    archived = 0
    with get_sync_db() as conn:
        for m in messages:
            if not isinstance(m, dict):
                continue
            msg_id = str(m.get("msg_id") or m.get("id") or "").strip()
            if not msg_id:
                continue
            chat_id = str(m.get("chat") or m.get("chat_id") or "").strip()
            chat_name = str(m.get("chat_name") or "").strip()
            sender_name = str(m.get("sender_name") or m.get("sender") or m.get("author") or "").strip()
            is_group = 1 if m.get("is_group") else 0
            msg_type = str(m.get("msg_type") or "chat")
            body = str(m.get("body") or "")
            has_media = 1 if m.get("has_media") else 0
            msg_ts = int(m.get("msg_ts") or m.get("ts") or 0)

            try:
                res = conn.execute(
                    """
                    INSERT OR IGNORE INTO wa_incoming_archive 
                    (msg_id, chat_id, chat_name, sender_name, is_group, msg_type, body, has_media, msg_ts, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (msg_id, chat_id, chat_name, sender_name, is_group, msg_type, body, has_media, msg_ts),
                )
                if res.rowcount > 0:
                    archived += 1
            except Exception as e:
                logger.debug("Failed to archive wa message %s: %s", msg_id, e)

        conn.commit()
    return archived


def search_wa_archive_sync(
    query: str = "",
    chat_id: str = "",
    sender: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Cari arsip pesan WA di database lokal SQLite secara instan dan permanen.
    """
    limit = max(1, min(limit, 100))
    clauses = []
    params: list[Any] = []

    if query.strip():
        clauses.append("body LIKE ?")
        params.append(f"%{query.strip()}%")

    if chat_id.strip():
        clauses.append("(chat_id LIKE ? OR chat_name LIKE ?)")
        params.extend([f"%{chat_id.strip()}%", f"%{chat_id.strip()}%"])

    if sender.strip():
        clauses.append("sender_name LIKE ?")
        params.append(f"%{sender.strip()}%")

    where_str = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT msg_id, chat_id, chat_name, sender_name, is_group, msg_type, body, has_media, msg_ts, created_at
        FROM wa_incoming_archive
        {where_str}
        ORDER BY msg_ts DESC, created_at DESC
        LIMIT ?
    """
    params.append(limit)

    results: list[dict[str, Any]] = []
    with get_sync_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        for r in rows:
            results.append({
                "msg_id": r["msg_id"],
                "chat": r["chat_id"],
                "chat_name": r["chat_name"],
                "sender_name": r["sender_name"],
                "is_group": bool(r["is_group"]),
                "msg_type": r["msg_type"],
                "body": r["body"],
                "has_media": bool(r["has_media"]),
                "msg_ts": r["msg_ts"],
                "created_at": r["created_at"],
            })
    return results
