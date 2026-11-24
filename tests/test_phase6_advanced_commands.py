"""Phase 6 coverage: advanced Telegram commands (/setsheet, /swarm, /ram, ...).

Hermetic: Telegram context, database, swarm engine, dan progress reporter di-fake.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def ac(monkeypatch):
    from alfa.bot.advanced_commands import commands

    sent: list[tuple] = []

    async def fake_send(context, chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(commands, "safe_send_message", fake_send)
    monkeypatch.setattr(commands, "is_authorized", lambda uid: True)
    commands.sent = sent
    return commands


def make_update(uid=7, cid=42):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        effective_chat=SimpleNamespace(id=cid),
    )


def make_context(args=None, bot=None):
    return SimpleNamespace(args=list(args or []), bot=bot or AsyncMock())


def _texts(ac):
    return "\n".join(t for _, t, _ in ac.sent)


# ---------------------------------------------------------------------------
# /setsheet
# ---------------------------------------------------------------------------


def test_setsheet_unauthorized(ac, monkeypatch):
    monkeypatch.setattr(ac, "is_authorized", lambda uid: False)
    import asyncio

    asyncio.run(ac.setsheet_command(make_update(), make_context()))
    assert "Akses ditolak" in _texts(ac)


def test_setsheet_status_variants(ac, monkeypatch):
    import asyncio

    from alfa.integrations import google_sheets

    monkeypatch.setattr(google_sheets, "get_spreadsheet_id", lambda: "")
    monkeypatch.setattr(google_sheets, "DEFAULT_TAB_NAME", "Tab")
    asyncio.run(ac.setsheet_command(make_update(), make_context()))
    assert "Belum Terhubung" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(google_sheets, "get_spreadsheet_id", lambda: "sid")
    monkeypatch.setattr(
        google_sheets,
        "ensure_material_sheet_tab",
        lambda spreadsheet_id=None: {"status": "success", "title": "Sheet A"},
    )
    asyncio.run(ac.setsheet_command(make_update(), make_context()))
    assert "Terhubung" in _texts(ac) and "Sheet A" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        google_sheets,
        "ensure_material_sheet_tab",
        lambda spreadsheet_id=None: {"status": "error", "message": "akses ditolak"},
    )
    asyncio.run(ac.setsheet_command(make_update(), make_context()))
    assert "Peringatan Akses" in _texts(ac)


def test_setsheet_set_success_and_failure(ac, monkeypatch):
    import asyncio

    from alfa.integrations import google_sheets

    monkeypatch.setattr(
        google_sheets,
        "set_spreadsheet_id",
        lambda raw: {
            "status": "success",
            "spreadsheet_title": "Baru",
            "spreadsheet_id": "id1",
            "tab_name": "Tab",
        },
    )
    asyncio.run(ac.setsheet_command(make_update(), make_context(["https://sheet"])))
    assert "Berhasil Dikonfigurasi" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        google_sheets,
        "set_spreadsheet_id",
        lambda raw: {"status": "error", "message": "tidak valid"},
    )
    asyncio.run(ac.setsheet_command(make_update(), make_context(["x"])))
    assert "Gagal" in _texts(ac) and "tidak valid" in _texts(ac)


# ---------------------------------------------------------------------------
# /dashboard, /keys, /agents
# ---------------------------------------------------------------------------


def test_dashboard_magic_links_and_tma(ac, monkeypatch):
    import asyncio

    from alfa.dashboard.routes import auth

    monkeypatch.setattr(
        ac.tools,
        "open_web_dashboard",
        lambda port=8080: {
            "network_url": "http://192.168.1.5:8080",
            "local_url": "http://127.0.0.1:8080",
        },
    )
    monkeypatch.setattr(auth, "create_telegram_link", lambda uid: "tok")
    monkeypatch.setenv("ALFA_WEBAPP_URL", "https://mini.test/app")
    asyncio.run(ac.dashboard_command(make_update(), make_context()))
    text = _texts(ac)
    assert "COMMAND CENTER" in text
    assert "masuk otomatis" in text
    markup = ac.sent[-1][2]["reply_markup"]
    assert markup is not None

    ac.sent.clear()
    monkeypatch.delenv("ALFA_WEBAPP_URL", raising=False)
    monkeypatch.setattr(
        ac.tools,
        "open_web_dashboard",
        lambda port=8080: {
            "network_url": "",
            "local_url": "http://localhost:8080",
        },
    )
    asyncio.run(ac.dashboard_command(make_update(), make_context()))
    assert "Akses Lokal" in _texts(ac)


def test_dashboard_magic_link_error(ac, monkeypatch):
    import asyncio

    from alfa.dashboard.routes import auth

    monkeypatch.setattr(
        ac.tools,
        "open_web_dashboard",
        lambda port=8080: {"network_url": "http://192.168.1.5:8080", "local_url": "x"},
    )

    def boom(uid):
        raise RuntimeError("token gagal")  # noqa: TRY003

    monkeypatch.setattr(auth, "create_telegram_link", boom)
    asyncio.run(ac.dashboard_command(make_update(), make_context()))
    assert "COMMAND CENTER" in _texts(ac)


def test_dashboard_unauthorized(ac, monkeypatch):
    import asyncio

    monkeypatch.setattr(ac, "is_authorized", lambda uid: False)
    monkeypatch.setattr(
        ac.tools,
        "open_web_dashboard",
        lambda port=8080: (_ for _ in ()).throw(AssertionError("tidak dipanggil")),
    )
    asyncio.run(ac.dashboard_command(make_update(), make_context()))
    assert ac.sent == []


def test_keys_command(ac, monkeypatch):
    import asyncio

    monkeypatch.setattr(ac.database, "list_api_keys_sync", lambda: [])
    asyncio.run(ac.keys_command(make_update(), make_context()))
    assert "Vault Kosong" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        ac.database,
        "list_api_keys_sync",
        lambda: [
            {
                "name": "Main",
                "provider": "gemini",
                "is_active": True,
                "masked_key": "AIza***",
                "default_model": "gemini",
            },
            {
                "name": "Backup",
                "provider": "openai",
                "is_active": False,
                "masked_key": "sk-***",
                "default_model": "gpt",
            },
        ],
    )
    asyncio.run(ac.keys_command(make_update(), make_context()))
    text = _texts(ac)
    assert "ACTIVE" in text and "Backup" in text
    assert "Main" in text and "AIza***" in text


def test_agents_command(ac, monkeypatch):
    import asyncio

    monkeypatch.setattr(ac.database, "list_custom_agents_sync", lambda: [])
    asyncio.run(ac.agents_command(make_update(), make_context()))
    assert "Belum ada AI Agent" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        ac.database,
        "list_custom_agents_sync",
        lambda: [
            {
                "name": "Alpha",
                "role": "Lead",
                "provider": "gemini",
                "model": "m",
                "avatar_emoji": "🦊",
                "is_enabled": 1,
            },
            {
                "name": "Beta",
                "role": "Research",
                "provider": "openai",
                "model": "g",
                "is_enabled": 0,
            },
        ],
    )
    asyncio.run(ac.agents_command(make_update(), make_context()))
    text = _texts(ac)
    assert "Alpha" in text and "Aktif" in text
    assert "Beta" in text and "Nonaktif" in text


# ---------------------------------------------------------------------------
# /rapat
# ---------------------------------------------------------------------------


class FakeReporter:
    instances = []

    def __init__(self, context, chat_id, topic, header=""):
        self.topic = topic
        self.stopped = []
        FakeReporter.instances.append(self)

    async def start(self):
        pass

    async def stop(self, message=""):
        self.stopped.append(message)


def _patch_reporter(monkeypatch):
    import alfa.bot.progress as progress

    FakeReporter.instances = []
    monkeypatch.setattr(progress, "SwarmProgressReporter", FakeReporter)


def test_rapat_guide_and_unauthorized(ac, monkeypatch):
    import asyncio

    asyncio.run(ac.rapat_command(make_update(), make_context()))
    assert "Panduan Ruang Rapat" in _texts(ac)

    monkeypatch.setattr(ac, "is_authorized", lambda uid: False)
    ac.sent.clear()
    asyncio.run(ac.rapat_command(make_update(), make_context(["topik"])))
    assert ac.sent == []


def test_rapat_success(ac, monkeypatch, tmp_path):
    import asyncio

    import alfa.swarm.deliberation as deliberation
    import alfa.swarm.engine as engine

    _patch_reporter(monkeypatch)
    result = {
        "dialogue_transcript": [
            {
                "avatar_emoji": "🦊",
                "agent_name": "Alpha",
                "role": "Lead",
                "message": "pendapat",
            }
        ],
        "consensus": "sepakat",
        "action_plan": "langkah",
        "meeting_id": 9,
    }
    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        AsyncMock(return_value=result),
    )
    monkeypatch.setattr(
        deliberation,
        "export_meeting_report_files",
        lambda data: str(tmp_path / "report.md"),
    )
    asyncio.run(ac.rapat_command(make_update(), make_context(["rencana"])))
    text = _texts(ac)
    assert "Transkrip Diskusi" in text and "sepakat" in text
    assert "ACTION PLAN" in text


def test_rapat_engine_error(ac, monkeypatch):
    import asyncio

    import alfa.swarm.engine as engine

    _patch_reporter(monkeypatch)
    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        AsyncMock(side_effect=RuntimeError("engine mati")),
    )
    asyncio.run(ac.rapat_command(make_update(), make_context(["x"])))
    assert "kesalahan saat rapat" in _texts(ac)
    assert FakeReporter.instances[0].stopped == ["❌ Rapat gagal."]


def test_rapat_report_error(ac, monkeypatch):
    import asyncio

    import alfa.swarm.deliberation as deliberation
    import alfa.swarm.engine as engine

    _patch_reporter(monkeypatch)
    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        AsyncMock(return_value={"dialogue_transcript": []}),
    )
    monkeypatch.setattr(
        deliberation,
        "export_meeting_report_files",
        lambda data: (_ for _ in ()).throw(RuntimeError("export")),
    )
    asyncio.run(ac.rapat_command(make_update(), make_context(["x"])))
    assert "KONSENSUS & KEPUTUSAN RAPAT" in _texts(ac)


# ---------------------------------------------------------------------------
# /swarm
# ---------------------------------------------------------------------------


def test_swarm_guide_and_mode_toggles(ac, monkeypatch):
    import asyncio

    import alfa.bot.mode_commands as mc

    asyncio.run(ac.swarm_command(make_update(), make_context()))
    assert "Panduan Swarm" in _texts(ac)

    calls = []
    monkeypatch.setattr(mc, "set_telegram_mode_sync", lambda mode: calls.append(mode))
    asyncio.run(ac.swarm_command(make_update(), make_context(["single"])))
    asyncio.run(ac.swarm_command(make_update(), make_context(["swarm"])))
    assert calls == ["single", "swarm"]

    asyncio.run(ac.swarm_command(make_update(), make_context(["status"])))
    asyncio.run(ac.swarm_command(make_update(), make_context(["cancel"])))


def test_swarm_status_and_cancel_delegate(ac, monkeypatch):
    import asyncio

    import alfa.bot.mode_commands as mc

    called = {}

    async def status(update, context):
        called["status"] = True

    async def cancel(update, context):
        called["cancel"] = True

    monkeypatch.setattr(mc, "status_command", status)
    monkeypatch.setattr(mc, "cancel_command", cancel)
    asyncio.run(ac.swarm_command(make_update(), make_context(["status"])))
    asyncio.run(ac.swarm_command(make_update(), make_context(["cancel"])))
    assert called == {"status": True, "cancel": True}


def test_swarm_model_flows(ac, monkeypatch):
    import asyncio

    import alfa.bot.mode_commands as mc

    async def status(update, context):
        pass

    monkeypatch.setattr(mc, "status_command", status)
    agents = [
        {"id": 2, "name": "Alpha", "provider": "gemini", "model": "m"},
        {"id": 3, "name": "Beta", "provider": "openai", "model": "g"},
    ]
    monkeypatch.setattr(ac.database, "list_custom_agents_sync", lambda: agents)
    monkeypatch.setattr(
        ac.database,
        "update_custom_agent_sync",
        lambda aid, payload: {"status": "success"},
    )

    asyncio.run(ac.swarm_command(make_update(), make_context(["model"])))
    assert "Usage" in _texts(ac)

    ac.sent.clear()
    asyncio.run(ac.swarm_command(make_update(), make_context(["model", "99"])))
    assert "tidak ditemukan" in _texts(ac)

    ac.sent.clear()
    asyncio.run(ac.swarm_command(make_update(), make_context(["model", "alpha"])))
    assert "Alpha" in _texts(ac)

    ac.sent.clear()
    asyncio.run(
        ac.swarm_command(make_update(), make_context(["model", "2", "gemini", "mx"]))
    )
    assert "alpha" in _texts(ac).lower()

    ac.sent.clear()
    monkeypatch.setattr(
        ac.database,
        "update_custom_agent_sync",
        lambda aid, payload: {"status": "error", "message": "db down"},
    )
    asyncio.run(ac.swarm_command(make_update(), make_context(["model", "2", "gemini"])))
    assert "Gagal" in _texts(ac)


def test_swarm_templates(ac, monkeypatch):
    import asyncio

    import alfa.bot.mode_commands as mc

    monkeypatch.setattr(mc, "SWARM_TEMPLATES", {"riset": "Riset pasar singkat"})
    asyncio.run(ac.swarm_command(make_update(), make_context(["template"])))
    assert "Templat Misi Swarm" in _texts(ac)

    ac.sent.clear()
    asyncio.run(ac.swarm_command(make_update(), make_context(["template", "hilang"])))
    assert "tidak ada" in _texts(ac)

    ac.sent.clear()
    _patch_reporter(monkeypatch)
    import alfa.swarm.engine as engine

    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        AsyncMock(return_value={"execution_results": []}),
    )
    asyncio.run(ac.swarm_command(make_update(), make_context(["template", "riset"])))
    assert any("Eksekusi" in t or "eksekusi" in t for t in _texts(ac).splitlines())


def test_swarm_execution_success_with_file(ac, monkeypatch, tmp_path):
    import asyncio

    import alfa.swarm.engine as engine

    _patch_reporter(monkeypatch)
    deliverable = tmp_path / "hasil.csv"
    deliverable.write_text("a,b\n1,2\n", encoding="utf-8")
    result = {
        "execution_results": [
            {
                "agent_name": "Alpha",
                "role": "Lead",
                "tool_used": "tool_x",
                "duration_ms": 12,
                "execution_summary": "sukses",
                "deliverable_file": str(deliverable),
                "avatar_emoji": "🦊",
            }
        ],
        "consensus": "selesai",
        "meeting_id": 3,
    }
    monkeypatch.setattr(
        engine, "conduct_multi_agent_meeting", AsyncMock(return_value=result)
    )
    bot = AsyncMock()
    asyncio.run(ac.swarm_command(make_update(), make_context(["kerjakan"], bot=bot)))
    text = _texts(ac)
    assert "Laporan Eksekusi" in text and "tool_x" in text
    bot.send_document.assert_awaited_once()


def test_swarm_execution_engine_error(ac, monkeypatch):
    import asyncio

    import alfa.swarm.engine as engine

    _patch_reporter(monkeypatch)
    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        AsyncMock(side_effect=RuntimeError("swarm down")),
    )
    asyncio.run(ac.swarm_command(make_update(), make_context(["tugas"])))
    assert "kesalahan saat eksekusi swarm" in _texts(ac)


def test_swarm_execution_report_error(ac, monkeypatch):
    import asyncio

    import alfa.swarm.engine as engine

    _patch_reporter(monkeypatch)
    monkeypatch.setattr(
        engine,
        "conduct_multi_agent_meeting",
        AsyncMock(return_value={"execution_results": [{"agent_name": "A"}]}),
    )
    asyncio.run(ac.swarm_command(make_update(), make_context(["tugas"])))
    assert "Gagal mengirim laporan swarm" in _texts(ac)


def test_swarm_unauthorized(ac, monkeypatch):
    import asyncio

    monkeypatch.setattr(ac, "is_authorized", lambda uid: False)
    asyncio.run(ac.swarm_command(make_update(), make_context(["x"])))
    assert ac.sent == []


# ---------------------------------------------------------------------------
# /resume_swarm
# ---------------------------------------------------------------------------


class FakeCheckpoint:
    items: list[dict] = []
    result: dict = {}

    @staticmethod
    def list_resumable():
        return list(FakeCheckpoint.items)


def _patch_checkpoint(monkeypatch):
    import alfa.swarm.checkpoint as checkpoint

    FakeCheckpoint.items = []
    FakeCheckpoint.result = {}
    monkeypatch.setattr(checkpoint, "SwarmCheckpoint", FakeCheckpoint)


def test_resume_swarm_empty_and_list(ac, monkeypatch):
    import asyncio

    _patch_checkpoint(monkeypatch)
    asyncio.run(ac.resume_swarm_command(make_update(), make_context()))
    assert "Tidak ada sesi swarm" in _texts(ac)

    ac.sent.clear()
    FakeCheckpoint.items = [
        {
            "session_id": "s1",
            "status": "paused",
            "topic": "topik",
            "steps_done": 1,
            "steps_total": 3,
            "updated_at": None,
        },
        {"session_id": "", "status": None},
    ]
    asyncio.run(ac.resume_swarm_command(make_update(), make_context()))
    text = _texts(ac)
    assert "Checkpoints" in text and "s1" in text and "?" in text


def test_resume_swarm_success_and_error(ac, monkeypatch):
    import asyncio

    import alfa.swarm.engine as engine

    _patch_checkpoint(monkeypatch)
    _patch_reporter(monkeypatch)
    result = {
        "execution_results": [
            {
                "agent_name": "Alpha",
                "role": "Lead",
                "tool_used": "t",
                "execution_summary": "ok",
            }
        ],
        "consensus": "lanjut",
    }
    monkeypatch.setattr(
        engine, "resume_swarm_session", AsyncMock(return_value=result)
    )
    asyncio.run(ac.resume_swarm_command(make_update(), make_context(["s1"])))
    assert "Hasil Lanjutan" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        engine,
        "resume_swarm_session",
        AsyncMock(return_value={"status": "error", "message": "tidak bisa"}),
    )
    asyncio.run(ac.resume_swarm_command(make_update(), make_context(["s1"])))
    assert "Gagal resume" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        engine,
        "resume_swarm_session",
        AsyncMock(side_effect=RuntimeError("checkpoint rusak")),
    )
    asyncio.run(ac.resume_swarm_command(make_update(), make_context(["s1"])))
    assert "kesalahan saat resume" in _texts(ac)


# ---------------------------------------------------------------------------
# /ram, /skills, /apex
# ---------------------------------------------------------------------------


def test_ram_command(ac, monkeypatch):
    import asyncio

    from alfa.tools.system import management

    payload = {
        "system_ram": {
            "used_mb": 100,
            "total_mb": 1000,
            "available_mb": 900,
            "used_percent": 10,
        },
        "alfa_bot_mb": 50,
        "wa_sheets_bot_mb": 1200,
        "wa_process_count": 2,
        "python_gc_objects_collected": 5,
        "cleaned_orphaned_tmp_dirs": 1,
        "wa_recycled": False,
    }
    captured = {}

    def fake_clean(recycle_wa_if_needed=False):
        captured["recycle"] = recycle_wa_if_needed
        return payload

    monkeypatch.setattr(management, "system_clean_memory_and_cache", fake_clean)
    asyncio.run(ac.ram_command(make_update(), make_context()))
    text = _texts(ac)
    assert "100 MB / 1000 MB" in text
    assert "restart fresh" in text
    assert captured["recycle"] is False

    ac.sent.clear()
    payload["wa_recycled"] = True
    asyncio.run(ac.ram_command(make_update(), make_context(["full"])))
    assert "Berhasil di-recycle" in _texts(ac)
    assert captured["recycle"] is True


def test_skills_command_compile_paths(ac, monkeypatch):
    import asyncio

    from alfa.core.brain import skill_compiler

    monkeypatch.setattr(
        skill_compiler, "compile_skills_sync", lambda: {"status": "disabled"}
    )
    asyncio.run(ac.skills_command(make_update(), make_context(["compile"])))
    assert "nonaktif" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        skill_compiler,
        "compile_skills_sync",
        lambda: {"status": "error", "error": "rusak"},
    )
    asyncio.run(ac.skills_command(make_update(), make_context(["compile"])))
    assert "Kompilasi gagal" in _texts(ac)

    ac.sent.clear()
    monkeypatch.setattr(
        skill_compiler,
        "compile_skills_sync",
        lambda: {
            "status": "ok",
            "mode": "shadow",
            "scanned": 1,
            "groups": 2,
            "compiled": 3,
            "activated": 4,
            "min_support": 2,
        },
    )
    asyncio.run(ac.skills_command(make_update(), make_context(["compile"])))
    assert "SKILL COMPILER SELESAI" in _texts(ac)


def test_skills_command_metrics(ac, monkeypatch):
    import asyncio

    from alfa.core.brain import learning_loop, skill_compiler

    monkeypatch.setattr(
        learning_loop,
        "get_learning_loop_metrics",
        lambda: {
            "avg_confidence": 0.9,
            "total_active_skills": 2,
            "total_trajectories": 3,
            "total_hits": 4,
            "top_skills": [
                {
                    "learned_rule": "x" * 130,
                    "confidence": 0.8,
                    "success_count": 1,
                    "failure_count": 0,
                    "topic": "t",
                    "hit_count": 2,
                }
            ],
        },
    )
    monkeypatch.setattr(
        skill_compiler, "format_compiled_skills_status", lambda: "status"
    )
    asyncio.run(ac.skills_command(make_update(), make_context()))
    text = _texts(ac)
    assert "SELF-IMPROVING" in text
    assert "90%" in text and "..." in text

    ac.sent.clear()
    monkeypatch.setattr(
        skill_compiler,
        "format_compiled_skills_status",
        lambda: (_ for _ in ()).throw(ImportError("x")),
    )
    asyncio.run(ac.skills_command(make_update(), make_context()))
    assert "SELF-IMPROVING" in _texts(ac)


def test_apex_command(ac, monkeypatch):
    import asyncio

    from alfa.core import apex

    monkeypatch.setattr(
        apex,
        "run_autonomous_apex_maintenance",
        lambda force=False: (_ for _ in ()).throw(RuntimeError("maint")),
    )
    status = {
        "autonomy_level": "Level 5+",
        "governor": {"governor_mode": "TURBO", "cpu_temp_celsius": 45, "ram_available_mb": 100},
        "dreaming": {"total_compiled_fastpaths": 1, "total_fastpath_hits": 2, "estimated_tokens_saved": 3},
        "world_model": {"unresolved_anomalies_count": 0},
        "canary_evolution": {"active_synthesized_tools": 1},
        "learning_loop": {"total_active_skills": 2, "avg_confidence": 0.9},
        "cloud_rescue_vault": {"total_vaulted_files": 1},
        "symbolic_ledgers": {"audited_ledgers_count": 1},
        "temporal_graphrag": {"total_entities": 5, "total_relations": 6},
        "software_factory": {"total_builds": 1, "avg_e2e_score": 99},
        "computer_use": {"display": ":0", "resolution": "1920x1080"},
    }
    monkeypatch.setattr(apex, "get_apex_full_status", lambda: status)
    asyncio.run(ac.apex_command(make_update(), make_context()))
    text = _texts(ac)
    assert "COGNITIVE APEX" in text and "wa-sheets-bot" in text


def test_apex_unauthorized(ac, monkeypatch):
    import asyncio

    monkeypatch.setattr(ac, "is_authorized", lambda uid: False)
    asyncio.run(ac.apex_command(make_update(), make_context()))
    assert ac.sent == []
