"""Unit test hermetik untuk unit swarm engine (rekomendasi #4).

- _swarm_budget: parsing env timeout/max_steps, nilai kotor -> default.
- _budget_exceeded: timeout misi, batas langkah, dan nonaktif (0).
- _normalize_swarm_mode: alias mode rapat/eksekusi + fallback execute.
- _execute_agents_parallel: jalur sekuensial (tanpa deps), DAG 2 gelombang,
  cancel sinyal, budget habis saat gelombang, dan fallback siklus deps.

Semua eksternal (checkpoint DB, step executor nyata) di-patch — tanpa
network, tanpa DB produksi (lapisan conftest proteksi).
"""

import asyncio
import importlib
import time
from unittest.mock import MagicMock

import pytest

engine = importlib.import_module("alfa.swarm.engine")


@pytest.fixture
def _engine_state_clean(monkeypatch):
    """Reset state global engine supaya tes tidak saling bocor.
    State asli boleh ditimpa selama sesi ini saja (otomatis direstore)."""
    monkeypatch.setattr(engine, "_MISSION_START", None, raising=False)
    monkeypatch.setattr(engine, "_BUDGET_EXCEEDED", "", raising=False)
    monkeypatch.setattr(engine, "_PROVIDER_DEAD", "", raising=False)
    monkeypatch.setattr(engine, "_CHECKPOINT_AVAILABLE", False, raising=False)
    monkeypatch.setattr(engine, "_TARGET_FOLDER", "", raising=False)
    return engine


def _mk_participants(*names_roles):
    return [{"name": n, "role": r} for n, r in names_roles]


def _mk_pass(name: str):
    return (
        {
            "agent_name": name,
            "tool_used": "tool_x",
            "execution_summary": "beres",
            "deliverable_file": None,
        },
        True,
        "",
    )


def _mk_fail(name: str):
    return (
        {
            "agent_name": name,
            "tool_used": "tool_x",
            "execution_summary": "gagal",
            "deliverable_file": None,
        },
        False,
        "alasan gagal",
    )


def _patch_common(monkeypatch, *, fail_names=()):
    """Patch executor internal engine: langkah sukses/gagal tanpa LLM nyata."""
    recorded_errors: list[tuple] = []

    async def fake_step(agent, task_desc=None, *, topic="", intent_info=None):
        if agent["name"] in fail_names:
            return _mk_fail(agent["name"])
        return _mk_pass(agent["name"])

    monkeypatch.setattr(engine, "_execute_agent_step", fake_step)
    monkeypatch.setattr(
        engine,
        "_record_step_error",
        lambda sid, sr, fb: recorded_errors.append((sid, sr["agent_name"])),
    )
    monkeypatch.setattr(engine, "_SwarmCheckpoint", MagicMock())
    monkeypatch.setattr(engine, "_cancel_requested", lambda sid: False)
    return recorded_errors


# --- _swarm_budget ------------------------------------------------------------
def test_swarm_budget_parsing(_engine_state_clean, monkeypatch):
    monkeypatch.delenv("ALFA_SWARM_TASK_TIMEOUT", raising=False)
    monkeypatch.delenv("ALFA_SWARM_MAX_STEPS", raising=False)
    timeout, max_steps = engine._swarm_budget()
    assert timeout == 1800.0
    assert max_steps == 40

    monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "120")
    monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "8")
    assert engine._swarm_budget() == (120.0, 8)

    # Nilai tak valid jatuh ke default, bukan crash
    monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "bukan angka")
    monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "0 saa")
    assert engine._swarm_budget() == (1800.0, 40)

    # 0 = budget dinonaktifkan, dipertahankan sebagai 0
    monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "0")
    monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "0")
    assert engine._swarm_budget() == (0.0, 0)


# --- _budget_exceeded ----------------------------------------------------------
def test_budget_exceeded_timeout_and_steps(_engine_state_clean, monkeypatch):
    monkeypatch.delenv("ALFA_SWARM_TASK_TIMEOUT", raising=False)
    monkeypatch.delenv("ALFA_SWARM_MAX_STEPS", raising=False)

    # Tanpa milestone mulai -> belum melebihi apa pun
    assert engine._budget_exceeded([]) == ""

    # Milestone lama -> timeout misi
    engine._MISSION_START = time.monotonic() - 10_000
    assert "timeout misi" in engine._budget_exceeded([])

    # Reset milestone, cek batas jumlah langkah
    engine._MISSION_START = None
    steps = [{"step_num": i} for i in range(40)]
    assert "batas 40 langkah" in engine._budget_exceeded(steps)
    assert engine._budget_exceeded(steps[:39]) == ""

    # Budget dimatikan (0/0): selalu lulus
    monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "0")
    monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "0")
    engine._MISSION_START = time.monotonic() - 99_999
    assert engine._budget_exceeded(steps) == ""


# --- _provider_dead_streak ----------------------------------------------------
def test_provider_dead_streak_summary_signal(_engine_state_clean):
    dead = {
        "status": "error",
        "tool_output": "",
        "execution_summary": "SEMUA provider gagal (kuota)",
    }
    ok = {"status": "success", "tool_output": "ok", "execution_summary": "ok"}
    assert engine._provider_dead_streak([]) == ""
    # Sinyal juga terbaca dari execution_summary, tidak hanya tool_output
    assert engine._provider_dead_streak([dead, dead, dead]) != ""
    assert engine._provider_dead_streak([ok, dead, dead]) == ""
    # Entri None aman (fallback (s or {}).get)
    assert engine._provider_dead_streak([None, None, None]) == ""


# --- _normalize_swarm_mode -----------------------------------------------------
def test_normalize_swarm_mode(_engine_state_clean):
    assert engine._normalize_swarm_mode(None) == "execute"
    assert engine._normalize_swarm_mode("") == "execute"
    assert engine._normalize_swarm_mode("RAPAT") == "plan"
    assert engine._normalize_swarm_mode("  eksekusi  ") == "execute"
    assert engine._normalize_swarm_mode("plan") == "plan"
    assert engine._normalize_swarm_mode("plan_and_execute") == "plan_and_execute"
    assert engine._normalize_swarm_mode("mode_aneh") == "execute"


# --- _execute_agents_parallel: jalur flat (tanpa deps) -------------------------
async def test_parallel_flat_success(_engine_state_clean, monkeypatch):
    _patch_common(monkeypatch)
    participants = _mk_participants(("A", "dev"), ("B", "dev"))
    exec_steps, ctx_lines, failed = [], [], []

    result = await engine._execute_agents_parallel(
        participants,
        {},
        "topik",
        {},
        "sess_1",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert result is False
    assert len(exec_steps) == 2
    assert all(s["verification"] == "PASS" for s in exec_steps)
    assert failed == []
    assert len(ctx_lines) == 2


async def test_parallel_records_failures(_engine_state_clean, monkeypatch):
    errors = _patch_common(monkeypatch, fail_names={"B"})
    participants = _mk_participants(("A", "dev"), ("B", "dev"))
    exec_steps, ctx_lines, failed = [], [], []

    result = await engine._execute_agents_parallel(
        participants,
        {},
        "topik",
        {},
        "sess_2",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert result is False
    verdicts = [s["verification"] for s in exec_steps]
    assert verdicts == ["PASS", "FAIL"]
    assert [f["agent_name"] for f in failed] == ["B"]
    # error hanya direkam untuk langkah gagal, satu kali
    assert [(sid, name) for sid, name in errors] == [("sess_2", "B")]


async def test_parallel_cancel_pre_wave(_engine_state_clean, monkeypatch):
    async def never_step(agent, task_desc=None, *, topic="", intent_info=None):
        raise AssertionError

    monkeypatch.setattr(engine, "_execute_agent_step", never_step)
    monkeypatch.setattr(engine, "_record_step_error", MagicMock())
    monkeypatch.setattr(engine, "_cancel_requested", lambda sid: True)

    exec_steps, ctx_lines, failed = [], [], []
    result = await engine._execute_agents_parallel(
        _mk_participants(("A", "dev"), ("B", "dev")),
        {},
        "topik",
        {},
        "sess_c1",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert result is True
    assert exec_steps == []
    assert failed == []


async def test_parallel_budget_halts(_engine_state_clean, monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.delenv("ALFA_SWARM_TASK_TIMEOUT", raising=False)
    engine._MISSION_START = time.monotonic() - 10_000  # milestone lampau
    exec_steps, ctx_lines, failed = [], [], []

    result = await engine._execute_agents_parallel(
        _mk_participants(("A", "dev"), ("B", "dev")),
        {},
        "topik",
        {},
        "sess_b1",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert result is True
    assert "timeout misi" in engine._BUDGET_EXCEEDED
    assert exec_steps == []


# --- _execute_agents_parallel: DAG & siklus ------------------------------------
async def test_parallel_dag_two_waves(_engine_state_clean, monkeypatch):
    seen_order: list[str] = []
    seen_tasks: list[str] = []

    async def slow_step(agent, task_desc=None, *, topic="", intent_info=None):
        seen_order.append(agent["name"])
        seen_tasks.append(task_desc or "")
        await asyncio.sleep(0.01)  # beri ruang antar-gelombang
        return _mk_pass(agent["name"])

    monkeypatch.setattr(engine, "_execute_agent_step", slow_step)
    monkeypatch.setattr(engine, "_record_step_error", MagicMock())
    monkeypatch.setattr(engine, "_cancel_requested", lambda sid: False)

    participants = _mk_participants(("A", "dev"), ("B", "dev"))
    subtask = {
        "A": {"task": "kerja A", "depends_on": []},
        "B": {"task": "kerja B", "depends_on": ["A"]},
    }
    exec_steps, ctx_lines, failed = [], [], []
    res = await engine._execute_agents_parallel(
        participants,
        subtask,
        "topik",
        {},
        "sess_dag",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert res is False
    assert seen_order == ["A", "B"]
    assert len(exec_steps) == 2
    assert any("kerja A" in t for t in seen_tasks)


async def test_parallel_cycle_fallback_flat(_engine_state_clean, monkeypatch):
    """Siklus deps: kembali ke jalur flat — semua tetap dieksekusi, tidak hang."""
    calls = _patch_common(monkeypatch)
    participants = _mk_participants(("A", "dev"), ("B", "dev"))
    cycle = {"A": {"depends_on": ["B"]}, "B": {"depends_on": ["A"]}}
    exec_steps, ctx_lines, failed = [], [], []

    res = await engine._execute_agents_parallel(
        participants,
        cycle,
        "topik",
        {},
        "sess_cycle",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert res is False
    # Flat fallback: kedua agen dieksekusi
    assert sorted(s["agent_name"] for s in exec_steps) == ["A", "B"]
    assert len(calls) == 0  # tidak ada failed steps


# --- langkah ber-exception -------------------------------------------------------
async def test_parallel_exception_step_marked_fail(_engine_state_clean, monkeypatch):
    async def boom(agent, task_desc=None, *, topic="", intent_info=None):
        raise RuntimeError

    monkeypatch.setattr(engine, "_execute_agent_step", boom)
    monkeypatch.setattr(engine, "_record_step_error", MagicMock())
    monkeypatch.setattr(engine, "_cancel_requested", lambda sid: False)
    monkeypatch.setattr(engine, "_SwarmCheckpoint", MagicMock())

    exec_steps, ctx_lines, failed = [], [], []
    res = await engine._execute_agents_parallel(
        _mk_participants(("A", "dev")),
        {},
        "topik",
        {},
        "sess_exc",
        "execute",
        exec_steps,
        ctx_lines,
        failed,
    )
    assert res is False
    assert exec_steps
    assert exec_steps[0]["verification"] == "FAIL"
    assert "[EXCEPTION]" in exec_steps[0]["execution_summary"]
    assert failed
    assert failed[0]["agent_name"] == "A"
