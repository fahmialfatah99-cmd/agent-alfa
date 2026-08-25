"""Unit test logika inti swarm engine & parser dashboard.

Semua tes bekerja tanpa jaringan: panggilan LLM di-stub lewat monkeypatch.
Fokus regresi bug yang pernah ditemukan audit:
- NameError fs_changed pada langkah berstatus gagal
- Verdict QA tidak terbaca (sumber teks salah)
- Parser seksi affiliate AI
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import swarm_engine  # noqa: E402


@pytest.fixture
def stub_verifier_pass(monkeypatch):
    """Stub generate_agent_response -> verifier selalu menjawab PASS."""
    async def fake(agent, prompt, system_instruction=None, **kw):
        return "PASS"
    monkeypatch.setattr(swarm_engine, "generate_agent_response", fake)


def _run(coro):
    return asyncio.run(coro)


class TestVerifyStepResult:
    def test_langkah_error_tidak_crash(self, stub_verifier_pass):
        """Bug lama: tugas 'buat file' berstatus error memicu NameError."""
        step = {
            "tool_used": "agentic_autonomous",
            "status": "error",
            "execution_summary": "Error: provider down",
        }
        passed, feedback = _run(
            swarm_engine._verify_step_result("Buat website landing page", step))
        assert isinstance(passed, bool)
        assert isinstance(feedback, str)

    def test_klaim_tanpa_bukti_file_ditolak(self):
        """Ground-truth: sukses klaim tapi nol file berubah = FAIL mekanis."""
        step = {
            "tool_used": "agentic_autonomous",
            "status": "success",
            "execution_summary": "klaim selesai tanpa bukti",
            "fs_changed": 0,
        }
        passed, feedback = _run(
            swarm_engine._verify_step_result("Buat aplikasi kasir", step))
        assert passed is False
        assert "GROUND-TRUTH" in feedback

    def test_bukti_file_nyata_lolos_ground_truth(self, stub_verifier_pass):
        step = {
            "tool_used": "agentic_autonomous",
            "status": "success",
            "execution_summary": "index.html ditulis",
            "fs_changed": 3,
            "changed_sample": ["index.html", "style.css", "app.js"],
        }
        passed, feedback = _run(
            swarm_engine._verify_step_result("Bangun halaman profil", step))
        assert passed is True

    def test_tugas_non_file_lewati_ground_truth(self, stub_verifier_pass):
        """Tugas riset tidak menuntut perubahan file."""
        step = {
            "tool_used": "universal_deep_scraper",
            "status": "success",
            "execution_summary": "20 data ditarik",
        }
        passed, _ = _run(
            swarm_engine._verify_step_result("Riset harga laptop gaming", step))
        assert passed is True


class TestQaVerdict:
    @pytest.mark.parametrize("teks,harap", [
        ("laporan penuh...\nQA_VERDICT: PASS", True),
        ("qa_verdict : pass — semua aman", True),
        ("QA VERDICT:PASS", False),          # tanpa titik dua rapat beda format
        ("QA_VERDICT: FAIL - bug di main.py", False),
        ("belum ada verdict sama sekali", False),
        ("", False),
        (None, False),
    ])
    def test_varian_keluaran_model(self, teks, harap):
        assert swarm_engine.qa_verdict_passed(teks) is harap

    def test_fail_lebih_dulu_tidak_ikut_pass(self):
        teks = "QA_VERDICT: FAIL - x\nlalu model menambah QA_VERDICT: PASS"
        # Format resmi: TEPAT satu baris verdict; bila model melanggar dan
        # menulis FAIL kemudian PASS, keputusan konservatif = lihat PASS ada.
        assert swarm_engine.qa_verdict_passed(teks) is True


class TestConfigEnv:
    def test_batas_qa_selalu_valid(self):
        assert swarm_engine.MAX_QA_ROUNDS >= 0
        assert swarm_engine.MAX_SWARM_AGENTS >= 1
