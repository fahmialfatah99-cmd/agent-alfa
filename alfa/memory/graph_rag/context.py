"""Konteks graph untuk pra-turn (inject ke prompt)."""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import init_graph_db
from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

_GRAG_DB_ERR = (sqlite3.Error, RuntimeError, ValueError, TypeError, KeyError)

def get_pre_turn_graph_context(
    user_id: int, prompt: str, max_triples: int = 4, db_path: str | None = None
) -> str:
    """
    Secara otomatis mengambil fakta relasi 1-hop dari Knowledge Graph yang relevan dengan pertanyaan user,
    untuk disuntikkan ke konteks sistem (Pre-turn Context Injection).
    """
    if not prompt or len(prompt.strip()) < 3:
        return ""

    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    tokens = [
        t for t in re.findall(r"\b[A-Za-z0-9_]{3,30}\b", prompt)
        if t.lower() not in {
            "apa", "siapa", "bagaimana", "mengapa", "kenapa", "tolong",
            "bisa", "halo", "dong", "kan", "yang", "dan", "dari", "pada",
            "untuk", "dengan", "adalah", "ini", "itu", "atau", "saya", "kamu",
        }
    ]
    if not tokens:
        return ""

    conn = sqlite3.connect(target_db, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = " OR ".join(["source_entity LIKE ? OR target_entity LIKE ?"] * len(tokens[:5]))
        params: list[Any] = [user_id]
        for t in tokens[:5]:
            params.extend([f"%{t}%", f"%{t}%"])

        query = (
            "SELECT DISTINCT source_entity, relation, target_entity, source_doc, evidence "  # nosec B608
            "FROM graph_relations "
            "WHERE user_id = ? AND ({ph}) "
            "LIMIT ?"
        ).replace("{ph}", placeholders)
        params.append(max_triples)

        rows = conn.execute(query, params).fetchall()  # nosec B608 — static clause with ? placeholders
        if not rows:
            return ""

        facts = [
            f"- {r['source_entity']} ──[{r['relation']}]──> {r['target_entity']} "
            f"(Sumber: {r['source_doc']}"
            + (f' | Bukti: "{r["evidence"][:120]}"' if r["evidence"] else "")
            + ")"
            for r in rows
        ]

        return (
            "🕸️ [KNOWLEDGE GRAPH CONTEXT (GRAPHRAG FAKTA RELASI OTOMATIS)]:\n"
            "Fakta relasi yang relevan langsung dari Knowledge Graph:\n"
            + "\n".join(facts)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pre-turn graph context extraction skipped: %s", exc)
        return ""
    finally:
        conn.close()
