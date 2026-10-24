"""Smart search tools: pencarian ber-ranking (FTS5/BM25) untuk arsip WA
dan memori pengetahuan — additive-only, tidak menyentuh tool lama."""

from __future__ import annotations

import os
from typing import Any

from alfa.core.db.wa_index import (
    search_memories_ranked_sync,
    search_wa_archive_ranked_sync,
)
from alfa.tools.registry import register_tool


def _effective_user_id(user_id: int | None) -> int:
    """User efektif: eksplisit menang; default primari dari ALLOWED_USER_IDS."""
    if user_id is not None and user_id > 0:
        return int(user_id)
    raw = (os.getenv("ALLOWED_USER_IDS") or "").strip()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            return int(part)
    return 0


@register_tool(category="system")
def wa_search_ranked(
    query: str, chat_id: str = "", sender: str = "", limit: int = 15
) -> dict[str, Any]:
    """Cari arsip pesan WhatsApp secara RANKED (FTS5 BM25) di database lokal.

    Perbedaan dengan ``wa_get_history_archive``: hasil diurutkan relevansi
    (bukan urut waktu), dengan highlight potongan menarik di tiap baris.

    Args:
        query: kata kunci pencarian (bebas, multi-kata).
        chat_id: filter sebagian nama/kode grup atau nomor.
        sender: filter nama pengirim.
        limit: jumlah hasil maksimal (1-100).
    """
    rows = search_wa_archive_ranked_sync(
        query=query, chat_id=chat_id, sender=sender, limit=limit
    )
    mode = "ranked"
    if rows and all(row.get("rank_score") is None for row in rows):
        mode = "fallback_like"
    return {
        "status": "ok",
        "mode": mode,
        "count": len(rows),
        "results": rows,
    }


@register_tool(category="system")
def memory_search_ranked(
    query: str, user_id: int | None = None, limit: int = 10
) -> dict[str, Any]:
    """Cari memori pengetahuan jangka-panjang ALFA secara RANKED (BM25).

    Cocok untuk menemukan fakta fakta yang ALFA pernah simpan (kategori,
    topik, isi). Fallback otomatis ke pencarian LIKE bila FTS5 tak tersedia.

    Args:
        query: kata kunci (bebas, multi-kata).
        user_id: target pengguna (opsional; default user primari).
        limit: jumlah hasil maksimal (1-50).
    """
    rows = search_memories_ranked_sync(
        user_id=_effective_user_id(user_id), query=query, limit=limit
    )
    mode = "ranked"
    if rows and all(row.get("rank_score") is None for row in rows):
        mode = "fallback_like"
    return {
        "status": "ok",
        "mode": mode,
        "count": len(rows),
        "results": rows,
    }
