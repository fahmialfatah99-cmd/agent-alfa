"""Phase 5 coverage: swarm step executor — planner, verifier, forced-JSON, scraping gate.

Hermetic: LLM/tool/DB dipalsukan; filesystem memakai tmp_path.
"""

from __future__ import annotations

import json

import pytest

from alfa.swarm import step_executor as se


@pytest.fixture(autouse=True)
def _clear_scrape_state():
    se._reset_scrape_state()
    yield
    se._reset_scrape_state()


# ── planner ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decompose_task_parses_and_filters(monkeypatch):
    monkeypatch.setattr(
        se,
        "generate_agent_response",
        lambda *a, **k: _async_result(
            json.dumps(
                [
                    {"name": "Alpha", "task": "tulis laporan", "depends_on": ["Beta"]},
                    {"name": "Beta", "task": "riset data", "depends_on": []},
                    {"name": "Asing", "task": "tidak boleh", "depends_on": []},
                    {"name": "Alpha", "task": "", "depends_on": []},
                    {"name": "Beta", "task": "lagi", "depends_on": "bukan-list"},
                ]
            )
        ),
    )
    participants = [{"name": "Alpha", "role": "Writer"}, {"name": "Beta", "role": "Intel"}]
    out = await se._decompose_task("topik", participants)
    assert out["Alpha"] == {"task": "tulis laporan", "depends_on": ["Beta"]}
    assert out["Beta"] == {"task": "lagi", "depends_on": []}


@pytest.mark.asyncio
async def test_decompose_task_invalid_output_returns_empty(monkeypatch):
    monkeypatch.setattr(se, "generate_agent_response", lambda *a, **k: _async_result("tidak ada json"))
    assert await se._decompose_task("topik", [{"name": "A"}]) == {}


@pytest.mark.asyncio
async def test_decompose_task_handles_exception(monkeypatch):
    async def boom(*a, **k):
        msg = "llm mati"
        raise ValueError(msg)

    monkeypatch.setattr(se, "generate_agent_response", boom)
    assert await se._decompose_task("topik", [{"name": "A"}]) == {}


async def _async_result(value):
    return value


# ── verifier ─────────────────────────────────────────────────────────────────


def test_verify_ground_truth_rejects_no_file_change(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "mechanical")
    monkeypatch.setattr(se, "_EXEC_FS_SNAPSHOT", {"a": 1})
    monkeypatch.setattr(se, "_hash_sandbox_projects", lambda: {"a": 1})
    passed, feedback = _run(
        se._verify_step_result(
            "buat website", {"status": "success", "tool_used": "x", "fs_changed": 0}
        )
    )
    assert passed is False
    assert "GROUND-TRUTH" in feedback


def test_verify_mechanical_accepts_file_change(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "mechanical")
    passed, feedback = _run(
        se._verify_step_result(
            "tulis file", {"status": "success", "fs_changed": 2, "changed_sample": ["a.py"]}
        )
    )
    assert passed is True
    assert feedback == ""


def test_verify_mechanical_accepts_success_with_tool(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "mechanical")
    passed, _ = _run(
        se._verify_step_result("analisa data", {"status": "success", "tool_used": "web_search"})
    )
    assert passed is True


def test_verify_mechanical_rejects_without_evidence(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "mechanical")
    passed, feedback = _run(se._verify_step_result("analisa", {"status": "error"}))
    assert passed is False
    assert "mechanical judge" in feedback


def test_verify_llm_pass(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "llm")
    monkeypatch.setattr(se, "generate_agent_response", lambda *a, **k: _async_result("PASS"))
    passed, feedback = _run(
        se._verify_step_result("analisa", {"status": "success", "execution_summary": "ok"})
    )
    assert passed is True
    assert feedback == ""


def test_verify_llm_fail(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "llm")
    monkeypatch.setattr(
        se, "generate_agent_response", lambda *a, **k: _async_result("FAIL: tidak ada bukti")
    )
    passed, feedback = _run(
        se._verify_step_result("analisa", {"status": "success", "execution_summary": "janji"})
    )
    assert passed is False
    assert "tidak ada bukti" in feedback


def test_verify_llm_exception_mechanical_fallback(monkeypatch):
    monkeypatch.setenv("ALFA_SWARM_JUDGE", "llm")

    async def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(se, "generate_agent_response", boom)
    passed, _ = _run(
        se._verify_step_result("tulis laporan", {"status": "success", "tool_used": "write"})
    )
    assert passed is True


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# ── single-shot fallback ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_shot_writes_content(monkeypatch, tmp_path):
    written = {}

    async def fake_llm(*a, **k):
        return "```html\n<!DOCTYPE html><html><body>Halo</body></html>\n```"

    monkeypatch.setattr(se, "generate_agent_response", fake_llm)
    monkeypatch.setattr(
        se.tools,
        "write_local_file",
        lambda **kwargs: written.update(kwargs) or {"status": "success"},
    )
    monkeypatch.setattr(se, "log_live", lambda *a, **k: None)

    out = await se._single_shot_edit_fallback(
        {"name": "A"}, "buat website", str(tmp_path)
    )
    assert "diperbarui" in out
    assert written["file_path"].endswith(".html")
    assert written["content"].startswith("<!DOCTYPE html>")


@pytest.mark.asyncio
async def test_single_shot_empty_content(monkeypatch, tmp_path):
    async def fake_llm(*a, **k):
        return "   "

    monkeypatch.setattr(se, "generate_agent_response", fake_llm)
    out = await se._single_shot_edit_fallback({"name": "A"}, "tulis laporan", str(tmp_path))
    assert "kosong" in out


@pytest.mark.asyncio
async def test_single_shot_uses_existing_newest_file(monkeypatch, tmp_path):
    existing = tmp_path / "lama.md"
    existing.write_text("# lama", encoding="utf-8")

    async def fake_llm(*a, **k):
        return "# laporan baru yang cukup panjang"

    monkeypatch.setattr(se, "generate_agent_response", fake_llm)
    monkeypatch.setattr(
        se.tools, "write_local_file", lambda **kwargs: {"status": "success"}
    )
    monkeypatch.setattr(se, "log_live", lambda *a, **k: None)
    out = await se._single_shot_edit_fallback({"name": "A"}, "tulis laporan", str(tmp_path))
    assert "lama.md" in out


@pytest.mark.asyncio
async def test_single_shot_write_error(monkeypatch, tmp_path):
    async def fake_llm(*a, **k):
        return "konten yang cukup panjang untuk ditulis"

    monkeypatch.setattr(se, "generate_agent_response", fake_llm)

    def boom(**kwargs):
        msg = "disk penuh"
        raise OSError(msg)

    monkeypatch.setattr(se.tools, "write_local_file", boom)
    out = await se._single_shot_edit_fallback({"name": "A"}, "tulis laporan", str(tmp_path))
    assert "gagal tulis" in out


# ── command policy ───────────────────────────────────────────────────────────


def test_command_policy_empty_and_allowed(monkeypatch):
    assert se._command_policy_denial("   ") == "perintah kosong"
    from alfa.security import command_policy

    monkeypatch.setattr(command_policy, "check_agent_command", lambda cmd, working_dir="": "")
    assert se._command_policy_denial("ls", "/tmp") == ""


def test_command_policy_denied_and_error(monkeypatch):
    from alfa.security import command_policy

    monkeypatch.setattr(
        command_policy, "check_agent_command", lambda cmd, working_dir="": "rm -rf dilarang"
    )
    assert se._command_policy_denial("rm -rf /") == "rm -rf dilarang"

    def boom(cmd, working_dir=""):
        msg = "policy rusak"
        raise TypeError(msg)

    monkeypatch.setattr(command_policy, "check_agent_command", boom)
    assert "gagal verifikasi" in se._command_policy_denial("ls")


# ── forced JSON execution ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forced_json_empty_and_invalid(monkeypatch):
    monkeypatch.setattr(se, "generate_agent_response", lambda *a, **k: _async_result(""))
    assert "tidak merespons" in await se._forced_json_execution({"name": "A"}, "tugas")

    monkeypatch.setattr(
        se, "generate_agent_response", lambda *a, **k: _async_result("bukan json")
    )
    assert "rencana tidak valid" in await se._forced_json_execution({"name": "A"}, "tugas")

    monkeypatch.setattr(
        se, "generate_agent_response", lambda *a, **k: _async_result('[{"tool":}]')
    )
    assert "JSON rusak" in await se._forced_json_execution({"name": "A"}, "tugas")


@pytest.mark.asyncio
async def test_forced_json_executes_allowed_and_denied(monkeypatch):
    actions = [
        {"tool": "write_local_file", "path": "/tmp/a.txt", "content": "x"},
        {"tool": "execute_bash_command", "command": "ls", "working_dir": "/tmp"},
        {"tool": "execute_bash_command", "command": "rm -rf /", "working_dir": "/tmp"},
        {"tool": "tidak_ada", "path": "/tmp/b"},
        "bukan-dict",
    ]
    monkeypatch.setattr(
        se,
        "generate_agent_response",
        lambda *a, **k: _async_result(json.dumps(actions)),
    )
    written = {}
    monkeypatch.setattr(
        se.tools,
        "write_local_file",
        lambda **kwargs: written.update(kwargs) or {"status": "success"},
    )
    monkeypatch.setattr(
        se.tools, "execute_bash_command", lambda **kwargs: {"status": "success"}
    )
    monkeypatch.setattr(
        se,
        "_command_policy_denial",
        lambda command, working_dir="": "dilarang" if "rm" in command else "",
    )
    monkeypatch.setattr(se, "log_live", lambda *a, **k: None)

    out = await se._forced_json_execution({"name": "A"}, "tugas")
    assert "write_local_file -> success" in out
    assert "execute_bash_command -> success" in out
    assert "DENIED (dilarang)" in out
    assert written["file_path"] == "/tmp/a.txt"


@pytest.mark.asyncio
async def test_forced_json_tool_exception(monkeypatch):
    monkeypatch.setattr(
        se,
        "generate_agent_response",
        lambda *a, **k: _async_result('[{"tool":"write_local_file","path":"/tmp/a","content":"x"}]'),
    )

    def boom(**kwargs):
        msg = "gagal tulis"
        raise OSError(msg)

    monkeypatch.setattr(se.tools, "write_local_file", boom)
    monkeypatch.setattr(se, "log_live", lambda *a, **k: None)
    out = await se._forced_json_execution({"name": "A"}, "tugas")
    assert "EXC gagal tulis" in out


# ── scrape gate ──────────────────────────────────────────────────────────────


def test_step_scrape_gate_non_research_and_signals():
    assert se._step_needs_deep_scrape("Writer", "Specialist", "tulis laporan", {}) == (False, "")

    ok, reason = se._step_needs_deep_scrape("Writer", "Specialist", "tulis laporan", {})
    assert ok is False and reason == ""

    ok, reason = se._step_needs_deep_scrape(
        "Research Prime", "Intel", "kumpulkan data supplier", {}
    )
    assert ok is True and reason == ""

    ok, reason = se._step_needs_deep_scrape(
        "Research Prime", "Intel", "tulis ringkasan", {}
    )
    assert ok is False and "tidak meminta" in reason


def test_step_scrape_gate_intent_dedupes():
    intent = {"is_scrape": True, "clean_query": "harga"}
    ok, _ = se._step_needs_deep_scrape("Research", "Intel", "tulis ringkasan", intent)
    assert ok is True
    ok, reason = se._step_needs_deep_scrape("Research", "Intel", "tulis ringkasan", intent)
    assert ok is False
    assert "sudah dilakukan" in reason


# ── execute step ─────────────────────────────────────────────────────────────


def _patch_common(monkeypatch, tmp_path, hashes):
    out_dir = tmp_path / "swarm"
    target = tmp_path / "target"
    out_dir.mkdir(exist_ok=True)
    target.mkdir(exist_ok=True)
    monkeypatch.setattr(se, "_get_swarm_output_dir", lambda: str(out_dir))
    monkeypatch.setattr(se, "_get_target_folder", lambda: str(target))
    monkeypatch.setattr(se, "_hash_sandbox_projects", lambda: hashes.pop(0))
    monkeypatch.setattr(se.database, "log_agent_activity_sync", lambda **kwargs: None)
    monkeypatch.setattr(se, "log_live", lambda *a, **k: None)
    from alfa.swarm import personas

    monkeypatch.setattr(personas, "get_adaptive_system_instruction", lambda *a, **k: "sys")
    return out_dir, target


@pytest.mark.asyncio
async def test_execute_general_agent_with_file_change(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, [{"a": 1}, {"a": 2}])
    monkeypatch.setattr(se, "_step_needs_deep_scrape", lambda *a, **k: (False, ""))
    monkeypatch.setattr(
        se, "generate_agent_response", lambda *a, **k: _async_result("hasil kerja")
    )
    result = await se.execute_swarm_task_step(
        {"name": "Writer", "role": "Specialist", "id": 1}, "tulis file", "topik", {}
    )
    assert result["status"] == "success"
    assert result["tool_used"] == "agentic_autonomous"
    assert result["fs_changed"] == 1
    assert result["changed_sample"] == ["a"]


@pytest.mark.asyncio
async def test_execute_general_agent_forces_json_when_no_change(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, [{"a": 1}, {"a": 1}, {"a": 1}, {"a": 1}])
    monkeypatch.setattr(se, "_step_needs_deep_scrape", lambda *a, **k: (False, ""))
    monkeypatch.setattr(
        se, "generate_agent_response", lambda *a, **k: _async_result("teks saja")
    )

    async def forced(agent, task):
        return "(forced-exec) hasil"

    async def single_shot(agent, task, folder):
        return "(single-shot) kosong"

    monkeypatch.setattr(se, "_forced_json_execution", forced)
    monkeypatch.setattr(se, "_single_shot_edit_fallback", single_shot)
    result = await se.execute_swarm_task_step(
        {"name": "Writer", "role": "Specialist", "id": 2}, "tulis file", "topik", {}
    )
    assert result["fs_changed"] == 0
    assert "TIDAK ada file berubah" in result["execution_summary"]


@pytest.mark.asyncio
async def test_execute_research_scraper_success(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, [{"a": 1}, {"a": 2}])
    monkeypatch.setattr(se, "_step_needs_deep_scrape", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        se.tools,
        "universal_deep_scraper",
        lambda **kwargs: {
            "total_scraped": 2,
            "items": [{"title": "Produk A", "price": 1000, "domain": "shopee"}],
        },
    )
    result = await se.execute_swarm_task_step(
        {"name": "Research", "role": "Intel", "id": 3},
        "kumpulkan data",
        "topik",
        {"clean_query": "harga"},
    )
    assert result["tool_used"] == "universal_deep_scraper"
    assert "Scraping Berhasil" in result["execution_summary"]
    assert result["deliverable_data"][0]["title"] == "Produk A"


@pytest.mark.asyncio
async def test_execute_research_zero_results_falls_back_to_web_search(monkeypatch, tmp_path):
    out_dir, _ = _patch_common(monkeypatch, tmp_path, [{"a": 1}, {"a": 1}])
    monkeypatch.setattr(se, "_step_needs_deep_scrape", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        se.tools,
        "universal_deep_scraper",
        lambda **kwargs: {"total_scraped": 0, "items": []},
    )
    monkeypatch.setattr(
        se.tools,
        "web_search",
        lambda query, max_results=8: {
            "results": [{"title": "Hasil", "url": "https://example.test"}]
        },
    )
    result = await se.execute_swarm_task_step(
        {"name": "Research", "role": "Intel", "id": 4},
        "kumpulkan data",
        "topik",
        {"clean_query": "harga"},
    )
    assert "fallback web_search" in result["execution_summary"]
    assert (out_dir / "LAPORAN-Riset.md").is_file()


@pytest.mark.asyncio
async def test_execute_research_exception_marks_error(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, [{"a": 1}, {"a": 1}])
    monkeypatch.setattr(se, "_step_needs_deep_scrape", lambda *a, **k: (True, ""))

    def boom(**kwargs):
        msg = "scraper mati"
        raise RuntimeError(msg)

    monkeypatch.setattr(se.tools, "universal_deep_scraper", boom)
    result = await se.execute_swarm_task_step(
        {"name": "Research", "role": "Intel", "id": 5},
        "kumpulkan data",
        "topik",
        {"clean_query": "harga"},
    )
    assert result["status"] == "error"
    assert "scraper mati" in result["execution_summary"]
