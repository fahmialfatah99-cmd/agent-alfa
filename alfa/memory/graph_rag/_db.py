"""Inisialisasi DB graph & normalisasi nama entitas."""
from __future__ import annotations

import logging
import os
import sqlite3

from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

_FILLER_PREFIXES = (
    "framework ",
    "library ",
    "sistem ",
    "aplikasi ",
    "sebagai ",
    "adalah ",
    "merupakan ",
    "yakni ",
    "yaitu ",
    "sebuah ",
    "suatu ",
    "bagian dari ",
    "komponen dari ",
    "cabang dari ",
    "terhubung ke ",
    "berbasis ",
    "the ",
    "a ",
    "an ",
)

_FILLER_SUFFIXES = (
    " sebagai backend rest api",
    " sebagai backend",
    " sebagai frontend",
    " sebagai server",
    " sebagai api",
    " sebagai database",
    " sebagai layanan",
    " sebagai service",
    " sebagai sistem",
    " untuk backend",
    " untuk frontend",
    " untuk server",
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DEFAULT_DB_PATH = os.getenv("ALFA_DB_PATH", os.path.join(REPO_ROOT, "agent_data.db"))

def init_graph_db(db_path: str | None = None):
    """Ensure SQLite tables for GraphRAG entities and relations exist."""
    target_db = _resolve_db_path(db_path)
    conn = sqlite3.connect(target_db, timeout=10)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                entity_type TEXT DEFAULT 'concept',
                description TEXT DEFAULT '',
                source_doc TEXT NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ge_user_name ON graph_entities(user_id, name);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ge_source ON graph_entities(user_id, source_doc);"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_entity TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                source_doc TEXT NOT NULL,
                evidence TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gr_user_src ON graph_relations(user_id, source_entity);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gr_user_tgt ON graph_relations(user_id, target_entity);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gr_source_doc ON graph_relations(user_id, source_doc);"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_entity_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                canonical_name TEXT NOT NULL,
                alias TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gea_user_alias ON graph_entity_aliases(user_id, alias);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gea_user_canon ON graph_entity_aliases(user_id, canonical_name);"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_communities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                community_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                entities_json TEXT NOT NULL,
                summary TEXT DEFAULT '',
                source_doc TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gc_user_id ON graph_communities(user_id);"
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to init graph db: {e}")
    finally:
        conn.close()

def normalize_entity_name(raw_name: str) -> str:
    """Normalisasi nama entitas untuk mencegah fragmentasi graf."""
    if not raw_name:
        return ""
    text = raw_name.strip().strip("'\"`.,:;()[]{}")
    t_lower = text.lower()

    for sfx in _FILLER_SUFFIXES:
        if t_lower.endswith(sfx):
            text = text[:-len(sfx)].strip()
            t_lower = text.lower()
            break

    for pfx in _FILLER_PREFIXES:
        if t_lower.startswith(pfx):
            text = text[len(pfx):].strip()
            t_lower = text.lower()
            break

    text = text.strip().strip("'\"`.,:;()[]{}")
    return text if text else raw_name.strip()
