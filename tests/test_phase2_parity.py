"""Regression tests for Phase 2 model/agent parity (Anthropic, routing, MCP, worktree)."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "phase2_parity.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as conn

    conn.init_db_sync()
    return db_file


# ── 2a. Anthropic native adapter ──────────────────────────────────────────────


def test_messages_url_normalization():
    from alfa.core.brain.anthropic_native import messages_url

    assert messages_url("") == "https://api.anthropic.com/v1/messages"
    assert messages_url("https://api.anthropic.com") == (
        "https://api.anthropic.com/v1/messages"
    )
    assert messages_url("https://api.anthropic.com/v1") == (
        "https://api.anthropic.com/v1/messages"
    )
    assert messages_url("https://gw.local/v1/messages") == (
        "https://gw.local/v1/messages"
    )


def test_openai_tool_schema_converted_to_anthropic():
    from alfa.core.brain.anthropic_native import to_anthropic_tools

    converted = to_anthropic_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Cari web",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
            },
            {"type": "function", "function": {}},
        ]
    )
    assert len(converted) == 1
    assert converted[0]["name"] == "web_search"
    assert converted[0]["input_schema"]["required"] == ["q"]


def test_history_drops_leading_assistant_message():
    from alfa.core.brain.anthropic_native import _history_messages

    messages = _history_messages(
        [
            {"role": "model", "content": "tanpa pertanyaan"},
            {"role": "user", "content": "halo"},
            {"role": "model", "content": "hai"},
        ]
    )
    assert messages == [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "hai"},
    ]


def test_stream_block_finalizer_parses_tool_json():
    from alfa.core.brain.anthropic_native import _finalize_stream_blocks

    content = _finalize_stream_blocks(
        {
            0: {"type": "text", "text": "halo "},
            1: {
                "type": "tool_use",
                "id": "t1",
                "name": "x",
                "input": {},
                "_json": '{"a": 1}',
            },
        }
    )
    assert content[0] == {"type": "text", "text": "halo "}
    assert content[1]["input"] == {"a": 1}
    assert "_json" not in content[1]


@pytest.mark.asyncio
async def test_anthropic_tool_loop_returns_final_text(monkeypatch, isolated_db):
    from alfa.core.brain import agentic
    from alfa.core.brain import anthropic_native as an

    payloads: list[dict] = []

    async def fake_request(url, headers, payload, timeout):
        payloads.append(payload)
        if len(payloads) == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "execute_bash_command",
                        "input": {"command": "echo hi"},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        return {
            "content": [{"type": "text", "text": "selesai"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }

    async def fake_run_tools(gate, tool_calls):
        assert tool_calls[0]["function"]["name"] == "execute_bash_command"
        return ["ok"]

    monkeypatch.setattr(an, "_request_messages", fake_request)
    monkeypatch.setattr(agentic, "_run_tool_calls", fake_run_tools)
    monkeypatch.setattr(
        "alfa.core.rate_limiter.check_rate_limit", lambda **kwargs: (True, "")
    )

    reply = await an.run_anthropic_agentic_turn(
        api_key="dummy",
        model="claude-3-7-sonnet-latest",
        system_instruction="sys",
        user_text="jalankan echo",
        base_url="https://api.anthropic.com",
        approval_gate=lambda *a, **k: None,
    )

    assert reply == "selesai"
    assert len(payloads) == 2
    second = payloads[1]["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"
    assert second[-1]["content"][0]["content"] == "ok"


@pytest.mark.asyncio
async def test_provider_adapter_dispatches_anthropic(monkeypatch, isolated_db):
    from alfa.bot.pipeline import provider_adapter as pa

    async def fake_anthropic_turn(
        brain,
        preferred_model,
        system_instruction,
        user_text,
        history_msgs,
        approval_gate,
        streamer,
        *,
        timeout=180.0,
    ):
        return "halo dari claude"

    class FakeDB:
        def __init__(self):
            self.saved = []

        async def save_chat_message(self, user_id, role, content):
            self.saved.append((role, content))

        def list_active_keys_sync(self, **kwargs):
            return []

    monkeypatch.setattr(pa, "_anthropic_turn", fake_anthropic_turn)
    db = FakeDB()
    reply = await pa.openai_compat_turn(
        mb=None,
        brain={
            "provider": "anthropic",
            "api_key": "dummy",
            "model": "claude-3-7-sonnet-latest",
            "base_url": "",
            "key_id": 1,
            "label": "anthropic-test",
        },
        preferred_model="claude-3-7-sonnet-latest",
        system_instruction="sys",
        user_prompt="hai",
        multimodal_parts=None,
        history_msgs=[],
        history_rows=[],
        approval_gate=lambda *a, **k: None,
        streamer=None,
        meeting_intent=False,
        meetings_before=0,
        db=db,
        user_id=1,
        display_user_text="hai",
    )
    assert reply == "halo dari claude"
    assert ("model", "halo dari claude") in db.saved


# ── 2b. Capability-aware routing ──────────────────────────────────────────────


def test_capability_routing_prefers_vision_capable_model():
    from alfa.core.brain.model_router import (
        model_capabilities,
        order_models_by_capability,
    )

    assert "vision" in model_capabilities("gemini-3.8-flash")
    assert "vision" in model_capabilities("claude-3-7-sonnet-latest")
    assert "vision" not in model_capabilities("deepseek-chat")

    ordered = order_models_by_capability(
        ["deepseek-chat", "gemini-3.8-flash"], {"vision"}
    )
    assert ordered == ["gemini-3.8-flash", "deepseek-chat"]


def test_legacy_route_order_unchanged_without_capabilities():
    from alfa.core.brain.model_router import order_models_by_capability

    models = ["a", "b", "c"]
    assert order_models_by_capability(models, None) == models


def test_required_capabilities_includes_vision_for_images():
    from alfa.core.brain.model_router import required_capabilities

    assert "vision" in required_capabilities("apa ini?", has_images=True)
    assert "vision" not in required_capabilities("apa ini?", has_images=False)


# ── 2c. Dynamic MCP bridge ────────────────────────────────────────────────────


def test_mcp_refresh_cache_and_schema(monkeypatch, tmp_path):
    from alfa.core.brain import mcp_bridge as bridge

    monkeypatch.setattr(bridge, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(bridge, "CACHE_FILE", str(tmp_path / "mcp_tools.json"))
    monkeypatch.setenv("ALFA_MCP_DYNAMIC_TOOLS", "1")

    monkeypatch.setattr(
        "alfa.mcp.client.list_tools_sync",
        lambda server, timeout=30: {
            "status": "success",
            "tools": [
                {
                    "name": "search.icons",
                    "description": "Cari ikon",
                    "input": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                }
            ],
        },
    )

    refreshed = bridge.refresh_tools("lottiefiles")
    assert refreshed["status"] == "success"
    assert refreshed["total_tools"] == 1

    schemas = bridge.build_tool_schemas()
    assert len(schemas) == 1
    name = schemas[0]["function"]["name"]
    assert name.startswith("mcp__lottiefiles__")
    assert bridge.split_dynamic_name(name) is not None

    called: dict = {}

    def fake_call(server, tool, args, timeout=60):
        called.update({"server": server, "tool": tool, "args": args})
        return {"status": "success", "result": {"ok": True}}

    monkeypatch.setattr("alfa.mcp.client.call_tool_sync", fake_call)
    out = json.loads(bridge.call_dynamic(name, {"q": "x"}))
    assert out["status"] == "success"
    assert called["server"] == "lottiefiles"
    assert called["tool"] == "search.icons"
    assert called["args"] == {"q": "x"}


def test_dynamic_mcp_unknown_tool_is_rejected(monkeypatch, tmp_path):
    from alfa.core.brain import mcp_bridge as bridge

    monkeypatch.setattr(bridge, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(bridge, "CACHE_FILE", str(tmp_path / "empty.json"))
    monkeypatch.setenv("ALFA_MCP_DYNAMIC_TOOLS", "1")
    out = json.loads(bridge.call_dynamic("mcp__srv__tidak_ada", {}))
    assert out["status"] == "error"
    assert "cache" in out["message"].lower()


def test_dynamic_mcp_tool_execution_hook(monkeypatch):
    from alfa.core.brain import mcp_bridge, tool_exec

    monkeypatch.setattr(mcp_bridge, "enabled", lambda: True)
    monkeypatch.setattr(
        mcp_bridge,
        "call_dynamic",
        lambda name, args, timeout=45: f'{{"status": "success", "name": "{name}"}}',
    )
    out = tool_exec._execute_tool("mcp__lottiefiles__search_icons", '{"q": "x"}')
    assert '"status": "success"' in out
    assert "mcp__lottiefiles__search_icons" in out


def test_build_openai_tools_includes_cached_mcp_tools(monkeypatch):
    from alfa.core.brain import mcp_bridge, tool_schema

    monkeypatch.setenv("ALFA_MCP_DYNAMIC_TOOLS", "1")
    monkeypatch.setattr(
        mcp_bridge,
        "build_tool_schemas",
        lambda server_id="": [
            {
                "type": "function",
                "function": {
                    "name": "mcp__srv__echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    names = {
        item["function"]["name"] for item in tool_schema.build_openai_tools()
    }
    assert "mcp__srv__echo" in names


# ── 2d. Coding worktree API ───────────────────────────────────────────────────


def test_coding_worktree_routes_registered():
    from alfa.dashboard.app import app

    paths = set(app.openapi().get("paths", {}))
    assert "/api/coding/worktrees" in paths
    assert "/api/coding/worktrees/{task_name}/merge" in paths
    assert "/api/coding/worktrees/{task_name}/rollback" in paths
