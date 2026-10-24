"""Unit hermetik: run-trace (observability ringan) + integrasi wrapper swarm.

Tracing wajib gagal-lembut: tak pernah mengganggu jalur utama swarm.
"""

from __future__ import annotations

import sqlite3

import pytest

from alfa.core.db import run_trace
from alfa.core.db.connection import get_sync_db
from alfa.swarm import engine as swarm_engine
from alfa.swarm import workspace_hygiene


@pytest.fixture()
def _clean_trace_table():
    from alfa.core.db.connection import init_db_sync

    init_db_sync()
    with get_sync_db() as conn:
        try:
            conn.execute("DELETE FROM run_traces")
            conn.commit()
        except (sqlite3.Error, OSError, ValueError):
            pass
    yield
    with get_sync_db() as conn:
        try:
            conn.execute("DELETE FROM run_traces")
            conn.commit()
        except (sqlite3.Error, OSError, ValueError):
            pass


def _fake_result() -> dict:
    return {
        "dialogue_transcript": ["a", "b"],
        "execution_results": [
            {
                "agent_name": "A",
                "tool_used": "bash",
                "deliverable_file": None,
                "execution_summary": "beres",
            },
            {
                "agent_name": "B",
                "tool_used": None,
                "deliverable_file": "laporan.md",
                "execution_summary": "[EXCEPTION] gagal x",
            },
        ],
        "consensus": "OK",
        "vote_tally": {"p1-A": 1},
    }


def test_record_and_list_summarize_run(_clean_trace_table):
    run_trace.record_swarm_meeting_sync(
        session_id="uji-3",
        topic="rapat anggaran Q4",
        mode="execute",
        rounds=2,
        duration_ms=1234,
        participants=["A", "B"],
        result=_fake_result(),
    )
    runs = run_trace.list_runs_sync()
    assert len(runs) == 1
    row = runs[0]
    assert row["run_id"] == "uji-3"
    assert row["status"] == "ok"
    assert row["kind"] == "swarm_meeting"
    assert row["duration_ms"] == 1234
    meta = row["meta"]
    assert meta["topic"].startswith("rapat anggaran")
    assert meta["participants"] == ["A", "B"]
    summary = row["summary"]
    assert summary["steps"] == 2
    assert summary["tools_used"] == 1
    assert summary["deliverables"] == 1
    assert summary["step_errors"] == 1
    assert summary["dialogue_rounds"] == 2
    assert summary["has_vote_tally"] is True
    assert summary["has_consensus"] is True
    single = run_trace.get_run_sync("uji-3")
    assert single is not None
    assert single["summary"] == summary
    assert run_trace.get_run_sync("tidak-ada") is None


def test_error_run_and_upsert_same_session(_clean_trace_table):
    run_trace.record_swarm_meeting_sync(
        session_id="uji-err",
        topic="uji gagal",
        mode="plan",
        rounds=1,
        duration_ms=10,
        participants=["A"],
        error="exception",
    )
    runs = run_trace.list_runs_sync()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert runs[0]["summary"] == {}
    # Upsert: record ulang run_id sama → tak menambah baris.
    run_trace.record_swarm_meeting_sync(
        session_id="uji-err",
        topic="uji gagal",
        mode="plan",
        rounds=1,
        duration_ms=20,
        participants=["A"],
        result={"execution_results": [], "consensus": "x"},
    )
    assert len(run_trace.list_runs_sync()) == 1
    row = run_trace.get_run_sync("uji-err") or {}
    assert row["status"] == "ok"
    assert row["summary"]["has_consensus"] is True


def test_engine_wrapper_records_ok_and_error_traces(
    _clean_trace_table, monkeypatch
):
    monkeypatch.setattr(workspace_hygiene, "register_session", lambda sid: sid)
    monkeypatch.setattr(workspace_hygiene, "unregister_session", lambda sid: None)
    monkeypatch.setattr(
        workspace_hygiene, "_clear_cancel_flag", lambda sid: None
    )

    async def fake_impl_ok(**_kw):
        return _fake_result()

    monkeypatch.setattr(
        swarm_engine, "_conduct_multi_agent_meeting_impl", fake_impl_ok
    )

    import asyncio

    result = asyncio.run(
        swarm_engine.conduct_multi_agent_meeting(
            "uji jejak sehat", session_id="trace-ok-1"
        )
    )
    assert result["consensus"] == "OK"
    row = run_trace.get_run_sync("trace-ok-1")
    assert row is not None
    assert row["status"] == "ok"
    assert row["summary"]["steps"] == 2

    class _LedakanError(RuntimeError):
        pass

    async def fake_impl_boom(**_kw):
        raise _LedakanError

    monkeypatch.setattr(
        swarm_engine, "_conduct_multi_agent_meeting_impl", fake_impl_boom
    )
    with pytest.raises(RuntimeError):
        asyncio.run(
            swarm_engine.conduct_multi_agent_meeting(
                "uji jejak gagal", session_id="trace-err-1"
            )
        )
    err_row = run_trace.get_run_sync("trace-err-1")
    assert err_row is not None
    assert err_row["status"] == "error"
    assert err_row["meta"]["error"] == "exception"


def test_trace_failure_never_breaks_main_path(monkeypatch):
    class _BoomError(RuntimeError):
        pass

    def _boom(**_kw):
        raise _BoomError

    monkeypatch.setattr(run_trace, "record_swarm_meeting_sync", _boom)
    # Helper engine menelan error apapun dari tracing.
    swarm_engine._record_swarm_trace_safely(
        "uji-swell", "topik", "plan", 2, 0.0, ["A"]
    )
    # summarize tak pernah melempar pada bentuk aneh pun.
    weird = run_trace.summarize_swarm_result({"execution_results": "anomali"})
    assert weird == {
        "steps": 0,
        "tools_used": 0,
        "deliverables": 0,
        "step_errors": 0,
        "dialogue_rounds": 0,
        "has_vote_tally": False,
        "has_consensus": False,
    }
