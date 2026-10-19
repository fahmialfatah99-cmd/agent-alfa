"""
Agentic Corrective RAG (CRAG) Engine with Self-Reflection for ALFA Bot.
Implements an active, self-correcting document reading loop:
1. Initial Hybrid Search & Cross-Encoder Re-ranking.
2. Self-Evaluation: Checks semantic confidence and query keyword coverage.
3. Corrective Expansion: If confidence is low or key concepts are missing,
   automatically triggers query rewriting and neighboring chunk expansion (chunk_index +/- 1).
4. Evidence Synthesis with strict verifiable source citations.
"""

import logging
import re
import sqlite3
from typing import Any

from alfa.memory.vector import (
    _resolve_db_path,
    hybrid_search,
    rerank_results,
)

logger = logging.getLogger("AgenticRAG")


def evaluate_retrieval_confidence(
    query: str, retrieved_chunks: list[dict[str, Any]]
) -> tuple[float, list[str]]:
    """
    Evaluates retrieval confidence score (0.0 to 1.0) and identifies missing key terms.
    """
    if not retrieved_chunks:
        return 0.0, [query]

    q_tokens = [t.lower() for t in re.findall(r"\b\w+\b", query) if len(t) > 2]
    if not q_tokens:
        return 0.5, []

    combined_text = " ".join(
        str(c.get("chunk_text", "")).lower() for c in retrieved_chunks
    )

    found_tokens = [t for t in q_tokens if t in combined_text]
    coverage = len(found_tokens) / len(q_tokens)

    top_sim = float(retrieved_chunks[0].get("similarity_score", 0.0))
    top_rerank = float(retrieved_chunks[0].get("rerank_score", top_sim))

    # Weighted confidence metric
    confidence = round(0.4 * coverage + 0.3 * top_sim + 0.3 * top_rerank, 4)
    missing_tokens = [t for t in q_tokens if t not in found_tokens]

    return confidence, missing_tokens


def expand_neighbor_chunks(
    user_id: int,
    chunks: list[dict[str, Any]],
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Expands candidate chunks to include adjacent chunks (chunk_index - 1 and + 1)
    from the same document to recover truncated sentences, tables, or sections.
    """
    target_db = _resolve_db_path(db_path)
    conn = sqlite3.connect(target_db, timeout=10)
    conn.row_factory = sqlite3.Row
    expanded: list[dict[str, Any]] = []
    seen_ids = set()

    try:
        for c in chunks:
            cid = c.get("id")
            doc_title = c.get("doc_title")
            c_idx = c.get("chunk_index", 0)

            if cid not in seen_ids:
                seen_ids.add(cid)
                expanded.append(dict(c))

            # Fetch neighbor chunks (c_idx - 1, c_idx + 1)
            neighbor_rows = conn.execute(
                """
                SELECT id, doc_title, chunk_index, chunk_text, category, source_type, created_at
                FROM vector_knowledge_embeddings
                WHERE user_id = ? AND doc_title = ? AND chunk_index IN (?, ?)
            """,
                (user_id, doc_title, c_idx - 1, c_idx + 1),
            ).fetchall()

            for nr in neighbor_rows:
                if nr["id"] not in seen_ids:
                    seen_ids.add(nr["id"])
                    item = dict(nr)
                    item["similarity_score"] = round(c.get("similarity_score", 0.5) * 0.9, 4)
                    item["hybrid_score"] = round(c.get("hybrid_score", 0.5) * 0.9, 4)
                    item["rerank_score"] = round(c.get("rerank_score", 0.5) * 0.9, 4)
                    item["match_reasons"] = ["Context window neighbor expansion"]
                    expanded.append(item)

        return expanded
    finally:
        conn.close()


def agentic_document_query(
    user_id: int,
    query: str,
    doc_title: str | None = None,
    category: str | None = None,
    max_iterations: int = 2,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Executes an autonomous, self-correcting Corrective RAG (CRAG) loop on documents.

    Returns:
        dict containing:
        - confidence_score: float
        - iterations_run: int
        - citations: list of cited chunk references
        - synthesized_context: formatted context with explicit citations
        - missing_concepts: list of unaddressed query terms if any
    """
    current_query = query.strip()
    if not current_query:
        return {
            "status": "error",
            "message": "Query pencarian tidak boleh kosong.",
            "confidence_score": 0.0,
            "citations": [],
            "synthesized_context": "",
        }

    iterations_run = 0
    all_chunks: list[dict[str, Any]] = []
    confidence = 0.0
    missing_tokens: list[str] = []

    for _it in range(max_iterations):
        iterations_run += 1

        # 1. Hybrid search with re-ranking
        candidates = hybrid_search(
            user_id=user_id,
            query=current_query,
            top_k=5,
            category=category,
            db_path=db_path,
        )

        # Filter by doc_title if specified
        if doc_title and doc_title.strip():
            candidates = [
                c
                for c in candidates
                if doc_title.lower() in str(c.get("doc_title", "")).lower()
            ]

        # 2. Self-Reflection & Quality Assessment
        conf, missing = evaluate_retrieval_confidence(query, candidates)
        confidence = conf
        missing_tokens = missing

        if not all_chunks:
            all_chunks = candidates
        else:
            # Merge new candidates
            existing_ids = {c["id"] for c in all_chunks}
            for cand in candidates:
                if cand["id"] not in existing_ids:
                    all_chunks.append(cand)

        # High confidence threshold reached -> proceed to synthesis
        if confidence >= 0.65 or not missing_tokens:
            break

        # 3. Corrective Action: Expand neighboring context & reformulate query
        all_chunks = expand_neighbor_chunks(user_id, all_chunks, db_path=db_path)
        if missing_tokens:
            current_query = f"{query} {' '.join(missing_tokens)}"

    # Re-rank final pool
    final_chunks = rerank_results(query, all_chunks, top_k=6)

    # Format synthesized context with exact verifiable citations
    citation_cards = []
    context_blocks = []

    for i, c in enumerate(final_chunks, 1):
        d_title = c.get("doc_title", "Dokumen")
        c_idx = c.get("chunk_index", 0)
        c_text = c.get("chunk_text", "").strip()
        score = c.get("rerank_score", c.get("similarity_score", 0.0))
        reasons = ", ".join(c.get("match_reasons", ["Relevan"]))

        citation_tag = f"[Kutipan #{i} | {d_title} (Bagian {c_idx})]"
        citation_cards.append({
            "citation_id": i,
            "doc_title": d_title,
            "chunk_index": c_idx,
            "score": score,
            "reasons": reasons,
            "snippet": c_text[:200] + ("..." if len(c_text) > 200 else ""),
        })

        context_blocks.append(
            f"{citation_tag}\n{c_text}\n(Akurasi Relevansi: {int(score * 100)}% | Alasan: {reasons})\n"
        )

    synthesized_context = "\n---\n".join(context_blocks)

    return {
        "status": "success",
        "query": query,
        "confidence_score": confidence,
        "iterations_run": iterations_run,
        "total_citations": len(citation_cards),
        "citations": citation_cards,
        "synthesized_context": synthesized_context,
        "missing_concepts": missing_tokens,
    }
