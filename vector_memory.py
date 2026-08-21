"""
Semantic Vector Memory & Hybrid RAG Engine for ALFA Sovereign AI Bot.
Provides vector embeddings, semantic search, sliding-window chunking, and document ingestion
for permanent long-term memory across chat turns, documents, and research notes.
"""

import os
import sys
import json
import math
import sqlite3
import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

logger = logging.getLogger("VectorMemory")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")


def init_vector_db():
    """Ensure vector knowledge table and indices exist in SQLite."""
    try:
        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_knowledge_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    doc_title TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    source_type TEXT DEFAULT 'text',
                    char_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vke_user_cat ON vector_knowledge_embeddings(user_id, category);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vke_doc ON vector_knowledge_embeddings(user_id, doc_title);")
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to init vector db: {e}")


init_vector_db()


def _local_subword_embedding(text: str, dim: int = 384) -> List[float]:
    """
    High-quality deterministic subword & character n-gram hashing dense vectorizer.
    Produces a normalized dense vector of dimension `dim` (default 384) for offline fallback.
    """
    vec = np.zeros(dim, dtype=np.float32)
    clean_text = text.lower().strip()
    words = clean_text.split()
    
    # 1. Word level hashing
    for w in words:
        h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
        vec[idx] += sign * (1.0 + math.log(len(w) + 1))
        
    # 2. Character 3-gram and 4-gram hashing
    for n in (3, 4):
        for i in range(max(0, len(clean_text) - n + 1)):
            ngram = clean_text[i:i+n]
            h = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
            vec[idx] += sign * 0.5
            
    # L2 normalize
    norm = np.linalg.norm(vec)
    if norm > 1e-6:
        vec = vec / norm
    return vec.tolist()


def get_text_embedding(text: str) -> List[float]:
    """
    Generate vector embedding using Gemini API (text-embedding-004) if available,
    otherwise fallback seamlessly to local dense subword vectorizer.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key and api_key != "your_gemini_api_key_here":
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            resp = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text
            )
            if hasattr(resp, "embedding") and hasattr(resp.embedding, "values"):
                vec = np.array(resp.embedding.values, dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 1e-6:
                    vec = vec / norm
                return vec.tolist()
            elif hasattr(resp, "embeddings") and len(resp.embeddings) > 0:
                vec = np.array(resp.embeddings[0].values, dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 1e-6:
                    vec = vec / norm
                return vec.tolist()
        except Exception as e:
            logger.debug(f"Gemini embedding API fallback to local vectorizer: {e}")
            
    return _local_subword_embedding(text)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-6 or norm_b < 1e-6:
        return 0.0
    return float(dot / (norm_a * norm_b))


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    """
    Splits text into chunks preserving sentence and paragraph boundaries.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return []
        
    chunks = []
    current_chunk = []
    current_len = 0
    
    for p in paragraphs:
        p_len = len(p)
        if current_len + p_len > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            if overlap > 0 and len(current_chunk) > 1:
                current_chunk = [current_chunk[-1], p]
                current_len = len(current_chunk[0]) + p_len
            else:
                current_chunk = [p]
                current_len = p_len
        else:
            current_chunk.append(p)
            current_len += p_len + 1
            
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    return chunks


def ingest_document(
    user_id: int, 
    title: str, 
    content_or_path: str, 
    category: str = "general"
) -> Dict[str, Any]:
    """
    Ingest a document (raw text or file path like .txt, .md, .pdf, .py, .csv, .json)
    into the vector database with chunking and embeddings.
    """
    init_vector_db()
    source_type = "text"
    text_content = content_or_path.strip()
    
    # Check if content_or_path is an existing file
    if os.path.isfile(content_or_path):
        source_type = os.path.splitext(content_or_path)[1].lstrip(".").lower() or "file"
        try:
            if source_type == "pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(content_or_path)
                    pages_text = [page.extract_text() or "" for page in reader.pages]
                    text_content = "\n\n".join(pages_text)
                except ImportError:
                    return {"status": "error", "message": "pypdf belum terpasang untuk membaca file PDF."}
            else:
                with open(content_or_path, "r", encoding="utf-8", errors="ignore") as f:
                    text_content = f.read()
        except Exception as read_err:
            return {"status": "error", "message": f"Gagal membaca file {content_or_path}: {read_err}"}
            
    if not text_content:
        return {"status": "error", "message": "Konten dokumen kosong."}
        
    # Chunk text
    chunks = chunk_text(text_content, chunk_size=500, overlap=60)
    if not chunks:
        chunks = [text_content[:1000]]
        
    # Delete old chunks for this document if already existing
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("DELETE FROM vector_knowledge_embeddings WHERE user_id = ? AND doc_title = ?", (user_id, title))
        conn.commit()
        
    # Ingest chunks with embeddings
    saved_count = 0
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        for idx, chunk in enumerate(chunks):
            emb = get_text_embedding(chunk)
            conn.execute("""
                INSERT INTO vector_knowledge_embeddings
                (user_id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, char_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                user_id, 
                title, 
                idx, 
                chunk, 
                json.dumps(emb), 
                category, 
                source_type, 
                len(chunk)
            ))
            saved_count += 1
        conn.commit()
        
    logger.info(f"Ingested '{title}' ({saved_count} chunks, category: {category}) into Vector Brain for user {user_id}")
    return {
        "status": "success",
        "message": f"Dokumen '{title}' berhasil diindeks ke dalam Vector Brain ({saved_count} chunks, kategori: {category})!",
        "doc_title": title,
        "total_chunks": saved_count,
        "category": category,
        "source_type": source_type,
        "total_chars": len(text_content)
    }


def semantic_search(
    user_id: int, 
    query: str, 
    top_k: int = 5, 
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Perform fast cosine similarity semantic search across all stored vector knowledge chunks.
    """
    init_vector_db()
    if not query.strip():
        return []
        
    query_emb = get_text_embedding(query)
    
    # Fetch candidate embeddings
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        if category and category.strip() and category.lower() != "all":
            rows = conn.execute("""
                SELECT id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, created_at
                FROM vector_knowledge_embeddings
                WHERE user_id = ? AND category = ?
            """, (user_id, category.strip())).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, created_at
                FROM vector_knowledge_embeddings
                WHERE user_id = ?
            """, (user_id,)).fetchall()
            
    if not rows:
        return []
        
    scored_results = []
    for r in rows:
        try:
            stored_emb = json.loads(r["embedding_json"])
            sim = cosine_similarity(query_emb, stored_emb)
            scored_results.append({
                "id": r["id"],
                "doc_title": r["doc_title"],
                "chunk_index": r["chunk_index"],
                "chunk_text": r["chunk_text"],
                "similarity_score": round(sim, 4),
                "category": r["category"],
                "source_type": r["source_type"],
                "created_at": r["created_at"]
            })
        except Exception as parse_err:
            logger.debug(f"Error parsing embedding for row {r['id']}: {parse_err}")
            
    # Sort descending by similarity
    scored_results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored_results[:top_k]


def list_ingested_documents(user_id: int) -> List[Dict[str, Any]]:
    """List summary of all documents currently ingested in Vector Brain."""
    init_vector_db()
    docs = []
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT doc_title, category, source_type, COUNT(*) as total_chunks, SUM(char_count) as total_chars, MAX(created_at) as last_indexed
            FROM vector_knowledge_embeddings
            WHERE user_id = ?
            GROUP BY doc_title, category, source_type
            ORDER BY last_indexed DESC
        """, (user_id,)).fetchall()
        for r in rows:
            docs.append({
                "doc_title": r["doc_title"],
                "category": r["category"],
                "source_type": r["source_type"],
                "total_chunks": r["total_chunks"],
                "total_chars": r["total_chars"],
                "last_indexed": r["last_indexed"]
            })
    return docs


def delete_document(user_id: int, doc_title: str) -> Dict[str, Any]:
    """Delete all chunks belonging to a document title."""
    init_vector_db()
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        cursor = conn.execute("DELETE FROM vector_knowledge_embeddings WHERE user_id = ? AND doc_title = ?", (user_id, doc_title))
        deleted_count = cursor.rowcount
        conn.commit()
        
    return {
        "status": "success",
        "message": f"Dokumen '{doc_title}' ({deleted_count} chunks) berhasil dihapus dari Vector Brain.",
        "deleted_chunks": deleted_count
    }
