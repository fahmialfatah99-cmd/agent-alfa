"""Phase 6 coverage: system management tools — API keys, agents, cron, MCP, audit.

Hermetic: DB SQLite sementara, plugin/swarm/psutil/subprocess di-mock.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from alfa.tools.system import management as mgmt


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "mgmt.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return db_file


@pytest.fixture(autouse=True)
def _no_real_swarm(monkeypatch):
    # Jangan pernah menyentuh proses/layanan nyata dari tes management.
    monkeypatch.setattr(mgmt.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="active", returncode=0))
    yield


# ---------------------------------------------------------------------------
# Plugin dinamis
# ---------------------------------------------------------------------------


def test_self_add_new_tool_success(monkeypatch):
    fake = types.ModuleType("plugins")
    seen = {}
    fake.create_and_register_plugin = lambda name, desc, code, test_kwargs=None: seen.update(
        name=name, desc=desc, code=code, kwargs=test_kwargs
    ) or {"status": "success"}
    monkeypatch.setitem(sys.modules, "plugins", fake)
    out = mgmt.self_add_new_tool("t", "d", "code", '{"a": 1}')
    assert out == {"status": "success"}
    assert seen["kwargs"] == {"a": 1}


def test_self_add_new_tool_invalid_json(monkeypatch):
    fake = types.ModuleType("plugins")
    seen = {}
    fake.create_and_register_plugin = lambda name, desc, code, test_kwargs=None: seen.update(
        kwargs=test_kwargs
    ) or {"status": "success"}
    monkeypatch.setitem(sys.modules, "plugins", fake)
    mgmt.self_add_new_tool("t", "d", "code", "bukan-json")
    assert seen["kwargs"] == {}


def test_self_add_new_tool_error(monkeypatch):
    fake = types.ModuleType("plugins")
    fake.create_and_register_plugin = MagicMock(side_effect=RuntimeError("gagal"))
    monkeypatch.setitem(sys.modules, "plugins", fake)
    out = mgmt.self_add_new_tool("t", "d", "code")
    assert out["status"] == "error"


def test_list_and_delete_dynamic_plugins(monkeypatch):
    fake = types.ModuleType("plugins")
    fake.list_all_plugins = lambda: [{"name": "a"}]
    fake.delete_plugin = lambda name: {"status": "deleted", "name": name}
    monkeypatch.setitem(sys.modules, "plugins", fake)
    assert mgmt.list_dynamic_plugins()["total_plugins"] == 1
    assert mgmt.delete_dynamic_plugin("a")["name"] == "a"


def test_plugin_helpers_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "plugins", None)
    assert mgmt.list_dynamic_plugins()["status"] == "error"
    assert mgmt.delete_dynamic_plugin("a")["status"] == "error"


def test_query_token_usage(monkeypatch):
    monkeypatch.setattr(
        mgmt.database,
        "get_api_usage_summary_sync",
        lambda hours=24: {
            "window_hours": hours,
            "tokens_today": 10,
            "calls_today": 2,
            "total_all_time": 100,
            "per_key": [
                {
                    "key_name": "k",
                    "provider": "gemini",
                    "total_tokens": 10,
                    "calls": 2,
                    "last_used": "now",
                    "extra": "drop",
                }
            ],
            "by_context": [{"ctx": 1}],
        },
    )
    out = mgmt.query_token_usage(6)
    assert out["status"] == "success"
    assert out["per_key"][0]["key_name"] == "k"
    assert "extra" not in out["per_key"][0]


def test_query_token_usage_error(monkeypatch):
    monkeypatch.setattr(
        mgmt.database,
        "get_api_usage_summary_sync",
        MagicMock(side_effect=RuntimeError("db")),
    )
    assert mgmt.query_token_usage()["status"] == "error"


# ---------------------------------------------------------------------------
# Dashboard & LAN bridge
# ---------------------------------------------------------------------------


class _FakeSocket:
    def __init__(self, connect_result=0, ip="192.168.1.20"):
        self.connect_result = connect_result
        self.ip = ip
        self.closed = False

    def settimeout(self, value):
        pass

    def connect_ex(self, addr):
        return self.connect_result

    def connect(self, addr):
        pass

    def getsockname(self):
        return (self.ip, 12345)

    def close(self):
        self.closed = True


def test_open_web_dashboard_active_with_lan(monkeypatch):
    import socket as socket_mod

    fake_sock = _FakeSocket(connect_result=1)
    monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: fake_sock)
    bridge = MagicMock()
    monkeypatch.setattr(mgmt, "_ensure_lan_bridge", bridge)
    out = mgmt.open_web_dashboard(8080)
    assert out["status"] == "success"
    assert "192.168.1.20" in out["network_url"]
    bridge.assert_called_once_with("192.168.1.20", 8080)


def test_open_web_dashboard_starts_service(monkeypatch):
    import socket as socket_mod

    fake_sock = _FakeSocket(connect_result=1, ip="127.0.0.1")
    monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: fake_sock)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="inactive" if len(calls) == 1 else "active")

    monkeypatch.setattr(mgmt.subprocess, "run", fake_run)
    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda s: None)
    out = mgmt.open_web_dashboard(9999)
    assert out["status"] == "success"
    assert any("start" in c for c in calls)


def test_open_web_dashboard_error(monkeypatch):
    monkeypatch.setattr(
        mgmt.subprocess,
        "run",
        MagicMock(side_effect=OSError("systemctl hilang")),
    )
    assert mgmt.open_web_dashboard()["status"] == "error"


def test_ensure_lan_bridge_noop():
    mgmt._ensure_lan_bridge("127.0.0.1", 1)
    mgmt._ensure_lan_bridge("", 1)


def test_ensure_lan_bridge_port_open(monkeypatch):
    import socket as socket_mod

    monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: _FakeSocket(connect_result=0))
    mgmt._ensure_lan_bridge("10.0.0.5", 8080)


def test_ensure_lan_bridge_starts_socat(monkeypatch):
    import socket as socket_mod

    monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: _FakeSocket(connect_result=1))
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/socat")
    popen = MagicMock()
    monkeypatch.setattr(mgmt.subprocess, "Popen", popen)
    mgmt._ensure_lan_bridge("10.0.0.5", 8080)
    popen.assert_called_once()


def test_ensure_lan_bridge_socat_missing(monkeypatch):
    import socket as socket_mod

    monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: _FakeSocket(connect_result=1))
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    popen = MagicMock()
    monkeypatch.setattr(mgmt.subprocess, "Popen", popen)
    mgmt._ensure_lan_bridge("10.0.0.5", 8080)
    popen.assert_not_called()


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def test_manage_api_keys_flow(isolated_db):
    out = mgmt.manage_api_keys("list")
    assert out["status"] == "success"
    before = out["total_keys"]

    assert mgmt.manage_api_keys("add")["status"] == "error"
    added = mgmt.manage_api_keys("add", name="Kunci", provider="groq", api_key="sk-x")
    assert added["status"] == "success"
    key_id = added["key_id"]
    assert key_id

    listed = mgmt.manage_api_keys("list")
    assert listed["total_keys"] == before + 1

    assert mgmt.manage_api_keys("activate")["status"] == "error"
    assert mgmt.manage_api_keys("activate", key_id=key_id)["status"] == "success"

    assert mgmt.manage_api_keys("delete")["status"] == "error"
    assert mgmt.manage_api_keys("delete", key_id=key_id)["status"] == "success"

    assert mgmt.manage_api_keys("nope")["status"] == "error"


def test_manage_api_keys_error(monkeypatch):
    monkeypatch.setattr(
        mgmt.database, "list_api_keys_sync", MagicMock(side_effect=RuntimeError("db"))
    )
    assert mgmt.manage_api_keys("list")["status"] == "error"


# ---------------------------------------------------------------------------
# Custom agents
# ---------------------------------------------------------------------------


def test_manage_custom_agents_flow(isolated_db):
    before = mgmt.manage_custom_agents("list")["total_agents"]
    assert mgmt.manage_custom_agents("add")["status"] == "error"

    added = mgmt.manage_custom_agents(
        "add", name="Riset", role="Researcher", persona="", system_instruction=""
    )
    assert added["status"] == "success"
    agent_id = added["agent_id"]

    listed = mgmt.manage_custom_agents("list")
    assert listed["total_agents"] == before + 1

    assert mgmt.manage_custom_agents("toggle")["status"] == "error"
    assert mgmt.manage_custom_agents("toggle", agent_id=agent_id)["status"] == "success"
    assert mgmt.manage_custom_agents("toggle", agent_id=99999)["status"] == "error"

    assert mgmt.manage_custom_agents("delete")["status"] == "error"
    assert mgmt.manage_custom_agents("delete", agent_id=agent_id)["status"] == "success"

    assert mgmt.manage_custom_agents("nope")["status"] == "error"


def test_manage_custom_agents_error(monkeypatch):
    monkeypatch.setattr(
        mgmt.database, "list_custom_agents_sync", MagicMock(side_effect=RuntimeError("db"))
    )
    assert mgmt.manage_custom_agents("list")["status"] == "error"


# ---------------------------------------------------------------------------
# AI meeting & subagent
# ---------------------------------------------------------------------------


@pytest.fixture
def mode_env(monkeypatch):
    from alfa.bot import mode_commands
    from alfa.core import runtime_ctx

    state = {"mode": "single", "prompt": ""}
    monkeypatch.setattr(mode_commands, "get_telegram_mode_sync", lambda: state["mode"])
    monkeypatch.setattr(runtime_ctx, "get_current_user_prompt", lambda: state["prompt"])
    return state


def test_conduct_ai_meeting_skipped_in_single_mode(mode_env):
    out = mgmt.conduct_ai_meeting("tulis kode")
    assert out["status"] == "skipped"


def test_conduct_ai_meeting_explicit_swarm(mode_env, monkeypatch):
    from alfa.swarm import engine

    async def fake_meeting(topic, participants, rounds, mode, target_folder=""):
        return {
            "meeting_id": 1,
            "title": "Rapat",
            "participants": participants,
            "dialogue_transcript": [1, 2],
            "execution_results": [],
            "vote_tally": {},
            "consensus": "setuju",
            "action_plan": "x",
        }

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", fake_meeting)
    out = mgmt.conduct_ai_meeting("rapat tim", participants="A, B", rounds=9, mode="plan")
    assert out["status"] == "success"
    assert out["total_rounds"] == 3
    assert out["participants"] == ["A", "B"]
    assert out["total_dialogues"] == 2


def test_conduct_ai_meeting_folder_execute(mode_env, monkeypatch):
    from alfa.swarm import engine

    captured = {}

    async def fake_meeting(topic, participants, rounds, mode, target_folder=""):
        captured["mode"] = mode
        return {}

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", fake_meeting)
    out = mgmt.conduct_ai_meeting("rapat tugas", folder="/tmp/x")
    assert out["status"] == "success"
    assert captured["mode"] == "execute"


def test_conduct_ai_meeting_general_advisory(mode_env, monkeypatch):
    from alfa.swarm import engine, live_logger

    monkeypatch.setattr(
        live_logger, "detect_task_intent", lambda topic: {"is_general_advisory": True}
    )

    async def fake_meeting(topic, participants, rounds, mode, target_folder=""):
        return {"mode_used": mode, "rounds": rounds}

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", fake_meeting)
    out = mgmt.conduct_ai_meeting("rapat strategi", rounds=1)
    assert out["mode"] == "plan"
    assert out["total_rounds"] >= 2


@pytest.mark.asyncio
async def test_conduct_ai_meeting_inside_event_loop(mode_env, monkeypatch):
    from alfa.swarm import engine

    async def fake_meeting(*a, **k):
        return {"meeting_id": 2}

    monkeypatch.setattr(engine, "conduct_multi_agent_meeting", fake_meeting)
    out = mgmt.conduct_ai_meeting("rapat tim")
    assert out["status"] == "success"
    assert out["meeting_id"] == 2


def test_conduct_ai_meeting_error(mode_env, monkeypatch):
    from alfa.swarm import engine

    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        MagicMock(side_effect=RuntimeError("swarm down")),
    )
    assert mgmt.conduct_ai_meeting("rapat tim")["status"] == "error"


def test_spawn_background_subagent_skipped(mode_env):
    mode_env["prompt"] = "kerjakan tugas biasa"
    out = mgmt.spawn_background_subagent("riset")
    assert out["status"] == "skipped"


def test_spawn_background_subagent_success(mode_env, monkeypatch):
    from alfa.swarm import subagents

    mode_env["prompt"] = "jalankan di background"
    monkeypatch.setattr(
        subagents,
        "spawn_subagent",
        lambda **kwargs: {"status": "spawned", "task_id": "x", "kwargs": kwargs},
    )
    out = mgmt.spawn_background_subagent("riset", agent_role="Researcher")
    assert out["status"] == "spawned"
    assert out["kwargs"]["role"] == "Researcher"


def test_spawn_background_subagent_error(mode_env, monkeypatch):
    from alfa.swarm import subagents

    mode_env["prompt"] = "jalankan di background"
    monkeypatch.setattr(
        subagents, "spawn_subagent", MagicMock(side_effect=RuntimeError("boom"))
    )
    assert mgmt.spawn_background_subagent("riset")["status"] == "error"


def test_check_subagent_status(monkeypatch):
    monkeypatch.setattr(
        mgmt.database, "get_subagent_task_sync", lambda task_id: None
    )
    assert mgmt.check_subagent_status("x")["status"] == "error"
    monkeypatch.setattr(
        mgmt.database, "get_subagent_task_sync", lambda task_id: {"id": task_id}
    )
    out = mgmt.check_subagent_status("x")
    assert out["status"] == "success"
    assert out["task"]["id"] == "x"
    monkeypatch.setattr(
        mgmt.database,
        "get_subagent_task_sync",
        MagicMock(side_effect=RuntimeError("db")),
    )
    assert mgmt.check_subagent_status("x")["status"] == "error"


# ---------------------------------------------------------------------------
# Cron tasks
# ---------------------------------------------------------------------------


def test_recurring_tasks_flow(isolated_db, monkeypatch):
    from alfa.core import runtime_ctx

    monkeypatch.setattr(runtime_ctx, "get_current_user_id", lambda: 111)
    monkeypatch.setattr(runtime_ctx, "get_current_chat_id", lambda: 222)

    added = mgmt.add_recurring_task("Cuci", "instruksi", interval_minutes=0)
    assert added["status"] == "success"
    job_id = added["job_id"]

    listed = mgmt.list_recurring_tasks()
    assert listed["status"] == "success"
    assert any(j["id"] == job_id for j in listed["tasks"])

    assert mgmt.cancel_recurring_task(job_id)["status"] == "success"
    assert mgmt.cancel_recurring_task(job_id)["status"] == "error"


def test_add_recurring_task_swarm_template(isolated_db, monkeypatch):
    from alfa.core import notification, runtime_ctx

    monkeypatch.setattr(runtime_ctx, "get_current_user_id", lambda: 1)
    monkeypatch.setattr(runtime_ctx, "get_current_chat_id", lambda: 2)
    monkeypatch.setattr(
        notification, "get_swarm_templates", lambda: {"template": "instruksi panjang"}
    )
    added = mgmt.add_recurring_task("Misi", "template", kind="swarm")
    assert added["status"] == "success"
    assert "swarm" in added["message"]


def test_recurring_tasks_errors(monkeypatch):
    from alfa.core import runtime_ctx

    monkeypatch.setattr(runtime_ctx, "get_current_user_id", lambda: 1)
    monkeypatch.setattr(runtime_ctx, "get_current_chat_id", lambda: 2)
    monkeypatch.setattr(
        mgmt.database, "add_cron_job_sync", MagicMock(side_effect=RuntimeError("db"))
    )
    monkeypatch.setattr(
        mgmt.database, "list_cron_jobs_sync", MagicMock(side_effect=RuntimeError("db"))
    )
    monkeypatch.setattr(
        mgmt.database, "delete_cron_job_sync", MagicMock(side_effect=RuntimeError("db"))
    )
    assert mgmt.add_recurring_task("t", "p")["status"] == "error"
    assert mgmt.list_recurring_tasks()["status"] == "error"
    assert mgmt.cancel_recurring_task(1)["status"] == "error"


# ---------------------------------------------------------------------------
# Audit proyek
# ---------------------------------------------------------------------------


def test_audit_project_honesty_clean(tmp_path):
    (tmp_path / "app.py").write_text("print('halo')\n", encoding="utf-8")
    out = mgmt.audit_project_honesty(str(tmp_path))
    assert out["verdict"] == "BERSIH"
    assert out["files_scanned"] == 1


def test_audit_project_honesty_suspects(tmp_path):
    (tmp_path / "api.py").write_text(
        "import random\n# endpoint data\nvalue = random.randint(1, 10)\n", encoding="utf-8"
    )
    (tmp_path / "mock.py").write_text("mock_data = 1\nlorem ipsum\n", encoding="utf-8")
    out = mgmt.audit_project_honesty(str(tmp_path))
    assert out["status"] == "success"
    assert out["verdict"].endswith("TEMUAN")
    labels = {s["pola"] for s in out["suspects"]}
    assert "mock-database" in labels or "lorem-placeholder" in labels


def test_audit_project_honesty_random_not_in_context(tmp_path):
    (tmp_path / "util.py").write_text("import random\nx = random.random()\n", encoding="utf-8")
    out = mgmt.audit_project_honesty(str(tmp_path))
    assert out["verdict"] == "BERSIH"


def test_audit_project_honesty_missing_dir(tmp_path):
    out = mgmt.audit_project_honesty(str(tmp_path / "nope"))
    assert out["status"] == "error"


def test_audit_project_honesty_skips_big_and_binary(tmp_path, monkeypatch):
    big = tmp_path / "big.py"
    big.write_text("x" * 600_000, encoding="utf-8")
    (tmp_path / "ok.py").write_text("halo\n", encoding="utf-8")
    out = mgmt.audit_project_honesty(str(tmp_path))
    assert out["files_scanned"] == 1


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_mcp_connect_status_call(monkeypatch):
    from alfa.mcp import client as mc

    monkeypatch.setattr(mc, "start_connect", lambda server, redirect: {"status": "success", "auth_url": "u"})
    monkeypatch.setattr(mc, "connection_status", lambda server="": {"connected": True})
    monkeypatch.setattr(
        mc, "list_tools_sync", lambda server: {"status": "success", "tools": [{"name": "echo"}]}
    )
    seen = {}
    monkeypatch.setattr(
        mc,
        "call_tool_sync",
        lambda server, tool, args: seen.update(server=server, tool=tool, args=args)
        or {"status": "success"},
    )
    assert mgmt.mcp_connect("lottiefiles")["auth_url"] == "u"
    assert mgmt.mcp_status()["connected"] is True
    assert mgmt.mcp_call("lottiefiles", "echo", '{"a": 1}')["status"] == "success"
    assert seen["args"] == {"a": 1}
    assert (
        mgmt.mcp_call("lottiefiles", "missing", "bukan-json")["status"] == "error"
    )


def test_mcp_tools_helpers(monkeypatch):
    from alfa.core.brain import mcp_bridge

    monkeypatch.setattr(
        mcp_bridge,
        "cached_tools",
        lambda server: [
            {"name": "a", "dynamic_name": "d", "description": "x", "extra": "drop"}
        ],
    )
    monkeypatch.setattr(mcp_bridge, "refresh_tools", lambda server: {"refreshed": server})
    monkeypatch.setattr(mcp_bridge, "refresh_connected", lambda: {"refreshed": "all"})
    out = mgmt.mcp_list_tools("lottiefiles")
    assert out["total_tools"] == 1
    assert "extra" not in out["tools"][0]
    assert mgmt.mcp_list_tools("lottiefiles", refresh=True)["refreshed"] == "lottiefiles"
    assert mgmt.mcp_refresh_tools()["refreshed"] == "all"
    assert mgmt.mcp_refresh_tools("lottiefiles")["refreshed"] == "lottiefiles"


def test_mcp_tools_errors(monkeypatch):
    from alfa.mcp import client as mc

    monkeypatch.setattr(mc, "start_connect", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(mc, "connection_status", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(mc, "list_tools_sync", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(mc, "call_tool_sync", MagicMock(side_effect=RuntimeError("x")))
    from alfa.core.brain import mcp_bridge

    monkeypatch.setattr(mcp_bridge, "cached_tools", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(mcp_bridge, "refresh_tools", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(mcp_bridge, "refresh_connected", MagicMock(side_effect=RuntimeError("x")))
    assert mgmt.mcp_connect()["status"] == "error"
    assert mgmt.mcp_status()["status"] == "error"
    assert mgmt.mcp_call("s", "t")["status"] == "error"
    assert mgmt.mcp_list_tools()["status"] == "error"
    assert mgmt.mcp_refresh_tools()["status"] == "error"


# ---------------------------------------------------------------------------
# Pembersihan memori
# ---------------------------------------------------------------------------


def test_system_clean_memory_and_cache(tmp_path, monkeypatch):
    import tempfile

    fake_psutil = types.ModuleType("psutil")
    fake_psutil.virtual_memory = lambda: SimpleNamespace(
        total=8 * 1024**3, available=4 * 1024**3, used=4 * 1024**3, percent=50
    )

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def memory_info(self):
            return SimpleNamespace(rss=512 * 1024**2)

    fake_psutil.Process = Proc

    class Iter:
        def __init__(self, infos):
            self.infos = infos

        def __iter__(self):
            for info in self.infos:
                yield SimpleNamespace(info=info)

    fake_psutil.process_iter = lambda attrs: Iter(
        [
            {
                "pid": 1,
                "name": "wa",
                "cmdline": ["node", "wa-sheets-bot"],
                "memory_info": SimpleNamespace(rss=200 * 1024**2),
            },
            {
                "pid": 2,
                "name": "chrome",
                "cmdline": ["chrome", "session-bot-session"],
                "memory_info": SimpleNamespace(rss=300 * 1024**2),
            },
            {"pid": 3, "name": "x", "cmdline": None, "memory_info": None},
        ]
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    orphan = tmp_path / "org.chromium.abc"
    orphan.mkdir()
    (tmp_path / "keep").mkdir()
    out = mgmt.system_clean_memory_and_cache(recycle_wa_if_needed=True)
    assert out["status"] == "success"
    assert out["wa_process_count"] == 2
    assert out["wa_sheets_bot_mb"] == 500
    assert out["cleaned_orphaned_tmp_dirs"] == 1
    assert out["wa_recycled"] is False
    assert not orphan.exists()
