"""Ekstraksi triple dari teks (heuristik) & indeksasi dokumen."""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from alfa.memory.graph_rag._db import init_graph_db, normalize_entity_name
from alfa.memory.graph_rag._llm import extract_triples_with_llm
from alfa.memory.graph_rag.communities import detect_and_save_communities
from alfa.memory.vector import _resolve_db_path

logger = logging.getLogger(__name__)

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

_GRAG_DB_ERR = (sqlite3.Error, RuntimeError, ValueError, TypeError, KeyError)

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
    except _GRAG_DB_ERR as comm_err:  # noqa: BLE001
        logger.debug("Community detection pass skipped: %s", comm_err)

    return {
        "status": "success",
        "doc_title": doc_title,
        "total_entities": len(saved_entities),
        "total_relations": saved_relations,
        "message": f"GraphRAG berhasil memetakan {len(saved_entities)} entitas dan {saved_relations} relasi dari '{doc_title}'.",
    }
