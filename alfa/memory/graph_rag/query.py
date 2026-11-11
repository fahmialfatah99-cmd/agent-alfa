"""Pencarian, koneksi antare entitas, & ringkasan graph."""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import init_graph_db, normalize_entity_name
from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

def graph_rag_search(
    user_id: int,
    query: str,
    max_depth: int = 2,
    top_k: int = 5,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Performs multi-hop graph traversal across multiple documents to answer synthesis queries.
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    q_tokens = [t.lower() for t in re.findall(r"\b\w+\b", query) if len(t) > 2]
    conn = sqlite3.connect(target_db, timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        # 1. Find seed entities matching query
        query_pattern = f"%{query}%"
        seed_rows = conn.execute(
            """
            SELECT DISTINCT source_entity, target_entity, relation, source_doc, evidence
            FROM graph_relations
            WHERE user_id = ? AND (
                source_entity LIKE ? OR target_entity LIKE ? OR relation LIKE ? OR evidence LIKE ?
            )
            LIMIT 15
        """,
            (user_id, query_pattern, query_pattern, query_pattern, query_pattern),
        ).fetchall()

        if not seed_rows and q_tokens:
            # Match any individual token
            placeholders = " OR ".join(
                ["source_entity LIKE ? OR target_entity LIKE ?"] * len(q_tokens)
            )
            params: list[Any] = [user_id]
            for tok in q_tokens:
                params.extend([f"%{tok}%", f"%{tok}%"])
            seed_rows = conn.execute(
                f"""
                SELECT DISTINCT source_entity, target_entity, relation, source_doc, evidence
                FROM graph_relations
                WHERE user_id = ? AND ({placeholders})
                LIMIT 15
            """,  # nosec B608 - placeholders are fixed "?" markers; only the
                # static OR-clause string is interpolated, never user data
                params,
            ).fetchall()

        # 2. Multi-Hop Traversal (connect dots across documents)
        paths = []
        cross_doc_links = []
        docs_involved = set()

        for row in seed_rows:
            src = row["source_entity"]
            rel = row["relation"]
            tgt = row["target_entity"]
            doc = row["source_doc"]
            docs_involved.add(doc)

            hop_1 = {
                "source": src,
                "relation": rel,
                "target": tgt,
                "source_doc": doc,
                "evidence": row["evidence"],
            }
            paths.append(hop_1)

            # Traverse 2nd hop: find connections where tgt is source_entity
            if max_depth >= 2:
                hop_2_rows = conn.execute(
                    """
                    SELECT source_entity, relation, target_entity, source_doc, evidence
                    FROM graph_relations
                    WHERE user_id = ? AND source_entity = ? AND target_entity != ?
                    LIMIT 5
                """,
                    (user_id, tgt, src),
                ).fetchall()

                for h2 in hop_2_rows:
                    doc2 = h2["source_doc"]
                    docs_involved.add(doc2)
                    paths.append({
                        "source": h2["source_entity"],
                        "relation": h2["relation"],
                        "target": h2["target_entity"],
                        "source_doc": doc2,
                        "evidence": h2["evidence"],
                        "connected_from": src,
                    })
                    if doc != doc2:
                        cross_doc_links.append({
                            "path": f"{src} ──[{rel}]──> {tgt} ──[{h2['relation']}]──> {h2['target_entity']}",
                            "doc_origin": doc,
                            "doc_destination": doc2,
                        })

        # 3. Generate Mermaid visualization graph
        mermaid_lines = ["graph LR"]
        for p in paths[:top_k * 2]:
            s_clean = re.sub(r"[^a-zA-Z0-9_]", "_", p["source"])
            t_clean = re.sub(r"[^a-zA-Z0-9_]", "_", p["target"])
            mermaid_lines.append(
                f'    {s_clean}["{p["source"]}"] -->|"{p["relation"]}"| {t_clean}["{p["target"]}"]'
            )

        mermaid_graph = "\n".join(mermaid_lines)

        return {
            "status": "success",
            "query": query,
            "total_relations_found": len(paths),
            "documents_involved": list(docs_involved),
            "cross_document_links": cross_doc_links,
            "graph_paths": paths[:top_k],
            "mermaid_diagram": mermaid_graph,
        }
    finally:
        conn.close()

def graph_rag_find_connection(
    user_id: int,
    entity_a: str,
    entity_b: str,
    max_depth: int = 3,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Find shortest relational path connecting Entity A to Entity B across indexed documents.
    Uses Breadth-First Search (BFS) over graph_relations.
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    a_clean = entity_a.strip()
    b_clean = entity_b.strip()
    if not a_clean or not b_clean:
        return {"status": "error", "message": "entity_a dan entity_b tidak boleh kosong."}

    conn = sqlite3.connect(target_db, timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        a_norm = normalize_entity_name(a_clean)
        b_norm = normalize_entity_name(b_clean)

        # Find matching seed entities (with normalization & alias resolution)
        seed_a_rows = conn.execute(
            """
            SELECT DISTINCT source_entity FROM graph_relations
            WHERE user_id = ? AND (LOWER(source_entity) = LOWER(?) OR LOWER(source_entity) = LOWER(?) OR source_entity LIKE ?)
            UNION
            SELECT DISTINCT target_entity FROM graph_relations
            WHERE user_id = ? AND (LOWER(target_entity) = LOWER(?) OR LOWER(target_entity) = LOWER(?) OR target_entity LIKE ?)
            UNION
            SELECT canonical_name FROM graph_entity_aliases
            WHERE user_id = ? AND (LOWER(alias) = LOWER(?) OR LOWER(alias) = LOWER(?))
            LIMIT 5
            """,
            (user_id, a_clean, a_norm, f"%{a_norm}%", user_id, a_clean, a_norm, f"%{a_norm}%", user_id, a_clean, a_norm),
        ).fetchall()

        seed_b_rows = conn.execute(
            """
            SELECT DISTINCT source_entity FROM graph_relations
            WHERE user_id = ? AND (LOWER(source_entity) = LOWER(?) OR LOWER(source_entity) = LOWER(?) OR source_entity LIKE ?)
            UNION
            SELECT DISTINCT target_entity FROM graph_relations
            WHERE user_id = ? AND (LOWER(target_entity) = LOWER(?) OR LOWER(target_entity) = LOWER(?) OR target_entity LIKE ?)
            UNION
            SELECT canonical_name FROM graph_entity_aliases
            WHERE user_id = ? AND (LOWER(alias) = LOWER(?) OR LOWER(alias) = LOWER(?))
            LIMIT 5
            """,
            (user_id, b_clean, b_norm, f"%{b_norm}%", user_id, b_clean, b_norm, f"%{b_norm}%", user_id, b_clean, b_norm),
        ).fetchall()

        targets_b = {r[0].lower(): r[0] for r in seed_b_rows}
        if not seed_a_rows or not targets_b:
            return {
                "status": "not_found",
                "message": f"Tidak ditemukan entitas untuk '{a_clean}' atau '{b_clean}' dalam knowledge graph.",
                "path_found": False,
                "chain": "",
                "documents": [],
            }

        def _matches_target(ent: str) -> bool:
            e_low = ent.lower()
            return any(tb in e_low or e_low in tb for tb in targets_b)

        import collections

        queue: collections.deque[tuple[str, list[dict[str, Any]], set[str]]] = collections.deque()
        for r in seed_a_rows:
            ent = r[0]
            queue.append((ent, [], {ent.lower()}))

        found_path = None
        while queue:
            curr, path_edges, visited = queue.popleft()
            if _matches_target(curr) and path_edges:
                found_path = path_edges
                break

            if len(path_edges) >= max_depth:
                continue

            neighbors = conn.execute(
                """
                SELECT source_entity, relation, target_entity, source_doc, evidence
                FROM graph_relations
                WHERE user_id = ? AND (
                    source_entity = ? OR target_entity = ?
                    OR (? LIKE '%' || source_entity || '%' AND length(source_entity) >= 3)
                    OR (? LIKE '%' || target_entity || '%' AND length(target_entity) >= 3)
                    OR (source_entity LIKE '%' || ? || '%' AND length(?) >= 3)
                    OR (target_entity LIKE '%' || ? || '%' AND length(?) >= 3)
                )
                LIMIT 25
                """,
                (user_id, curr, curr, curr, curr, curr, curr, curr, curr),
            ).fetchall()

            for n in neighbors:
                src, rel, tgt, doc, ev = (
                    n["source_entity"],
                    n["relation"],
                    n["target_entity"],
                    n["source_doc"],
                    n["evidence"],
                )
                next_node = (
                    tgt
                    if (src.lower() == curr.lower() or src.lower() in curr.lower())
                    else src
                )
                if next_node.lower() not in visited:
                    new_visited = visited | {next_node.lower()}
                    edge_info = {
                        "from": src,
                        "relation": rel,
                        "to": tgt,
                        "step": f"{src} ──[{rel}]──> {tgt}",
                        "source_doc": doc,
                        "evidence": ev,
                    }
                    queue.append((next_node, path_edges + [edge_info], new_visited))

        if not found_path:
            return {
                "status": "not_found",
                "message": f"Tidak ditemukan jalur relasi yang menghubungkan '{a_clean}' dengan '{b_clean}' (maks {max_depth} hop).",
                "path_found": False,
                "chain": "",
                "documents": [],
            }

        docs_involved = list({edge["source_doc"] for edge in found_path})
        chain_str = " ──> ".join(edge["step"] for edge in found_path)

        mermaid_lines = ["graph LR"]
        for edge in found_path:
            s_clean = re.sub(r"[^a-zA-Z0-9_]", "_", edge["from"])
            t_clean = re.sub(r"[^a-zA-Z0-9_]", "_", edge["to"])
            mermaid_lines.append(
                f'    {s_clean}["{edge["from"]}"] -->|"{edge["relation"]}"| {t_clean}["{edge["to"]}"]'
            )
        mermaid_diag = "\n".join(mermaid_lines)

        return {
            "status": "success",
            "path_found": True,
            "entity_a": a_clean,
            "entity_b": b_clean,
            "hops_count": len(found_path),
            "connection_chain": chain_str,
            "documents_involved": docs_involved,
            "path_details": found_path,
            "mermaid_diagram": mermaid_diag,
            "message": f"Ditemukan koneksi {len(found_path)} langkah antara '{a_clean}' dan '{b_clean}'.",
        }
    finally:
        conn.close()

def graph_rag_get_overview(
    user_id: int,
    doc_title: str = "",
    top_n: int = 10,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Generate an architectural overview and top entity hubs from the Knowledge Graph.
    Identifies high-centrality hubs and relation networks.
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    conn = sqlite3.connect(target_db, timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        doc_filter = ""
        params: list[Any] = [user_id]
        if doc_title:
            doc_filter = "AND source_doc = ?"
            params.append(doc_title.strip())

        # 1. Total counts (pola konstanta .replace agar bandit-B608-safe)
        total_rel_sql = (
            "SELECT COUNT(*) FROM graph_relations WHERE user_id = ? {df}"  # nosec B608
        ).replace("{df}", doc_filter)
        total_rel = conn.execute(total_rel_sql, params).fetchone()[0]

        total_ent_sql = (
            "SELECT COUNT(DISTINCT name) FROM graph_entities WHERE user_id = ? {df}"  # nosec B608
        ).replace("{df}", doc_filter)
        total_ent = conn.execute(total_ent_sql, params).fetchone()[0]

        # 2. Top Hubs (Degree Centrality: entities with highest in + out edges)
        hubs_sql = (
            "SELECT entity, COUNT(*) as degree FROM ("  # nosec B608
            "  SELECT source_entity AS entity FROM graph_relations WHERE user_id = ? {df}"
            "  UNION ALL"
            "  SELECT target_entity AS entity FROM graph_relations WHERE user_id = ? {df}"
            ") GROUP BY entity ORDER BY degree DESC LIMIT ?"
        ).replace("{df}", doc_filter)
        hubs_rows = conn.execute(hubs_sql, params + params + [top_n]).fetchall()

        top_hubs = [
            {"entity": r["entity"], "connections_count": r["degree"]}
            for r in hubs_rows
        ]

        # 3. Documents breakdown
        docs_rows = conn.execute(
            """
            SELECT source_doc, COUNT(*) as relations_count
            FROM graph_relations
            WHERE user_id = ?
            GROUP BY source_doc
            ORDER BY relations_count DESC
            """,
            (user_id,),
        ).fetchall()
        docs_breakdown = [
            {"doc_title": r["source_doc"], "relations_count": r["relations_count"]}
            for r in docs_rows
        ]

        # 4. Core Mermaid diagram of the top hubs
        hub_names = [h["entity"] for h in top_hubs[:6]]
        mermaid_lines = ["graph LR"]
        if hub_names:
            placeholders = " OR ".join(
                ["source_entity = ? OR target_entity = ?"] * len(hub_names)
            )
            edge_params: list[Any] = [user_id]
            if doc_title:
                edge_params.append(doc_title.strip())
            for h in hub_names:
                edge_params.extend([h, h])

            core_edges_sql = (
                "SELECT DISTINCT source_entity, relation, target_entity "  # nosec B608
                "FROM graph_relations "
                "WHERE user_id = ? {df} AND ({ph}) "
                "LIMIT 15"
            ).replace("{df}", doc_filter).replace("{ph}", placeholders)
            core_edges = conn.execute(core_edges_sql, edge_params).fetchall()

            for edge in core_edges:
                s_clean = re.sub(r"[^a-zA-Z0-9_]", "_", edge["source_entity"])
                t_clean = re.sub(r"[^a-zA-Z0-9_]", "_", edge["target_entity"])
                mermaid_lines.append(
                    f'    {s_clean}["{edge["source_entity"]}"] -->|"{edge["relation"]}"| {t_clean}["{edge["target_entity"]}"]'
                )

        mermaid_diag = "\n".join(mermaid_lines)

        return {
            "status": "success",
            "filter_doc": doc_title or "All Documents",
            "total_entities": total_ent,
            "total_relations": total_rel,
            "top_hubs": top_hubs,
            "documents_indexed": docs_breakdown,
            "core_mermaid_diagram": mermaid_diag,
            "message": f"Overview GraphRAG: {total_ent} entitas dan {total_rel} relasi terpetakan.",
        }
    finally:
        conn.close()
