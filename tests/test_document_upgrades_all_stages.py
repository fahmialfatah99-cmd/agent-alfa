"""
Comprehensive verification test suite for Advanced Document Reading Upgrades (Tahap 1 - 4):
- Tahap 1: Layout-Aware Parsing (PDF, Word, Excel, CSV) & Hybrid Search (Dense + BM25) + Re-ranking.
- Tahap 2: Context Caching Engine (Gemini Server Caching & TTL lifecycle).
- Tahap 3: Agentic Corrective RAG (CRAG with Self-Reflection) & Tabular Data Analysis (Pandas).
- Tahap 4: Multi-Document GraphRAG Traversal, Entity Extraction & Mermaid Diagram Generation.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.memory import (
    agentic_rag,
    context_cache,
    doc_parser,
    graph_rag,
    table_analyzer,
    vector,
)
from alfa.tools import memory_tools


class TestStage1ParsingAndHybridSearch:
    """Tests for Tahap 1: Document Parsing, Contextual Chunking, Hybrid Search, and Re-ranking."""

    def test_doc_parser_contextual_chunking_preserves_breadcrumbs(self):
        text = (
            "# Laporan Finansial Alfa 2026\n"
            "Berikut adalah ringkasan performa finansial Q1.\n\n"
            "## Pendapatan dan Arus Kas\n"
            "Total pendapatan mencapai 500 juta rupiah dengan pertumbuhan 25% YoY.\n"
            "Semua target divisi penjualan tercapai sesuai KPI kuartal pertama.\n\n"
            "## Biaya Operasional\n"
            "Biaya server cloud sebesar 45 juta rupiah, pengeluaran gaji tim 150 juta rupiah."
        )

        chunks = doc_parser.chunk_document_contextual(
            text, doc_title="Laporan Finansial", chunk_size=150, overlap=30
        )
        assert len(chunks) >= 2
        for c in chunks:
            assert "[Dokumen: Laporan Finansial" in c
            assert "Bagian:" in c

    def test_csv_extraction_into_markdown_table(self, tmp_path):
        csv_file = tmp_path / "test_data.csv"
        csv_file.write_text("Produk,Kategori,Harga\nServer Alfa,Cloud,5000000\nBot Alfa,AI,1500000\n", encoding="utf-8")

        text, src_type = doc_parser.extract_document_content(str(csv_file))
        assert src_type == "csv"
        assert "Produk" in text and "Kategori" in text and "Harga" in text
        assert "Server Alfa" in text and "5000000" in text

    def test_hybrid_search_and_reranking_accuracy(self, tmp_path):
        test_db = str(tmp_path / "hybrid_test.db")
        vector.init_vector_db(test_db)

        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            # Ingest doc 1
            vector.ingest_document(
                user_id=1,
                title="Sistem Keamanan Alfa",
                content_or_path="Arsitektur otentikasi menggunakan JWT Token dengan enkripsi AES-256 dan firewall cloud.",
                category="security",
                db_path=test_db,
            )

            # Ingest doc 2
            vector.ingest_document(
                user_id=1,
                title="Resep Masakan Dapur",
                content_or_path="Bahan membuat kue cokelat lezat adalah tepung terigu, cokelat bubuk, dan susu vanila.",
                category="culinary",
                db_path=test_db,
            )

            # Search with hybrid search
            res = vector.hybrid_search(
                user_id=1,
                query="enkripsi AES-256 dan otentikasi JWT",
                top_k=2,
                db_path=test_db,
            )

            assert len(res) >= 1
            top = res[0]
            assert top["doc_title"] == "Sistem Keamanan Alfa"
            assert "hybrid_score" in top
            assert "bm25_score" in top
            assert "rerank_score" in top
            assert any("match" in r.lower() or "coverage" in r.lower() for r in top["match_reasons"])


class TestStage2ContextCaching:
    """Tests for Tahap 2: Context Caching Engine."""

    def test_context_cache_lifecycle_and_db_persistence(self, tmp_path):
        test_db = str(tmp_path / "cache_test.db")
        context_cache.init_context_cache_db(test_db)

        doc_content = "Ini adalah dokumen manual operasi raksasa sovereign AI bot alfa yang memiliki ratusan instruksi."

        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            # Create cache
            res = context_cache.create_or_get_document_cache(
                file_path_or_text=doc_content,
                doc_title="Manual Operasi Alfa",
                model="gemini-2.5-flash",
                ttl_minutes=30,
                db_path=test_db,
            )

            assert res["status"] == "success"
            cache_name = res["cache_name"]
            assert cache_name.startswith("local-cache-")
            assert res["doc_title"] == "Manual Operasi Alfa"

            # Reuse existing cache (should return cached=True)
            res_cached = context_cache.create_or_get_document_cache(
                file_path_or_text=doc_content,
                doc_title="Manual Operasi Alfa",
                model="gemini-2.5-flash",
                db_path=test_db,
            )
            assert res_cached["status"] == "success"
            assert res_cached["cached"] is True
            assert res_cached["cache_name"] == cache_name

            # List active caches
            caches = context_cache.list_active_context_caches(db_path=test_db)
            assert len(caches) == 1
            assert caches[0]["cache_name"] == cache_name

            # Query cache
            query_res = context_cache.query_cached_document(
                cache_name=cache_name,
                prompt="Apa isi dokumen?",
                model="gemini-2.5-flash",
            )
            assert query_res["status"] in ("success", "offline_fallback")
            assert query_res["cache_used"] == cache_name

            # Delete cache
            deleted = context_cache.delete_context_cache(cache_name, db_path=test_db)
            assert deleted is True
            assert len(context_cache.list_active_context_caches(db_path=test_db)) == 0


class TestStage3AgenticRAGAndTableAnalyzer:
    """Tests for Tahap 3: Agentic CRAG with Self-Reflection and Tabular Data Analyzer."""

    def test_agentic_rag_reflection_and_citations(self, tmp_path):
        test_db = str(tmp_path / "crag_test.db")
        vector.init_vector_db(test_db)

        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            vector.ingest_document(
                user_id=99,
                title="SOP Deployment",
                content_or_path=(
                    "Langkah 1: Jalankan pytest untuk memverifikasi unit test.\n"
                    "Langkah 2: Build Docker image dengan tag v2.\n"
                    "Langkah 3: Deploy container ke klaster Kubernetes production."
                ),
                category="devops",
                db_path=test_db,
            )

            # Query CRAG engine
            res = agentic_rag.agentic_document_query(
                user_id=99,
                query="Bagaimana SOP deployment container ke Kubernetes?",
                db_path=test_db,
            )

            assert res["status"] == "success"
            assert res["confidence_score"] > 0.0
            assert res["total_citations"] >= 1
            assert len(res["citations"]) >= 1
            assert "Kubernetes" in res["synthesized_context"]
            assert "[Kutipan #" in res["synthesized_context"]

    def test_table_analyzer_pandas_exact_calculations(self, tmp_path):
        # Create a sample sales CSV
        csv_file = tmp_path / "sales_report.csv"
        df = pd.DataFrame({
            "Cabang": ["Jakarta", "Surabaya", "Jakarta", "Bandung", "Surabaya"],
            "Kategori": ["Laptop", "Mouse", "Keyboard", "Laptop", "Laptop"],
            "Omzet": [25000000, 300000, 750000, 24000000, 26000000],
        })
        df.to_csv(csv_file, index=False)

        # 1. Structure inspection
        info = table_analyzer.inspect_table_structure(str(csv_file))
        assert info["status"] == "success"
        assert info["total_rows"] == 5
        assert info["total_columns"] == 3

        # 2. Summary stats
        summary = table_analyzer.analyze_tabular_data(str(csv_file), operation="summary")
        assert summary["status"] == "success"
        assert "mean" in summary["markdown_result"]

        # 3. Filtering
        filtered = table_analyzer.analyze_tabular_data(
            str(csv_file),
            operation="filter",
            filter_column="Cabang",
            filter_value="Jakarta",
        )
        assert filtered["status"] == "success"
        assert filtered["matched_rows"] == 2

        # 4. Aggregation (exact sum of Omzet by Cabang)
        agg = table_analyzer.analyze_tabular_data(
            str(csv_file),
            operation="aggregate",
            group_by="Cabang",
            agg_column="Omzet",
            agg_func="sum",
        )
        assert agg["status"] == "success"
        assert "Jakarta" in agg["markdown_result"]
        # Jakarta: 25000000 + 750000 = 25750000
        assert "25750000" in agg["markdown_result"]


class TestStage4MultiDocumentGraphRAG:
    """Tests for Tahap 4: Multi-Document GraphRAG Engine."""

    def test_graph_rag_multi_document_traversal(self, tmp_path):
        test_db = str(tmp_path / "graph_test.db")
        graph_rag.init_graph_db(test_db)

        # Doc 1: Alfa Architecture
        doc1_text = (
            "Agent Alfa adalah sistem kecerdasan otonom untuk otomasi server. "
            "Agent Alfa menggunakan framework FastAPI sebagai backend REST API."
        )
        res1 = graph_rag.extract_and_index_document_graph(
            user_id=7, doc_title="Arsitektur Alfa", text_content=doc1_text, db_path=test_db
        )
        assert res1["status"] == "success"
        assert res1["total_relations"] >= 1

        # Doc 2: Cloud Infrastructure
        doc2_text = (
            "FastAPI terintegrasi dengan Docker Swarm untuk orkestrasi container. "
            "Docker Swarm berjalan pada server Ubuntu LTS di data center."
        )
        res2 = graph_rag.extract_and_index_document_graph(
            user_id=7, doc_title="Infrastruktur Cloud", text_content=doc2_text, db_path=test_db
        )
        assert res2["status"] == "success"

        # Multi-Hop Search across Document 1 and Document 2
        search_res = graph_rag.graph_rag_search(
            user_id=7,
            query="FastAPI dan Agent Alfa",
            max_depth=2,
            db_path=test_db,
        )

        assert search_res["status"] == "success"
        assert search_res["total_relations_found"] >= 1
        assert "Arsitektur Alfa" in search_res["documents_involved"]
        assert len(search_res["graph_paths"]) >= 1
        assert "graph LR" in search_res["mermaid_diagram"]

        # Pathfinding: Connect Agent Alfa to Docker Swarm across documents
        path_res = graph_rag.graph_rag_find_connection(
            user_id=7,
            entity_a="Agent Alfa",
            entity_b="Docker Swarm",
            max_depth=3,
            db_path=test_db,
        )
        assert path_res["status"] == "success"
        assert path_res["path_found"] is True
        assert path_res["hops_count"] >= 1
        assert "Arsitektur Alfa" in path_res["documents_involved"]
        assert "Infrastruktur Cloud" in path_res["documents_involved"]
        assert "graph LR" in path_res["mermaid_diagram"]

        # Overview: Centrality & Hubs
        overview_res = graph_rag.graph_rag_get_overview(
            user_id=7,
            doc_title="",
            top_n=5,
            db_path=test_db,
        )
        assert overview_res["status"] == "success"
        assert overview_res["total_entities"] >= 2
        assert overview_res["total_relations"] >= 2
        assert len(overview_res["top_hubs"]) >= 1
        assert "graph LR" in overview_res["core_mermaid_diagram"]

        # Communities: Global cluster detection
        comm_res = graph_rag.graph_rag_get_communities(
            user_id=7,
            doc_title="",
            db_path=test_db,
        )
        assert comm_res["status"] == "success"
        assert comm_res["total_communities"] >= 1
        assert len(comm_res["communities"]) >= 1

        # Pre-turn context generation
        preturn_ctx = graph_rag.get_pre_turn_graph_context(
            user_id=7,
            prompt="Apakah Agent Alfa mendukung Docker Swarm?",
            db_path=test_db,
        )
        assert "KNOWLEDGE GRAPH CONTEXT" in preturn_ctx
        assert "Agent Alfa" in preturn_ctx or "FastAPI" in preturn_ctx



class TestMemoryToolsRegisteredWrapper:
    """Tests for tools exposed to the Agent Alfa workforce in memory_tools.py."""

    def test_memory_tools_wrappers_execute_cleanly(self, tmp_path):
        test_db = str(tmp_path / "tools_wrapper.db")

        # 1. Hybrid search wrapper
        res_h = memory_tools.hybrid_search_vector_brain(
            query="Test query", db_path=test_db
        )
        assert res_h["status"] == "success"

        # 2. Context cache wrapper
        res_c = memory_tools.manage_document_context_cache(
            action="list"
        )
        assert res_c["status"] == "success"

        # 3. CRAG query wrapper
        res_crag = memory_tools.agentic_document_query_crag(
            query="Pertanyaan sistem", db_path=test_db
        )
        assert res_crag["status"] == "success"

        # 4. GraphRAG wrapper
        res_g = memory_tools.graph_rag_query_multi_doc(
            query="Test Entitas", db_path=test_db
        )
        assert res_g["status"] == "success"

        # 5. GraphRAG Pathfinder wrapper
        res_p = memory_tools.graph_rag_find_path(
            entity_a="Entitas A", entity_b="Entitas B", db_path=test_db
        )
        assert res_p["status"] in ("success", "not_found")

        # 6. GraphRAG Overview wrapper
        res_o = memory_tools.graph_rag_get_overview(
            db_path=test_db
        )
        assert res_o["status"] == "success"

        # 7. GraphRAG Communities wrapper
        res_comm = memory_tools.graph_rag_get_communities(
            db_path=test_db
        )
        assert res_comm["status"] == "success"
