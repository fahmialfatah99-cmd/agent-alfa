"""ALFA Memory subpackage (Vector memory and Reflection)."""

from alfa.memory import reflection, vector
from alfa.memory.reflection import (
    reflect_recent_conversation,
    should_reflect,
)
from alfa.memory.vector import (
    chunk_text,
    cosine_similarity,
    delete_document,
    get_embedding,
    get_text_embedding,
    get_text_embedding_with_meta,
    ingest_document,
    init_vector_db,
    list_ingested_documents,
    save_to_vector_memory,
    search_vector_memory,
    semantic_search,
)

__all__ = [
    "vector",
    "reflection",
    "init_vector_db",
    "get_text_embedding",
    "get_embedding",
    "get_text_embedding_with_meta",
    "cosine_similarity",
    "chunk_text",
    "ingest_document",
    "semantic_search",
    "list_ingested_documents",
    "delete_document",
    "save_to_vector_memory",
    "search_vector_memory",
    "should_reflect",
    "reflect_recent_conversation",
]
