"""Pencarian ranked (FTS5) untuk arsip WA & memori pengetahuan.

Bersifat additive-only: tidak mengubah satu tabel atau fungsi lama.
- Bila FTS5 tersedia → query di-ranking dengan BM25 + highlight.
- Bila FTS5 tidak tersedia / index gagal dibangun → fungsi jatuh otomatis
  ke pencarian LIKE yang sudah lama dipakai (zero-regression).
Index dibangun lazy (freshness check per call) dan dibatasi jumlah baris
agar selalu murah untuk dataset pribadi.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from alfa.core.db.connection import get_sync_db
from alfa.core.db.wa_tracking import search_wa_archive_sync

logger = logging.getLogger("DB.WaIndex")

_META_TABLE = "_alfa_index_meta"
_WA_INDEX_NAME = "wa_archive_fts"
_MEMORY_INDEX_NAME = "memory_fts"

# Batas ukuran agar rebuild tidak pernah mahal (dataset pribadi).
_MAX_ARCHIVE_ROWS = 100_000
_MAX_MEMORY_ROWS = 20_000

# <: lebih> penanda highlight publik (aman-teks, tak kena Markup HTML WA).
_HL_OPEN = "<<"
_HL_CLOSE = ">>"

_fts_available: bool | None = None


def _fts_ok() -> bool:
    """Cek sekali (memo) apakah backend SQLite mendukung FTS5."""
    global _fts_available
    if _fts_available is None:
        try:
            probe = sqlite3.connect(":memory:")
            try:
                probe.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
                _fts_available = True
            finally:
                probe.close()
        except (sqlite3.Error, OSError, ValueError):  # pragma: no cover - backend tanpa FTS5
            _fts_available = False
    return _fts_available


def _meta_get(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    try:
        row = conn.execute(
            f"SELECT info FROM {_META_TABLE} WHERE name = ?",  # nosec B608 — nama tabel konstanta internal
            (name,),
        ).fetchone()
    except sqlite3.OperationalError:
        return {}
    if not row:
        return {}
    try:
        return dict(json.loads(row[0]))
    except (ValueError, TypeError):
        return {}


def _meta_set(conn: sqlite3.Connection, name: str, info: dict[str, Any]) -> None:
    conn.execute(
        f"INSERT INTO {_META_TABLE} (name, info) VALUES (?, ?) "  # nosec B608 — nama tabel konstanta internal
        "ON CONFLICT(name) DO UPDATE SET info = excluded.info",
        (name, json.dumps(info)),
    )


def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_META_TABLE} ("  # nosec B608 — nama tabel konstanta internal
        "name TEXT PRIMARY KEY, info TEXT NOT NULL DEFAULT '{}')"
    )


def _quote_fts_tokens(query: str) -> str:
    """Amankan query bebas utk FTS5 MATCH: tiap token jadi quoted-phrase.

    Tanda kutip dalam token di-escape; token kosong dibuang. Termasuk
    karakter khusus (``-``, ``*``, ``AND``/``OR`` literal) pun aman.
    """
    tokens = []
    for raw in query.split():
        token = raw.replace('"', '""').strip()
        if token:
            tokens.append(f'"{token}"')
    return " OR ".join(tokens)


# ── Arsip WA ────────────────────────────────────────────────────────────────


def ensure_wa_index_sync() -> str:
    """Pastikan index FTS arsip WA segar. Kembalikan status ringkas.

    Status: ``built`` (rebuild penuh), ``current`` (sudah segar),
    ``unavailable`` (FTS5 tidak ada), ``skipped`` (dataset terlalu besar),
    ``error`` (DB gagal — fitur utama tetap jalan via fallback LIKE).
    """
    if not _fts_ok():
        return "unavailable"
    try:
        with get_sync_db() as conn:
            _ensure_meta_table(conn)
            total = conn.execute(
                "SELECT COUNT(*) FROM wa_incoming_archive"
            ).fetchone()[0]
            if total > _MAX_ARCHIVE_ROWS:
                return "skipped"
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS wa_archive_fts USING fts5("
                "body, chat_id UNINDEXED, chat_name UNINDEXED, "
                "sender_name UNINDEXED, msg_id UNINDEXED)"
            )
            fts_count = conn.execute(
                "SELECT COUNT(*) FROM wa_archive_fts"
            ).fetchone()[0]
            meta = _meta_get(conn, _WA_INDEX_NAME)
            if meta.get("count") == total and fts_count == total:
                return "current"
            conn.execute("DELETE FROM wa_archive_fts")
            conn.execute(
                """
                INSERT INTO wa_archive_fts
                    (body, chat_id, chat_name, sender_name, msg_id)
                SELECT body, chat_id, COALESCE(chat_name, ''),
                       COALESCE(sender_name, ''), msg_id
                FROM wa_incoming_archive
                WHERE body IS NOT NULL AND TRIM(body) <> ''
                """
            )
            built = conn.execute(
                "SELECT COUNT(*) FROM wa_archive_fts"
            ).fetchone()[0]
            _meta_set(conn, _WA_INDEX_NAME, {"count": total, "indexed": built})
            conn.commit()
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("Index FTS arsip WA gagal dibangun: %s", exc)
        return "error"
    else:
        return "built"


def _wa_fallback(
    query: str, chat_id: str, sender: str, limit: int
) -> list[dict[str, Any]]:
    """Jalur lama (LIKE) unchanged untuk hasil yang stabil."""
    rows = search_wa_archive_sync(
        query=query, chat_id=chat_id, sender=sender, limit=limit
    )
    for row in rows:
        row.setdefault("snippet", "")
        row.setdefault("rank_score", None)
    return rows


def search_wa_archive_ranked_sync(
    query: str,
    chat_id: str = "",
    sender: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Cari arsip WA ber-ranking (BM25) dengan highlight.

    Bentuk hasil = kolom arsip yang sama seperti pencarian lama + dua key
    tambahan (``snippet``, ``rank_score``) — additive, tidak mengubah
    kontrak consumer yang membaca field lama. Bila FTS5 tidak tersedia,
    fungsi jatuh ke pencarian LIKE lama secara transparan.
    """
    limit = max(1, min(int(limit), 100))
    query = (query or "").strip()
    if not query:
        return _wa_fallback(query, chat_id, sender, limit)
    if ensure_wa_index_sync() not in {"built", "current"}:
        return _wa_fallback(query, chat_id, sender, limit)
    match_expr = _quote_fts_tokens(query)
    if not match_expr:
        return _wa_fallback(query, chat_id, sender, limit)
    try:
        with get_sync_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT a.msg_id, a.chat_id, a.chat_name, a.sender_name,
                       a.is_group, a.msg_type, a.body, a.has_media, a.msg_ts,
                       f.rk, f.snip
                FROM (
                    SELECT msg_id, bm25(wa_archive_fts) AS rk,
                           highlight(wa_archive_fts, 0, ?, ?) AS snip
                    FROM wa_archive_fts
                    WHERE wa_archive_fts MATCH ?
                ) f
                JOIN wa_incoming_archive a ON a.msg_id = f.msg_id
                WHERE (? = '' OR a.chat_id LIKE ? OR a.chat_name LIKE ?)
                  AND (? = '' OR a.sender_name LIKE ?)
                ORDER BY f.rk
                LIMIT ?
                """,
                (
                    _HL_OPEN,
                    _HL_CLOSE,
                    match_expr,
                    chat_id.strip(),
                    f"%{chat_id.strip()}%",
                    f"%{chat_id.strip()}%",
                    sender.strip(),
                    f"%{sender.strip()}%",
                    limit,
                ),
            )
            rows = [dict(r) for r in cursor.fetchall()]
        # Kolom tambahan: snip → snake_case agar konsisten.
        for row in rows:
            row["snippet"] = row.pop("snip", "")
            row["rank_score"] = row.get("rk")
    except sqlite3.Error as exc:
        logger.warning("Pencarian ranked WA gagal, fallback LIKE: %s", exc)
        return _wa_fallback(query, chat_id, sender, limit)
    else:
        return rows


# ── Memori pengetahuan ──────────────────────────────────────────────────────


def ensure_memory_index_sync() -> str:
    """Index FTS untuk ``knowledge_memory`` (state memori belajar ALFA)."""
    if not _fts_ok():
        return "unavailable"
    try:
        with get_sync_db() as conn:
            _ensure_meta_table(conn)
            total, max_upd = conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(updated_at), '') "
                "FROM knowledge_memory"
            ).fetchone()
            if total > _MAX_MEMORY_ROWS:
                return "skipped"
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
                "topic, content, mid UNINDEXED, user_id UNINDEXED, "
                "category UNINDEXED)"
            )
            meta = _meta_get(conn, _MEMORY_INDEX_NAME)
            fts_count = conn.execute(
                "SELECT COUNT(*) FROM memory_fts"
            ).fetchone()[0]
            if (
                meta.get("count") == total
                and meta.get("max_updated_at") == max_upd
                and fts_count == total
            ):
                return "current"
            conn.execute("DELETE FROM memory_fts")
            conn.execute(
                """
                INSERT INTO memory_fts (topic, content, mid, user_id, category)
                SELECT COALESCE(key_topic, ''), COALESCE(content, ''),
                       id, user_id, COALESCE(category, '')
                FROM knowledge_memory
                """
            )
            _meta_set(
                conn,
                _MEMORY_INDEX_NAME,
                {"count": total, "max_updated_at": max_upd},
            )
            conn.commit()
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("Index FTS memori gagal dibangun: %s", exc)
        return "error"
    else:
        return "built"


def search_memories_ranked_sync(
    user_id: int, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Cari memori ber-ranking; fallback LIKE identik ``search_memories``."""
    limit = max(1, min(int(limit), 50))
    query = (query or "").strip()

    def _like_fallback() -> list[dict[str, Any]]:
        pattern = f"%{query.lower()}%"
        with get_sync_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, category, key_topic, content, updated_at
                FROM knowledge_memory
                WHERE user_id = ? AND (LOWER(key_topic) LIKE ?
                    OR LOWER(content) LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, pattern, pattern, limit),
            ).fetchall()
        out_rows: list[dict[str, Any]] = [dict(r) for r in rows]
        for row in out_rows:
            row.setdefault("snippet", "")
            row.setdefault("rank_score", None)
        return out_rows

    if not query or ensure_memory_index_sync() not in {"built", "current"}:
        return _like_fallback()
    match_expr = _quote_fts_tokens(query)
    if not match_expr:
        return _like_fallback()
    try:
        with get_sync_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT km.id, km.category, km.key_topic, km.content,
                           km.updated_at, f.rk, f.snip
                    FROM (
                        SELECT mid AS kmid, bm25(memory_fts) AS rk,
                               highlight(memory_fts, 1, ?, ?) AS snip
                        FROM memory_fts
                        WHERE memory_fts MATCH ? AND user_id = ?
                    ) f
                    JOIN knowledge_memory km ON km.id = f.kmid
                    WHERE km.user_id = ?
                    ORDER BY f.rk
                    LIMIT ?
                    """,
                    (
                        _HL_OPEN,
                        _HL_CLOSE,
                        match_expr,
                        user_id,
                        user_id,
                        limit,
                    ),
                ).fetchall()
            ]
        for row in rows:
            row["snippet"] = row.pop("snip", "")
            row["rank_score"] = row.get("rk")
    except sqlite3.Error as exc:
        logger.warning("Pencarian ranked memori gagal, fallback LIKE: %s", exc)
        return _like_fallback()
    else:
        return rows
