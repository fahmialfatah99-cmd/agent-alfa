"""Knowledge memory, vector search, and second brain indexing tools."""

import logging
import os
from typing import Any

from alfa.core import database
from alfa.core.runtime_ctx import (
    current_user_id_var,
    get_current_user_id,
)
from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Memory")


@register_tool(category="memory")
def save_knowledge_memory(
    key_topic: str, content: str, category: str = "general"
) -> dict[str, Any]:
    """
    Save or update an important fact, user preference, project detail, or note into persistent long-term memory.
    Use this tool whenever the user tells you to remember something, or when important facts about the user/project are shared.

    Args:
        key_topic: Short title or identifier for this memory (e.g. 'user_work_hours', 'project_stack', 'trading_rules').
        content: The detailed information to remember.
        category: Category tag (e.g. 'preference', 'project', 'server', 'general').
    """
    try:
        user_id = get_current_user_id()
        msg = database.save_memory_fact_sync(
            user_id=user_id, key_topic=key_topic, content=content, category=category
        )
        return {"status": "success", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="memory")
def search_knowledge_memory(query: str) -> dict[str, Any]:
    """
    Search the persistent long-term memory for previously saved facts, user preferences, or notes.
    Use this tool when answering questions about user preferences, stored projects, or past instructions.

    Args:
        query: Keyword or phrase to look up.
    """
    try:
        user_id = get_current_user_id()
        memories = database.search_memories_sync(user_id=user_id, query=query)
        if not memories:
            try:
                from alfa.core.db.wa_index import search_memories_ranked_sync

                ranked = search_memories_ranked_sync(user_id=user_id, query=query, limit=10)
                if ranked:
                    memories = [
                        {
                            "category": r.get("category", "general"),
                            "key_topic": r.get("key_topic", ""),
                            "content": r.get("content", ""),
                            "updated_at": r.get("updated_at", ""),
                        }
                        for r in ranked
                    ]
            except Exception as rank_err:  # noqa: BLE001
                logger.debug("Ranked memory search fallback error: %s", rank_err)

        return {"status": "success", "memories": memories}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="memory")
def semantic_search_vector_brain(
    query: str, top_k: int = 5, category: str = "", db_path: str | None = None
) -> dict[str, Any]:
    """
    NEURAL VECTOR BRAIN: Performs semantic similarity search (Hybrid RAG) across all permanent
    knowledge embeddings, documents, research reports, and notes based on meaning/context.

    Args:
        query: Search query, question, or conceptual topic.
        top_k: Number of most relevant document chunks to return (default: 5).
        category: Optional category filter (e.g. 'bisnis', 'coding', 'personal', or empty for all).
        db_path: Optional custom sqlite DB path for isolated environments.
    """
    try:
        from alfa.memory import vector as vector_memory

        user_id = current_user_id_var.get() or 0
        results = vector_memory.semantic_search(
            user_id=user_id,
            query=query,
            top_k=top_k,
            category=category or None,
            db_path=db_path,
        )
        return {
            "status": "success",
            "query": query,
            "total_matches": len(results),
            "matches": results,
        }
    except Exception as e:
        return {"status": "error", "message": f"Vector semantic search error: {str(e)}"}


@register_tool(category="memory")
def search_vector_memory(
    query: str, top_k: int = 5, category: str = "", db_path: str | None = None
) -> dict[str, Any]:
    """
    Search vector memory using semantic similarity search.

    Args:
        query: Conceptual query or phrase to search for.
        top_k: Number of most relevant results to return (default: 5).
        category: Optional category filter.
        db_path: Optional custom sqlite DB path for isolated environments.
    """
    return semantic_search_vector_brain(
        query=query, top_k=top_k, category=category, db_path=db_path
    )


@register_tool(category="memory")
def ingest_document_to_vector_brain(
    title: str,
    content_or_file_path: str,
    category: str = "general",
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    NEURAL VECTOR BRAIN: Ingests, chunks, embeds, and indexes a document or local file
    (.txt, .md, .pdf, .py, .csv, .json, or raw text) into the permanent Vector Brain database.

    Args:
        title: Title / Label for the document.
        content_or_file_path: Raw text string OR absolute/relative file path to ingest.
        category: Knowledge category (e.g. 'bisnis', 'technical', 'finance', 'project').
        db_path: Optional custom sqlite DB path for isolated environments.
    """
    try:
        from alfa.memory import vector as vector_memory

        user_id = current_user_id_var.get() or 0
        return vector_memory.ingest_document(
            user_id=user_id,
            title=title,
            content_or_path=content_or_file_path,
            category=category,
            db_path=db_path,
        )
    except Exception as e:
        return {"status": "error", "message": f"Document ingestion error: {str(e)}"}


@register_tool(category="memory")
def save_to_vector_memory(
    title: str, content: str, category: str = "general", db_path: str | None = None
) -> dict[str, Any]:
    """
    Save or ingest text, notes, or document into persistent vector memory for semantic search.

    Args:
        title: Title / Label for the memory.
        content: Raw text content to remember in vector memory.
        category: Category tag (e.g. 'general', 'notes', 'technical', 'finance').
        db_path: Optional custom sqlite DB path for isolated environments.
    """
    return ingest_document_to_vector_brain(
        title=title, content_or_file_path=content, category=category, db_path=db_path
    )


@register_tool(category="memory")
def list_vector_brain_documents(db_path: str | None = None) -> dict[str, Any]:
    """
    NEURAL VECTOR BRAIN: List all documents and files currently indexed in the Semantic Vector Brain.
    """
    try:
        from alfa.memory import vector as vector_memory

        user_id = current_user_id_var.get() or 0
        docs = vector_memory.list_ingested_documents(user_id=user_id, db_path=db_path)
        return {"status": "success", "total_documents": len(docs), "documents": docs}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="memory")
def extract_and_link_knowledge(
    entity: str,
    relation: str,
    target_value: str,
    category: str = "general",
    tags: str = "",
) -> dict[str, Any]:
    """
    GOD MODE: Semantic Knowledge Graph & Second Brain Linker.
    Stores structured knowledge facts as subject-predicate-object triples
    (e.g. entity: 'Proyek Alfa', relation: 'deadline', target_value: '25 Agustus 2026', tags: 'work, urgent').

    Args:
        entity: The subject entity (e.g. 'Fahmi', 'Server Production', 'Project X').
        relation: The relationship / predicate (e.g. 'role', 'ip_address', 'framework').
        target_value: The target value / object (e.g. 'Lead Engineer', '103.12.34.56', 'FastAPI').
        category: Category taxonomy (e.g. 'work', 'personal', 'server', 'finance').
        tags: Comma-separated tags (e.g. 'urgent, devops').
    """
    uid = get_current_user_id()
    if not uid:
        return {"status": "error", "message": "User context tidak ditemukan."}
    return database.add_knowledge_relation_sync(
        uid, entity, relation, target_value, category, tags
    )


@register_tool(category="memory")
def export_knowledge_base(format: str = "markdown") -> dict[str, Any]:
    """
    GOD MODE: Export Second Brain Knowledge Base.
    Exports all persistent user memories and semantic knowledge graph relations
    into a structured Markdown or JSON file sent to Telegram as an attachment.

    Args:
        format: 'markdown' (default) or 'json'.
    """
    try:
        import json

        uid = get_current_user_id()
        if not uid:
            return {"status": "error", "message": "User context tidak ditemukan."}

        data = database.export_full_second_brain_sync(uid)
        fmt = format.lower()

        if fmt == "json":
            out_name = f"second_brain_export_{uid}.json"
            out_path = os.path.join(SANDBOX_DIR, out_name)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            out_name = f"second_brain_export_{uid}.md"
            out_path = os.path.join(SANDBOX_DIR, out_name)
            md_lines = [
                "# 🧠 Second Brain Knowledge Export",
                f"**User ID:** `{uid}` | **Exported At:** `{data['exported_at']}`\n",
                f"## 📌 Fakta Memori Permanen ({data['total_facts']} fakta)",
            ]
            for fact in data.get("facts", []):
                md_lines.append(
                    f"• **[{fact['category'].upper()}] {fact['key_topic']}**: {fact['content']}"
                )

            md_lines.append(
                f"\n## 🕸️ Knowledge Graph Relations ({data['total_relations']} relasi)"
            )
            for r in data.get("knowledge_graph", []):
                tag_str = f" `[{r['tags']}]`" if r["tags"] else ""
                md_lines.append(
                    f"• **{r['entity']}** ──({r['relation']})──> **{r['target_value']}** ({r['category']}){tag_str}"
                )

            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))

        size_kb = round(os.path.getsize(out_path) / 1024, 1)
        return {
            "status": "success",
            "message": f"Berkas Second Brain '{out_name}' ({size_kb} KB) berhasil diexport dan akan dikirim ke Telegram.",
            "file_path": out_path,
            "total_facts": data["total_facts"],
            "total_relations": data["total_relations"],
        }
    except Exception as e:
        return {"status": "error", "message": f"Export second brain error: {str(e)}"}


# ── UPGRADE TAHAP 1-4: ADVANCED DOCUMENT READING & RAG SUITE ──────────────────


@register_tool(category="memory")
def hybrid_search_vector_brain(
    query: str,
    top_k: int = 5,
    category: str = "",
    alpha: float = 0.65,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    UPGRADE TAHAP 1: Hybrid Vector + BM25 Lexical Search with Re-ranking.
    Combines dense semantic understanding with exact sparse keyword matching,
    followed by cross-encoder re-ranking for ultra-precise retrieval.

    Args:
        query: Search query or conceptual question.
        top_k: Number of most relevant results to return (default: 5).
        category: Optional category filter.
        alpha: Weight for dense vector vs sparse BM25 (0.65 = 65% vector, 35% keyword).
        db_path: Optional custom sqlite DB path.
    """
    try:
        from alfa.memory import vector as vector_memory

        user_id = current_user_id_var.get() or 0
        results = vector_memory.hybrid_search(
            user_id=user_id,
            query=query,
            top_k=top_k,
            category=category or None,
            alpha=alpha,
            rerank=True,
            db_path=db_path,
        )
        return {
            "status": "success",
            "query": query,
            "total_matches": len(results),
            "matches": results,
        }
    except Exception as e:
        return {"status": "error", "message": f"Hybrid search error: {str(e)}"}


@register_tool(category="memory")
def manage_document_context_cache(
    action: str = "create",
    file_path: str = "",
    doc_title: str = "",
    ttl_minutes: int = 60,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """
    UPGRADE TAHAP 2: Gemini Server-Side Context Caching Controller.
    Caches large documents (> 10,000 tokens) in server memory to cut token costs by ~80%
    and accelerate multi-turn queries.

    Args:
        action: 'create' (cache a document), 'list' (view active caches), or 'delete' (remove cache).
        file_path: Path to large document file or text content.
        doc_title: Label for the cached document.
        ttl_minutes: Cache time-to-live in minutes (default: 60).
        model: Gemini model supporting caching (default: 'gemini-2.5-flash').
    """
    try:
        from alfa.memory import context_cache

        act = action.lower().strip()
        if act == "create":
            return context_cache.create_or_get_document_cache(
                file_path_or_text=file_path,
                doc_title=doc_title,
                model=model,
                ttl_minutes=ttl_minutes,
            )
        elif act == "list":
            caches = context_cache.list_active_context_caches()
            return {"status": "success", "total_caches": len(caches), "caches": caches}
        elif act == "delete":
            deleted = context_cache.delete_context_cache(cache_name=file_path)
            return {"status": "success", "deleted": deleted}
        return {"status": "error", "message": f"Aksi '{action}' tidak dikenal."}
    except Exception as e:
        return {"status": "error", "message": f"Context cache error: {str(e)}"}


@register_tool(category="memory")
def agentic_document_query_crag(
    query: str,
    doc_title: str = "",
    category: str = "",
    max_iterations: int = 2,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    UPGRADE TAHAP 3: Agentic Corrective RAG (CRAG) with Self-Reflection.
    Self-evaluates retrieval confidence, expands query and neighboring chunks (+/- 1)
    if confidence is low, and returns synthesized context with verifiable citations.

    Args:
        query: The user question or information to find.
        doc_title: Optional filter for a specific document name.
        category: Optional category filter.
        max_iterations: Max reflection and correction iterations (default: 2).
        db_path: Optional custom sqlite DB path.
    """
    try:
        from alfa.memory import agentic_rag

        user_id = current_user_id_var.get() or 0
        return agentic_rag.agentic_document_query(
            user_id=user_id,
            query=query,
            doc_title=doc_title or None,
            category=category or None,
            max_iterations=max_iterations,
            db_path=db_path,
        )
    except Exception as e:
        return {"status": "error", "message": f"Agentic CRAG error: {str(e)}"}


@register_tool(category="memory")
def analyze_document_tabular_data(
    file_path: str,
    operation: str = "summary",
    sheet_name: str = "",
    filter_column: str = "",
    filter_value: str = "",
    group_by: str = "",
    agg_column: str = "",
    agg_func: str = "sum",
) -> dict[str, Any]:
    """
    UPGRADE TAHAP 3: Exact Tabular Data Analyzer (Pandas Engine).
    Executes 100% mathematically exact calculations on spreadsheets (.xlsx, .csv, .tsv)
    without LLM calculation errors.

    Args:
        file_path: Path to spreadsheet or CSV file.
        operation: 'summary' (stats), 'filter' (query rows), 'aggregate' (group-by), or 'top_n'.
        sheet_name: Specific sheet name (for Excel).
        filter_column: Column name to filter by.
        filter_value: Value to search for.
        group_by: Column to group by.
        agg_column: Numeric column to aggregate (sum, mean, max, min).
        agg_func: Aggregation function ('sum', 'mean', 'count', 'min', 'max').
    """
    try:
        from alfa.memory import table_analyzer

        return table_analyzer.analyze_tabular_data(
            file_path=file_path,
            operation=operation,
            sheet_name=sheet_name or None,
            filter_column=filter_column or None,
            filter_value=filter_value or None,
            group_by=group_by or None,
            agg_column=agg_column or None,
            agg_func=agg_func,
        )
    except Exception as e:
        return {"status": "error", "message": f"Tabular analysis error: {str(e)}"}


@register_tool(category="memory")
def graph_rag_query_multi_doc(
    query: str, max_depth: int = 2, top_k: int = 5, db_path: str | None = None
) -> dict[str, Any]:
    """
    UPGRADE TAHAP 4: Multi-Document GraphRAG Traversal & Reasoning.
    Connects facts across multiple documents by traversing 1-hop and 2-hop knowledge graph
    relationships and renders Mermaid graph diagrams.

    Args:
        query: Entity, concept, or relationship question connecting multiple documents.
        max_depth: Graph traversal depth (1 = direct relations, 2 = 2-hop connected reasoning).
        top_k: Number of relation paths to return.
        db_path: Optional custom sqlite DB path.
    """
    try:
        from alfa.memory import graph_rag

        user_id = current_user_id_var.get() or 0
        return graph_rag.graph_rag_search(
            user_id=user_id,
            query=query,
            max_depth=max_depth,
            top_k=top_k,
            db_path=db_path,
        )
    except Exception as e:
        return {"status": "error", "message": f"GraphRAG search error: {str(e)}"}


@register_tool(category="memory")
def index_document_to_graph(
    doc_title: str, content_or_path: str, db_path: str | None = None
) -> dict[str, Any]:
    """
    UPGRADE TAHAP 4: Ingest and map a document into the Multi-Document Knowledge Graph.

    Args:
        doc_title: Title or label for the document.
        content_or_path: File path or raw text content to map into graph entities and relations.
        db_path: Optional custom sqlite DB path.
    """
    try:
        from alfa.memory import doc_parser, graph_rag

        user_id = current_user_id_var.get() or 0
        if os.path.isfile(content_or_path):
            text, _ = doc_parser.extract_document_content(content_or_path)
        else:
            text = content_or_path

        return graph_rag.extract_and_index_document_graph(
            user_id=user_id,
            doc_title=doc_title,
            text_content=text,
            db_path=db_path,
        )
    except Exception as e:
        return {"status": "error", "message": f"Graph indexing error: {str(e)}"}


@register_tool(category="memory")
def graph_rag_find_path(
    entity_a: str, entity_b: str, max_depth: int = 3, db_path: str | None = None
) -> dict[str, Any]:
    """
    GRAPHRAG PATHFINDER: Temukan rute/rantai relasi terpendek yang menghubungkan Entitas A ke Entitas B
    lintas seluruh dokumen yang terindeks (menggunakan Breadth-First Search).

    Args:
        entity_a: Nama entitas awal (misal: 'Agent Alfa', 'Vendor A', 'Server X').
        entity_b: Nama entitas target (misal: 'Docker Swarm', 'Kabel Dropcore', 'Database Y').
        max_depth: Batas kedalaman penelusuran hop (default: 3).
        db_path: Path opsional database kustom.
    """
    try:
        from alfa.memory import graph_rag

        user_id = current_user_id_var.get() or 0
        return graph_rag.graph_rag_find_connection(
            user_id=user_id,
            entity_a=entity_a,
            entity_b=entity_b,
            max_depth=max_depth,
            db_path=db_path,
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"GraphRAG pathfinder error: {str(e)}"}


@register_tool(category="memory")
def graph_rag_get_overview(
    doc_title: str = "", top_hubs: int = 10, db_path: str | None = None
) -> dict[str, Any]:
    """
    GRAPHRAG OVERVIEW & CENTRALITY: Menghasilkan ringkasan holistik dari Knowledge Graph,
    termasuk entitas sentral (top hubs dengan koneksi terbanyak), daftar dokumen yang terpetakan,
    dan diagram Mermaid jaringan inti.

    Args:
        doc_title: Filter opsional untuk 1 dokumen tertentu (kosongkan untuk seluruh dokumen).
        top_hubs: Jumlah entitas terpenting yang ditampilkan (default: 10).
        db_path: Path opsional database kustom.
    """
    try:
        from alfa.memory import graph_rag

        user_id = current_user_id_var.get() or 0
        return graph_rag.graph_rag_get_overview(
            user_id=user_id,
            doc_title=doc_title,
            top_n=top_hubs,
            db_path=db_path,
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"GraphRAG overview error: {str(e)}"}


@register_tool(category="memory")
def graph_rag_get_communities(
    doc_title: str = "", db_path: str | None = None
) -> dict[str, Any]:
    """
    GRAPHRAG GLOBAL COMMUNITY DETECTION: Mendeteksi kluster/komunitas entitas di Knowledge Graph
    untuk analisis topik makro (Global Search) lintas dokumen.

    Args:
        doc_title: Filter opsional untuk dokumen tertentu.
        db_path: Path opsional database kustom.
    """
    try:
        from alfa.memory import graph_rag

        user_id = current_user_id_var.get() or 0
        return graph_rag.graph_rag_get_communities(
            user_id=user_id,
            doc_title=doc_title,
            db_path=db_path,
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"GraphRAG communities error: {str(e)}"}

