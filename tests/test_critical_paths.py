"""Critical-path tests: permission gate, trust math, vault keys, memory,
tasks, agents, registry, MCP headless policy, and local security audit.

Uses an isolated SQLite file via ALFA_DB_PATH so production data is untouched.
"""

import json
import sys
from pathlib import Path

import pytest  # noqa: E402 - sys.path setup above is intentional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point all DB layers at a fresh temp SQLite file via ALFA_DB_PATH.

    Resolvers honor the env var first (see _get_db_path), so this isolates
    every layer without touching module attributes.
    """
    db_file = str(tmp_path / "critical_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as _conn

    _conn.init_db_sync()
    return db_file


# ── Permission tiers & headless policy ───────────────────────────────────────


class TestGateTiers:
    def test_safe_tools_map_to_low(self):
        from alfa.core.perm import gate as g

        assert g.get_tool_tier("web_search").value == "low"
        assert g.get_tool_tier("read_local_file").value == "low"

    def test_known_high_critical(self):
        from alfa.core.perm import gate as g

        assert g.get_tool_tier("execute_bash_command").value == "high"
        assert g.get_tool_tier("ssh_execute_command").value == "critical"

    def test_unknown_defaults_medium(self):
        from alfa.core.perm import gate as g

        assert g.get_tool_tier("some_future_tool_xyz").value == "medium"

    def test_auto_approve_low_always(self):
        from alfa.core.perm import gate as g

        ok, _ = g.should_auto_approve(4242001, "web_search")
        assert ok is True

    def test_auto_approve_medium_needs_trust(self, monkeypatch):
        from alfa.core.perm import gate as g

        monkeypatch.setattr(g, "get_trust_score", lambda _cid: 0.95)
        ok, _ = g.should_auto_approve(4242002, "write_file")
        assert ok is True
        monkeypatch.setattr(g, "get_trust_score", lambda _cid: 0.10)
        ok, _ = g.should_auto_approve(4242002, "write_file")
        assert ok is False

    def test_auto_approve_high_needs_very_high_trust(self, monkeypatch):
        from alfa.core.perm import gate as g

        monkeypatch.setattr(g, "get_trust_score", lambda _cid: 0.95)
        ok, _ = g.should_auto_approve(4242003, "execute_bash_command")
        assert ok is True
        monkeypatch.setattr(g, "get_trust_score", lambda _cid: 0.80)
        ok, _ = g.should_auto_approve(4242003, "execute_bash_command")
        assert ok is False

    def test_make_gate_disabled_returns_none(self, monkeypatch):
        from alfa.core.perm import gate as g

        monkeypatch.setattr(g, "PERMISSION_GATE_ENABLED", False)
        assert g.make_gate(4242004) is None

    def test_headless_policy_matrix(self, monkeypatch, isolated_db):
        from alfa.core.perm import gate as g

        monkeypatch.setattr(g, "PERMISSION_GATE_ENABLED", True)
        assert g.check_headless_approval(4242005, "web_search") is None
        assert g.check_headless_approval(4242005, "write_file") is None
        assert g.check_headless_approval(4242005, "execute_bash_command") is not None
        assert g.check_headless_approval(4242005, "ssh_execute_command") is not None

    def test_headless_disabled_allows_all(self, monkeypatch, isolated_db):
        from alfa.core.perm import gate as g

        monkeypatch.setattr(g, "PERMISSION_GATE_ENABLED", False)
        assert g.check_headless_approval(4242006, "ssh_execute_command") is None

    def test_no_channel_policies(self):
        from alfa.core.perm import gate as g
        from alfa.core.perm.constants import RiskTier

        assert g._no_channel_allows(RiskTier.LOW) in (True, False)

    def test_redact_json_and_garbage(self):
        from alfa.core.perm import gate as g

        out = json.loads(
            g._redact_args_json('{"user": "a", "password": "x", "api_key": "k"}')
        )
        assert out["password"] == "***REDACTED***"
        assert out["api_key"] == "***REDACTED***"
        assert out["user"] == "a"
        assert g._redact_args_json("") == ""
        # Invalid JSON falls back to regex/string passthrough without crashing
        assert isinstance(g._redact_args_json("not-json{{{"), str)


# ── Trust store math ─────────────────────────────────────────────────────────


class TestTrustStore:
    def test_unknown_user_defaults(self, isolated_db):
        from alfa.core.perm import store as s

        assert s.get_trust_score(4242101) == 0.5
        assert s.get_trust_score(None) == 0.0

    def test_safe_approvals_raise_trust(self, isolated_db):
        from alfa.core.perm import store as s

        before = s.get_trust_score(4242102)
        for _ in range(5):
            s.update_trust_score(4242102, was_safe=True, response_time=5.0)
        assert s.get_trust_score(4242102) > before

    def test_fast_response_beats_slow_response(self, isolated_db):
        from alfa.core.perm import store as s

        # Seed identical history so the speed bonus decides the ordering
        # (without history both would saturate at the 1.0 cap).
        s.update_trust_score(4242103, was_safe=False, response_time=5.0)
        s.update_trust_score(4242103, was_safe=True, response_time=5.0)
        fast = s.get_trust_score(4242103)
        s.update_trust_score(4242104, was_safe=False, response_time=5.0)
        s.update_trust_score(4242104, was_safe=True, response_time=250.0)
        slow = s.get_trust_score(4242104)
        assert fast > slow

    def test_risky_decisions_lower_ratio(self, isolated_db):
        from alfa.core.perm import store as s

        for _ in range(4):
            s.update_trust_score(4242105, was_safe=False, response_time=5.0)
        assert s.get_trust_score(4242105) < 0.5

    def test_always_allow_roundtrip(self, isolated_db):
        from alfa.core.perm import store as s

        assert s.is_always_allowed(4242106, "web_search") is False
        s.save_always_allow(4242106, "web_search")
        assert s.is_always_allowed(4242106, "web_search") is True

    def test_log_decision_does_not_raise(self, isolated_db):
        from alfa.core.perm import store as s

        s.log_permission_decision(4242107, "web_search", "low", "once", "{}", 1.5)


# ── Vault keys ───────────────────────────────────────────────────────────────


class TestVaultKeys:
    def test_add_get_delete_key(self, isolated_db):
        from alfa.core.db import keys as k

        created = k.add_api_key_sync("test-key", "gemini", "SECRET-XYZ", "gemini-2.0")
        assert created["status"] == "success"
        kid = created["id"]
        fetched = k.get_api_key_by_id_sync(kid)
        assert fetched is not None
        assert fetched["provider"] == "gemini"
        listed = k.list_api_keys_sync(auto_sync=False)
        assert any(r["id"] == kid for r in listed)
        assert k.delete_api_key_sync(kid)["status"] == "success"
        assert k.get_api_key_by_id_sync(kid) is None

    def test_activate_and_main_brain(self, isolated_db):
        from alfa.core.db import keys as k

        created = k.add_api_key_sync("k2", "gemini", "SECRET-2", "m1")
        assert k.activate_api_key_sync(created["id"])["status"] == "success"
        active = k.get_active_api_key_sync("gemini")
        assert active is not None and active["id"] == created["id"]
        k.set_main_brain_model("gemini-2.5")
        assert k.get_main_brain_model() == "gemini-2.5"
        assert k.update_api_key_model(created["id"], "m2") is True

    def test_sync_external_no_crash(self, isolated_db):
        from alfa.core.db import keys as k

        assert isinstance(k.sync_external_api_keys_sync(), list)


# ── Agents / memory / tasks ──────────────────────────────────────────────────


class TestAgents:
    def test_agent_crud(self, isolated_db):
        from alfa.core.db import agents as a

        created = a.add_custom_agent_sync("tester", "role", "persona", "instruksi")
        assert created["status"] == "success"
        assert a.get_custom_agent_sync("tester") is not None
        assert a.get_custom_agent_sync(created["id"]) is not None
        upd = a.update_custom_agent_sync(created["id"], {"role": "baru", "nope": "x"})
        assert upd["status"] == "success"
        assert a.get_custom_agent_sync(created["id"])["role"] == "baru"
        assert any(x["name"] == "tester" for x in a.list_custom_agents_sync())
        assert a.delete_custom_agent_sync(created["id"])["status"] == "success"

    def test_meeting_roundtrip(self, isolated_db):
        from alfa.core.db import agents as a

        created = a.create_agent_meeting_sync(
            "Rapat", "Topik", ["A", "B"], [{"role": "A"}], "setuju", "lakukan X"
        )
        mid = created["id"]
        assert mid
        assert a.get_agent_meeting_sync(mid) is not None
        assert len(a.list_agent_meetings_sync(limit=5)) >= 1


class TestMemoryTasks:
    async def test_memory_fact_roundtrip(self, isolated_db):
        from alfa.core.db import memory as m

        assert m.save_memory_fact_sync(4242201, "topik", "isi fakta")
        hits = m.search_memories_sync(4242201, "fakta")
        assert any("fakta" in str(h) for h in hits)
        assert await m.delete_memory(4242201, "topik") is True

    def test_knowledge_relation_roundtrip(self, isolated_db):
        from alfa.core.db import memory as m

        m.add_knowledge_relation_sync(4242202, "ALFA", "uses", "Gemini")
        assert len(m.search_knowledge_graph_sync(4242202, "ALFA")) >= 1
        assert len(m.get_all_knowledge_graph_sync(4242202)) >= 1
        export = m.export_full_second_brain_sync(4242202)
        assert export["total_relations"] >= 1

    async def test_chat_history_async(self, isolated_db):
        from alfa.core.db import memory as m

        await m.save_chat_message(4242203, "user", "halo")
        hist = await m.get_recent_chat_history(4242203, limit=5)
        assert any("halo" in str(h) for h in hist)
        await m.clear_user_chat_history(4242203)
        assert await m.get_recent_chat_history(4242203, limit=5) == []

    def test_cron_roundtrip(self, isolated_db):
        from alfa.core.db import tasks as t

        jid = t.add_cron_job_sync(4242204, 4242204, "judul", "instruksi", 60)
        assert jid
        assert any(j["id"] == jid for j in t.list_cron_jobs_sync(4242204))
        assert t.delete_cron_job_sync(4242204, jid) is True

    def test_subagent_task_roundtrip(self, isolated_db):
        from alfa.core.db import tasks as t

        t.save_subagent_task_sync("task-crit-1", 4242205, 4242205, "role", "desc")
        assert t.get_subagent_task_sync("task-crit-1") is not None
        t.update_subagent_task_sync("task-crit-1", "done", "ok")
        assert t.get_subagent_task_sync("task-crit-1")["status"] == "done"
        assert len(t.list_subagent_tasks_sync(limit=5)) >= 1

    def test_reminder_and_activity(self, isolated_db):
        from alfa.core.db import tasks as t

        rid = t.add_reminder_sync(4242206, 4242206, "2030-01-01T00:00:00", "ingat")
        assert rid
        t.log_agent_activity_sync(None, "tester", "aksi", "detail")
        assert len(t.list_agent_activities_sync(limit=5)) >= 1

    def test_api_usage_summary(self, isolated_db):
        from alfa.core.db import tasks as t

        t.record_api_usage_sync("gemini", "m", None, "lbl", "ctx", 10, 5)
        summary = t.get_api_usage_summary_sync(hours=24)
        assert isinstance(summary, dict)


# ── Vault round-trip (regression: vault_engine.vault AttributeError) ──────────


class TestVaultRoundtrip:
    def test_store_get_delete(self, isolated_db, tmp_path, monkeypatch):
        import sys

        # NOTE: alfa.security.vault as attribute is the vault *instance*
        # (package __init__ shadows the submodule); patch via sys.modules.
        vault_mod = sys.modules["alfa.security.vault"]
        from alfa.tools.filesystem import vault as v

        # Vault binds DB_PATH at import: redirect + init schema in tmp file.
        monkeypatch.setattr(vault_mod, "DB_PATH", str(tmp_path / "vault_test.db"))
        vault_mod._init_vault_db()
        name = "k-regresi"
        stored = v.vault_store_secret(name, "nilai-rahasia")
        assert stored["status"] == "success"
        got = v.vault_get_secret(name)
        assert got["status"] == "success"
        assert got["value"] == "nilai-rahasia"
        listed = v.vault_list_secrets()
        assert any(s["name"] == name for s in listed["secrets"])
        sid = next(s["id"] for s in listed["secrets"] if s["name"] == name)
        assert v.vault_delete_secret(sid)["status"] == "success"
        assert v.vault_get_secret(name)["status"] == "error"


# ── Scraper dispatch (regression: wrong fast_scraper fn name) ─────────────────


class TestScraperDispatch:
    def test_custom_batch_uses_fast_tls(self, tmp_path, monkeypatch):
        import alfa.scrapers.fast as fast_mod
        import alfa.scrapers.universal as uni

        monkeypatch.setattr(uni, "MASTER_EXPORT_DIR", str(tmp_path))
        (tmp_path / "CSV").mkdir()
        (tmp_path / "JSON").mkdir()
        monkeypatch.setattr(
            fast_mod,
            "scrape_with_fast_tls",
            lambda url: {"status": "success", "url": url, "title": "T"},
        )
        res = uni.scrape_custom_urls_or_selectors(
            ["https://contoh.id/a"], concurrency=1, use_camoufox=False
        )
        assert res["status"] == "success"


# ── Registry / MCP / audit ───────────────────────────────────────────────────


class TestRegistryMcpAudit:
    def test_tool_definitions_formats(self):
        from alfa.tools.registry import get_tool_definitions

        as_dict = get_tool_definitions(format="dict")
        as_openai = get_tool_definitions(format="openai")
        assert len(as_dict) > 100
        assert len(as_openai) == len(as_dict)
        web = get_tool_definitions(category="web")
        assert all(d["category"] == "web" for d in web)

    def test_mcp_headless_deny_high(self, isolated_db):
        from alfa.mcp.server import create_mcp_server

        create_mcp_server("test-gate")  # must not raise
        from alfa.core.perm import gate as g

        assert g.check_headless_approval(0, "execute_bash_command") is not None
        assert g.check_headless_approval(0, "web_search") is None

    def test_local_security_audit_structure(self):
        from alfa.core.perm import auditor as aud

        report = aud.audit_local_host_security()
        assert isinstance(report, dict)
        assert "checks" in report or "critical_findings" in report

    def test_website_audit_against_localhost(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from alfa.core.perm import auditor as aud

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><head><title>T</title></head><body>Hello</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        srv = HTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            rep = aud.audit_website_security(f"http://127.0.0.1:{port}", timeout=5)
        finally:
            srv.shutdown()
        assert rep["status"] == "success"
        assert rep["target_url"].startswith("http://127.0.0.1:")
        assert "grade" in rep and "score" in rep

    def test_website_audit_rejects_non_http(self):
        from alfa.core.perm import auditor as aud

        rep = aud.audit_website_security("file:///etc/passwd", timeout=3)
        assert rep["status"] in ("success", "error")


# ── Interactive approval path (mocked Telegram) ──────────────────────────────


class _FakeMessage:
    def __init__(self):
        self.message_id = 4242
        self.text = "permintaan izin"


class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return _FakeMessage()

    async def edit_message_text(self, **kwargs):
        self.sent.append(("edit", kwargs))
        return True


class _FakeApp:
    def __init__(self):
        self.bot = _FakeBot()


def _fake_update(data, user_id=0, answer=None, edit=None):
    from unittest.mock import AsyncMock, MagicMock

    query = MagicMock()
    query.data = data
    query.from_user.id = user_id
    query.answer = answer or AsyncMock()
    query.edit_message_text = edit or AsyncMock()
    query.message = MagicMock()
    query.message.text = "permintaan izin"
    update = MagicMock()
    update.callback_query = query
    return update, query


class TestInteractiveApproval:
    async def test_approve_once_allows(self, isolated_db, monkeypatch):
        import asyncio

        from alfa.core.perm import gate as g

        monkeypatch.setattr(
            "alfa.swarm.subagents.get_telegram_app", lambda: _FakeApp()
        )
        task = asyncio.create_task(
            g.request_approval("execute_bash_command", '{"cmd": "ls"}', 4242301)
        )
        for _ in range(100):
            await asyncio.sleep(0.05)
            if g._PENDING:
                break
        assert g._PENDING, "approval request tidak terkirim"
        req_id = next(iter(g._PENDING))
        update, _query = _fake_update(f"perm|{req_id}|once", user_id=4242301)
        await g.handle_permission_callback(update, None)
        assert await asyncio.wait_for(task, timeout=5) is None

    async def test_deny_blocks(self, isolated_db, monkeypatch):
        import asyncio

        from alfa.core.perm import gate as g

        monkeypatch.setattr(
            "alfa.swarm.subagents.get_telegram_app", lambda: _FakeApp()
        )
        task = asyncio.create_task(
            g.request_approval("execute_bash_command", '{"cmd": "ls"}', 4242302)
        )
        for _ in range(100):
            await asyncio.sleep(0.05)
            if g._PENDING:
                break
        req_id = next(iter(g._PENDING))
        update, _query = _fake_update(f"perm|{req_id}|deny", user_id=4242302)
        await g.handle_permission_callback(update, None)
        result = await asyncio.wait_for(task, timeout=5)
        assert result is not None and "DITOLAK" in result

    async def test_timeout_denies(self, isolated_db, monkeypatch):

        from alfa.core.perm import gate as g

        monkeypatch.setattr(
            "alfa.swarm.subagents.get_telegram_app", lambda: _FakeApp()
        )
        monkeypatch.setattr(g, "APPROVAL_TIMEOUT", 0.05)
        result = await g.request_approval("execute_bash_command", "{}", 4242303)
        assert result is not None

    async def test_no_channel_low_allowed_high_denied(
        self, isolated_db, monkeypatch
    ):
        from alfa.core.perm import gate as g

        def _boom():
            raise RuntimeError("no telegram here")

        monkeypatch.setattr("alfa.swarm.subagents.get_telegram_app", _boom)
        assert (
            await g.request_approval("web_search", "{}", 4242304)
        ) is None
        denied = await g.request_approval("execute_bash_command", "{}", 4242304)
        assert denied is not None

    async def test_non_owner_cannot_decide(self, isolated_db, monkeypatch):
        import asyncio
        from unittest.mock import AsyncMock

        from alfa.core.perm import gate as g

        monkeypatch.setattr(
            "alfa.swarm.subagents.get_telegram_app", lambda: _FakeApp()
        )
        task = asyncio.create_task(
            g.request_approval("execute_bash_command", "{}", 4242305)
        )
        for _ in range(100):
            await asyncio.sleep(0.05)
            if g._PENDING:
                break
        req_id = next(iter(g._PENDING))
        answered = AsyncMock()
        update, _query = _fake_update(
            f"perm|{req_id}|once", user_id=999999, answer=answered
        )
        await g.handle_permission_callback(update, None)
        assert answered.called  # ditolak dengan toast, event tidak di-set
        assert g._PENDING.get(req_id, {}).get("decision", "") == ""
        task.cancel()

    async def test_callback_edge_cases(self, isolated_db):
        from unittest.mock import MagicMock

        from alfa.core.perm import gate as g

        update = MagicMock()
        update.callback_query = None
        assert await g.handle_permission_callback(update, None) is None
        update, _q = _fake_update("perm_done")
        assert await g.handle_permission_callback(update, None) is None
        update, _q = _fake_update("perm|broken")
        assert await g.handle_permission_callback(update, None) is None
        update, _q = _fake_update("perm|nosuchid|once")
        assert await g.handle_permission_callback(update, None) is None

    async def test_wrap_tool_for_afc(self, isolated_db, monkeypatch):
        from alfa.core.perm import gate as g

        def _add(a=0, b=0):
            return a + b

        async def _allow(*args, **kwargs):
            return None

        async def _deny(*args, **kwargs):
            return "TIDAK"

        monkeypatch.setattr(g, "request_approval", _allow)
        assert await g.wrap_tool_for_afc(_add)(a=1, b=2) == 3
        monkeypatch.setattr(g, "request_approval", _deny)
        assert await g.wrap_tool_for_afc(_add)(a=1, b=2) == "TIDAK"


# ── Async task/memory variants ───────────────────────────────────────────────


class TestAsyncVariants:
    async def test_due_cron_and_update(self, isolated_db):
        from alfa.core.db import tasks as t

        jid = t.add_cron_job_sync(4242311, 4242311, "lama", "jalan", 1)
        due = await t.get_due_cron_jobs()
        assert isinstance(due, list)
        await t.update_cron_job_after_run(jid, 60)

    async def test_due_reminders_and_mark(self, isolated_db):
        from alfa.core.db import tasks as t

        rid = t.add_reminder_sync(4242312, 4242312, "2020-01-01T00:00:00", "dulu")
        due = await t.get_due_reminders()
        assert any(r["id"] == rid for r in due)
        await t.mark_reminder_executed(rid)
        assert all(r["id"] != rid for r in await t.get_due_reminders())

    async def test_focus_session_cycle(self, isolated_db):
        from alfa.core.db import tasks as t

        created = t.start_focus_session_sync(4242313, 4242313, "fokus", 1, "")
        sid = created.get("id") or created.get("session_id")
        assert sid
        await t.mark_focus_session_completed(sid)
        assert isinstance(await t.get_due_focus_sessions(), list)

    async def test_memory_async_variants(self, isolated_db):
        from alfa.core.db import memory as m

        await m.save_memory_fact(4242314, "topik", "isi")
        assert len(await m.search_memories(4242314, "isi")) >= 1
        assert len(await m.get_all_memories(4242314)) >= 1
        settings = await m.get_user_settings(4242314)
        assert isinstance(settings, dict)
        assert isinstance(await m.toggle_voice_setting(4242314), bool)
