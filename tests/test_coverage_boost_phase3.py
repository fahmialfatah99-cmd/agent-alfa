"""Fast, hermetic unit tests for Telegram bot commands, menus, and progress reporter (Phase 3 Coverage Boost)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from telegram.error import BadRequest, RetryAfter


class _DummyBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.photos: list[dict[str, Any]] = []
        self.docs: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=len(self.sent) + 100)

    async def edit_message_text(self, **kwargs: Any) -> Any:
        self.edited.append(kwargs)
        return SimpleNamespace(message_id=kwargs.get("message_id", 101))

    async def send_photo(self, **kwargs: Any) -> Any:
        self.photos.append(kwargs)
        return SimpleNamespace(message_id=201)

    async def send_document(self, **kwargs: Any) -> Any:
        self.docs.append(kwargs)
        return SimpleNamespace(message_id=301)


class _DummyQuery:
    def __init__(self, data: str = "") -> None:
        self.data = data
        self.answered = False
        self.edited: list[dict[str, Any]] = []
        self.fail_mode: str | None = None

    async def answer(self, *args: Any, **kwargs: Any) -> None:
        self.answered = True

    async def edit_message_text(self, **kwargs: Any) -> None:
        if self.fail_mode == "not_modified":
            msg = "Message is not modified"
            raise BadRequest(msg)
        if self.fail_mode == "bad_request":
            msg = "Can't parse entities"
            raise BadRequest(msg)
        if self.fail_mode == "retry":
            raise RetryAfter(2)
        if self.fail_mode == "runtime":
            raise RuntimeError("boom")
        self.edited.append(kwargs)


def _make_update_ctx(
    user_id: int = 123456789,
    chat_id: int = 123456789,
    args: list[str] | None = None,
    callback_data: str | None = None,
) -> tuple[Any, Any, _DummyBot, _DummyQuery | None]:
    bot = _DummyBot()
    query = _DummyQuery(callback_data) if callback_data is not None else None
    replies: list[str] = []

    async def _reply_text(text: str, **kwargs: Any) -> None:
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(
            id=user_id, first_name="Tester", full_name="Tester Alfa"
        ),
        effective_chat=SimpleNamespace(id=chat_id),
        message=SimpleNamespace(reply_text=_reply_text, replies=replies),
        callback_query=query,
    )
    context = SimpleNamespace(bot=bot, args=args or [])
    return update, context, bot, query


@pytest.mark.asyncio
async def test_mode_commands_full_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    from alfa.bot import mode_commands as mc
    from alfa.core import database

    monkeypatch.setattr(mc, "_is_authorized", lambda uid: uid == 123456789)
    sent_messages: list[str] = []

    async def _fake_send(ctx: Any, cid: int, text: str, **kwargs: Any) -> None:
        sent_messages.append(str(text))

    monkeypatch.setattr(mc, "safe_send_message", _fake_send)

    # 1. Mode sync helpers
    mc._MODE_CACHE["ts"] = 0.0
    assert mc.get_telegram_mode_sync() in ("single", "swarm")
    assert mc.set_telegram_mode_sync("swarm") == "swarm"
    assert mc.get_telegram_mode_sync() == "swarm"
    mc._MODE_CACHE["ts"] = 0.0
    assert mc._read_mode_from_db() == "swarm"
    assert mc.set_telegram_mode_sync("single") == "single"
    with pytest.raises(ValueError):
        mc.set_telegram_mode_sync("invalid_mode")

    # 2. /mode command branches
    for args in ([], ["status"], ["single"], ["swarm"], ["unknown"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await mc.mode_command(u, c)
    # Unauthorized
    u_unauth, c_unauth, _, _ = _make_update_ctx(user_id=999)
    await mc.mode_command(u_unauth, c_unauth)

    # 3. /single command branches
    u, c, _, _ = _make_update_ctx(args=[])
    await mc.single_command(u, c)

    monkeypatch.setattr(mc, "_run_single_turn", lambda uid, p, cid: asyncio.sleep(0, result="OK single"))
    u, c, _, _ = _make_update_ctx(args=["halo", "dunia"])
    await mc.single_command(u, c)

    async def _fail_turn(uid: int, p: str, cid: int) -> str:
        raise RuntimeError("single_error")

    monkeypatch.setattr(mc, "_run_single_turn", _fail_turn)
    u, c, _, _ = _make_update_ctx(args=["gagal"])
    await mc.single_command(u, c)

    # 4. format_swarm_result
    s_txt, f_txt, files = mc.format_swarm_result(
        {
            "execution_results": [
                {
                    "agent_name": "Coder",
                    "role": "Dev",
                    "tool_used": "bash",
                    "duration_ms": 120,
                    "execution_summary": "Done",
                    "deliverable_file": __file__,
                }
            ],
            "consensus": "Berhasil",
            "session_id": "s1",
        }
    )
    assert "Coder" in s_txt and "Berhasil" in f_txt and __file__ in files
    s_empty, _, _ = mc.format_swarm_result({})
    assert "tanpa langkah" in s_empty

    # 5. /cancel, /status, /tools, /tugas
    for fn in (mc.cancel_command, mc.status_command, mc.tools_command, mc.tugas_command):
        u, c, _, _ = _make_update_ctx()
        await fn(u, c)

    # 6. /persona command & callbacks
    monkeypatch.setattr(
        database,
        "list_custom_agents_sync",
        lambda: [
            {
                "id": 1,
                "name": "AlphaBot",
                "role": "Researcher",
                "persona": "Research specialist",
                "system_instruction": "Be precise",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "avatar_emoji": "🔬",
                "is_enabled": 1,
            }
        ],
    )
    for args in ([], ["list"], ["AlphaBot"], ["1"], ["tidak_ada"], ["reset"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await mc.persona_command(u, c)

    for cb in ("px|list", "px|set|1", "px|reset", "other|1"):
        u, c, _, _ = _make_update_ctx(callback_data=cb)
        await mc.handle_persona_callback(u, c)

    # 7. /pipeline command branches
    from alfa.pipelines import engine as pipe_eng

    monkeypatch.setattr(
        pipe_eng,
        "list_pipelines",
        lambda: [{"id": "p1", "name": "Pipe 1", "steps": 2, "description": "Desc"}],
    )
    monkeypatch.setattr(
        pipe_eng,
        "load_pipeline",
        lambda pid: {
            "id": pid,
            "name": "Pipe 1",
            "description": "Desc",
            "vars": {"k": "v"},
            "steps": [{"id": "s1", "type": "tool", "tool": "ping", "depends_on": ["s0"]}],
        },
    )

    async def _fake_run_pipe(pid: str, overrides: Any = None) -> dict[str, Any]:
        return {"status": "success", "trace": [{"status": "ok"}]}

    monkeypatch.setattr(pipe_eng, "run_pipeline", _fake_run_pipe)

    for args in (
        [],
        ["list"],
        ["show"],
        ["show", "p1"],
        ["run"],
        ["run", "p1", "a=1"],
        ["other"],
    ):
        u, c, _, _ = _make_update_ctx(args=args)
        await mc.pipeline_command(u, c)

    assert len(sent_messages) >= 15


@pytest.mark.asyncio
async def test_basic_commands_full_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    from alfa.bot import basic_commands as bc
    from alfa.core import database, rate_limiter

    monkeypatch.setattr(bc, "_is_authorized", lambda uid: uid == 123456789)
    sent: list[str] = []

    async def _fake_send(ctx: Any, cid: int, text: str, **kwargs: Any) -> None:
        sent.append(str(text))

    monkeypatch.setattr(bc, "safe_send_message", _fake_send)
    monkeypatch.setattr(
        bc,
        "get_system_stats",
        lambda: {
            "cpu": "10%",
            "ram": "40%",
            "swap": "0%",
            "disk": "50%",
            "battery": "99%",
            "ip_addresses": "127.0.0.1",
            "uptime": "1h",
            "top_ram_processes": ["python"],
            "top_cpu_processes": ["python"],
        },
    )

    # Unauthorized /start & /cron
    u_un, c_un, _, _ = _make_update_ctx(user_id=999)
    await bc.start_command(u_un, c_un)
    await bc.cron_command(u_un, c_un)

    # Authorized commands
    for fn in (
        bc.start_command,
        bc.menu_command,
        bc.cekagen_command,
        bc.stats_command,
        bc.memory_command,
        bc.clear_command,
        bc.id_command,
        bc.voice_command,
        bc.cron_command,
        bc.proactive_command,
    ):
        u, c, _, _ = _make_update_ctx()
        await fn(u, c)

    # Memory with items & Cron with items
    await database.save_memory_fact(123456789, "server_port", "8080", "fact")
    monkeypatch.setattr(
        database,
        "list_cron_jobs_sync",
        lambda uid: [
            {
                "id": 1,
                "title": "Check CPU",
                "is_active": 1,
                "kind": "single",
                "interval_minutes": 30,
                "prompt_instruction": "check cpu",
                "next_run": "2026-10-19 10:00",
            }
        ],
    )
    u, c, _, _ = _make_update_ctx()
    await bc.memory_command(u, c)
    await bc.cron_command(u, c)

    # /budget command branches
    for args in ([], ["set", "invalid", "x"], ["set", "500000", "200"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await bc.budget_command(u, c)

    monkeypatch.setattr(
        rate_limiter,
        "get_budget_report",
        lambda uid: {
            "status": "ok",
            "pct": 0.95,
            "exceeded": False,
            "warn": True,
            "total_tokens": 95000,
            "budget_limit": 100000,
            "remaining": 5000,
            "total_calls": 19,
            "call_limit": 20,
            "by_key": [{"key_label": "gem-1", "total_tokens": 95000, "calls": 19}],
        },
    )
    u, c, _, _ = _make_update_ctx()
    await bc.budget_command(u, c)
    assert len(sent) >= 12


@pytest.mark.asyncio
async def test_wa_menu_and_advanced_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from alfa import tools
    from alfa.bot import advanced_commands as ac
    from alfa.bot import wa_menu as wm

    monkeypatch.setattr(ac, "_is_authorized", lambda uid: uid == 123456789)
    monkeypatch.setattr(wm, "_is_authorized", lambda uid: uid == 123456789)

    sent: list[str] = []

    async def _fake_send(ctx: Any, cid: int, text: str, **kwargs: Any) -> None:
        sent.append(str(text))

    monkeypatch.setattr(ac, "safe_send_message", _fake_send)

    # Stub WA & site tools on alfa.tools
    monkeypatch.setattr(
        tools,
        "manage_wa_sheets_bot",
        lambda action="status": {"is_running": True, "enabled_on_boot": True},
    )
    monkeypatch.setattr(
        tools,
        "open_web_dashboard",
        lambda port=8080: {
            "local_url": "http://localhost:8080",
            "network_url": "http://192.168.1.10:8080",
        },
    )
    monkeypatch.setattr(
        tools,
        "wa_get_me",
        lambda: {"status": "success", "me": {"pushname": "AlfaOwner"}},
    )
    monkeypatch.setattr(
        tools,
        "wa_get_chats",
        lambda limit=10: {
            "status": "success",
            "chats": [
                {
                    "id": "123@c.us",
                    "name": "Budi",
                    "is_group": False,
                    "unread": 2,
                    "last_preview": "Halo",
                    "last_from_me": False,
                    "last_ts": 1700000000,
                }
            ],
        },
    )
    monkeypatch.setattr(
        tools,
        "wa_get_messages",
        lambda chat="", limit=15: {
            "status": "success",
            "chat_name": "Budi",
            "messages": [
                {"from_me": False, "sender": "Budi", "body": "Pesan 1", "ts": 1700000000}
            ],
        },
    )
    monkeypatch.setattr(
        tools,
        "wa_get_incoming",
        lambda limit=10: {
            "status": "success",
            "incoming": [
                {
                    "msg_type": "chat",
                    "is_group": True,
                    "from_me": False,
                    "chat_name": "Grup Kerja",
                    "sender_name": "Andi",
                    "body": "Laporan masuk",
                    "ts": "2026-10-14T14:16:22Z",
                }
            ],
        },
    )
    monkeypatch.setattr(
        tools,
        "wa_send_message",
        lambda to="", message="": {"status": "success", "to": to},
    )
    monkeypatch.setattr(
        tools,
        "wa_list_formats",
        lambda: {
            "status": "success",
            "formats": [{"name": "Stok", "enabled": True, "keywords": ["stok"], "tab": "StokTab"}],
        },
    )
    monkeypatch.setattr(
        tools,
        "wa_toggle_format",
        lambda name="", enabled=True: {"status": "success"},
    )
    monkeypatch.setattr(
        tools,
        "wa_add_format",
        lambda name="", keywords="", tab="": {"status": "success"},
    )
    monkeypatch.setattr(
        tools,
        "wa_delete_format",
        lambda name="": {"status": "success"},
    )
    monkeypatch.setattr(
        tools,
        "wa_get_records",
        lambda report_format="", limit=10: {
            "status": "success",
            "records": [
                {
                    "synced_to_sheets": True,
                    "format_name": "Stok",
                    "timestamp": "10:00",
                    "sender": "Andi",
                    "group": "Gudang",
                    "body": "Stok aman",
                }
            ],
        },
    )
    monkeypatch.setattr(
        tools,
        "wa_search_messages",
        lambda query="": {
            "status": "success",
            "hits": [{"chat": "Budi", "ts": 1700000000, "from_me": False, "sender": "Budi", "body": query}],
        },
    )
    monkeypatch.setattr(
        tools,
        "serve_site",
        lambda action="status", slug="": {
            "status": "ok",
            "title": "Demo Site",
            "slug": slug or "demo",
            "sites": [
                {
                    "slug": "demo",
                    "title": "Demo Site",
                    "backend_on": True,
                    "frontend_on": False,
                    "backend_port": 9001,
                    "stack": {"has_backend": True},
                },
                {
                    "slug": "static_doc",
                    "title": "Static Doc",
                    "backend_on": False,
                    "frontend_on": False,
                    "stack": {},
                },
            ],
            "logs": {"backend": "line1\nline2"},
            "note": "cli only",
        },
    )

    # 1. wa_menu callbacks
    for cb in (
        "wx|home",
        "wx|chats|0",
        "wx|chat|0",
        "wx|chat|99",
        "wx|in|0",
        "wx|fmt",
        "wx|ft|0",
        "wx|rep|0|0",
        "wx|send",
        "wx|noop",
    ):
        u, c, _, _ = _make_update_ctx(callback_data=cb)
        assert await wm.handle_wa_callback(u, c) is True

    # 2. advanced_commands: /wa, /sites, st|* callbacks
    u, c, _, _ = _make_update_ctx()
    await ac.wa_command(u, c)
    await ac.sites_command(u, c)

    for cb in ("st|list", "st|view|0", "st|view|1", "st|start|0", "st|stop|0", "st|logs|0", "st|view|99"):
        u, c, _, _ = _make_update_ctx(callback_data=cb)
        assert await ac.handle_sites_callback(u, c) is True

    # 3. /wachat, /wamasuk, /wakirim, /waformat, /wareport, /wacari, /dashboard, /keys, /agents
    for args in ([], ["5"], ["Budi"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.wachat_command(u, c)

    u, c, _, _ = _make_update_ctx(args=["5"])
    await ac.wamasuk_command(u, c)

    for args in ([], ["08123", "Halo", "tes"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.wakirim_command(u, c)

    for args in (
        [],
        ["list"],
        ["on", "Stok"],
        ["off", "Stok"],
        ["add", "Order", "|", "order,beli", "|", "OrderTab"],
        ["add"],
        ["del", "Stok"],
        ["invalid"],
    ):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.waformat_command(u, c)

    for args in ([], ["Stok", "5"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.wareport_command(u, c)

    for args in ([], ["stok"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.wacari_command(u, c)

    for fn in (ac.dashboard_command, ac.keys_command, ac.agents_command):
        u, c, _, _ = _make_update_ctx()
        await fn(u, c)

    # 4. /rapat, /swarm, /resume_swarm with stubbed swarm_engine
    from alfa.swarm import engine as swarm_engine

    deliverable = tmp_path / "out.txt"
    deliverable.write_text("hasil deliverable", encoding="utf-8")

    async def _fake_meeting(topic: str, rounds: int = 1, mode: str = "execute") -> dict[str, Any]:
        return {
            "meeting_id": 42,
            "consensus": "Konsensus tercapai",
            "action_plan": "Langkah 1, Langkah 2",
            "dialogue_transcript": [
                {"agent_name": "Alpha", "role": "Lead", "message": "Diskusi 1"}
            ],
            "execution_results": [
                {
                    "agent_name": "Alpha",
                    "role": "Lead",
                    "tool_used": "bash",
                    "duration_ms": 50,
                    "execution_summary": "Sukses",
                    "deliverable_file": str(deliverable),
                }
            ],
        }

    async def _fake_resume(session_id: str) -> dict[str, Any]:
        return {
            "status": "success",
            "consensus": "Lanjutan sukses",
            "execution_results": [
                {
                    "agent_name": "Alpha",
                    "role": "Lead",
                    "tool_used": "bash",
                    "execution_summary": "Resumed ok",
                }
            ],
        }

    monkeypatch.setattr(swarm_engine, "conduct_multi_agent_meeting", _fake_meeting)
    monkeypatch.setattr(swarm_engine, "resume_swarm_session", _fake_resume)

    for args in ([], ["Arsitektur", "Baru"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.rapat_command(u, c)

    for args in (
        [],
        ["model"],
        ["model", "1"],
        ["model", "1", "gemini", "gemini-2.5-flash"],
        ["model", "tidak_ada"],
        ["status"],
        ["cancel"],
        ["single"],
        ["swarm"],
        ["template"],
        ["template", "tidak_ada"],
        ["template", "audit-server"],
        ["Kerjakan", "audit"],
    ):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.swarm_command(u, c)

    for args in ([], ["sess_123"]):
        u, c, _, _ = _make_update_ctx(args=args)
        await ac.resume_swarm_command(u, c)


@pytest.mark.asyncio
async def test_swarm_progress_reporter_unit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from alfa.bot.progress import SwarmProgressReporter, _short

    assert _short("halo   dunia", 20) == "halo dunia"
    assert len(_short("x" * 50, 10)) == 10

    feed_file = tmp_path / "live_meeting_feed.jsonl"
    feed_file.write_text("", encoding="utf-8")

    _, ctx, bot, _ = _make_update_ctx()
    rep = SwarmProgressReporter(
        ctx, 123, "Topik Uji Swarm", poll_interval=0.02, min_edit_interval=0.0
    )
    monkeypatch.setattr(rep, "_feed_path", lambda: str(feed_file))

    await rep.start()
    assert rep.message_id is not None

    # Write feed events of all tags
    events = [
        {"tag": "PLAN", "text": "🗂️ Agent1: analisis kode"},
        {"tag": "EXEC", "text": "⚙️ Agent1 mulai eksekusi tool"},
        {"tag": "VERIFY", "text": "✅ PASS — Agent1 (10ms)"},
        {"tag": "VERIFY", "text": "❌ FAIL — Agent2 (error)"},
        {"tag": "FILE", "text": "out.txt disimpan"},
        {"tag": "QA", "text": "Verifikasi QA"},
        {"tag": "DIALOG", "text": "Agent1 berbicara"},
        {"tag": "DONE", "text": "Misi selesai"},
    ]
    with open(feed_file, "a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    for entry in rep._read_new():
        rep._ingest(entry)

    rendered = rep._render()
    assert "Agent1" in rendered
    assert rep._finished is True

    await rep.stop("Catatan akhir")
    assert len(bot.edited) >= 1


def test_dashboard_system_and_swarm_routes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import importlib

    from fastapi.testclient import TestClient

    from alfa import tools
    from alfa.scrapers import universal as univ_scraper
    from alfa.swarm import engine as swarm_engine

    dash_mod = importlib.import_module("alfa.dashboard.app")
    client = TestClient(dash_mod.app)

    # Stub heavy external/scraper/swarm calls
    monkeypatch.setattr(
        univ_scraper,
        "scrape_universal_keyword",
        lambda query="", category="", limit=10: {"status": "success", "items": []},
    )
    monkeypatch.setattr(
        univ_scraper,
        "scrape_custom_urls_or_selectors",
        lambda urls=None, concurrency=5, use_camoufox=False: {"status": "success", "items": []},
    )
    monkeypatch.setattr(
        univ_scraper,
        "list_all_scrape_batches",
        lambda limit=15: [{"batch_id": "b1", "count": 2}],
    )
    monkeypatch.setattr(
        tools,
        "crawl4ai_web_crawler",
        lambda url="": {"status": "success", "markdown": "# Crawl4AI"},
    )
    monkeypatch.setattr(
        tools,
        "scrapling_stealth_fetch",
        lambda url="", css_selector="", extract_type="": {"status": "success", "data": ["Line 1"]},
    )
    monkeypatch.setattr(
        tools,
        "markitdown_convert_document",
        lambda source_path_or_url="": {"status": "success", "markdown_snippet": "# MarkItDown"},
    )
    monkeypatch.setattr(
        tools,
        "scrapy_spider_quick_scrape",
        lambda url="", item_selectors_json="": {"status": "success", "extracted_fields": {"k": "v"}},
    )
    monkeypatch.setattr(
        tools,
        "crawlee_web_scraper",
        lambda start_urls="", max_requests=3: {
            "status": "success",
            "pages": [{"title": "T", "url": start_urls, "text_summary": "S"}],
        },
    )
    monkeypatch.setattr(
        tools,
        "firecrawl_scrape_and_crawl",
        lambda url="": {"status": "success", "markdown": "# Firecrawl"},
    )

    async def _fake_meeting(**kwargs: Any) -> dict[str, Any]:
        return {"status": "success", "meeting_id": 1, "consensus": "OK"}

    monkeypatch.setattr(swarm_engine, "conduct_multi_agent_meeting", _fake_meeting)

    # 1. Observability routes
    assert client.get("/api/traces?limit=10").status_code == 200
    assert client.get("/api/traces/tr_123").status_code == 200
    assert client.get("/api/checkpoints").status_code == 200
    assert client.get("/api/evals/runs").status_code == 200
    assert client.get("/api/evals/runs/invalid..name").status_code == 200
    assert client.get("/api/evals/runs/nonexistent.json").status_code == 200

    # 2. Meetings & Agents routes
    assert client.get("/api/meetings").status_code == 200
    assert client.get("/api/meeting/history").status_code == 200
    assert client.post("/api/meetings/cancel").status_code == 200
    assert client.post("/api/meetings/start", json={"topic": "Uji Rapat"}).status_code == 200
    assert client.get("/api/agents").status_code == 200
    assert client.get("/api/agent-activity").status_code == 200

    # 3. Pipelines & Memory routes
    assert client.get("/api/pipelines").status_code == 200
    assert client.get("/api/pipelines/tidak_ada").status_code == 404
    assert client.get("/api/pipelines/p1/runs").status_code == 200
    assert client.get("/api/memory").status_code == 200
    assert (
        client.post(
            "/api/memory/add",
            json={"type": "fact", "key_topic": "k1", "content": "c1", "category": "general"},
        ).status_code
        == 200
    )

    # 4. Settings, Telemetry & Workspace routes
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/system/home-dir").status_code == 200
    assert client.get("/api/artifacts").status_code == 200
    assert client.get("/api/workspace/roots").status_code == 200

    # 5. Scraper routes across all engines
    assert client.get("/api/scraper/batches").status_code == 200
    assert client.post("/api/scraper/universal", json={"query": ""}).status_code == 200
    assert client.post("/api/scraper/universal", json={"query": "mouse", "limit": 5}).status_code == 200
    assert client.post("/api/scraper/custom-batch", json={"urls": []}).status_code == 200
    assert (
        client.post("/api/scraper/custom-batch", json={"urls": ["https://example.com"]}).status_code
        == 200
    )
    for eng in ("crawl4ai", "scrapling", "markitdown", "scrapy", "crawlee", "firecrawl", "auto_hybrid"):
        r = client.post(
            "/api/scraper/modern-lab",
            json={"url": "https://example.com", "engine": eng, "css_selector": "h1"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"

