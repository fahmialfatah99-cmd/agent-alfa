"""Deteksi komunitas (community detection) pada graph."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import init_graph_db
from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

def detect_and_save_communities(
    user_id: int, doc_title: str = "", db_path: str | None = None
) -> list[dict[str, Any]]:
    """
    Deteksi kluster komunitas (Connected Components & Degree Centrality)
    dan simpan ke tabel graph_communities untuk analisis global (Global Search).
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    conn = sqlite3.connect(target_db, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT source_entity, relation, target_entity, source_doc
            FROM graph_relations
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()

        if not rows:
            return []

        import collections
        import json

        adj: dict[str, set[str]] = collections.defaultdict(set)
        degree: dict[str, int] = collections.defaultdict(int)
        doc_map: dict[str, set[str]] = collections.defaultdict(set)
        edge_samples: dict[str, list[str]] = collections.defaultdict(list)

        for r in rows:
            u, rel, v, doc = (
                str(r["source_entity"]),
                str(r["relation"]),
                str(r["target_entity"]),
                str(r["source_doc"]),
            )
            adj[u].add(v)
            adj[v].add(u)
            degree[u] += 1
            degree[v] += 1
            doc_map[u].add(doc)
            doc_map[v].add(doc)
            edge_samples[u].append(f"{u} ──[{rel}]──> {v}")

        visited: set[str] = set()
        communities: list[dict[str, Any]] = []
        comm_id = 1

        for node in sorted(adj.keys(), key=lambda x: degree[x], reverse=True):
            if node in visited:
                continue

            component: list[str] = []
            queue: collections.deque[str] = collections.deque([node])
            visited.add(node)

            while queue:
                curr = queue.popleft()
                component.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            component.sort(key=lambda x: degree[x], reverse=True)
            top_hub = component[0]
            docs_in_comm = list({d for m in component for d in doc_map[m]})
            samples = [e for m in component[:3] for e in edge_samples[m][:2]][:4]

            summary = (
                f"Kluster berpusat pada '{top_hub}' dengan {len(component)} entitas "
                f"({', '.join(component[:4])}) dalam dokumen {', '.join(docs_in_comm)}."
            )

            comm_data = {
                "community_id": comm_id,
                "name": f"Kluster {top_hub} ({len(component)} entitas)",
                "top_hub": top_hub,
                "member_count": len(component),
                "members": component,
                "documents": docs_in_comm,
                "sample_relations": samples,
                "summary": summary,
            }
            communities.append(comm_data)

            conn.execute(
                """
                INSERT OR REPLACE INTO graph_communities
                (user_id, community_id, name, entities_json, summary, source_doc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    comm_id,
                    comm_data["name"],
                    json.dumps(component, ensure_ascii=False),
                    summary,
                    docs_in_comm[0] if docs_in_comm else "",
                ),
            )
            comm_id += 1

        conn.commit()
        return communities
    finally:
        conn.close()

def graph_rag_get_communities(
    user_id: int,
    doc_title: str = "",
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Mengambil daftar komunitas entitas (Global Search) yang terbentuk di Knowledge Graph.
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    comms = detect_and_save_communities(user_id=user_id, doc_title=doc_title, db_path=target_db)
    return {
        "status": "success",
        "user_id": user_id,
        "total_communities": len(comms),
        "communities": comms,
        "message": f"Ditemukan {len(comms)} kluster komunitas relasi di knowledge graph.",
    }
