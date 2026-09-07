"""Knowledge memory, vector search, and second brain indexing tools."""

import datetime
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from alfa.core import database
from alfa.core.runtime_ctx import (
    current_chat_id_var,
    current_user_id_var,
    get_current_chat_id,
    get_current_user_id,
)
from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Memory")



@register_tool(category="memory")
def save_knowledge_memory(key_topic: str, content: str, category: str = "general") -> Dict[str, Any]:
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
        msg = database.save_memory_fact_sync(user_id=user_id, key_topic=key_topic, content=content, category=category)
        return {
            "status": "success",
            "message": msg
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="memory")
def search_knowledge_memory(query: str) -> Dict[str, Any]:
    """
    Search the persistent long-term memory for previously saved facts, user preferences, or notes.
    Use this tool when answering questions about user preferences, stored projects, or past instructions.
    
    Args:
        query: Keyword or phrase to look up.
    """
    try:
        user_id = get_current_user_id()
        memories = database.search_memories_sync(user_id=user_id, query=query)
        return {"status": "success", "memories": memories}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="memory")
def semantic_search_vector_brain(query: str, top_k: int = 5, category: str = "") -> Dict[str, Any]:
    """
    NEURAL VECTOR BRAIN: Performs semantic similarity search (Hybrid RAG) across all permanent
    knowledge embeddings, documents, research reports, and notes based on meaning/context.
    
    Args:
        query: Search query, question, or conceptual topic.
        top_k: Number of most relevant document chunks to return (default: 5).
        category: Optional category filter (e.g. 'bisnis', 'coding', 'personal', or empty for all).
    """
    try:
        import vector_memory
        user_id = current_user_id_var.get() or 0
        results = vector_memory.semantic_search(user_id=user_id, query=query, top_k=top_k, category=category or None)
        return {
            "status": "success",
            "query": query,
            "total_matches": len(results),
            "matches": results
        }
    except Exception as e:
        return {"status": "error", "message": f"Vector semantic search error: {str(e)}"}


@register_tool(category="memory")
def ingest_document_to_vector_brain(title: str, content_or_file_path: str, category: str = "general") -> Dict[str, Any]:
    """
    NEURAL VECTOR BRAIN: Ingests, chunks, embeds, and indexes a document or local file 
    (.txt, .md, .pdf, .py, .csv, .json, or raw text) into the permanent Vector Brain database.
    
    Args:
        title: Title / Label for the document.
        content_or_file_path: Raw text string OR absolute/relative file path to ingest.
        category: Knowledge category (e.g. 'bisnis', 'technical', 'finance', 'project').
    """
    try:
        import vector_memory
        user_id = current_user_id_var.get() or 0
        return vector_memory.ingest_document(user_id=user_id, title=title, content_or_path=content_or_file_path, category=category)
    except Exception as e:
        return {"status": "error", "message": f"Document ingestion error: {str(e)}"}


@register_tool(category="memory")
def list_vector_brain_documents() -> Dict[str, Any]:
    """
    NEURAL VECTOR BRAIN: List all documents and files currently indexed in the Semantic Vector Brain.
    """
    try:
        import vector_memory
        user_id = current_user_id_var.get() or 0
        docs = vector_memory.list_ingested_documents(user_id=user_id)
        return {
            "status": "success",
            "total_documents": len(docs),
            "documents": docs
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="memory")
def extract_and_link_knowledge(entity: str, relation: str, target_value: str, category: str = "general", tags: str = "") -> Dict[str, Any]:
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
    return database.add_knowledge_relation_sync(uid, entity, relation, target_value, category, tags)


@register_tool(category="memory")
def export_knowledge_base(format: str = "markdown") -> Dict[str, Any]:
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
            for f in data.get("facts", []):
                md_lines.append(f"• **[{f['category'].upper()}] {f['key_topic']}**: {f['content']}")
                
            md_lines.append(f"\n## 🕸️ Knowledge Graph Relations ({data['total_relations']} relasi)")
            for r in data.get("knowledge_graph", []):
                tag_str = f" `[{r['tags']}]`" if r['tags'] else ""
                md_lines.append(f"• **{r['entity']}** ──({r['relation']})──> **{r['target_value']}** ({r['category']}){tag_str}")
                
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))
                
        size_kb = round(os.path.getsize(out_path) / 1024, 1)
        return {
            "status": "success",
            "message": f"Berkas Second Brain '{out_name}' ({size_kb} KB) berhasil diexport dan akan dikirim ke Telegram.",
            "file_path": out_path,
            "total_facts": data['total_facts'],
            "total_relations": data['total_relations']
        }
    except Exception as e:
        return {"status": "error", "message": f"Export second brain error: {str(e)}"}

