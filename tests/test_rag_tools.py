"""Perilaku tool RAG/vector — layer yang tadinya tak terlihat model.

8 tool ini terdaftar lewat dekorator `@register_tool`, tetapi daftar manual
`AVAILABLE_TOOLS` menimpanya — sehingga tidak pernah muncul di skema tools
yang dilihat LLM. Sekarang registry jadi sumber kebenaran tunggal; file ini
menguji perilakunya supaya tidak hanya "terdaftar", tapi benar-benar bekerja.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def vec_db(tmp_path):
    return str(tmp_path / "vector.db")


# ── Vector memory ────────────────────────────────────────────────────────────


class TestVectorMemory:
    def test_save_dan_search(self, vec_db):
        from alfa.tools import save_to_vector_memory, search_vector_memory

        res = save_to_vector_memory(
            "Judul Uji", "ALFA adalah ekosistem AI otonom dengan multi-agent swarm.", "umum", vec_db
        )
        assert res["status"] == "success", res
        assert res["total_chunks"] >= 1

        found = search_vector_memory("multi-agent swarm", 3, db_path=vec_db)
        assert found["status"] == "success", found
        assert found["total_matches"] >= 1
        assert "multi-agent" in found["matches"][0]["chunk_text"]

    def test_search_dengan_kategori_tidak_cocok(self, vec_db):
        from alfa.tools import save_to_vector_memory, search_vector_memory

        save_to_vector_memory("Doc A", "konten unikxyz", "kategori-a", vec_db)
        res = search_vector_memory("konten unikxyz", 5, "kategori-b", vec_db)
        assert res["status"] == "success"
        assert res["total_matches"] == 0

    def test_search_db_kosong_tidak_crash(self, vec_db):
        from alfa.tools import search_vector_memory

        res = search_vector_memory("apa saja", 3, db_path=vec_db)
        assert res["status"] == "success"
        assert res["total_matches"] == 0

    def test_hybrid_search(self, vec_db):
        from alfa.tools import hybrid_search_vector_brain, save_to_vector_memory

        save_to_vector_memory("Doc Hybrid", "ALFA memakai memori vektor hybrid search", "umum", vec_db)
        res = hybrid_search_vector_brain("vektor", 3, db_path=vec_db)
        assert res["status"] == "success", res
        assert res["total_matches"] >= 1


# ── Knowledge graph ──────────────────────────────────────────────────────────


class TestGraphRag:
    def test_index_dan_query(self, vec_db):
        from alfa.tools import graph_rag_query_multi_doc, index_document_to_graph

        res = index_document_to_graph(
            "Dok Uji", "ALFA memakai memori vektor dan knowledge graph.", vec_db
        )
        assert res["status"] == "success", res
        assert res["total_entities"] >= 1
        assert res["total_relations"] >= 1

        q = graph_rag_query_multi_doc("memori", 2, 3, db_path=vec_db)
        assert q["status"] == "success", q
        assert q["total_relations_found"] >= 1
        assert "Dok Uji" in q["documents_involved"]

    def test_index_dengan_path_file(self, tmp_path, vec_db):
        from alfa.tools import index_document_to_graph

        doc = tmp_path / "catatan.txt"
        doc.write_text("Catatan tentang arsitektur ALFA.", encoding="utf-8")
        res = index_document_to_graph("Dok Path", str(doc), vec_db)
        assert res["status"] == "success", res
        assert res["total_entities"] >= 1


# ── Analisis data tabular ────────────────────────────────────────────────────


class TestTabularAnalyzer:
    def test_summary_tidak_bisa_dibaca(self, tmp_path):
        from alfa.tools import analyze_document_tabular_data

        missing = tmp_path / "tidak-ada.csv"
        res = analyze_document_tabular_data(str(missing), "summary")
        assert res["status"] == "error"

    def test_summary_csv_sederhana(self, tmp_path):
        pytest.importorskip("pandas")
        from alfa.tools import analyze_document_tabular_data

        csv = tmp_path / "data.csv"
        csv.write_text("nama,nilai\nA,10\nB,20\nC,30\n", encoding="utf-8")
        res = analyze_document_tabular_data(str(csv), "summary")
        assert res["status"] == "success", res
        assert res.get("total_rows") == 3


# ── Context cache ────────────────────────────────────────────────────────────


class TestContextCache:
    def test_create_tanpa_konten_ditolak(self):
        from alfa.tools import manage_document_context_cache

        res = manage_document_context_cache("create", "", "", 30)
        assert res["status"] == "error"
        assert "kosong" in (res.get("message") or "").lower()

    def test_action_tidak_dikenal_ditolak(self):
        from alfa.tools import manage_document_context_cache

        res = manage_document_context_cache("aksi-ngawur", "", "", 30)
        assert res["status"] == "error"


# ── CRAG agentic query ───────────────────────────────────────────────────────


class TestCragQuery:
    def test_query_tanpa_dokumen_tidak_crash(self, vec_db):
        from alfa.tools import agentic_document_query_crag

        res = agentic_document_query_crag("apa itu ALFA?", db_path=vec_db)
        assert isinstance(res, dict)
        assert "status" in res


# ── Registrasi sebagai tool yang terlihat model ──────────────────────────────


class TestRagToolsTerdaftar:
    RAG_TOOLS = (
        "agentic_document_query_crag",
        "analyze_document_tabular_data",
        "graph_rag_query_multi_doc",
        "hybrid_search_vector_brain",
        "index_document_to_graph",
        "manage_document_context_cache",
        "save_to_vector_memory",
        "search_vector_memory",
    )

    def test_semua_terlihat_oleh_model(self):
        from alfa.core.brain.tool_schema import build_openai_tools

        names = {t["function"]["name"] for t in build_openai_tools()}
        for tool in self.RAG_TOOLS:
            assert tool in names, tool

    def test_semua_ada_di_risk_tier(self):
        from alfa.core.perm.constants import TOOL_CLASSIFICATION

        for tool in self.RAG_TOOLS:
            assert tool in TOOL_CLASSIFICATION, tool

    def test_tidak_ada_yang_gada_berbahaya(self):
        """Tool memory tidak boleh diklasifikasi sebagai tool berbahaya."""
        from alfa.core.perm.constants import TOOL_CLASSIFICATION, RiskTier

        for tool in self.RAG_TOOLS:
            tier = TOOL_CLASSIFICATION[tool][0]
            assert tier in (RiskTier.LOW, RiskTier.MEDIUM), (tool, tier)
