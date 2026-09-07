"""
Semantic Vector Memory & Hybrid RAG Engine for ALFA Sovereign AI Bot.
Provides vector embeddings, semantic search, sliding-window chunking, and document ingestion
for permanent long-term memory across chat turns, documents, and research notes.
"""

import collections
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("VectorMemory")
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_data.db")
DB_PATH = DEFAULT_DB_PATH


def _resolve_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database path, allowing callers and tests to supply an isolated DB path."""
    return custom_path if custom_path is not None else DB_PATH


def init_vector_db(db_path: Optional[str] = None):
    """Ensure vector knowledge table and indices exist in SQLite."""
    target_path = _resolve_db_path(db_path)
    conn = sqlite3.connect(target_path, timeout=10)
    try:
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
        logger.error(f"Failed to init vector db ({target_path}): {e}")
    finally:
        conn.close()


init_vector_db()


def _local_subword_embedding(text: str, dim: int = 768) -> List[float]:
    """
    High-quality deterministic subword & character n-gram hashing dense vectorizer
    with positional dampening and BM25-style term frequency saturation.
    Produces a normalized dense unit vector of dimension `dim` (default 768) for offline fallback.
    """
    if not text or not text.strip():
        return [0.0] * dim

    vec = np.zeros(dim, dtype=np.float32)
    clean_text = text.lower().strip()
    words = re.findall(r"\b\w+\b", clean_text)
    if not words:
        return [0.0] * dim

    total_words = len(words)
    word_counts = collections.Counter(words)

    # Track first seen position for positional weighting
    first_seen: Dict[str, int] = {}
    for idx, w in enumerate(words):
        if w not in first_seen:
            first_seen[w] = idx

    # BM25 term frequency saturation parameters
    k1 = 1.2
    b = 0.75
    avg_len = 30.0
    len_norm = (1.0 - b) + b * (total_words / avg_len)

    # 1. Word-level hashing with BM25 TF saturation and positional weighting
    for w, count in word_counts.items():
        tf_weight = (count * (k1 + 1.0)) / (count + k1 * len_norm)
        pos = first_seen[w]
        pos_weight = 1.0 + (0.5 / (1.0 + 0.08 * pos))
        word_len_weight = math.log(max(1, len(w)) + 1.0)
        combined_weight = tf_weight * pos_weight * word_len_weight

        h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
        bucket = h % dim
        sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
        vec[bucket] += sign * combined_weight

        # 2. Subword character n-grams with word boundary tags
        bounded_w = f"^{w}$"
        w_n = len(bounded_w)
        for n in (3, 4):
            if w_n >= n:
                for i in range(w_n - n + 1):
                    ngram = bounded_w[i : i + n]
                    h_ng = int(hashlib.sha256(ngram.encode("utf-8")).hexdigest(), 16)
                    ng_bucket = h_ng % dim
                    ng_sign = 1.0 if ((h_ng >> 8) % 2 == 0) else -1.0
                    vec[ng_bucket] += ng_sign * (0.35 * tf_weight)

    # L2 normalize to strictly unit length
    norm = np.linalg.norm(vec)
    if norm > 1e-6:
        vec = vec / norm
        return vec.tolist()
    return [0.0] * dim


def _attempt_local_library_embedding(text: str, dim: int = 768) -> Optional[List[float]]:
    """
    Attempt to use any installed local embedding library (fastembed, sentence_transformers, onnxruntime).
    Returns normalized unit float vector if successful, or None.
    """
    # 1. FastEmbed
    try:
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        embeddings = list(model.embed([text]))
        if embeddings and len(embeddings) > 0:
            vec = np.array(embeddings[0], dtype=np.float32)
            if len(vec) != dim and dim > 0:
                if len(vec) < dim:
                    vec = np.pad(vec, (0, dim - len(vec)), "constant")
                else:
                    vec = vec[:dim]
            norm = np.linalg.norm(vec)
            if norm > 1e-6:
                vec = vec / norm
            return vec.tolist()
    except Exception:
        pass

    # 2. Sentence Transformers
    try:
        from sentence_transformers import SentenceTransformer
        st_model = SentenceTransformer("all-MiniLM-L6-v2")
        emb = st_model.encode(text)
        vec = np.array(emb, dtype=np.float32)
        if len(vec) != dim and dim > 0:
            if len(vec) < dim:
                vec = np.pad(vec, (0, dim - len(vec)), "constant")
            else:
                vec = vec[:dim]
        norm = np.linalg.norm(vec)
        if norm > 1e-6:
            vec = vec / norm
        return vec.tolist()
    except Exception:
        pass

    return None


def get_text_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Generate vector embedding using:
    1. Local embedding model library if available (fastembed / sentence_transformers).
    2. Gemini API (gemini-embedding-001 / text-embedding-004) if API key is present.
    3. Deterministic local subword dense vectorizer as reliable zero-cost offline engine.
    """
    # 1. Attempt local embedding library
    local_vec = _attempt_local_library_embedding(text, dim=dim)
    if local_vec is not None:
        return local_vec

    # 2. Attempt Gemini API
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key and api_key != "your_gemini_api_key_here":
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            resp = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text
            )
            raw_vals = None
            if hasattr(resp, "embedding") and hasattr(resp.embedding, "values"):
                raw_vals = resp.embedding.values
            elif hasattr(resp, "embeddings") and len(resp.embeddings) > 0:
                raw_vals = resp.embeddings[0].values

            if raw_vals is not None:
                vec = np.array(raw_vals, dtype=np.float32)
                if len(vec) != dim and dim > 0:
                    if len(vec) < dim:
                        vec = np.pad(vec, (0, dim - len(vec)), "constant")
                    else:
                        vec = vec[:dim]
                norm = np.linalg.norm(vec)
                if norm > 1e-6:
                    vec = vec / norm
                return vec.tolist()
        except Exception as e:
            logger.debug(f"Gemini embedding API fallback to local vectorizer: {e}")

    # 3. Deterministic local subword fallback
    return _local_subword_embedding(text, dim=dim)


# API alias
get_embedding = get_text_embedding


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two float vectors with safe dimension alignment."""
    if not vec_a or not vec_b:
        return 0.0
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    if a.shape[0] != b.shape[0]:
        target_dim = max(a.shape[0], b.shape[0])
        if a.shape[0] < target_dim:
            a = np.pad(a, (0, target_dim - a.shape[0]), "constant")
        if b.shape[0] < target_dim:
            b = np.pad(b, (0, target_dim - b.shape[0]), "constant")
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
    category: str = "general",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Ingest a document (raw text or file path like .txt, .md, .pdf, .py, .csv, .json)
    into the vector database with chunking and embeddings.
    """
    target_db = _resolve_db_path(db_path)
    init_vector_db(target_db)
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
        
    # Reindex atomically in a single transaction: delete old chunks and insert
    # new ones together so a failure never leaves the document half-deleted.
    saved_count = 0
    conn = sqlite3.connect(target_db, timeout=10)
    try:
        conn.execute("DELETE FROM vector_knowledge_embeddings WHERE user_id = ? AND doc_title = ?", (user_id, title))
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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        
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
    category: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Perform fast cosine similarity semantic search across all stored vector knowledge chunks.
    """
    target_db = _resolve_db_path(db_path)
    init_vector_db(target_db)
    if not query.strip():
        return []
        
    query_emb = get_text_embedding(query)
    
    # Fetch candidate embeddings
    conn = sqlite3.connect(target_db, timeout=10)
    try:
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
    finally:
        conn.close()
            
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


def list_ingested_documents(user_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List summary of all documents currently ingested in Vector Brain."""
    target_db = _resolve_db_path(db_path)
    init_vector_db(target_db)
    docs = []
    conn = sqlite3.connect(target_db, timeout=10)
    try:
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
    finally:
        conn.close()
    return docs


def delete_document(user_id: int, doc_title: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Delete all chunks belonging to a document title."""
    target_db = _resolve_db_path(db_path)
    init_vector_db(target_db)
    conn = sqlite3.connect(target_db, timeout=10)
    try:
        cursor = conn.execute("DELETE FROM vector_knowledge_embeddings WHERE user_id = ? AND doc_title = ?", (user_id, doc_title))
        deleted_count = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
        
    return {
        "status": "success",
        "message": f"Dokumen '{doc_title}' ({deleted_count} chunks) berhasil dihapus dari Vector Brain.",
        "deleted_chunks": deleted_count
    }


def save_to_vector_memory(
    user_id: int,
    title: str,
    content: str,
    category: str = "general",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Save content or note into vector memory (alias for ingest_document)."""
    return ingest_document(
        user_id=user_id,
        title=title,
        content_or_path=content,
        category=category,
        db_path=db_path
    )


def search_vector_memory(
    user_id: int,
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search vector memory using semantic search (alias for semantic_search)."""
    return semantic_search(
        user_id=user_id,
        query=query,
        top_k=top_k,
        category=category,
        db_path=db_path
    )
