"""Unit test hermetik fase-2: router callback & panel menu handlers.

Fokus blok belum tercover: ``handle_callback_query`` (gate otorisasi, reset
budget) dan ``_dispatch_menu_callback`` (seluruh tombol menu utama — modul,
mode, agen, tools, persona, keys/cron fallback, status WA & kontrol bot).

Semua dependensi eksternal (database, subcommand modul lain, manajemen
proses WA, rate limiter) di-patch — tanpa DB produksi, tanpa proses nyata.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import alfa.bot.handlers as h


def _upd(user_id=77):
    """(update, query) MagicMock dengan atribut akses eksplisit."""
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = user_id
    update.effective_chat.id = 42
    return update, query


@pytest.fixture
def _menu_env(monkeypatch):
    sent: list[dict] = []

    async def fake_send(context, chat_id, text, **kw):
        sent.append({"chat_id": chat_id, "text": text})

    monkeypatch.setattr(h, "safe_send_message", fake_send)
    return sent


def _cmd_mock(monkeypatch, dotted):
    """Patch fungsi command oleh AsyncMock; kembalikan mock utk assert."""
    import importlib

    mod_name, _, attr = dotted.rpartition(".")
    mod = importlib.import_module(mod_name)
    m = AsyncMock()
    monkeypatch.setattr(mod, attr, m, raising=False)
    return m


def _fn_mock(monkeypatch, dotted, ret=None):
    """Patch fungsi biasa (sync); kembalikan mock utk assert."""
    import importlib

    mod_name, _, attr = dotted.rpartition(".")
    mod = importlib.import_module(mod_name)
    m = MagicMock(return_value=ret)
    monkeypatch.setattr(mod, attr, m, raising=False)
    return m


def _db_mock(monkeypatch, dotted, ret=None):
    """Patch fungsi database — selalu AsyncMock (fungsi db async)."""
    import importlib

    mod_name, _, attr = dotted.rpartition(".")
    mod = importlib.import_module(mod_name)
    m = AsyncMock(return_value=ret)
    monkeypatch.setattr(mod, attr, m, raising=False)
    return m


@pytest.fixture
def _routers_off(monkeypatch):
    """Nonaktifkan semua sub-router callback (return False)."""
    monkeypatch.setattr(h, "handle_doc_action_callback", AsyncMock(return_value=False))
    monkeypatch.setattr(
        h, "handle_forward_action_callback", AsyncMock(return_value=False)
    )
    for dotted in (
        "alfa.bot.mode_commands.handle_persona_callback",
        "alfa.bot.wa_menu.handle_wa_callback",
        "alfa.bot.advanced_commands.handle_sites_callback",
        "alfa.bot.cloud_menu.handle_cloud_callback",
    ):
        _cmd_mock(monkeypatch, dotted)


# ── Dispatch tombol menu utama ───────────────────────────────────────────────
async def test_btn_menu_routes_menu_command(_menu_env, monkeypatch):
    mc = _cmd_mock(monkeypatch, "alfa.bot.basic_commands.menu_command")
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_menu", 77, 42)
    mc.assert_awaited_once_with(upd, ctx)


async def test_btn_sheets_gdrive_cloud_routes(_menu_env, monkeypatch):
    sheets = _cmd_mock(monkeypatch, "alfa.bot.cloud_menu.render_sheets_home")
    drive = _cmd_mock(monkeypatch, "alfa.bot.cloud_menu.render_drive_home")
    hub = _cmd_mock(monkeypatch, "alfa.bot.cloud_menu.render_cloud_hub")

    for data, mock, args_len in (
        ("btn_sheets", sheets, 3),
        ("btn_gdrive", drive, 2),
        ("btn_cloud", hub, 2),
    ):
        upd, ctx = MagicMock(), MagicMock()
        await h._dispatch_menu_callback(upd, ctx, data, 77, 42)
        assert mock.await_count == 1, data
        assert len(mock.await_args.args) == args_len, data


async def test_btn_stats_sends_system_overview(_menu_env, monkeypatch):
    monkeypatch.setattr(
        h,
        "get_system_stats",
        lambda: {
            "cpu": "9%",
            "ram": "4GB",
            "swap": "0B",
            "disk": "120G/512G",
            "battery": "93%",
            "ip_addresses": "192.168.1.7",
            "uptime": "2 jam",
            "top_ram_processes": ["chrome"],
        },
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_stats", 77, 42)
    assert "Status Server" in _menu_env[-1]["text"]
    assert "chrome" in _menu_env[-1]["text"]


async def test_btn_ram_routes_ram_command(_menu_env, monkeypatch):
    rc = _cmd_mock(monkeypatch, "alfa.bot.advanced_commands.ram_command")
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_ram", 77, 42)
    rc.assert_awaited_once_with(upd, ctx)


async def test_btn_memory_empty_and_filled(_menu_env, monkeypatch):
    db = _db_mock(monkeypatch, "alfa.core.database.get_all_memories", ret=[])

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_memory", 77, 42)
    db.assert_awaited_once_with(77)
    assert "masih kosong" in _menu_env[-1]["text"]

    db.return_value = [
        {"category": "idea", "key_topic": "email", "content": "admin@ex.com"}
    ]
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_memory", 77, 42)
    assert "Memori Tersimpan (1 item)" in _menu_env[-1]["text"]
    assert "[IDEA]" in _menu_env[-1]["text"]


async def test_btn_toggle_voice_sends_status(_menu_env, monkeypatch):
    db = _db_mock(monkeypatch, "alfa.core.database.toggle_voice_setting", ret=True)

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_toggle_voice", 77, 42)
    db.assert_awaited_once_with(77)
    assert "AKTIF" in _menu_env[-1]["text"]

    db.return_value = False
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_toggle_voice", 77, 42)
    assert "NONAKTIF" in _menu_env[-1]["text"]


async def test_btn_python_info_sends_text(_menu_env):
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_python_info", 77, 42)
    assert "Python Sandbox" in _menu_env[-1]["text"]


async def test_btn_clear_resets_history(_menu_env, monkeypatch):
    db = _db_mock(monkeypatch, "alfa.core.database.clear_user_chat_history")

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_clear", 77, 42)
    db.assert_awaited_once_with(77)
    assert "direset" in _menu_env[-1]["text"]


async def test_btn_help_sends_full_list(_menu_env):
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_help", 77, 42)
    assert "Daftar Perintah Lengkap" in _menu_env[-1]["text"]


async def test_btn_mode_single_swarm_status(_menu_env, monkeypatch):
    import alfa.bot.mode_commands as mcmod

    setter = MagicMock()
    monkeypatch.setattr(mcmod, "set_telegram_mode_sync", setter)
    status = _cmd_mock(monkeypatch, "alfa.bot.mode_commands.status_command")

    for data, mode_arg in (
        ("btn_mode_single", "single"),
        ("btn_mode_swarm", "swarm"),
    ):
        upd, ctx = MagicMock(), MagicMock()
        await h._dispatch_menu_callback(upd, ctx, data, 77, 42)
        setter.assert_called_with(mode_arg)
    assert "SINGLE aktif" in _menu_env[-2]["text"]
    assert "SWARM aktif" in _menu_env[-1]["text"]

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_status", 77, 42)
    status.assert_awaited_once_with(upd, ctx)


async def test_btn_meeting_info_and_swarm_info(_menu_env, monkeypatch):
    import alfa.bot.mode_commands as mcmod

    monkeypatch.setattr(mcmod, "get_telegram_mode_sync", lambda: "single")

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_meeting_info", 77, 42)
    assert "/rapat" in _menu_env[-1]["text"]

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_swarm_info", 77, 42)
    assert "/swarm" in _menu_env[-1]["text"]
    assert "mode single" in _menu_env[-1]["text"]


async def test_btn_swarm_info_mode_probe_error(_menu_env, monkeypatch):
    # Probe mode gagal → catatan default mode swarm dipakai (jangan meledak).
    import alfa.bot.mode_commands as mcmod

    def boom():
        raise ValueError()

    monkeypatch.setattr(mcmod, "get_telegram_mode_sync", boom)
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_swarm_info", 77, 42)
    assert "/swarm" in _menu_env[-1]["text"]
    assert "mode swarm aktif" in _menu_env[-1]["text"]


async def test_btn_agents_uses_bot_module_fn(_menu_env, monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(
        h, "_get_bot_module", lambda: SimpleNamespace(agents_command=fake)
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_agents", 77, 42)
    fake.assert_awaited_once_with(upd, ctx)


async def test_btn_agents_fallback_advanced(_menu_env, monkeypatch):
    monkeypatch.setattr(h, "_get_bot_module", lambda: None)
    fb = _cmd_mock(monkeypatch, "alfa.bot.advanced_commands.agents_command")
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_agents", 77, 42)
    fb.assert_awaited_once_with(upd, ctx)


async def test_btn_tools_pipeline_tasks_routes(_menu_env, monkeypatch):
    tools = _cmd_mock(monkeypatch, "alfa.bot.mode_commands.tools_command")
    pipe = _cmd_mock(monkeypatch, "alfa.bot.mode_commands.pipeline_command")
    tugas = _cmd_mock(monkeypatch, "alfa.bot.mode_commands.tugas_command")

    for data, mock in (
        ("btn_tools", tools),
        ("btn_pipeline", pipe),
        ("btn_tasks", tugas),
    ):
        upd, ctx = MagicMock(), MagicMock()
        await h._dispatch_menu_callback(upd, ctx, data, 77, 42)
        assert mock.await_count == 1, data
        assert mock.await_args.args == (upd, ctx), data


async def test_btn_persona_menu_render(_menu_env, monkeypatch):
    pm = _cmd_mock(monkeypatch, "alfa.bot.mode_commands.render_persona_menu")
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_persona", 77, 42)
    pm.assert_awaited_once_with(upd, ctx)


async def test_btn_keys_via_bot_module(_menu_env, monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(
        h, "_get_bot_module", lambda: SimpleNamespace(keys_command=fake)
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_keys", 77, 42)
    fake.assert_awaited_once_with(upd, ctx)


async def test_btn_cron_fallback_advanced(_menu_env, monkeypatch):
    # Modul utama tak tersedia → fallback perintah lanjutan (cron).
    monkeypatch.setattr(h, "_get_bot_module", lambda: None)
    fb = _cmd_mock(monkeypatch, "alfa.bot.advanced_commands.cron_command")
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_cron", 77, 42)
    fb.assert_awaited_once_with(upd, ctx)


# ── Kontrol WhatsApp sheets bot ──────────────────────────────────────────────
async def test_wa_status_running_and_stopped(_menu_env, monkeypatch):
    wa = MagicMock()
    wa.return_value = {"is_running": True, "details": "PID 999", "message": "ok"}
    monkeypatch.setattr("alfa.tools.manage_wa_sheets_bot", wa)

    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_wa_status", 77, 42)
    assert wa.call_args.args == ("status",)
    assert "RUNNING (Aktif)" in _menu_env[-1]["text"]
    assert "PID 999" in _menu_env[-1]["text"]

    wa.return_value = {"is_running": False, "details": "", "message": "mati"}
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_wa_status", 77, 42)
    assert "STOPPED (Mati)" in _menu_env[-1]["text"]


async def test_wa_restart_start_stop(_menu_env, monkeypatch):
    wa = MagicMock(side_effect=lambda act: {"message": f"{act} diproses"})
    monkeypatch.setattr("alfa.tools.manage_wa_sheets_bot", wa)

    for data, action in (
        ("btn_wa_restart", "restart"),
        ("btn_wa_start", "start"),
        ("btn_wa_stop", "stop"),
    ):
        upd, ctx = MagicMock(), MagicMock()
        await h._dispatch_menu_callback(upd, ctx, data, 77, 42)
        assert wa.call_args.args == (action,), data
    assert "restart diproses" in _menu_env[-3]["text"]
    assert "start diproses" in _menu_env[-2]["text"]
    assert "stop diproses" in _menu_env[-1]["text"]


# ── handle_callback_query: gate & reset budget ───────────────────────────────
async def test_budget_reset_flow(_menu_env, _routers_off, monkeypatch):
    import alfa.core.rate_limiter as rl

    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    reset = MagicMock(return_value=7)
    monkeypatch.setattr(rl, "reset_user_usage_today", reset)
    monkeypatch.setattr(
        rl,
        "get_user_usage_today",
        lambda uid: {"budget_limit": 120000, "call_limit": 200},
    )

    upd, query = _upd(user_id=77)
    query.data = "budget:reset"
    await h.handle_callback_query(upd, MagicMock())
    reset.assert_called_once_with(77)
    assert "Kuota harian berhasil di-reset" in _menu_env[-1]["text"]
    assert "120,000" in _menu_env[-1]["text"]


async def test_unauthorized_denied(_routers_off, monkeypatch):
    monkeypatch.setattr(h, "_is_authorized", lambda uid: False)
    upd, query = _upd()
    query.data = "btn_menu"
    await h.handle_callback_query(upd, MagicMock())
    query.edit_message_text.assert_awaited_once()
    assert "ditolak" in query.edit_message_text.await_args.args[0]


async def test_perm_prefix_skips_answer(_routers_off, monkeypatch):
    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    upd, query = _upd()
    query.data = "perm|dir-1"
    await h.handle_callback_query(upd, MagicMock())
    query.answer.assert_not_awaited()


async def test_missing_callback_query_returns(_routers_off):
    upd = MagicMock()
    upd.callback_query = None
    await h.handle_callback_query(upd, MagicMock())  # tidak meledak
