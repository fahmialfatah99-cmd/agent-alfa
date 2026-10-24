"""Unit test hermetik fase-2: orchestrator meeting, QA loop, deliberasi/voting.

Fokus blok yang belum tercover di ``alfa/swarm/engine.py``:
- _conduct_multi_agent_meeting_impl mode ``execute``: dekomposisi tugas,
  eksekusi parallel, QA loop Sentinel (PASS / FAIL→fix→PASS / habis putaran,
  budget, cancel di tengah perbaikan), tanpa agen QA (skip) + fallback nama.
- Auto-create folder proyek & jalur target folder (env + sanitize).
- Mode ``plan``: deliberasi terstruktur (parse JSON), pemungutan suara
  mekanis (winner + dissent), konsensus + ACTION PLAN, fallback teks polos.
- Jalur awal: tanpa workforce (error), cancel sebelum launch.

Semua eksternal di-patch: DB agen, checkpoint, eksekutor langkah, LLM,
harvest/sanitize berkas, registry workspace — tanpa network, tanpa DB
produksi (lapisan proteksi conftest).
"""

import os
from unittest.mock import MagicMock

import pytest

import alfa.swarm.engine as engine
import alfa.swarm.workspace_hygiene as wsh


@pytest.fixture
def _engine_clean(monkeypatch):
    """Reset state global engine + lingkungan impl hermetik."""
    monkeypatch.setattr(engine, "_MISSION_START", None, raising=False)
    monkeypatch.setattr(engine, "_BUDGET_EXCEEDED", "", raising=False)
    monkeypatch.setattr(engine, "_PROVIDER_DEAD", "", raising=False)
    monkeypatch.setattr(engine, "_CHECKPOINT_AVAILABLE", False, raising=False)
    monkeypatch.setattr(engine, "_TARGET_FOLDER", "", raising=False)
    monkeypatch.setattr(engine, "MAX_QA_ROUNDS", 2, raising=False)
    # Dict snapshot engine dimutasi in-place oleh impl — isolasi agar kamus
    # asli modul tidak berubah lintas tes.
    monkeypatch.setattr(engine, "_SANDBOX_SNAPSHOT", {}, raising=False)
    monkeypatch.setattr(engine, "_EXEC_FS_SNAPSHOT", {}, raising=False)
    monkeypatch.setattr(wsh, "_TARGET_FOLDER", "", raising=False)
    monkeypatch.setattr(wsh, "_SANDBOX_SNAPSHOT", {}, raising=False)
    monkeypatch.setattr(wsh, "_EXEC_FS_SNAPSHOT", {}, raising=False)
    monkeypatch.setattr(wsh, "register_session", MagicMock(), raising=False)
    monkeypatch.setattr(wsh, "unregister_session", MagicMock(), raising=False)
    monkeypatch.setattr(wsh, "set_current_session", MagicMock(), raising=False)
    monkeypatch.setattr(wsh, "smart_slug", lambda t: "proyek-x", raising=False)
    monkeypatch.delenv("ALFA_TARGET_FOLDER", raising=False)

    monkeypatch.setattr(engine, "log_live", MagicMock())
    monkeypatch.setattr(engine, "detect_task_intent", lambda t: {"intent": "uji"})
    monkeypatch.setattr(engine, "_sandbox_project_dirs", lambda: {})
    monkeypatch.setattr(engine, "_hash_sandbox_projects", lambda: {})
    monkeypatch.setattr(engine, "_harvest_new_sandbox_projects", lambda t: {})
    monkeypatch.setattr(engine, "sanitize_project_directory", MagicMock())
    monkeypatch.setattr(engine, "_SwarmCheckpoint", MagicMock())
    monkeypatch.setattr(engine, "_clear_cancel_flag", MagicMock())
    monkeypatch.setattr(engine, "_cancel_requested", lambda *a, **k: False)
    return engine


def _agents(*rows):
    """Agen minimal lengkap (kunci persona dipakai prompt mode plan)."""
    return [
        {
            "name": n,
            "role": r,
            "is_enabled": 1,
            "persona": "persona uji",
            "avatar_emoji": "🤖",
            "color_theme": "cyan",
        }
        for n, r in rows
    ]


def _step(agent, **kw):
    """Langkah mirrored shape seperti hasil execute_swarm_task_step nyata."""
    st = {
        "agent_name": agent["name"],
        "role": agent.get("role", ""),
        "tool_used": "tool_x",
        "duration_ms": 5,
        "execution_summary": "langkah utama selesai",
        "deliverable_file": None,
        "verification": "PASS",
        "phase": "main",
    }
    st.update(kw)
    return st


def _setup_qa(monkeypatch, *, agents, verdicts, decompose=None, cancel_state=None):
    """Pasang seluruh mock impl untuk skenario execute.

    Mencatat: (phases, detail) — detail["fixers"], detail["subtask_map_seen"].
    Setiap giliran QA diketahui dari task ber-flag "ATURAN QA"; verdict
    diambil berurutan dari ``verdicts`` (stok habis => FAIL).
    """
    monkeypatch.setattr(engine.database, "list_custom_agents_sync", lambda: agents)
    monkeypatch.setattr(engine.database, "init_db_sync", MagicMock())

    async def fake_decompose(topic, participants):
        return decompose or {}

    monkeypatch.setattr(engine, "_decompose_task", fake_decompose)

    seen: dict = {"subtask_map": None, "parallel_called": False}

    async def fake_parallel(
        participants,
        subtask_map,
        topic,
        intent_info,
        session_id,
        mode,
        execution_steps,
        ctx_lines,
        failed_steps,
    ):
        seen["parallel_called"] = True
        seen["subtask_map"] = dict(subtask_map or {})
        for a in participants:
            execution_steps.append(_step(a))
        return False

    monkeypatch.setattr(engine, "_execute_agents_parallel", fake_parallel)

    detail = {"fixers": []}
    verdict_q = list(verdicts)

    def _bump_cancel():
        if cancel_state is not None:
            cancel_state["flag"] = True

    async def fake_exec(agent, task_desc=None, topic="", intent_info=None):
        task = str(task_desc or "")
        if "QA MENEMUKAN BUG" in task:  # giliran perbaikan fixer
            _bump_cancel()
            detail["fixers"].append(agent["name"])
            return _step(agent, phase="fix", execution_summary="perbaikan selesai")
        if "ATURAN QA" in task:  # giliran juri QA Sentinel
            verdict = verdict_q.pop(0) if verdict_q else "FAIL"
            text = (
                "Semua aman.\nQA_VERDICT: PASS"
                if verdict == "PASS"
                else "Ada bug: 1) contoh error.\nQA_VERDICT: FAIL - 1) contoh error"
            )
            return _step(agent, phase="pending", execution_summary=text,
                         generated_content=text)
        return _step(agent)

    monkeypatch.setattr(engine, "execute_swarm_task_step", fake_exec)

    async def fake_gen(agent=None, prompt="", system_instruction=None):
        return "KONSENSUS SELESAI\n\nACTION PLAN: 1. Uji\n2. Deploy"

    monkeypatch.setattr(engine, "generate_agent_response", fake_gen)
    return seen, detail


def _phases(res):
    return [s.get("phase") for s in res["execution_results"]]


# ── Mode execute: QA loop Sentinel ──────────────────────────────────────────
async def test_qa_pass_first_round(_engine_clean, monkeypatch):
    agents = _agents(("A", "dev"), ("B", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="qa-p1"
    )
    assert res["status"] == "success"
    assert _phases(res) == ["main", "main", "qa_round_1"]
    assert res["consensus"].startswith("KONSENSUS SELESAI")
    assert res["action_plan"].startswith("ACTION PLAN")


async def test_qa_fail_then_fix_then_pass(_engine_clean, monkeypatch):
    agents = _agents(("A", "dev"), ("B", "dev"), ("Sentinel QA", "penjamin mutu"))
    decompose = {"B": {"task": "Perbaiki modul hitung", "depends_on": []}}
    _setup_qa(monkeypatch, agents=agents, verdicts=["FAIL", "PASS"],
              decompose=decompose)

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="qa-fp"
    )
    assert res["status"] == "success"
    # Semantic yang benar: QA1 FAIL → 2 fixer → QA2 PASS → stop.
    assert _phases(res) == [
        "main",
        "main",
        "qa_round_1",
        "qa_fix_round_1",
        "qa_fix_round_1",
        "qa_round_2",
    ]


async def test_qa_rounds_exhausted_logs_warning(_engine_clean, monkeypatch):
    agents = _agents(("A", "dev"), ("B", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["FAIL", "FAIL"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="qa-xx"
    )
    assert _phases(res)[-1] == "qa_fix_round_2"
    warn = [
        c for c in engine.log_live.call_args_list
        if "Batas putaran QA habis" in str(c.args[1])
    ]
    assert warn, "Harus ada peringatan batas putaran QA"


async def test_qa_budget_stops_loop(_engine_clean, monkeypatch):
    monkeypatch.setattr(engine, "_budget_exceeded", lambda steps: "timeout misi")
    agents = _agents(("A", "dev"), ("B", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=[])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="qa-bd"
    )
    assert res["status"] == "success"
    assert _phases(res) == ["main", "main"]
    assert engine._BUDGET_EXCEEDED == "timeout misi"


async def test_qa_cancel_during_fixers(_engine_clean, monkeypatch):
    cancel_state = {"flag": False}

    def fake_cancel(*a, **k):
        return cancel_state["flag"]

    monkeypatch.setattr(engine, "_cancel_requested", fake_cancel)
    agents = _agents(("A", "dev"), ("B", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["FAIL"],
              cancel_state=cancel_state)

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="qa-cx"
    )
    assert res["status"] == "cancelled"
    assert "dibatalkan pengguna" in res["consensus"]
    assert _phases(res) == ["main", "main", "qa_round_1", "qa_fix_round_1"]
    # Cancel dinyatakan setelah fixer pertama — fixer kedua terlewati.
    assert len(res["execution_results"][-1]["agent_name"]) > 0


async def test_cancel_before_launch(_engine_clean, monkeypatch):
    monkeypatch.setattr(engine, "_cancel_requested", lambda *a, **k: True)
    agents = _agents(("A", "dev"), ("B", "dev"))
    seen, _ = _setup_qa(monkeypatch, agents=agents, verdicts=[])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="cn-x"
    )
    assert res["status"] == "cancelled"
    assert not seen["parallel_called"]
    assert res["execution_results"] == []


async def test_no_workforce_agents_error(_engine_clean, monkeypatch):
    monkeypatch.setattr(engine.database, "list_custom_agents_sync", lambda: [])
    monkeypatch.setattr(engine.database, "init_db_sync", MagicMock())

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", session_id="no-agen"
    )
    assert res["status"] == "error"
    assert "workforce" in res["error"]


async def test_no_qa_agent_skips_loop(_engine_clean, monkeypatch):
    agents = _agents(("A", "dev"), ("B", "penulis"))
    _setup_qa(monkeypatch, agents=agents, verdicts=[])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="qa-skip"
    )
    assert res["status"] == "success"
    assert _phases(res) == ["main", "main"]


async def test_qa_fallback_by_name_keyword(_engine_clean, monkeypatch):
    # Tanpa agen bernama "Sentinel QA" — fallback menangkap nama berkeyword uji.
    agents = _agents(("A", "dev"), ("Penguji Utama", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3",
        participant_names=["A", "Penguji Utama"],
        session_id="qa-fb",
    )
    qa_steps = [
        s for s in res["execution_results"]
        if str(s.get("phase", "")).startswith("qa_round")
    ]
    assert len(qa_steps) == 1
    assert qa_steps[0]["agent_name"] == "Penguji Utama"


# ── Folder target: auto-create, realpath, sanitize ───────────────────────────
async def test_auto_create_folder_and_env(_engine_clean, monkeypatch):
    makedirs = MagicMock()
    monkeypatch.setattr(engine.os, "makedirs", makedirs)
    monkeypatch.setenv("ALFA_TARGET_FOLDER", "")
    agents = _agents(("A", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "buat landing ram monitor", participant_names=["A"], session_id="ac-ok"
    )
    assert makedirs.call_count == 1
    assert makedirs.call_args.kwargs.get("exist_ok") is True
    assert "proyek-x_" in res["target_folder"]
    assert os.environ.get("ALFA_TARGET_FOLDER") == res["target_folder"]


async def test_auto_create_makedirs_error_logs_warning(_engine_clean, monkeypatch):
    def boom(*a, **k):
        raise OSError()

    monkeypatch.setattr(engine.os, "makedirs", boom)
    agents = _agents(("A", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "buat skrip monitoring", participant_names=["A"], session_id="ac-err"
    )
    assert res["target_folder"] == ""
    target_logs = [
        str(c.args[1]) for c in engine.log_live.call_args_list
        if c.args[0] == "TARGET" and "Gagal buat folder" in str(c.args[1])
    ]
    assert target_logs, "Harus log peringatan gagal buat folder"


async def test_explicit_target_folder_triggers_sanitize(
    _engine_clean, monkeypatch, tmp_path
):
    expected_dir = os.path.realpath(os.path.expanduser(str(tmp_path)))
    agents = _agents(("A", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3",
        participant_names=["A"],
        target_folder=str(tmp_path),
        session_id="tg-ok",
    )
    assert res["target_folder"] == expected_dir
    engine.sanitize_project_directory.assert_called_once_with(expected_dir)


async def test_checkpoint_saved_when_available(_engine_clean, monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "_CHECKPOINT_AVAILABLE", True, raising=True)
    agents = _agents(("A", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3",
        participant_names=["A"],
        target_folder=str(tmp_path),
        session_id="ck-ok",
    )
    assert engine._SwarmCheckpoint.save.called
    assert engine._SwarmCheckpoint.mark_completed.called


async def test_checkpoint_errors_swallowed(_engine_clean, monkeypatch, tmp_path):
    # Checkpoint gagal (simpan & selesaikan) TIDAK boleh menggugurkan misi.
    ck = MagicMock()
    ck.save.side_effect = ValueError("ruang penuh")
    ck.mark_completed.side_effect = ValueError("ruang penuh")
    monkeypatch.setattr(engine, "_SwarmCheckpoint", ck)
    monkeypatch.setattr(engine, "_CHECKPOINT_AVAILABLE", True, raising=True)
    agents = _agents(("A", "dev"), ("Sentinel QA", "penjamin mutu"))
    _setup_qa(monkeypatch, agents=agents, verdicts=["PASS"])

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A"], session_id="ck-err"
    )
    assert res["status"] == "success"
    assert ck.save.called and ck.mark_completed.called


async def test_cancel_after_decompose(_engine_clean, monkeypatch):
    state = {"v": False}
    monkeypatch.setattr(engine, "_cancel_requested", lambda *a, **k: state["v"])
    agents = _agents(("A", "dev"), ("B", "dev"))
    seen, _ = _setup_qa(monkeypatch, agents=agents, verdicts=[])

    async def flip_decompose(topic, participants):
        state["v"] = True
        return {}

    monkeypatch.setattr(engine, "_decompose_task", flip_decompose)

    res = await engine._conduct_multi_agent_meeting_impl(
        "audit laporan Q3", participant_names=["A", "B"], session_id="cn-dx"
    )
    assert res["status"] == "cancelled"
    assert not seen["parallel_called"]
    assert res["execution_results"] == []


# ── Mode plan: deliberasi + pemungutan suara mekanis ─────────────────────────
def _plan_env(monkeypatch, *, agents, script, consensus_text):
    """script = list resolusi berurutan utk setiap giliran diskusi."""
    monkeypatch.setattr(engine.database, "list_custom_agents_sync", lambda: agents)
    monkeypatch.setattr(engine.database, "init_db_sync", MagicMock())
    prompts: list[str] = []
    queue = list(script)

    async def fake_gen(agent=None, prompt="", system_instruction=None):
        prompts.append(prompt)
        if "TOPIK RAPAT" in prompt:  # prompt konsensus kapten (final)
            return consensus_text
        # Skrip bisa habis lebih cepat (rounds tidak valid → default 2).
        return queue.pop(0) if queue else "(giliran tanpa skrip)"

    monkeypatch.setattr(engine, "generate_agent_response", fake_gen)
    return prompts


async def test_plan_deliberation_voting_winner_and_dissent(
    _engine_clean, monkeypatch
):
    agents = _agents(("Budi", "arsitek"), ("Ani", "data"))
    script = [
        '{"position":"Budi: pakai Postgres","evidence":"ACID","confidence":0.9,"votes":[]}',
        '{"position":"Ani: pakai SQLite","evidence":"ringan","confidence":0.7,"votes":[]}',
        '{"position":"Budi final: Postgres","evidence":"skala","confidence":0.9,'
        '"votes":[{"id":"p2-ani","approve":true,"reason":"hemat"}]}',
        '{"position":"Ani final: SQLite","evidence":"kekentalan","confidence":0.8,'
        '"votes":[{"id":"p2-ani","approve":true,"reason":"deal"},'
        '{"id":"p2-budi","approve":false,"reason":"mahal"}]}',
    ]
    prompts = _plan_env(
        monkeypatch,
        agents=agents,
        script=script,
        consensus_text="KONSENSUS CAPAI.\n\nACTION PLAN: 1. Migrasi DB",
    )

    res = await engine._conduct_multi_agent_meeting_impl(
        "strategi hemat kuota API", participant_names=["Budi", "Ani"],
        rounds=2, mode="plan", session_id="pl-vote",
    )
    assert res["status"] == "success"
    assert len(res["dialogue_transcript"]) == 4
    # Prompt putaran 2 menyertakan menu proposal dari putaran 1 (id p1-*).
    assert any("p1-budi" in p for p in prompts)
    # Suara dihitung mekanis — winner p2-ani (2 setuju, 0 tolak).
    assert res["vote_tally"]["winner"]["id"] == "p2-ani"
    assert res["vote_tally"]["winner"]["votes_for"] == 2
    assert res["dissent"] == [
        {"voter": "Ani", "proposal_id": "p2-budi", "author": "Budi"}
    ]
    assert res["consensus_agreement"] == round(2 / 3, 4)
    assert {p["id"] for p in res["proposals"]} == {"p2-budi", "p2-ani"}
    assert res["action_plan"].startswith("ACTION PLAN")


async def test_plan_plain_text_fallback_no_votes(_engine_clean, monkeypatch):
    agents = _agents(("Budi", "arsitek"), ("Ani", "data"))
    script = [
        "Saya setuju pakai Postgres saja.",
        "Menurutku SQLite cukup untuk kebutuhan ini.",
    ]
    _plan_env(
        monkeypatch,
        agents=agents,
        script=script,
        consensus_text="KONSENSUS TEKS POLOS.",
    )

    res = await engine._conduct_multi_agent_meeting_impl(
        "strategi hemat kuota API", participant_names=["Budi", "Ani"],
        rounds=1, mode="plan", session_id="pl-plain",
    )
    assert res["status"] == "success"
    assert res["vote_tally"]["winner"] is None
    assert res["vote_tally"]["total_voters"] == 0
    assert res["dissent"] == []
    assert {p["id"] for p in res["proposals"]} == {"p1-budi", "p1-ani"}
    assert res["consensus_agreement"] == 0.0
    assert res["action_plan"] == ""
    assert res["consensus"] == "KONSENSUS TEKS POLOS."


async def test_plan_rounds_garbage_falls_back(_engine_clean, monkeypatch):
    agents = _agents(("Budi", "arsitek"))
    script = ["Posisi budi v1."]
    _plan_env(
        monkeypatch,
        agents=agents,
        script=script,
        consensus_text="KONSENSUS MINIMAL SAJA.",
    )

    res = await engine._conduct_multi_agent_meeting_impl(
        "strategi hemat kuota API", participant_names=["Budi"],
        rounds="tiga", mode="plan", session_id="pl-crash",
    )
    # rounds tak valid → default 2 putaran; 1 agen → 2 dialog.
    assert len(res["dialogue_transcript"]) == 2
    assert res["consensus"] == "KONSENSUS MINIMAL SAJA."


# ── Fase-3: DAG _execute_agents_parallel — jalur lanjutan ────────────────────
def _dag_env(monkeypatch):
    """Lingkungan DAG: checkpoint aktif, util error/logger dimata-matai."""
    monkeypatch.setattr(engine, "_CHECKPOINT_AVAILABLE", True, raising=True)
    monkeypatch.setattr(engine, "_record_step_error", MagicMock())
    monkeypatch.setattr(engine, "_budget_exceeded", lambda steps: "")
    monkeypatch.setattr(engine, "_provider_dead_streak", lambda steps: "")


async def test_dag_post_wave_cancel_hits_checkpoint(_engine_clean, monkeypatch):
    """Cancel di antara dua gelombang DAG → mark_cancelled, agen kedua tak jalan."""
    _dag_env(monkeypatch)
    cancel_state = {"flag": False}
    monkeypatch.setattr(
        engine, "_cancel_requested", lambda *a, **k: cancel_state["flag"]
    )
    agents = _agents(("A", "dev"), ("B", "dev"))
    subtask_map = {
        "A": {"task": "tugas A", "depends_on": []},
        "B": {"task": "tugas B", "depends_on": ["A"]},
    }
    calls = {"n": 0}

    async def fake_step(agent, task_desc="", topic="", intent_info=None, **kw):
        calls["n"] += 1
        if calls["n"] >= 1:  # flip setelah gelombang pertama tuntas
            cancel_state["flag"] = True
        return _step(agent), True, ""

    monkeypatch.setattr(engine, "_execute_agent_step", fake_step)

    steps: list = []
    ctx: list = []
    failed: list = []
    result = await engine._execute_agents_parallel(
        agents, subtask_map, "audit laporan Q3", {}, "dag-cancel", "execute",
        steps, ctx, failed,
    )
    assert result is True
    assert [s["agent_name"] for s in steps] == ["A"]
    engine._SwarmCheckpoint.mark_cancelled.assert_called_once_with("dag-cancel")


async def test_dag_invalid_wave_env_falls_back_defaults(_engine_clean, monkeypatch):
    """Env max-concurrent kotor → default 3; PARALLEL=off → gelombang 1."""
    _dag_env(monkeypatch)
    monkeypatch.setenv("ALFA_SWARM_MAX_CONCURRENT", "tiga")
    monkeypatch.setenv("ALFA_SWARM_PARALLEL", "off")
    agents = _agents(("A", "dev"), ("B", "dev"))

    async def fake_step(agent, task_desc="", topic="", intent_info=None, **kw):
        return _step(agent), True, ""

    monkeypatch.setattr(engine, "_execute_agent_step", fake_step)

    steps: list = []
    ctx: list = []
    failed: list = []
    result = await engine._execute_agents_parallel(
        agents, {}, "audit laporan Q3", {}, "dag-env", "execute",
        steps, ctx, failed,
    )
    assert result is False
    assert [s["agent_name"] for s in steps] == ["A", "B"]
