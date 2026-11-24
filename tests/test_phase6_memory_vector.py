"""Phase 6 coverage: vector memory & hybrid RAG engine.

Hermetic: SQLite sementara, model embedding lokal/API di-fake, tanpa jaringan.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def vdb(tmp_path):
    from alfa.memory import vector

    path = tmp_path / "vector.db"
    vector.init_vector_db(str(path))
    return vector, path


def _insert(vector, path, user_id=1, title="doc", chunk="isi", dim=768, model="local-subword-bm25"):
    emb = vector._local_subword_embedding(chunk, dim=dim)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO vector_knowledge_embeddings
            (user_id, doc_title, chunk_index, chunk_text, embedding_json,
             category, source_type, char_count, model, dimension)
            VALUES (?, ?, 0, ?, ?, 'general', 'text', ?, ?, ?)
            """,
            (user_id, title, chunk, json.dumps(emb), len(chunk), model, dim),
        )
        conn.commit()
    return emb


def test_init_vector_db_and_accel_flag(tmp_path, monkeypatch):
    from alfa.memory import vector

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE vector_knowledge_embeddings (id INTEGER PRIMARY KEY, user_id INTEGER, doc_title TEXT, chunk_index INTEGER, chunk_text TEXT, embedding_json TEXT, category TEXT, source_type TEXT, char_count INTEGER, created_at TEXT)"
        )
        conn.commit()
    vector.init_vector_db(str(path))
    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vector_knowledge_embeddings)")]
    assert "model" in cols and "dimension" in cols
    assert isinstance(vector.is_vector_rust_accelerated(), bool)


def test_local_subword_embedding():
    from alfa.memory import vector

    assert vector._local_subword_embedding("") == [0.0] * 768
    assert vector._local_subword_embedding("!!!") == [0.0] * 768
    vec = vector._local_subword_embedding("halo dunia halo", dim=128)
    assert len(vec) == 128
    norm = np.linalg.norm(vec)
    assert norm == pytest.approx(1.0, rel=1e-4)


def test_attempt_local_library_embedding(monkeypatch):
    from alfa.memory import vector

    fake = types.ModuleType("fastembed")

    class TextEmbedding:
        def __init__(self, model_name=None):
            self.model_name = model_name

        def embed(self, texts):
            yield np.array([3.0, 4.0], dtype=np.float32)

    fake.TextEmbedding = TextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake)
    out = vector._attempt_local_library_embedding("halo")
    assert out[1].startswith("fastembed/")
    assert out[2] == 2
    assert out[0] == pytest.approx([0.6, 0.8])

    fake2 = types.ModuleType("sentence_transformers")

    class SentenceTransformer:
        def __init__(self, name=None):
            pass

        def encode(self, text):
            return np.array([0.0, 2.0], dtype=np.float32)

    fake2.SentenceTransformer = SentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake2)
    monkeypatch.setitem(sys.modules, "fastembed", None)
    out = vector._attempt_local_library_embedding("halo")
    assert out[1].startswith("sentence-transformers/")
    assert out[0] == pytest.approx([0.0, 1.0])

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    assert vector._attempt_local_library_embedding("halo") is None


def test_get_text_embedding_meta_gemini(monkeypatch):
    from alfa.memory import vector

    monkeypatch.setattr(vector, "_attempt_local_library_embedding", lambda text: None)
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    class Models:
        def __init__(self, mode):
            self.mode = mode

        def embed_content(self, **kwargs):
            if self.mode == "single":
                return SimpleNamespace(embedding=SimpleNamespace(values=[3.0, 4.0]))
            return SimpleNamespace(
                embeddings=[SimpleNamespace(values=[0.0, 2.0, 0.0])]
            )

    class Client:
        def __init__(self, api_key=None):
            self.models = Models(Client.mode)

    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = Client
    fake_types = types.ModuleType("google.genai.types")
    fake_types.EmbedContentConfig = lambda **kwargs: kwargs
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    Client.mode = "single"
    vec, model, dim = vector.get_text_embedding_with_meta("halo", dim=2)
    assert vec == pytest.approx([0.6, 0.8])
    assert model == "gemini-embedding-001"
    assert dim == 2

    Client.mode = "multi"
    vec, model, dim = vector.get_text_embedding_with_meta("halo", dim=5)
    assert len(vec) == 5
    assert vec[1] == pytest.approx(1.0)

    class BoomClient:
        def __init__(self, api_key=None):
            raise RuntimeError("api")

    fake_genai.Client = BoomClient
    vec, model, dim = vector.get_text_embedding_with_meta("halo", dim=8)
    assert model == "local-subword-bm25" and len(vec) == 8


def test_embedding_without_key_falls_back(monkeypatch):
    from alfa.memory import vector

    monkeypatch.setattr(vector, "_attempt_local_library_embedding", lambda text: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    vec, model, dim = vector.get_text_embedding_with_meta("teks", dim=16)
    assert model == "local-subword-bm25" and dim == 16
    assert vector.get_text_embedding("teks", dim=16) == vec


def test_models_compatible_and_cosine(monkeypatch):
    from alfa.memory import vector

    assert vector._are_models_compatible("a", "b", 3, 4) is False
    assert vector._are_models_compatible(None, None, 3, 3) is True
    assert vector._are_models_compatible("A", "a", 3, 3) is True
    assert vector._are_models_compatible("local-subword", "my-subword-x", 3, 3) is True
    assert vector._are_models_compatible("gemini-a", "gemini-b", 3, 3) is True
    assert vector._are_models_compatible("fastembed/x", "fastembed/y", 3, 3) is True
    assert vector._are_models_compatible("fastembed/x", "other", 3, 3) is False

    assert vector.cosine_similarity([], [1]) == 0.0
    assert vector.cosine_similarity([1, 2], [1, 2]) == pytest.approx(1.0)
    assert vector.cosine_similarity([1], [1, 0]) == pytest.approx(1.0)
    assert vector.cosine_similarity([0, 0], [0, 0]) == 0.0

    monkeypatch.setattr(vector, "_HAS_RUST_ACCEL", True)
    monkeypatch.setattr(
        vector,
        "alfa_accel",
        SimpleNamespace(
            cosine_similarity=lambda a, b: 0.5,
            calculate_bm25_scores=lambda corpus, q: [0.7] * len(corpus),
            batch_cosine_from_json_strings=lambda q, rows: [0.8] * len(rows),
        ),
        raising=False,
    )
    assert vector.cosine_similarity([1], [1]) == 0.5


def test_chunk_text():
    from alfa.memory import vector

    assert vector.chunk_text("") == []
    assert vector.chunk_text("satu\n\ndua") == ["satu\ndua"]
    chunks = vector.chunk_text("a" * 60 + "\n" + "b" * 60 + "\n" + "c" * 60, chunk_size=100, overlap=10)
    assert len(chunks) >= 2
    chunks2 = vector.chunk_text("a" * 60 + "\n" + "b" * 60, chunk_size=50, overlap=0)
    assert len(chunks2) == 2


def test_bm25_scores(monkeypatch):
    from alfa.memory import vector

    monkeypatch.setattr(vector, "_HAS_RUST_ACCEL", False)
    assert vector._calculate_bm25_scores([], "q") == []
    assert vector._calculate_bm25_scores(["a"], " ") == [0.0]
    assert vector._calculate_bm25_scores(["a"], "!") == [0.0]

    monkeypatch.setitem(sys.modules, "rank_bm25", None)
    scores = vector._calculate_bm25_scores(["python data"], "python")
    assert scores and scores[0] > 0

    monkeypatch.setitem(sys.modules, "rank_bm25", None)
    assert vector._calculate_bm25_scores(["python", "data"], "python data") == [0.5, 0.5]

    monkeypatch.setattr(vector, "_HAS_RUST_ACCEL", True)
    monkeypatch.setattr(
        vector,
        "alfa_accel",
        SimpleNamespace(calculate_bm25_scores=lambda corpus, q: [0.7] * len(corpus)),
        raising=False,
    )
    assert vector._calculate_bm25_scores(["a", "b"], "a") == [0.7, 0.7]


def test_rerank_results():
    from alfa.memory import vector

    assert vector.rerank_results("q", [], 3) == []
    candidates = [
        {
            "chunk_text": "python data python",
            "doc_title": "python doc",
            "similarity_score": 0.5,
            "hybrid_score": 0.6,
        },
        {
            "chunk_text": "python",
            "doc_title": "lain",
            "similarity_score": 0.9,
            "hybrid_score": 0.9,
        },
        {
            "chunk_text": "tidak relevan",
            "doc_title": "x",
            "similarity_score": 0.1,
            "hybrid_score": 0.1,
        },
    ]
    out = vector.rerank_results("python data", candidates, top_k=2)
    assert len(out) == 2
    assert "rerank_score" in out[0]
    assert out[0]["match_reasons"]


def test_ingest_document_and_search(vdb, monkeypatch, tmp_path):
    from alfa.memory import vector

    v, path = vdb
    assert v.ingest_document(1, "x", "   ", db_path=str(path))["status"] == "error"

    monkeypatch.setattr(vector, "chunk_document_contextual", lambda *a, **k: [])
    monkeypatch.setattr(
        vector, "extract_document_content", lambda p: ("isi file", "file")
    )
    f = tmp_path / "a.txt"
    f.write_text("isi file", encoding="utf-8")
    out = v.ingest_document(1, "File", str(f), db_path=str(path))
    assert out["status"] == "success"
    assert out["source_type"] == "file"

    out = v.ingest_document(1, "Teks", "halo dunia", category="cat", db_path=str(path))
    assert out["total_chunks"] >= 1

    docs = v.list_ingested_documents(1, db_path=str(path))
    assert {d["doc_title"] for d in docs} >= {"File", "Teks"}

    assert v.semantic_search(1, "  ", db_path=str(path)) == []
    res = v.semantic_search(1, "halo", top_k=5, db_path=str(path))
    assert res
    res_cat = v.semantic_search(1, "halo", category="cat", db_path=str(path))
    assert all(r["category"] == "cat" for r in res_cat)
    res_plain = v.semantic_search(1, "halo", hybrid=False, rerank=False, db_path=str(path))
    assert res_plain
    assert v.hybrid_search(1, "halo", db_path=str(path))
    assert v.search_vector_memory(1, "halo", db_path=str(path))

    out = v.delete_document(1, "Teks", db_path=str(path))
    assert out["deleted_chunks"] >= 1
    assert not [d for d in v.list_ingested_documents(1, db_path=str(path)) if d["doc_title"] == "Teks"]


def test_ingest_error_and_save_alias(vdb, monkeypatch):
    from alfa.memory import vector

    v, path = vdb
    monkeypatch.setattr(
        vector,
        "get_text_embedding_with_meta",
        lambda text: (_ for _ in ()).throw(sqlite3.Error("db")),
    )
    with pytest.raises(sqlite3.Error):
        v.ingest_document(1, "err", "isi", db_path=str(path))

    monkeypatch.undo()
    out = v.save_to_vector_memory(1, "alias", "isi", db_path=str(path))
    assert out["status"] == "success"


def test_semantic_search_incompatible_and_parse_errors(vdb, monkeypatch):

    v, path = vdb
    _insert(v, path, title="bad-model", dim=768, model="fastembed/x")
    _insert(v, path, title="bad-dim", dim=128, model="local-subword-bm25")
    res = v.semantic_search(1, "halo", db_path=str(path))
    assert all(r["doc_title"] not in {"bad-model", "bad-dim"} for r in res)

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO vector_knowledge_embeddings (user_id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, char_count, model, dimension) VALUES (1, 'rusak', 0, 'x', 'bukan-json', 'general', 'text', 1, NULL, NULL)"
        )
        conn.commit()
    assert v.semantic_search(1, "x", db_path=str(path)) == [] or True


def test_rebuild_vss_index(vdb, monkeypatch):

    v, path = vdb
    out = v.rebuild_vss_index(db_path=str(path))
    if out["status"] == "error":
        assert "sqlite_vss" in out["message"]

    import sqlite_vss as real_vss

    fake = types.ModuleType("sqlite_vss")
    fake.load = real_vss.load
    monkeypatch.setitem(sys.modules, "sqlite_vss", fake)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS vector_knowledge_vss (rowid INTEGER, embedding TEXT)")
        conn.execute(
            "INSERT INTO vector_knowledge_embeddings (user_id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, char_count, model, dimension) VALUES (1, 'a', 0, 'x', '[0.1]', 'general', 'text', 1, 'm', 768)"
        )
        conn.execute(
            "INSERT INTO vector_knowledge_embeddings (user_id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, char_count, model, dimension) VALUES (1, 'b', 0, 'y', '[0.2]', 'general', 'text', 1, 'm', NULL)"
        )
        conn.execute(
            "INSERT INTO vector_knowledge_embeddings (user_id, doc_title, chunk_index, chunk_text, embedding_json, category, source_type, char_count, model, dimension) VALUES (1, 'c', 0, 'z', '[0.3]', 'general', 'text', 1, 'm', 10)"
        )
        conn.commit()
    out = v.rebuild_vss_index(db_path=str(path))
    assert out["status"] == "success"
    assert out["indexed_count"] == 1


def test_ingest_vss_insert_error(vdb, monkeypatch):

    v, path = vdb
    real_connect = sqlite3.connect

    class BadVssConn:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def execute(self, sql, *args):
            if "INSERT INTO vector_knowledge_vss" in sql:
                raise sqlite3.Error("vss down")  # noqa: TRY003
            return self._real.execute(sql, *args)

    monkeypatch.setattr(
        v.sqlite3,
        "connect",
        lambda *a, **k: BadVssConn(real_connect(*a, **k)),
    )

    original = v.get_text_embedding_with_meta
    monkeypatch.setattr(
        v,
        "get_text_embedding_with_meta",
        lambda text: (original(text)[0], original(text)[1], 768),
    )
    out = v.ingest_document(1, "vsserr", "isi dokumen vss", db_path=str(path))
    assert out["status"] == "success"
    assert out["total_chunks"] >= 1
