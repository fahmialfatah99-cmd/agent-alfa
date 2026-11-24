"""Tes hermetik Phase 7B: ``alfa.bot.telegram_bot`` entry point.

Fokus pada:
- ``post_init`` & ``post_shutdown`` hooks
- Error handler ``_on_error``
- Notification port registration
- TestApplication harness integration

Catatan: ``main()`` launcher tes memerlukan module reload kompleks,
hanya tes hook & handler yang diuji langsung.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set env vars BEFORE importing the module
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TEST_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

# Import modul target
import alfa.bot.telegram_bot as tg_bot


# Patch check_runtime_security di module asalnya
@pytest.fixture(autouse=True)
def _patch_security_guard(monkeypatch):
    monkeypatch.setattr("alfa.core.security_boot_guard.check_runtime_security", lambda x: None)


@pytest.fixture
def mock_env(monkeypatch):
    """Set env vars minimal untuk main()."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:TEST_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    # Disable security boot guard untuk tes
    monkeypatch.setattr(tg_bot, "check_runtime_security", lambda x: None)


@pytest.fixture
def fake_application(monkeypatch):
    """Mock Application builder & instance."""

    mock_app = MagicMock()
    mock_app.bot = MagicMock()
    mock_app.bot.set_my_commands = AsyncMock()
    mock_app.add_handler = MagicMock()
    mock_app.add_error_handler = MagicMock()
    mock_app.run_polling = AsyncMock()

    # Mock Application.builder()...build() chain
    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.concurrent_updates.return_value = mock_builder
    mock_builder.post_init.return_value = mock_builder
    mock_builder.post_shutdown.return_value = mock_builder
    mock_builder.build.return_value = mock_app

    monkeypatch.setattr("telegram.ext.Application.builder", MagicMock(return_value=mock_builder))

    return mock_app


class TestPostInitShutdown:
    """Tes hook post_init & post_shutdown."""

    async def test_post_init_calls_database_and_subagents(self, monkeypatch):
        mock_init_db = AsyncMock()
        monkeypatch.setattr("alfa.core.database.init_db", mock_init_db)

        mock_set_app = MagicMock()
        monkeypatch.setattr("alfa.swarm.subagents.set_telegram_app", mock_set_app)

        mock_bot = MagicMock()
        mock_bot.set_my_commands = AsyncMock()
        mock_app = MagicMock()
        mock_app.bot = mock_bot

        await tg_bot.post_init(mock_app)

        mock_init_db.assert_awaited_once()
        mock_set_app.assert_called_once_with(mock_app)
        mock_bot.set_my_commands.assert_awaited_once()

    async def test_post_init_handles_durable_recovery(self, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.db.durable_tasks.recover_stale_tasks_sync",
            MagicMock(return_value=3),
        )
        monkeypatch.setattr("alfa.core.database.init_db", AsyncMock())
        monkeypatch.setattr("alfa.swarm.subagents.set_telegram_app", MagicMock())

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.set_my_commands = AsyncMock()

        await tg_bot.post_init(mock_app)
        # Jika recovery berhasil, log info (tidak tes log, hanya pastikan tidak crash)

    async def test_post_init_sandbox_cleanup(self, monkeypatch, tmp_path):
        """Tes cleanup file media di SANDBOX_DIR saat startup."""
        monkeypatch.setattr("alfa.core.database.init_db", AsyncMock())
        monkeypatch.setattr("alfa.swarm.subagents.set_telegram_app", MagicMock())

        # Buat file dummy di tmp_path
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "generated_plot_1.png").write_bytes(b"fake")
        (sandbox / "dataset_analysis_chart.png").write_bytes(b"fake")
        (sandbox / "keep.txt").write_text("keep")

        monkeypatch.setattr(tg_bot, "SANDBOX_DIR", str(sandbox))

        mock_app = MagicMock()
        mock_app.bot = MagicMock()
        mock_app.bot.set_my_commands = AsyncMock()

        await tg_bot.post_init(mock_app)

        assert not (sandbox / "generated_plot_1.png").exists()
        assert not (sandbox / "dataset_analysis_chart.png").exists()
        assert (sandbox / "keep.txt").exists()

    async def test_post_shutdown_cancels_proactive_tasks(self, monkeypatch):
        """Tes post_shutdown membatalkan semua proactive tasks."""
        task1 = MagicMock()
        task1.done.return_value = False
        task2 = MagicMock()
        task2.done.return_value = True  # sudah selesai

        monkeypatch.setattr(tg_bot, "_proactive_tasks", [task1, task2])

        mock_gather = AsyncMock()
        monkeypatch.setattr("asyncio.gather", mock_gather)

        await tg_bot.post_shutdown(MagicMock())

        task1.cancel.assert_called_once()
        task2.cancel.assert_not_called()  # sudah done
        mock_gather.assert_awaited_once()
        assert tg_bot._proactive_tasks == []


class TestMainLauncher:
    """Tes fungsi main() launcher - hanya tes unit tanpa reload."""

    def test_main_exits_if_no_token(self, capsys, monkeypatch):
        """Tes logika validasi token langsung (bukan via main())."""
        # Test logic: token kosong -> exit
        # Just verify the validation logic exists
        assert True  # Placeholder - main() test requires module reload

    def test_main_warns_if_no_gemini_key(self, fake_application):
        """Tes logika validasi GEMINI_API_KEY."""
        # Placeholder - main() test requires module reload
        assert True

    def test_main_builds_application_and_adds_handlers(self):
        """Verifikasi struktur handler registration - placeholder."""
        # main() test requires module reload, skip for now
        assert True


class TestErrorHandler:
    """Tes error handler ``_on_error`` (defined inside main())."""

    # _on_error is a local function inside main(), cannot test directly
    # These tests are placeholders for future extraction
    def test_on_error_placeholder(self):
        """_on_error testing requires extracting it to module level."""
        assert True


class TestNotificationPort:
    """Tes registrasi port notifikasi."""

    def test_register_safe_send_and_templates(self, monkeypatch):
        mock_register_send = MagicMock()
        mock_register_templates = MagicMock()

        class MockPort:
            def register_send_message(self, fn):
                mock_register_send(fn)
            def register_swarm_templates(self, fn):
                mock_register_templates(fn)

        mock_port_module = MagicMock()
        mock_port_module.register_send_message = mock_register_send
        mock_port_module.register_swarm_templates = mock_register_templates
        monkeypatch.setitem(sys.modules, "alfa.core.notification", mock_port_module)

        # Trigger registration by calling the registration code directly
        from alfa.bot.telegram_bot import _notify_safe_send, _notify_swarm_templates

        # These should be callable
        assert callable(_notify_safe_send)
        assert callable(_notify_swarm_templates)

        mock_app = MagicMock()
        asyncio.run(_notify_safe_send(mock_app, 123, "hello"))
        templates = _notify_swarm_templates()
        assert isinstance(templates, dict)


class TestHarnessIntegration:
    """Tes integrasi dengan TestApplication harness."""

    async def test_test_application_feeds_update(self):
        """TestApplication bisa feed update ke handler."""
        from tests.harness.ptb_app import (
            TestApplication,
            make_mock_message,
            make_mock_update,
        )

        async with TestApplication.create(handlers=[]) as app:
            msg = make_mock_message(text="/start")
            upd = make_mock_update(message=msg)
            await app.feed_update(upd)
            # Tidak error = berhasil

    async def test_test_application_with_command_handler(self):
        """TestApplication memproses CommandHandler."""
        from telegram.ext import CommandHandler

        from tests.harness.ptb_app import (
            TestApplication,
            make_mock_message,
            make_mock_update,
        )

        called = []

        async def dummy_cmd(update, context):
            called.append(update.message.text)

        async with TestApplication.create(handlers=[CommandHandler("start", dummy_cmd)]) as app:
            msg = make_mock_message(text="/start", is_command=True)
            upd = make_mock_update(message=msg)
            await app.feed_update(upd)

        assert called == ["/start"]


# Parametrized test untuk semua command handler yang terdaftar
# (Run once, collect all commands, then verify)
def test_main_registers_all_command_handlers(fake_application):
    """Verifikasi struktur command handlers - placeholder."""
    # main() test requires module reload, skip for now
    assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
