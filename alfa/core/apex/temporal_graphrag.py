"""
Episodic Temporal GraphRAG Second Brain for ALFA OS (Level 5+ General Frontier).

Upgrades standard flat vector memory into a Dynamic Temporal Knowledge Graph:
1. Stores Entities (Nodes) with temporal tracking (`first_seen_at`, `last_seen_at`, `mention_count`).
2. Stores Relations (Edges) with Hebbian associative weights (`weight`) and temporal validity.
3. Performs Multi-Hop Subgraph Traversal (1-Hop direct + 2-Hop hidden bridge discovery)
   to connect ideas, projects, people, documents, and code across time.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("ApexTemporalGraphRAG")


def init_graphrag_tables() -> None:
    """Initialize SQLite tables for the Temporal Knowledge Graph (Nodes & Edges)."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_graph_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT UNIQUE,
                name TEXT UNIQUE,
                entity_type TEXT DEFAULT 'CONCEPT',
                summary TEXT DEFAULT '',
                mention_count INTEGER DEFAULT 1,
                first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_graph_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                relation_id TEXT UNIQUE,
                source_entity TEXT,
                relation_type TEXT,
                target_entity TEXT,
                context_snippet TEXT DEFAULT '',
                weight REAL DEFAULT 1.0,
                valid_from DATETIME DEFAULT CURRENT_TIMESTAMP,
                valid_until DATETIME DEFAULT NULL,
                active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_rel_src ON alfa_graph_relations(source_entity);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_rel_tgt ON alfa_graph_relations(target_entity);"
        )
        conn.commit()


def upsert_graph_entity(
    name: str,
    entity_type: str = "CONCEPT",
    summary: str = "",
) -> dict[str, Any]:
    """Insert or reinforce a node in the Temporal Knowledge Graph."""
    init_graphrag_tables()
    clean_name = " ".join(name.strip().split())
    if not clean_name:
        return {"status": "error", "message": "Empty entity name"}

    norm_key = clean_name.upper()
    eid = f"ent_{hashlib.sha256(norm_key.encode()).hexdigest()[:12]}"

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_graph_entities (entity_id, name, entity_type, summary, mention_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                entity_type = CASE WHEN excluded.entity_type != 'CONCEPT' THEN excluded.entity_type ELSE alfa_graph_entities.entity_type END,
                summary = CASE WHEN excluded.summary != '' THEN excluded.summary ELSE alfa_graph_entities.summary END,
                mention_count = alfa_graph_entities.mention_count + 1,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (eid, norm_key, entity_type.strip().upper(), summary.strip()),
        )
        conn.commit()

    return {"status": "success", "entity_id": eid, "name": norm_key, "entity_type": entity_type.upper()}


def upsert_graph_relation(
    source_entity: str,
    relation_type: str,
    target_entity: str,
    context_snippet: str = "",
    weight_delta: float = 0.25,
) -> dict[str, Any]:
    """Create or strengthen a directed temporal edge between two entities."""
    init_graphrag_tables()
    src = " ".join(source_entity.strip().split()).upper()
    tgt = " ".join(target_entity.strip().split()).upper()
    rel = "_".join(relation_type.strip().split()).upper() or "RELATED_TO"

    if not src or not tgt or src == tgt:
        return {"status": "skipped", "message": "Invalid or self-loop relation"}

    upsert_graph_entity(src)
    upsert_graph_entity(tgt)

    rid_hash = hashlib.sha256(f"{src}:{rel}:{tgt}".encode()).hexdigest()[:12]
    relation_id = f"rel_{rid_hash}"

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_graph_relations
            (relation_id, source_entity, relation_type, target_entity, context_snippet, weight, active)
            VALUES (?, ?, ?, ?, ?, 1.0, 1)
            ON CONFLICT(relation_id) DO UPDATE SET
                weight = MIN(10.0, ROUND(alfa_graph_relations.weight + ?, 3)),
                context_snippet = CASE WHEN excluded.context_snippet != '' THEN excluded.context_snippet ELSE alfa_graph_relations.context_snippet END,
                active = 1
            """,
            (relation_id, src, rel, tgt, context_snippet[:300], weight_delta),
        )
        conn.commit()

    return {
        "status": "success",
        "relation_id": relation_id,
        "source": src,
        "relation": rel,
        "target": tgt,
    }


_RELATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})\s+(?:menggunakan|memakai|uses|built with|berbasis)\s+([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})", re.I), "USES"),
    (re.compile(r"([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})\s+(?:terhubung dengan|integrasi dengan|connects to|linked to)\s+([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})", re.I), "CONNECTED_TO"),
    (re.compile(r"([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})\s+(?:menghasilkan|membuat|produces|generates|creates)\s+([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})", re.I), "PRODUCES"),
    (re.compile(r"([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})\s+(?:adalah bagian dari|part of|submodul dari)\s+([A-Za-z0-9_\-]{3,}(?:\s+[A-Za-z0-9_\-]{3,}){0,2})", re.I), "PART_OF"),
]


def ingest_text_to_temporal_graph(text: str, default_topic: str = "") -> dict[str, Any]:
    """
    Automatically extract entities and semantic triples from natural text and weave them
    into the Temporal Knowledge Graph.
    """
    init_graphrag_tables()
    if not text or len(text.strip()) < 5:
        return {"status": "empty", "entities_added": 0, "relations_added": 0}

    entities_added = 0
    relations_added = 0

    # 1. Extract explicit predicate relations
    for pat, rel_label in _RELATION_PATTERNS:
        for m in pat.finditer(text):
            src_cand, tgt_cand = m.group(1).strip(), m.group(2).strip()
            res = upsert_graph_relation(src_cand, rel_label, tgt_cand, context_snippet=text[:200])
            if res.get("status") == "success":
                relations_added += 1
                entities_added += 2

    # 2. Extract capitalized multi-word concepts / technical identifiers
    key_terms = re.findall(r"\b[A-Z][a-zA-Z0-9_\-]{2,}(?:\s+[A-Z][a-zA-Z0-9_\-]{2,})*\b", text)
    stop_caps = {"DAN", "ATAU", "UNTUK", "DARI", "PADA", "YANG", "INI", "ITU", "THE", "AND", "FOR"}
    clean_terms = []
    for t in key_terms:
        if t.upper() not in stop_caps and len(t) >= 3:
            clean_terms.append(t.upper())
    unique_terms = list(dict.fromkeys(clean_terms))[:8]

    for term in unique_terms:
        upsert_graph_entity(term, entity_type="CONCEPT", summary=text[:160])
        entities_added += 1
        if default_topic:
            upsert_graph_relation(default_topic, "MENTIONS", term, context_snippet=text[:160])
            relations_added += 1

    # Link co-occurring key terms within the same thought
    for i in range(len(unique_terms) - 1):
        r = upsert_graph_relation(
            unique_terms[i],
            "CO_OCCURS_WITH",
            unique_terms[i + 1],
            context_snippet=text[:160],
            weight_delta=0.15,
        )
        if r.get("status") == "success":
            relations_added += 1

    return {
        "status": "success",
        "entities_processed": entities_added,
        "relations_processed": relations_added,
        "extracted_concepts": unique_terms,
    }


def query_temporal_graphrag(query: str, max_hops: int = 2, limit: int = 10) -> dict[str, Any]:
    """
    Perform a Multi-Hop Subgraph Traversal (1-Hop direct + 2-Hop hidden bridge connections)
    across the Temporal Knowledge Graph.
    """
    init_graphrag_tables()
    tokens = [w.upper() for w in re.findall(r"[a-zA-Z0-9_\-]{3,}", query)]
    if not tokens:
        return {"status": "success", "matched_entities": [], "hop1_relations": [], "hop2_bridges": []}

    matched_entities: list[dict[str, Any]] = []
    hop1_relations: list[dict[str, Any]] = []
    hop2_bridges: list[dict[str, Any]] = []

    with get_sync_db() as conn:
        # Find seed entities matching any query token
        all_ents = conn.execute(
            "SELECT entity_id, name, entity_type, summary, mention_count, last_seen_at FROM alfa_graph_entities ORDER BY mention_count DESC"
        ).fetchall()

        seed_names: set[str] = set()
        for r in all_ents:
            ename = r["name"]
            if any(tok in ename for tok in tokens):
                matched_entities.append(dict(r))
                seed_names.add(ename)
                if len(matched_entities) >= limit:
                    break

        if seed_names:
            placeholders = ",".join("?" for _ in seed_names)
            params = list(seed_names) + list(seed_names)
            h1_rows = conn.execute(
                f"""
                SELECT source_entity, relation_type, target_entity, weight, context_snippet
                FROM alfa_graph_relations
                WHERE active = 1 AND (source_entity IN ({placeholders}) OR target_entity IN ({placeholders}))
                ORDER BY weight DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()

            frontier_nodes: set[str] = set()
            for r in h1_rows:
                d = dict(r)
                hop1_relations.append(d)
                if d["source_entity"] not in seed_names:
                    frontier_nodes.add(d["source_entity"])
                if d["target_entity"] not in seed_names:
                    frontier_nodes.add(d["target_entity"])

            # 2-Hop Bridge Discovery
            if max_hops >= 2 and frontier_nodes:
                fp_place = ",".join("?" for _ in frontier_nodes)
                f_params = list(frontier_nodes) + list(frontier_nodes)
                h2_rows = conn.execute(
                    f"""
                    SELECT source_entity, relation_type, target_entity, weight, context_snippet
                    FROM alfa_graph_relations
                    WHERE active = 1 AND (source_entity IN ({fp_place}) OR target_entity IN ({fp_place}))
                    ORDER BY weight DESC
                    LIMIT ?
                    """,
                    (*f_params, limit),
                ).fetchall()
                for r2 in h2_rows:
                    d2 = dict(r2)
                    if d2 not in hop1_relations:
                        hop2_bridges.append(d2)

    return {
        "status": "success",
        "query": query,
        "matched_entities": matched_entities,
        "hop1_relations": hop1_relations,
        "hop2_bridges": hop2_bridges[:limit],
    }


def format_temporal_graphrag_prompt(query: str, limit: int = 5) -> str:
    """
    Format relevant 1-Hop and 2-Hop Temporal GraphRAG connections into a concise
    system instruction block for automatic recall during LLM turns.
    """
    if not query or len(query.strip()) < 3:
        return ""
    res = query_temporal_graphrag(query, max_hops=2, limit=limit)
    h1 = res.get("hop1_relations", [])
    h2 = res.get("hop2_bridges", [])
    if not h1 and not h2:
        return ""

    lines = ["### 🕸️ TEMPORAL GRAPHRAG SECOND BRAIN (MULTI-HOP RECALL)"]
    for r in h1[:limit]:
        lines.append(
            f"- [1-Hop] `{r['source_entity']}` ➔ **{r['relation_type']}** ➔ `{r['target_entity']}` _(w={r.get('weight', 1.0)})_"
        )
    for r2 in h2[:3]:
        lines.append(
            f"- [2-Hop Bridge] `{r2['source_entity']}` ➔ **{r2['relation_type']}** ➔ `{r2['target_entity']}`"
        )
    return "\n".join(lines)



def get_temporal_graphrag_metrics() -> dict[str, Any]:
    """Return telemetry for the Episodic Temporal GraphRAG Second Brain."""
    init_graphrag_tables()
    with get_sync_db() as conn:
        nodes = conn.execute("SELECT COUNT(*) FROM alfa_graph_entities").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM alfa_graph_relations WHERE active = 1").fetchone()[0]
    return {
        "total_entities": int(nodes),
        "total_relations": int(edges),
    }
