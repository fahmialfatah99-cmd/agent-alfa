"""Siklus konsolidasi memori (graph + komunitas) saat tidur."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import init_graph_db
from alfa.memory.graph_rag.communities import detect_and_save_communities
from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

_GRAG_DB_ERR = (sqlite3.Error, RuntimeError, ValueError, TypeError, KeyError)

def consolidate_memory_sleep_cycle(
    db_path: str | None = None,
    user_id: int = 1,
    auto_alias: bool = True,
    recluster: bool = True,
) -> dict[str, Any]:
    """
    Siklus konsolidasi memori pengetahuan otonom (Autonomous Memory Sleep Cycle):
    1. Melakukan deduplikasi & inferensi alias kanonikal otomatis pada entitas graf.
    2. Menghitung reinforcement bobot relasi (relational frequency weight update).
    3. Menjalankan re-clustering komunitas dan pembaruan ringkasan global.
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    conn = sqlite3.connect(target_db, timeout=15)
    conn.row_factory = sqlite3.Row
    aliases_added = 0
    distinct_entities: set[str] = set()
    relations_count = 0
    communities_detected = 0

    try:
        ent_rows = conn.execute(
            "SELECT DISTINCT name FROM graph_entities WHERE user_id = ?", (user_id,)
        ).fetchall()
        for r in ent_rows:
            distinct_entities.add(r["name"].strip())

        rel_rows = conn.execute(
            "SELECT source_entity, relation, target_entity, weight FROM graph_relations WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        relations_count = len(rel_rows)
        for r in rel_rows:
            distinct_entities.add(r["source_entity"].strip())
            distinct_entities.add(r["target_entity"].strip())

        # Auto-alias inference
        if auto_alias and distinct_entities:
            existing_alias_rows = conn.execute(
                "SELECT canonical_name, alias FROM graph_entity_aliases WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            existing_map: dict[str, str] = {
                r["alias"].lower(): r["canonical_name"] for r in existing_alias_rows
            }

            honorifics = (
                "pak ", "ibu ", "bapak ", "dr. ", "dr ", "pt ", "cv ",
                "prof. ", "mr. ", "ms. ",
            )
            sorted_entities = sorted(list(distinct_entities), key=lambda x: (-len(x), x))

            for ent in sorted_entities:
                if not ent or len(ent) < 2:
                    continue
                ent_lower = ent.lower()

                for h in honorifics:
                    if ent_lower.startswith(h):
                        stripped = ent[len(h):].strip()
                        if stripped and stripped.lower() in [e.lower() for e in distinct_entities]:
                            canonical = next(e for e in distinct_entities if e.lower() == stripped.lower())
                            if ent_lower not in existing_map:
                                conn.execute(
                                    "INSERT OR IGNORE INTO graph_entity_aliases (user_id, canonical_name, alias) VALUES (?, ?, ?)",
                                    (user_id, canonical, ent),
                                )
                                existing_map[ent_lower] = canonical
                                aliases_added += 1

                for other in distinct_entities:
                    if ent != other and ent.lower() == other.lower():
                        canon = ent if (ent.istitle() or ent.isupper()) else other
                        al = other if canon == ent else ent
                        if al.lower() not in existing_map:
                            conn.execute(
                                "INSERT OR IGNORE INTO graph_entity_aliases (user_id, canonical_name, alias) VALUES (?, ?, ?)",
                                (user_id, canon, al),
                            )
                            existing_map[al.lower()] = canon
                            aliases_added += 1

        # Relation frequency reinforcement
        freq_map: dict[tuple[str, str, str], int] = {}
        for r in rel_rows:
            key = (r["source_entity"], r["relation"], r["target_entity"])
            freq_map[key] = freq_map.get(key, 0) + 1

        for (s, rel, t), count in freq_map.items():
            if count > 1:
                conn.execute(
                    "UPDATE graph_relations SET weight = ? WHERE user_id = ? AND source_entity = ? AND relation = ? AND target_entity = ?",
                    (float(count), user_id, s, rel, t),
                )

        conn.commit()
    except _GRAG_DB_ERR as exc:  # noqa: BLE001
        logger.exception("Error during memory consolidation")
        return {"status": "error", "error": str(exc), "user_id": user_id}
    finally:
        conn.close()

    if recluster:
        try:
            comms = detect_and_save_communities(user_id=user_id, db_path=target_db)
            communities_detected = len(comms)
        except _GRAG_DB_ERR as exc:  # noqa: BLE001
            logger.warning("Re-clustering during consolidation skipped: %s", exc)

    return {
        "status": "success",
        "user_id": user_id,
        "aliases_registered": aliases_added,
        "distinct_entities_count": len(distinct_entities),
        "relations_count": relations_count,
        "communities_count": communities_detected,
    }
