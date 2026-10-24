"""Unit hermetik: pencarian ranked FTS5 (wa_index) utk arsip WA & memori.

Semua jalur tanpa network / DB produksi (conftest mengalihkan DB produksi
ke file uji sementara); fallback LIKE diuji dengan mematikan FTS5 via
monkeypatch.
"""

from __future__ import annotations

import sqlite3

import pytest

from alfa.core.db import wa_index
from alfa.core.db.connection import get_sync_db


@pytest.fixture()
def _clean_search_tables():
    """Pastikan skema ada + bersihkan tabel sasaran di test-DB."""
    from alfa.core.db.connection import init_db_sync

    init_db_sync()
    with get_sync_db() as conn:
        for stmt in (
            "DELETE FROM wa_incoming_archive",
            "DELETE FROM knowledge_memory",
        ):
            try:
                conn.execute(stmt)
            except (sqlite3.Error, OSError, ValueError):
                pass
        for table in ("wa_archive_fts", "memory_fts"):
            try:
                conn.execute(f"DELETE FROM {table}")  # nosec B608 — konstanta
            except (sqlite3.Error, OSError, ValueError):
                pass
        for meta_row in ("wa_archive_fts", "memory_fts"):
            try:
                conn.execute(
                    "DELETE FROM _alfa_index_meta WHERE name = ?", (meta_row,)
                )
            except (sqlite3.Error, OSError, ValueError):
                pass
        conn.commit()
    wa_index._fts_available = None  # reset memo
    yield
    wa_index._fts_available = None


def _seed_archive(
    rows: list[tuple[str, str, str, str, int, int]],
) -> None:
    for msg_id, chat_name, sender, body, is_group, msg_ts in rows:
        with get_sync_db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO wa_incoming_archive
                    (msg_id, chat_id, chat_name, sender_name, is_group,
                     msg_type, body, has_media, msg_ts)
                VALUES (?, ?, ?, ?, ?, 'text', ?, 0, ?)
                """,
                (msg_id, f"cid-{msg_id}", chat_name, sender, is_group, body, msg_ts),
            )
            conn.commit()


def test_ranked_search_orders_by_relevance_with_snippet(_clean_search_tables):
    _seed_archive(
        [
            ("m1", "Grup A", "Budi", "catatan biasa tanpa topik khusus", 1, 100),
            (
                "m2",
                "Grup A",
                "Sinta",
                "laporan subfeeder opname blok 2301 subfeeder siap",
                1,
                200,
            ),
            ("m3", "Grup B", "Dewi", "ada subfeeder baru hari ini", 1, 300),
        ]
    )
    rows = wa_index.search_wa_archive_ranked_sync("subfeeder opname", limit=5)
    assert rows, "hasil tidak boleh kosong"
    top = rows[0]
    # m2 memuat dua term query & tf tertinggi → wajib di puncak.
    assert top["msg_id"] == "m2", f"harapan m2 di puncak, dapat {top['msg_id']}"
    assert top["snippet"], "snippet harus terisi saat ranked"
    assert "subfeeder" in top["snippet"]
    assert top["rank_score"] is not None
    assert top["chat_name"] == "Grup A"
    # m1 tidak memuat term mana pun → tidak boleh ikut hasil.
    assert {r["msg_id"] for r in rows} == {"m2", "m3"}


def test_falls_back_to_like_when_fts_absent(_clean_search_tables, monkeypatch):
    _seed_archive(
        [
            ("mx", "Grup X", "Pak Haji", "policy petroleum update terkini", 1, 900),
        ]
    )
    monkeypatch.setattr(wa_index, "_fts_ok", lambda: False)
    rows = wa_index.search_wa_archive_ranked_sync("petroleum", limit=5)
    assert len(rows) == 1
    assert rows[0]["msg_id"] == "mx"
    # Kontrak fallback: field arsip lengkap + key tambahan bernilai netral.
    assert rows[0]["rank_score"] is None
    assert "snippet" in rows[0]


def test_freshness_rebuild_pulls_new_row_in(_clean_search_tables):
    _seed_archive(
        [("mA", "G", "Andi", "jaringan opname perangkat baja", 1, 10)]
    )
    assert wa_index.ensure_wa_index_sync() == "built"
    rows = wa_index.search_wa_archive_ranked_sync("opname")
    assert [r["msg_id"] for r in rows] == ["mA"]
    assert wa_index.ensure_wa_index_sync() == "current"
    # Tambah baris baru → ensure membangun ulang → baris baru ditemukan.
    _seed_archive(
        [("mB", "G", "Rara", "opname subfeeder lokasi 88", 1, 20)]
    )
    assert wa_index.ensure_wa_index_sync() == "built"
    rows = wa_index.search_wa_archive_ranked_sync("subfeeder")
    assert [r["msg_id"] for r in rows] == ["mB"]


def test_query_with_special_chars_never_crashes(_clean_search_tables):
    _seed_archive(
        [
            (
                "mz",
                "G",
                "Tono",
                'laporan "subfeeder" khusus-nomor 9',
                0,
                55,
            )
        ]
    )
    # Aman walau query kaya karakter khusus FTS5 (dash & kutip).
    rows = wa_index.search_wa_archive_ranked_sync('laporan -- "khusus" -nomor')
    assert isinstance(rows, list)
    rows2 = wa_index.search_wa_archive_ranked_sync("")
    assert isinstance(rows2, list)


def test_memory_ranked_search_reuse_and_fallback(_clean_search_tables, monkeypatch):
    with get_sync_db() as conn:
        for topic, content in (
            ("stok-cabut", "laci subfeeder 2301 diisi cengkeh kering"),
            ("menu-harian", "sarapan nasi goreng telur mata sapi"),
        ):
            conn.execute(
                """
                INSERT OR IGNORE INTO knowledge_memory
                    (user_id, category, key_topic, content)
                VALUES (7, 'utama', ?, ?)
                """,
                (topic, content),
            )
        conn.commit()
    rows = wa_index.search_memories_ranked_sync(7, "cengkeh subfeeder")
    assert rows, "cengkeh harus ketemu"
    assert rows[0]["key_topic"] == "stok-cabut"
    assert "cengkeh" in rows[0]["snippet"]
    assert rows[0]["rank_score"] is not None
    monkeypatch.setattr(wa_index, "_fts_ok", lambda: False)
    fallback = wa_index.search_memories_ranked_sync(7, "cengkeh")
    assert fallback[0]["key_topic"] == "stok-cabut"
    assert fallback[0]["rank_score"] is None
    # User lain tidak melihat memori user 7 (fallback + ranked konsisten).
    assert wa_index.search_memories_ranked_sync(99, "cengkeh") == []
