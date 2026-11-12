"""Tes audit trail tool di runtime context (nama + argumen teredaksi)."""

from __future__ import annotations

from alfa.core import runtime_ctx as rc


def test_record_tool_keeps_name_only_compatible():
    rc.reset_turn_context()
    rc.record_executed_tool("baca_file")
    assert rc.get_current_executed_tools() == ["baca_file"]
    assert rc.get_current_executed_tool_calls() == [{"tool": "baca_file"}]


def test_record_tool_with_args_keeps_summary():
    rc.reset_turn_context()
    rc.record_executed_tool("tulis_file", '{"path": "/tmp/a.xlsx"}')
    calls = rc.get_current_executed_tool_calls()
    assert calls == [{"tool": "tulis_file", "args": '{"path": "/tmp/a.xlsx"}'}]
    assert rc.get_current_executed_tools() == ["tulis_file"]


def test_secret_values_are_redacted():
    rc.reset_turn_context()
    rc.record_executed_tool(
        "http",
        '{"url": "https://x", "api_key": "sk-rahasia", "token": "abc123"}',
    )
    args = rc.get_current_executed_tool_calls()[0]["args"]
    assert "sk-rahasia" not in args
    assert "abc123" not in args
    assert "***" in args


def test_args_are_truncated():
    rc.reset_turn_context()
    rc.record_executed_tool("bash", "x" * 1000)
    assert len(rc.get_current_executed_tool_calls()[0]["args"]) == 400


def test_reset_clears_tool_calls_and_artifacts():
    rc.reset_turn_context()
    rc.record_executed_tool("a", "{}")
    rc.record_turn_artifact("/tmp/a.xlsx")
    rc.reset_turn_context()
    assert rc.get_current_executed_tools() == []
    assert rc.get_current_executed_tool_calls() == []
    assert rc.get_current_turn_artifacts() == []
