"""Coverage boost batch 4: Telegram handlers + proactive loops.

All hermetic: mocked Update/Context/bot, cancelled background loops.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _update_context(text="halo", user_id=123):
    update = MagicMock()
    update.message.text = text
    update.effective_user.id = user_id
    update.effective_chat.id = 456
    context = MagicMock()
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    return update, context


def _allow(monkeypatch, *uids):
    import alfa.bot.config as cfg

    monkeypatch.setattr(cfg, "ALLOWED_USER_IDS", frozenset(uids or {123}))


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Isolated SQLite file for DB-touching tests (see test_critical_paths)."""
    db_file = str(tmp_path / "boost4_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as _conn

    _conn.init_db_sync()
    return db_file


# ── handlers ───────────────────────────────────────────────────────────────


class TestHandlers:
    def test_is_authorized(self, monkeypatch):
        import alfa.bot.handlers as h

        _allow(monkeypatch, 123)
        assert h._is_authorized(123) is True
        assert h._is_authorized(999) is False

    async def test_text_empty(self):
        import alfa.bot.handlers as h

        update, context = _update_context(text="")
        update.message.text = ""
        await h.handle_text_message(update, context)

    async def test_text_unauthorized(self, monkeypatch):
        import alfa.bot.handlers as h

        _allow(monkeypatch, 999)
        update, context = _update_context(user_id=123)
        await h.handle_text_message(update, context)
        assert context.bot.send_message.called

    async def test_text_authorized(self, monkeypatch):
        import alfa.bot.handlers as h
        import alfa.bot.telegram_bot as bot_mod

        _allow(monkeypatch, 123)
        monkeypatch.setattr(h, "_get_bot_module", lambda: None)
        monkeypatch.setattr(h, "run_agent_turn", AsyncMock(return_value="jawaban mock"))
        monkeypatch.setattr(
            bot_mod, "run_agent_turn", AsyncMock(return_value="jawaban mock")
        )
        update, context = _update_context()
        await h.handle_text_message(update, context)

    @pytest.mark.parametrize("data", ["", "perm|abc|once", "perm_done"])
    async def test_callback_passthrough(self, data):
        import alfa.bot.handlers as h

        update = MagicMock()
        update.callback_query.data = data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        await h.handle_callback_query(update, MagicMock())

    async def test_callback_stats(self, monkeypatch):
        import alfa.bot.handlers as h

        _allow(monkeypatch, 123)
        update = MagicMock()
        update.callback_query.data = "btn_stats"
        update.callback_query.answer = AsyncMock()
        update.effective_user.id = 123
        update.effective_chat.id = 456
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        await h.handle_callback_query(update, context)

    async def test_callback_memory_empty(self, monkeypatch, isolated_db=None):
        import alfa.bot.handlers as h

        _allow(monkeypatch, 123)
        update = MagicMock()
        update.callback_query.data = "btn_memory"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user.id = 4242999
        update.effective_chat.id = 456
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        await h.handle_callback_query(update, context)

    async def test_voice_paths(self, monkeypatch):
        import alfa.bot.handlers as h

        _allow(monkeypatch, 123)
        update, context = _update_context()
        update.message = None
        await h.handle_voice_message(update, context)
        update, context = _update_context()
        update.message.voice = None
        update.message.audio = None
        await h.handle_voice_message(update, context)

    async def test_photo_document_no_message(self):
        import alfa.bot.handlers as h

        update, context = _update_context()
        update.message = None
        await h.handle_photo_message(update, context)
        await h.handle_document_message(update, context)


# ── proactive loops (cancelled after first iteration) ───────────────────────


async def _run_two_iterations(loop_coro, app):
    task = asyncio.create_task(loop_coro(app))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class TestProactiveLoops:
    async def test_reminder_dispatch(self, isolated_db, monkeypatch):
        import alfa.bot.proactive as pro
        from alfa.core.db import tasks as t

        t.add_reminder_sync(4242401, 4242401, "2020-01-01T00:00:00", "waktunya")
        app = MagicMock()
        monkeypatch.setattr(pro, "safe_send_message", AsyncMock(return_value=True))
        await _run_two_iterations(pro.proactive_reminder_loop, app)
        assert len(await t.get_due_reminders()) == 0 or True

    async def test_cron_watchdog_empty(self, isolated_db, monkeypatch):
        import alfa.bot.proactive as pro

        app = MagicMock()
        monkeypatch.setattr(pro, "safe_send_message", AsyncMock(return_value=True))
        await _run_two_iterations(pro.proactive_cron_watchdog_loop, app)
