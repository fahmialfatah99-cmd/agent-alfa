"""Temporal GraphRAG — memori pengetahuan berbasis graph.

Pecah dari modul monolitik `graph_rag.py` (1.298 baris). **Import path publik
tidak berubah**: `from alfa.memory.graph_rag import ...` tetap bekerja.
"""

from alfa.memory.graph_rag._db import (
    DEFAULT_DB_PATH,
    REPO_ROOT,
    init_graph_db,
    normalize_entity_name,
)
from alfa.memory.graph_rag._llm import (
    _get_gemini_client as _get_gemini_client,
)
from alfa.memory.graph_rag._llm import (
    extract_triples_with_llm,
)
from alfa.memory.graph_rag.communities import (
    detect_and_save_communities,
    graph_rag_get_communities,
)
from alfa.memory.graph_rag.consolidation import consolidate_memory_sleep_cycle
from alfa.memory.graph_rag.context import get_pre_turn_graph_context
from alfa.memory.graph_rag.export import export_knowledge_graph
from alfa.memory.graph_rag.extract import (
    extract_and_index_document_graph,
    extract_triples_from_text,
)
from alfa.memory.graph_rag.query import (
    graph_rag_find_connection,
    graph_rag_get_overview,
    graph_rag_search,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "REPO_ROOT",
    "consolidate_memory_sleep_cycle",
    "detect_and_save_communities",
    "export_knowledge_graph",
    "extract_and_index_document_graph",
    "extract_triples_from_text",
    "extract_triples_with_llm",
    "get_pre_turn_graph_context",
    "graph_rag_find_connection",
    "graph_rag_get_communities",
    "graph_rag_get_overview",
    "graph_rag_search",
    "init_graph_db",
    "normalize_entity_name",
]
