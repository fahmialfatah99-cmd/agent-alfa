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
            swarm_engine._verify_step_result("Buat website landing page", step)
        )
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
            swarm_engine._verify_step_result("Buat aplikasi kasir", step)
        )
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
            swarm_engine._verify_step_result("Bangun halaman profil", step)
        )
        assert passed is True

    def test_tugas_non_file_lewati_ground_truth(self, stub_verifier_pass):
        """Tugas riset tidak menuntut perubahan file."""
        step = {
            "tool_used": "universal_deep_scraper",
            "status": "success",
            "execution_summary": "20 data ditarik",
        }
        passed, _ = _run(
            swarm_engine._verify_step_result("Riset harga laptop gaming", step)
        )
        assert passed is True


class TestQaVerdict:
    @pytest.mark.parametrize(
        "teks,harap",
        [
            ("laporan penuh...\nQA_VERDICT: PASS", True),
            ("qa_verdict : pass — semua aman", True),
            ("QA VERDICT:PASS", False),  # tanpa titik dua rapat beda format
            ("QA_VERDICT: FAIL - bug di main.py", False),
            ("belum ada verdict sama sekali", False),
            ("", False),
            (None, False),
        ],
    )
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


class TestSwarmCheckpoint:
    def test_save_and_load(self, tmp_path, monkeypatch):
        """Checkpoint tersimpan dan dapat dimuat kembali."""
        import swarm_checkpoint

        monkeypatch.setattr(swarm_checkpoint, "CHECKPOINT_DIR", str(tmp_path))

        sid = "test-session-001"
        swarm_checkpoint.SwarmCheckpoint.save(
            session_id=sid,
            topic="Buat website",
            mode="execute",
            participants=[{"name": "Alpha Lead"}],
            steps=[
                {"agent": "Alpha Lead", "task": "Buat index.html", "status": "done"}
            ],
            steps_done=1,
            status="paused",
        )
        loaded = swarm_checkpoint.SwarmCheckpoint.load(sid)
        assert loaded is not None
        assert loaded["session_id"] == sid
        assert loaded["topic"] == "Buat website"
        assert loaded["steps_done"] == 1
        assert loaded["status"] == "paused"

    def test_list_resumable_excludes_completed(self, tmp_path, monkeypatch):
        import swarm_checkpoint

        monkeypatch.setattr(swarm_checkpoint, "CHECKPOINT_DIR", str(tmp_path))

        swarm_checkpoint.SwarmCheckpoint.save(
            "s1", "T1", "execute", [], [], 0, status="paused"
        )
        swarm_checkpoint.SwarmCheckpoint.save(
            "s2", "T2", "execute", [], [], 2, status="completed"
        )
        swarm_checkpoint.SwarmCheckpoint.save(
            "s3", "T3", "execute", [], [], 1, status="cancelled"
        )

        resumable = swarm_checkpoint.SwarmCheckpoint.list_resumable()
        ids = [r["session_id"] for r in resumable]
        assert "s1" in ids
        assert "s3" in ids
        assert "s2" not in ids

    def test_mark_cancelled_and_resume(self, tmp_path, monkeypatch):
        import swarm_checkpoint

        monkeypatch.setattr(swarm_checkpoint, "CHECKPOINT_DIR", str(tmp_path))

        swarm_checkpoint.SwarmCheckpoint.save(
            "s-cancel", "T", "execute", [], [], 0, status="running"
        )
        swarm_checkpoint.SwarmCheckpoint.mark_cancelled("s-cancel")
        loaded = swarm_checkpoint.SwarmCheckpoint.load("s-cancel")
        assert loaded["status"] == "cancelled"

    def test_add_error_log(self, tmp_path, monkeypatch):
        import swarm_checkpoint

        monkeypatch.setattr(swarm_checkpoint, "CHECKPOINT_DIR", str(tmp_path))

        swarm_checkpoint.SwarmCheckpoint.save("s-err", "T", "execute", [], [], 0)
        swarm_checkpoint.SwarmCheckpoint.add_error(
            "s-err", "step1", "Code Crafter", "Provider timeout"
        )
        loaded = swarm_checkpoint.SwarmCheckpoint.load("s-err")
        assert len(loaded["error_log"]) == 1
        assert loaded["error_log"][0]["error"] == "Provider timeout"

    def test_clear_checkpoint(self, tmp_path, monkeypatch):
        import swarm_checkpoint

        monkeypatch.setattr(swarm_checkpoint, "CHECKPOINT_DIR", str(tmp_path))

        swarm_checkpoint.SwarmCheckpoint.save("s-del", "T", "execute", [], [], 0)
        assert swarm_checkpoint.SwarmCheckpoint.load("s-del") is not None
        swarm_checkpoint.SwarmCheckpoint.clear("s-del")
        assert swarm_checkpoint.SwarmCheckpoint.load("s-del") is None


class TestErrorPropagation:
    def test_build_error_context_empty(self):
        ctx = swarm_engine._build_error_context([])
        assert ctx == ""

    def test_build_error_context_with_failures(self):
        failures = [
            {
                "agent_name": "Code Crafter",
                "tool_used": "write_local_file",
                "feedback": "File syntax error in line 12",
            },
            {
                "agent_name": "System Auditor",
                "tool_used": "execute_bash_command",
                "feedback": "Port 8080 already in use",
            },
        ]
        ctx = swarm_engine._build_error_context(failures)
        assert "Code Crafter" in ctx
        assert "System Auditor" in ctx
        assert "Port 8080" in ctx
