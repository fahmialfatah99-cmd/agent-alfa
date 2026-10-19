"""
Multi-Document GraphRAG & Semantic Knowledge Graph Engine for ALFA Bot.
Implements entity extraction, relation mapping, and multi-hop graph traversal
to connect facts and reasoning across multiple disparate documents:
- Schema: Nodes (entities) and Edges (relations) linked to source documents and evidence snippets.
- Multi-Hop Traversal: 1-hop and 2-hop relational paths connecting cross-document facts.
- Graph Visualization: Generates interactive Mermaid diagram syntax for UI/chat rendering.
"""

import logging
import os
import re
import sqlite3
from typing import Any

from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger("GraphRAG")

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
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to init graph db: {e}")
    finally:
        conn.close()


init_graph_db()


# Entity & Relation Extraction Patterns (Indonesian & English)
_RELATION_PATTERNS = [
    # Indonesian: X adalah / merupakan Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:adalah|merupakan|yakni|yaitu)\s+([a-zA-Z0-9_\s]{3,50})",
        re.IGNORECASE,
    ),
    # Indonesian: X menggunakan / memakai Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:menggunakan|memakai|berbasis|dibangun dengan)\s+([A-Z][a-zA-Z0-9_\s]{2,40})",
        re.IGNORECASE,
    ),
    # Indonesian: X bagian dari / cabang dari Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:bagian dari|komponen dari|cabang dari)\s+([A-Z][a-zA-Z0-9_\s]{2,40})",
        re.IGNORECASE,
    ),
    # Indonesian: X terhubung ke / terintegrasi dengan Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:terhubung ke|terintegrasi dengan|berkomunikasi dengan)\s+([A-Z][a-zA-Z0-9_\s]{2,40})",
        re.IGNORECASE,
    ),
    # English: X uses / utilizes / integrates with Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:uses|utilizes|integrates with|runs on)\s+([A-Z][a-zA-Z0-9_\s]{2,40})",
        re.IGNORECASE,
    ),
    # English: X is a / is an Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:is a|is an)\s+([a-zA-Z0-9_\s]{3,50})",
        re.IGNORECASE,
    ),
]


def extract_triples_from_text(
    text: str, doc_title: str
) -> list[tuple[str, str, str, str]]:
    """
    Extracts Subject-Predicate-Object triples from sentences.
    Returns: list of (source_entity, relation, target_entity, evidence_sentence)
    """
    triples = []
    sentences = re.split(r"[.\n;]+", text)

    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 10:
            continue

        for p_idx, pat in enumerate(_RELATION_PATTERNS):
            m = pat.search(s_clean)
            if m:
                src = m.group(1).strip()
                tgt = m.group(2).strip()

                if p_idx == 0 or p_idx == 5:
                    rel = "adalah"
                elif p_idx == 1 or p_idx == 4:
                    rel = "menggunakan"
                elif p_idx == 2:
                    rel = "bagian_dari"
                elif p_idx == 3:
                    rel = "terhubung_ke"
                else:
                    rel = "relasi"

                if src.lower() != tgt.lower() and len(src) > 1 and len(tgt) > 1:
                    triples.append((src, rel, tgt, s_clean[:180]))
                    break

    return triples


def extract_and_index_document_graph(
    user_id: int,
    doc_title: str,
    text_content: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Extracts entities and relationships from document content and indexes them into GraphRAG.
    """
    target_db = _resolve_db_path(db_path)
    init_graph_db(target_db)

    triples = extract_triples_from_text(text_content, doc_title)
    if not triples:
        # Fallback: extract capitalized noun pairs
        capitalized = list(
            set(re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,20}\b", text_content))
        )
        if len(capitalized) >= 2:
            root = doc_title or capitalized[0]
            for other in capitalized[:6]:
                if other != root:
                    triples.append(
                        (root, "memuat_topik", other, f"{root} memuat pembahasan {other}")
                    )

    conn = sqlite3.connect(target_db, timeout=10)
    saved_relations = 0
    saved_entities = set()

    try:
        # Remove old graph records for this doc
        conn.execute(
            "DELETE FROM graph_relations WHERE user_id = ? AND source_doc = ?",
            (user_id, doc_title),
        )
        conn.execute(
            "DELETE FROM graph_entities WHERE user_id = ? AND source_doc = ?",
            (user_id, doc_title),
        )

        for src, rel, tgt, ev in triples:
            conn.execute(
                """
                INSERT INTO graph_relations
                (user_id, source_entity, relation, target_entity, weight, source_doc, evidence)
                VALUES (?, ?, ?, ?, 1.0, ?, ?)
            """,
                (user_id, src, rel, tgt, doc_title, ev),
            )
            saved_relations += 1

            for ent in (src, tgt):
                if ent not in saved_entities:
                    saved_entities.add(ent)
                    conn.execute(
                        """
                        INSERT INTO graph_entities
                        (user_id, name, entity_type, description, source_doc)
                        VALUES (?, ?, 'concept', ?, ?)
                    """,
                        (user_id, ent, f"Entitas dari {doc_title}", doc_title),
                    )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
        "doc_title": doc_title,
        "total_entities": len(saved_entities),
        "total_relations": saved_relations,
        "message": f"GraphRAG berhasil memetakan {len(saved_entities)} entitas dan {saved_relations} relasi dari '{doc_title}'.",
    }


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
