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


init_graph_db()


# Entity Normalization & Alias Rules
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


def _get_gemini_client(api_key: str | None = None) -> Any:
    """Inisialisasi klien google.genai secara aman (fallback None di CI/offline)."""
    try:
        from google.genai import Client

        key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not key or "CI_DUMMY" in key:
            return None
        return Client(api_key=key)
    except Exception:  # noqa: BLE001
        return None


def extract_triples_with_llm(
    text: str, doc_title: str, client: Any = None
) -> list[tuple[str, str, str, str]]:
    """
    Ekstrak Subject-Predicate-Object (SPO) triples menggunakan LLM (Open-IE).
    Kembalikan list of (source, relation, target, evidence).
    Jika gagal atau offline, fallback ke list kosong agar diproses oleh regex.
    """
    if client is None:
        client = _get_gemini_client()
    if client is None:
        return []

    try:
        prompt = (
            "Anda adalah AI Semantic Knowledge Graph Extractor.\n"
            f"Ekstrak semua relasi entitas fakta (Subject - Predicate - Object) dari teks dokumen '{doc_title}' berikut.\n"
            "Format output HARUS berupa JSON array of objects murni tanpa markdown/penjelasan:\n"
            '[{"source": "Entitas Subjek", "relation": "kata_kerja_relasi", "target": "Entitas Objek", "evidence": "Kutipan kalimat bukti"}]\n\n'
            "Aturan:\n"
            "1. Normalisasi nama subjek dan objek menjadi nama entitas ringkas.\n"
            "2. Gunakan relasi ringkas (misal: 'menggunakan', 'bagian_dari', 'terhubung_ke', 'adalah', 'berjalan_di').\n"
            "3. Hanya ekstrak fakta nyata yang ada pada teks.\n\n"
            f"Teks Dokumen:\n{text[:6000]}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw_text = (response.text or "").strip()
        import json

        if "```" in raw_text:
            m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
            if m:
                raw_text = m.group(1).strip()
        data = json.loads(raw_text)
        if isinstance(data, list):
            results: list[tuple[str, str, str, str]] = []
            for item in data:
                if isinstance(item, dict):
                    src = normalize_entity_name(str(item.get("source", "")))
                    rel = str(item.get("relation", "")).strip().replace(" ", "_").lower()
                    tgt = normalize_entity_name(str(item.get("target", "")))
                    ev = str(item.get("evidence", "")).strip()
                    if src and tgt and rel and src.lower() != tgt.lower():
                        results.append((src, rel, tgt, ev[:200]))
            if results:
                return results
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM Graph extraction fallback to regex: %s", exc)
    return []


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
    # Indonesian: X berjalan di / berjalan pada Y
    re.compile(
        r"([A-Z][a-zA-Z0-9_\s]{2,30})\s+(?:berjalan pada|berjalan di|dihosting di)\s+([a-zA-Z0-9_\s]{2,40})",
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
    triples: list[tuple[str, str, str, str]] = []
    sentences = re.split(r"[.\n;]+", text)

    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 10:
            continue

        for p_idx, pat in enumerate(_RELATION_PATTERNS):
            m = pat.search(s_clean)
            if m:
                raw_src = m.group(1).strip()
                raw_tgt = m.group(2).strip()
                src = normalize_entity_name(raw_src)
                tgt = normalize_entity_name(raw_tgt)

                if p_idx in (0, 5):
                    rel = "adalah"
                elif p_idx in (1, 4):
                    rel = "menggunakan"
                elif p_idx == 2:
                    rel = "bagian_dari"
                elif p_idx == 3:
                    rel = "terhubung_ke"
                elif p_idx == 6:
                    rel = "berjalan_di"
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

    # 1. Coba LLM Open-IE terlebih dahulu
    triples = extract_triples_with_llm(text_content, doc_title)

    # 2. Jika offline / LLM tidak tersedia / kosong, fallback ke regex
    if not triples:
        triples = extract_triples_from_text(text_content, doc_title)

    if not triples:
        # Fallback: extract capitalized noun pairs
        capitalized = list(
            set(re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,20}\b", text_content))
        )
        if len(capitalized) >= 2:
            root = normalize_entity_name(doc_title or capitalized[0])
            for other in capitalized[:6]:
                norm_other = normalize_entity_name(other)
                if norm_other and norm_other.lower() != root.lower():
                    triples.append(
                        (root, "memuat_topik", norm_other, f"{root} memuat pembahasan {norm_other}")
                    )

    conn = sqlite3.connect(target_db, timeout=10)
    saved_relations = 0
    saved_entities: set[str] = set()

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
        conn.execute(
            "DELETE FROM graph_communities WHERE user_id = ? AND source_doc = ?",
            (user_id, doc_title),
        )

        for raw_src, rel, raw_tgt, ev in triples:
            src = normalize_entity_name(raw_src)
            tgt = normalize_entity_name(raw_tgt)
            if not src or not tgt or src.lower() == tgt.lower():
                continue

            conn.execute(
                """
                INSERT INTO graph_relations
                (user_id, source_entity, relation, target_entity, weight, source_doc, evidence)
                VALUES (?, ?, ?, ?, 1.0, ?, ?)
            """,
                (user_id, src, rel, tgt, doc_title, ev),
            )
            saved_relations += 1

            for raw_val, norm_val in ((raw_src, src), (raw_tgt, tgt)):
                if norm_val not in saved_entities:
                    saved_entities.add(norm_val)
                    conn.execute(
                        """
                        INSERT INTO graph_entities
                        (user_id, name, entity_type, description, source_doc)
                        VALUES (?, ?, 'concept', ?, ?)
                    """,
                        (user_id, norm_val, f"Entitas dari {doc_title}", doc_title),
                    )

                raw_clean = raw_val.strip().strip("'\"`.,:;()[]{}")
                if raw_clean.lower() != norm_val.lower():
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO graph_entity_aliases (user_id, canonical_name, alias)
                        VALUES (?, ?, ?)
                    """,
                        (user_id, norm_val, raw_clean),
                    )

        conn.commit()
    finally:
        conn.close()

    # Community detection
    try:
        detect_and_save_communities(user_id=user_id, doc_title=doc_title, db_path=target_db)
    except Exception as comm_err:  # noqa: BLE001
        logger.debug("Community detection pass skipped: %s", comm_err)

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
