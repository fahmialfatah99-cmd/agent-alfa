"""
Unit tests for Local Vector Embeddings and Offline Semantic Search in vector_memory.
Follows strict TDD principles to verify deterministic offline embeddings,
semantic similarity ranking, chunking logic, and isolated database operations.
"""

import json
import os
import sqlite3
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vector_memory
from alfa.tools import memory_tools


class TestLocalVectorMemory:
    """Test suite for local vector memory and embedding operations."""

    def test_get_text_embedding_returns_normalized_vector(self):
        """Verify get_text_embedding and get_embedding return normalized unit float vectors."""
        text = "Artificial intelligence and autonomous agent system"
        vec1 = vector_memory.get_text_embedding(text)
        vec2 = vector_memory.get_embedding(text)

        assert isinstance(vec1, list)
        assert len(vec1) == 768
        assert all(isinstance(x, float) for x in vec1)

        # Norm should be 1.0 (unit vector)
        norm = np.linalg.norm(np.array(vec1, dtype=np.float32))
        assert pytest.approx(norm, abs=1e-4) == 1.0

        # get_embedding should return identical result
        assert vec1 == vec2

    def test_offline_behavior_deterministic_fallback(self):
        """Verify deterministic local embedding generation when offline or Gemini API fails."""
        text = "Sovereign AI offline second brain memory"

        # 1. Simulate no API key in environment
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            emb_no_key_1 = vector_memory.get_text_embedding(text)
            emb_no_key_2 = vector_memory.get_text_embedding(text)
            assert emb_no_key_1 == emb_no_key_2
            assert len(emb_no_key_1) == 768
            assert pytest.approx(np.linalg.norm(emb_no_key_1), abs=1e-4) == 1.0

        # 2. Simulate API key present but API call throws exception (network down, 429, etc.)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_test_key"}):
            with patch("google.genai.Client", side_effect=RuntimeError("Network unreachable")):
                emb_fail = vector_memory.get_text_embedding(text)
                assert emb_fail == emb_no_key_1  # Must fall back deterministically to local embedding

    def test_local_subword_embedding_features(self):
        """Verify _local_subword_embedding with positional and BM25-style frequency weighting."""
        text = "Python software development and coding automated algorithms in Python"
        vec_768 = vector_memory._local_subword_embedding(text, dim=768)
        vec_384 = vector_memory._local_subword_embedding(text, dim=384)

        assert len(vec_768) == 768
        assert len(vec_384) == 384
        assert pytest.approx(np.linalg.norm(vec_768), abs=1e-4) == 1.0
        assert pytest.approx(np.linalg.norm(vec_384), abs=1e-4) == 1.0

        # Empty string handling
        vec_empty = vector_memory._local_subword_embedding("", dim=768)
        assert len(vec_empty) == 768
        assert np.linalg.norm(vec_empty) == 0.0

    def test_semantic_similarity_ranking(self):
        """Verify semantically related texts have higher cosine similarity than unrelated texts."""
        # Ensure offline mode for deterministic comparison
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            emb_code_1 = vector_memory.get_text_embedding(
                "Python programming language for web backend development and software systems"
            )
            emb_code_2 = vector_memory.get_text_embedding(
                "Building software backend applications and web services with Python coding"
            )
            emb_unrelated = vector_memory.get_text_embedding(
                "Delicious recipe for strawberry shortcake with whipped cream and butter pastry"
            )

            sim_related = vector_memory.cosine_similarity(emb_code_1, emb_code_2)
            sim_unrelated = vector_memory.cosine_similarity(emb_code_1, emb_unrelated)

            assert sim_related > sim_unrelated
            assert sim_related > 0.35
            assert sim_unrelated < 0.25

    def test_cosine_similarity_dimension_alignment(self):
        """Verify cosine similarity handles mismatched dimensions safely."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0, 0.0, 0.0]
        sim = vector_memory.cosine_similarity(vec_a, vec_b)
        assert pytest.approx(sim, abs=1e-4) == 1.0

        assert vector_memory.cosine_similarity([], [1.0]) == 0.0
        assert vector_memory.cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_chunk_text_logic(self):
        """Verify chunk_text properly segments long text while preserving sentences/paragraphs."""
        # Empty text
        assert vector_memory.chunk_text("") == []

        # Short text
        short_text = "This is a single short paragraph."
        chunks = vector_memory.chunk_text(short_text, chunk_size=200, overlap=30)
        assert len(chunks) == 1
        assert chunks[0] == short_text

        # Multi-paragraph text
        paragraphs = [
            f"Paragraph {i}: " + ("This is detailed knowledge content about autonomous systems. " * 5)
            for i in range(10)
        ]
        full_text = "\n\n".join(paragraphs)
        chunks = vector_memory.chunk_text(full_text, chunk_size=300, overlap=50)

        assert len(chunks) > 1
        for c in chunks:
            assert len(c) > 0

    def test_isolated_database_crud_and_search(self, tmp_path):
        """Verify ingest_document, semantic_search, list_ingested_documents, and delete_document with custom DB path."""
        test_db = str(tmp_path / "test_vector.db")

        # Database initialization with isolated db path
        vector_memory.init_vector_db(db_path=test_db)
        assert os.path.isfile(test_db)

        # Ingest document into isolated database
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            res_ingest = vector_memory.ingest_document(
                user_id=42,
                title="Sovereign Architecture",
                content_or_path=(
                    "ALFA is a sovereign autonomous AI assistant designed for Telegram. "
                    "It has long-term memory and second brain capabilities for document storage and research. "
                    "All vector embeddings are indexed locally for resilience."
                ),
                category="architecture",
                db_path=test_db,
            )

            assert res_ingest["status"] == "success"
            assert res_ingest["doc_title"] == "Sovereign Architecture"
            assert res_ingest["total_chunks"] >= 1

            # Ingest second unrelated document
            vector_memory.ingest_document(
                user_id=42,
                title="Dessert Menu",
                content_or_path="Chocolate chip cookies recipe with brown sugar and vanilla extract.",
                category="culinary",
                db_path=test_db,
            )

            # Semantic search query
            results = vector_memory.semantic_search(
                user_id=42,
                query="autonomous AI assistant second brain memory",
                top_k=2,
                db_path=test_db,
            )

            assert len(results) >= 1
            top_hit = results[0]
            assert top_hit["doc_title"] == "Sovereign Architecture"
            assert "ALFA" in top_hit["chunk_text"]
            assert top_hit["similarity_score"] > 0.3

            # Search with category filter
            cat_results = vector_memory.semantic_search(
                user_id=42,
                query="sweet treats",
                category="culinary",
                db_path=test_db,
            )
            assert len(cat_results) == 1
            assert cat_results[0]["doc_title"] == "Dessert Menu"

            # List documents
            doc_list = vector_memory.list_ingested_documents(user_id=42, db_path=test_db)
            assert len(doc_list) == 2
            titles = [d["doc_title"] for d in doc_list]
            assert "Sovereign Architecture" in titles
            assert "Dessert Menu" in titles

            # Delete document
            del_res = vector_memory.delete_document(
                user_id=42, doc_title="Dessert Menu", db_path=test_db
            )
            assert del_res["status"] == "success"
            assert del_res["deleted_chunks"] >= 1

            remaining = vector_memory.list_ingested_documents(user_id=42, db_path=test_db)
            assert len(remaining) == 1
            assert remaining[0]["doc_title"] == "Sovereign Architecture"

    def test_memory_tools_seamless_interface(self, tmp_path):
        """Verify save_to_vector_memory and search_vector_memory in memory_tools operate seamlessly."""
        assert hasattr(memory_tools, "save_to_vector_memory")
        assert hasattr(memory_tools, "search_vector_memory")

        # Test tool invocations
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with patch("alfa.tools.memory_tools.current_user_id_var") as mock_uid:
                mock_uid.get.return_value = 999

                # Ingest via memory_tools
                with patch("vector_memory.ingest_document") as mock_ingest:
                    mock_ingest.return_value = {"status": "success", "total_chunks": 1}
                    res = memory_tools.save_to_vector_memory(
                        title="Test Note", content="Sample memory content", category="notes"
                    )
                    assert res["status"] == "success"
                    mock_ingest.assert_called_once()

                # Search via memory_tools
                with patch("vector_memory.semantic_search") as mock_search:
                    mock_search.return_value = [{"doc_title": "Test Note", "similarity_score": 0.88}]
                    search_res = memory_tools.search_vector_memory(query="Sample memory", top_k=3)
                    assert search_res["status"] == "success"
                    assert len(search_res["matches"]) == 1
                    mock_search.assert_called_once()

    def test_schema_migration_includes_model_and_dimension(self, tmp_path):
        """Verify vector database tables migrate safely and include model/dimension columns."""
        test_db = str(tmp_path / "legacy_vector.db")
        # Create legacy table without model or dimension
        conn = sqlite3.connect(test_db)
        conn.execute("""
            CREATE TABLE vector_knowledge_embeddings (
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
        conn.commit()
        conn.close()

        # Run init_vector_db migration
        vector_memory.init_vector_db(db_path=test_db)

        # Check columns
        conn = sqlite3.connect(test_db)
        cur = conn.execute("PRAGMA table_info(vector_knowledge_embeddings);")
        col_names = [col[1] for col in cur.fetchall()]
        conn.close()

        assert "model" in col_names
        assert "dimension" in col_names

    def test_dimension_and_model_compatibility_prevents_mismatch(self, tmp_path):
        """Verify semantic search filters out embeddings with mismatched dimensions or incompatible models."""
        test_db = str(tmp_path / "compat_vector.db")
        vector_memory.init_vector_db(db_path=test_db)

        # Ingest doc1 with 768-dim embedding (local subword)
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            vector_memory.ingest_document(
                user_id=10,
                title="Local Subword Doc",
                content_or_path="Quantum computing and superposition algorithms.",
                db_path=test_db,
            )

        # Ingest doc2 directly with 384-dim embedding simulating fastembed/MiniLM
        vec_384 = [0.1] * 384
        conn = sqlite3.connect(test_db)
        conn.execute("""
            INSERT INTO vector_knowledge_embeddings
            (user_id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, char_count, model, dimension, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            10, "FastEmbed Doc", 0, "Deep learning neural network optimization.",
            json.dumps(vec_384), "ai", "text", 50, "fastembed/bge-small-en-v1.5", 384
        ))
        conn.commit()
        conn.close()

        # Search with 768-dim query (local subword)
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            results_768 = vector_memory.semantic_search(
                user_id=10,
                query="Quantum computing principles",
                db_path=test_db
            )
            # Only the compatible 768-dim doc should be returned, NOT the 384-dim doc!
            assert len(results_768) == 1
            assert results_768[0]["doc_title"] == "Local Subword Doc"
            assert results_768[0]["dimension"] == 768

        # Search with 384-dim query (mocked local library)
        mock_meta = ([0.1] * 384, "fastembed/bge-small-en-v1.5", 384)
        with patch("vector_memory.get_text_embedding_with_meta", return_value=mock_meta):
            results_384 = vector_memory.semantic_search(
                user_id=10,
                query="Neural networks",
                db_path=test_db
            )
            # Only the compatible 384-dim doc should be returned, NOT the 768-dim doc!
            assert len(results_384) == 1
            assert results_384[0]["doc_title"] == "FastEmbed Doc"
            assert results_384[0]["dimension"] == 384
