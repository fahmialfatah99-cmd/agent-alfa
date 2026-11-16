"""Tes P1 Skill Compiler: kompilasi trajectory, shadow/on, retrieval prompt."""

from __future__ import annotations

import json
import sqlite3

import pytest

from alfa.core.brain import learning_loop, skill_compiler
from alfa.core.db.connection import get_sync_db, init_db_sync


@pytest.fixture()
def isolated_compiler_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "compiler_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALFA_SKILL_COMPILER", "shadow")
    init_db_sync()
    learning_loop.init_learning_tables()
    with get_sync_db() as conn:
        for table in ("agent_trajectories", "alfa_compiled_skills"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.Error:
                pass
        conn.commit()
    return db_file


def _seed(prompt: str, tools: list[str], turn_id: str, success: bool = True) -> None:
    learning_loop.record_trajectory(
        user_prompt=prompt,
        tool_calls=[{"tool": tool, "args": "{}"} for tool in tools],
        result_summary="ok",
        success=success,
        turn_id=turn_id,
    )


def test_shadow_mode_compiles_inactive(isolated_compiler_db):
    _seed("rekap material lahat", ["read_local_file", "update_excel_sheet"], "t1")
    _seed("rekap material curup", ["read_local_file", "update_excel_sheet"], "t2")
    _seed("rekap material bengkulu", ["read_local_file", "update_excel_sheet"], "t3")

    result = skill_compiler.compile_skills_sync()
    assert result["status"] == "ok"
    assert result["mode"] == "shadow"
    assert result["compiled"] == 1
    assert result["activated"] == 0

    rows = skill_compiler.list_compiled_skills_sync()
    assert len(rows) == 1
    assert rows[0]["active"] == 0
    assert json.loads(rows[0]["tool_sequence_json"]) == [
        "read_local_file",
        "update_excel_sheet",
    ]

    # Mode shadow tidak pernah menyuntikkan prompt.
    assert skill_compiler.retrieve_compiled_skills("rekap material lahat") == []
    assert skill_compiler.format_compiled_skills_prompt("rekap material lahat") == ""


def test_on_mode_activates_and_retrieves(isolated_compiler_db, monkeypatch):
    _seed("rekap material lahat", ["read_local_file", "update_excel_sheet"], "t1")
    _seed("rekap material curup", ["read_local_file", "update_excel_sheet"], "t2")
    monkeypatch.setenv("ALFA_SKILL_COMPILER", "on")

    result = skill_compiler.compile_skills_sync()
    assert result["activated"] == 1

    matches = skill_compiler.retrieve_compiled_skills("tolong rekap material lahat")
    assert len(matches) == 1
    prompt = skill_compiler.format_compiled_skills_prompt("rekap material lahat")
    assert "WORKFLOW TERKOMPILASI" in prompt
    assert "read_local_file → update_excel_sheet" in prompt
    assert "support 2×" in prompt


def test_min_support_skips_single_occurrence(isolated_compiler_db, monkeypatch):
    _seed("hapus file lama", ["execute_bash_command", "list_directory"], "t1")
    monkeypatch.setenv("ALFA_SKILL_COMPILER", "on")
    result = skill_compiler.compile_skills_sync(min_support=2)
    assert result["compiled"] == 0
    assert skill_compiler.list_compiled_skills_sync() == []


def test_off_mode_is_noop(isolated_compiler_db, monkeypatch):
    _seed("rekap material", ["read_local_file", "update_excel_sheet"], "t1")
    _seed("rekap material", ["read_local_file", "update_excel_sheet"], "t2")
    monkeypatch.setenv("ALFA_SKILL_COMPILER", "off")
    result = skill_compiler.compile_skills_sync()
    assert result["status"] == "disabled"
    assert skill_compiler.list_compiled_skills_sync() == []


def test_compile_is_idempotent_and_normalizes_duplicate_tools(isolated_compiler_db):
    _seed("rekap gudang", ["read_local_file", "read_local_file", "update_excel_sheet"], "t1")
    _seed("rekap gudang", ["read_local_file", "update_excel_sheet"], "t2")

    first = skill_compiler.compile_skills_sync(min_support=2)
    second = skill_compiler.compile_skills_sync(min_support=2)
    assert first["compiled"] == 1
    assert second["compiled"] == 1

    rows = skill_compiler.list_compiled_skills_sync()
    assert len(rows) == 1
    assert json.loads(rows[0]["tool_sequence_json"]) == [
        "read_local_file",
        "update_excel_sheet",
    ]


def test_failed_trajectory_is_ignored(isolated_compiler_db, monkeypatch):
    _seed("gagal", ["read_local_file", "update_excel_sheet"], "t1", success=False)
    _seed("gagal", ["read_local_file", "update_excel_sheet"], "t2", success=False)
    monkeypatch.setenv("ALFA_SKILL_COMPILER", "on")
    result = skill_compiler.compile_skills_sync(min_support=1)
    assert result["scanned"] == 0
    assert result["compiled"] == 0
