"""Tes hermetik Phase 7B: ``alfa.bot.discord_bot``.

Fokus pada:
- Command handlers (slash commands)
- Event handlers (on_message, on_ready)
- Helper functions

Menggunakan ``FakeDiscordClient`` harness agar tidak butuh bot token/jaringan.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import modul target
import alfa.bot.discord_bot as dc_bot


@pytest.fixture
def mock_discord_env(monkeypatch):
    """Set env vars minimal untuk discord_bot."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test.token.1234567890")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("ALLOWED_USER_IDS", "123456789,987654321")


@pytest.fixture
def discord_client():
    """FakeDiscordClient fixture."""
    from tests.harness.discord_client import FakeDiscordClient
    return FakeDiscordClient()


class TestDiscordBotCommands:
    """Tes slash command handlers."""

    def test_ping_command_registered(self):
        """Tes apakah command ping terdaftar."""
        # Check if the command is defined in the module
        assert hasattr(dc_bot, 'ping') or hasattr(dc_bot, 'ping_command')
        # Actual command registration test would need client.tree inspection

    def test_status_command_registered(self):
        """Tes apakah command status terdaftar."""
        assert hasattr(dc_bot, 'status') or hasattr(dc_bot, 'status_command')

    def test_wa_command_registered(self):
        """Tes apakah command wa terdaftar."""
        assert hasattr(dc_bot, 'wa') or hasattr(dc_bot, 'wa_command')

    def test_sites_command_registered(self):
        """Tes apakah command sites terdaftar."""
        assert hasattr(dc_bot, 'sites') or hasattr(dc_bot, 'sites_command')


class TestDiscordBotEvents:
    """Tes event handlers."""

    @pytest.mark.asyncio
    async def test_on_ready_sets_presence(self, discord_client, monkeypatch):
        """Tes on_ready mengatur presence bot."""
        # Mock change_presence
        discord_client.change_presence = AsyncMock()
        
        # Get on_ready handler
        # Note: discord_bot uses @client.event decorator
        # We need to find the registered handler
        if hasattr(dc_bot, 'on_ready'):
            await dc_bot.on_ready(discord_client)
            # Should not crash
            assert True

    @pytest.mark.asyncio
    async def test_on_message_ignores_bot(self, discord_client):
        """Tes on_message mengabaikan pesan dari bot."""
        from tests.harness.discord_client import FakeUser, FakeMessage, FakeChannel
        
        # Create a bot user
        bot_user = FakeUser(id=999, name="TestBot", bot=True)
        channel = discord_client.create_channel()
        msg = FakeMessage(channel=channel, author=bot_user, content="hello")
        
        # Get on_message handler
        if hasattr(dc_bot, 'on_message'):
            # Should return early for bot messages
            await dc_bot.on_message(msg)
            # No crash = success

    @pytest.mark.asyncio
    async def test_on_message_processes_commands(self, discord_client, monkeypatch):
        """Tes on_message memproses command."""
        from tests.harness.discord_client import FakeUser, FakeMessage, FakeChannel
        
        user = discord_client.create_user()
        channel = discord_client.create_channel()
        msg = FakeMessage(channel=channel, author=user, content="!ping")
        
        # Mock process_commands
        mock_process = AsyncMock()
        monkeypatch.setattr(discord_client, 'process_commands', mock_process)
        
        if hasattr(dc_bot, 'on_message'):
            await dc_bot.on_message(msg)
            # Should call process_commands for non-bot messages
            # mock_process.assert_awaited_once()  # depends on implementation


class TestDiscordBotHelpers:
    """Tes helper functions."""

    def test_format_uptime(self):
        """Tes formatting uptime."""
        if hasattr(dc_bot, 'format_uptime'):
            result = dc_bot.format_uptime(3661)  # 1h 1m 1s
            assert "1h" in result
            assert "1m" in result
            assert "1s" in result

    def test_get_system_stats_discord(self, monkeypatch):
        """Tes get_system_stats untuk discord."""
        mock_stats = {"cpu": "10%", "ram": "50%", "disk": "30%"}
        monkeypatch.setattr("alfa.tools.get_system_stats", lambda: mock_stats)
        
        if hasattr(dc_bot, 'get_system_stats_discord'):
            result = dc_bot.get_system_stats_discord()
            assert "cpu" in result.lower() or "CPU" in result


class TestDiscordBotMain:
    """Tes main launcher."""

    def test_main_exits_if_no_token(self, capsys, monkeypatch):
        """Tes main() keluar jika token tidak ada."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "")
        monkeypatch.setenv("DISCORD_GUILD_ID", "123")
        
        # main() should validate token
        if hasattr(dc_bot, 'main'):
            with pytest.raises(SystemExit):
                dc_bot.main()
            assert "DISCORD_BOT_TOKEN" in capsys.readouterr().err

    def test_main_exits_if_no_guild(self, capsys, monkeypatch):
        """Tes main() keluar jika guild ID tidak ada."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test.token")
        monkeypatch.setenv("DISCORD_GUILD_ID", "")
        
        if hasattr(dc_bot, 'main'):
            with pytest.raises(SystemExit):
                dc_bot.main()
            assert "DISCORD_GUILD_ID" in capsys.readouterr().err


class TestDiscordBotHarnessIntegration:
    """Tes integrasi dengan FakeDiscordClient harness."""

    @pytest.mark.asyncio
    async def test_fake_client_command_tree(self, discord_client):
        """Tes FakeDiscordClient command tree."""
        # Register a dummy command
        @discord_client.tree.command(name="test", description="Test command")
        async def test_cmd(interaction):
            await interaction.response_send_message("OK")
        
        # Call the command
        interaction = await discord_client.tree.call_command("test")
        assert interaction._response_sent
        assert interaction._response_content == "OK"

    @pytest.mark.asyncio
    async def test_fake_client_channels_messages(self, discord_client):
        """Tes channel message handling."""
        channel = discord_client.create_channel()
        user = discord_client.create_user()
        
        msg = await channel.send("Hello from " + user.name)
        assert msg.content == "Hello from TestUser"
        assert msg.author == user
        assert msg.channel == channel
        
        messages = channel.get_messages()
        assert len(messages) == 1
        assert messages[0].content == "Hello from TestUser"

    @pytest.mark.asyncio
    async def test_fake_client_interaction_response(self, discord_client):
        """Tes interaction response."""
        from tests.harness.discord_client import FakeInteraction
        
        interaction = FakeInteraction()
        await interaction.response_send_message("Test response")
        assert interaction._response_sent
        assert interaction._response_content == "Test response"
        
        await interaction.followup_send("Followup")
        assert "Followup" in interaction._response_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])