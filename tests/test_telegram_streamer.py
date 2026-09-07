"""Unit tests for TelegramStreamer progressive streaming response engine.

Tests rate-limit dampening (1.2s interval), exception suppression for
Telegram errors (Message is not modified, Message to edit not found),
RetryAfter backoff, and finalize() completion.
"""
import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram.error import BadRequest, RetryAfter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.bot.telegram_bot import TelegramStreamer, handle_text_message, run_agent_turn


def _run(coro):
    """Helper to run coroutines synchronously in pytest."""
    return asyncio.run(coro)


@pytest.fixture
def mock_context():
    """Mock Telegram ContextTypes.DEFAULT_TYPE with an async bot."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock(
        return_value=MagicMock(message_id=12345)
    )
    context.bot.edit_message_text = AsyncMock(
        return_value=MagicMock(message_id=12345)
    )
    return context


class TestTelegramStreamer:
    def test_streamer_initialization(self, mock_context):
        """Check default parameters and initial state of TelegramStreamer."""
        streamer = TelegramStreamer(context=mock_context, chat_id=999)
        assert streamer.chat_id == 999
        assert streamer.initial_text == "💭 Sedang berpikir..."
        assert streamer.min_edit_interval == 1.2
        assert streamer.message_id is None
        assert streamer.buffer == ""
        assert streamer.is_done is False

    def test_streamer_start_sends_placeholder(self, mock_context):
        """start() sends placeholder message and stores message_id."""
        streamer = TelegramStreamer(
            context=mock_context,
            chat_id=999,
            initial_text="Sedang mengetik...",
        )
        msg_id = _run(streamer.start())

        assert msg_id == 12345
        assert streamer.message_id == 12345
        mock_context.bot.send_message.assert_called_once_with(
            chat_id=999,
            text="Sedang mengetik...",
        )

    def test_push_chunk_rate_limit_throttling(self, mock_context):
        """push_chunk() throttles edits to respect min_edit_interval (e.g. 1.2s)."""
        streamer = TelegramStreamer(
            context=mock_context,
            chat_id=999,
            min_edit_interval=1.2,
        )

        current_time = 100.0

        def fake_monotonic():
            return current_time

        with patch("time.monotonic", side_effect=fake_monotonic):
            _run(streamer.start())
            mock_context.bot.edit_message_text.reset_mock()

            # Push chunk 1 at t=100.3 (0.3s elapsed < 1.2s) -> throttled, no edit
            current_time = 100.3
            _run(streamer.push_chunk("Halo"))
            assert streamer.buffer == "Halo"
            assert mock_context.bot.edit_message_text.call_count == 0

            # Push chunk 2 at t=100.8 (0.8s elapsed < 1.2s) -> throttled, no edit
            current_time = 100.8
            _run(streamer.push_chunk(" dunia"))
            assert streamer.buffer == "Halo dunia"
            assert mock_context.bot.edit_message_text.call_count == 0

            # Push chunk 3 at t=101.3 (1.3s elapsed >= 1.2s) -> edit triggered!
            current_time = 101.3
            _run(streamer.push_chunk("!"))
            assert streamer.buffer == "Halo dunia!"
            assert mock_context.bot.edit_message_text.call_count == 1
            call_args = mock_context.bot.edit_message_text.call_args[1]
            assert "Halo dunia! ▌" in call_args["text"]

            # Push chunk 4 at t=101.6 (0.3s since last edit < 1.2s) -> throttled
            current_time = 101.6
            _run(streamer.push_chunk(" Lagi"))
            assert mock_context.bot.edit_message_text.call_count == 1

            # Push chunk 5 at t=102.6 (1.3s since last edit >= 1.2s) -> second edit!
            current_time = 102.6
            _run(streamer.push_chunk(" tes."))
            assert mock_context.bot.edit_message_text.call_count == 2
            call_args2 = mock_context.bot.edit_message_text.call_args[1]
            assert "Halo dunia! Lagi tes. ▌" in call_args2["text"]

    def test_swallow_message_not_modified(self, mock_context):
        """'Message is not modified' Telegram BadRequest is safely swallowed."""
        mock_context.bot.edit_message_text.side_effect = BadRequest(
            "Message is not modified: specified new message content and reply markup are exactly the same"
        )
        streamer = TelegramStreamer(context=mock_context, chat_id=999, min_edit_interval=1.0)

        current_time = 200.0

        with patch("time.monotonic", side_effect=lambda: current_time):
            _run(streamer.start())
            current_time = 202.0
            # Should not raise exception
            _run(streamer.push_chunk("Sama persis"))
            assert streamer.buffer == "Sama persis"

    def test_swallow_message_to_edit_not_found(self, mock_context):
        """'Message to edit not found' Telegram BadRequest is safely caught without crash."""
        mock_context.bot.edit_message_text.side_effect = BadRequest("Message to edit not found")
        streamer = TelegramStreamer(context=mock_context, chat_id=999, min_edit_interval=1.0)

        current_time = 300.0

        with patch("time.monotonic", side_effect=lambda: current_time):
            _run(streamer.start())
            current_time = 302.0
            # Should not raise exception
            _run(streamer.push_chunk("Dihapus"))
            assert streamer.buffer == "Dihapus"

    def test_rate_limit_retry_after_triggers_backoff(self, mock_context):
        """RetryAfter (HTTP 429) triggers safe backoff and delays subsequent edits."""
        mock_context.bot.edit_message_text.side_effect = RetryAfter(retry_after=5)
        streamer = TelegramStreamer(context=mock_context, chat_id=999, min_edit_interval=1.0)

        current_time = 400.0

        def fake_monotonic():
            return current_time

        with patch("time.monotonic", side_effect=fake_monotonic):
            _run(streamer.start())

            # First edit triggers 429 RetryAfter 5s
            current_time = 402.0
            _run(streamer.push_chunk("Chunk 1"))
            assert streamer.backoff_until >= 407.0

            # Reset side effect for subsequent attempts
            mock_context.bot.edit_message_text.side_effect = None
            mock_context.bot.edit_message_text.reset_mock()

            # Next chunk at t=404.0 (< backoff_until 407.0) -> throttled by backoff
            current_time = 404.0
            _run(streamer.push_chunk(" Chunk 2"))
            assert mock_context.bot.edit_message_text.call_count == 0

            # Next chunk at t=408.0 (> backoff_until 407.0 and > last_edit + 1.0) -> edit allowed!
            current_time = 408.0
            _run(streamer.push_chunk(" Chunk 3"))
            assert mock_context.bot.edit_message_text.call_count == 1
            call_args = mock_context.bot.edit_message_text.call_args[1]
            assert "Chunk 1 Chunk 2 Chunk 3 ▌" in call_args["text"]

    def test_finalize_always_pushes_final_text(self, mock_context):
        """finalize() always pushes the final complete text without cursor, and marks done."""
        streamer = TelegramStreamer(context=mock_context, chat_id=999)
        _run(streamer.start())

        final_content = "Ini adalah kesimpulan akhir yang sangat rapi."
        _run(streamer.finalize(final_content))

        assert streamer.is_done is True
        # Verify edit_message_text was called with final content (no cursor ' ▌')
        mock_context.bot.edit_message_text.assert_called_with(
            chat_id=999,
            message_id=12345,
            text=final_content,
            parse_mode=pytest.importorskip("telegram.constants").ParseMode.MARKDOWN,
        )

        # Subsequent push_chunk after finalize is ignored
        mock_context.bot.edit_message_text.reset_mock()
        _run(streamer.push_chunk("abaikan"))
        assert mock_context.bot.edit_message_text.call_count == 0

    def test_finalize_fallback_when_start_failed(self, mock_context):
        """If start() failed (no message_id), finalize() falls back to send_message."""
        mock_context.bot.send_message.side_effect = [
            Exception("Network timeout on start"),
            MagicMock(message_id=99999),
        ]
        streamer = TelegramStreamer(context=mock_context, chat_id=999)
        msg_id = _run(streamer.start())
        assert msg_id is None
        assert streamer.message_id is None

        # finalize should fall back to safe_send_message / send_message
        _run(streamer.finalize("Pesan alternatif."))
        assert streamer.is_done is True
        assert mock_context.bot.send_message.call_count == 2
        last_call_args = mock_context.bot.send_message.call_args[1]
        assert last_call_args["text"] == "Pesan alternatif."

    def test_finalize_splits_long_message(self, mock_context):
        """If final text exceeds Telegram limits (>3900 chars), first chunk edits in place and remainder sends."""
        streamer = TelegramStreamer(context=mock_context, chat_id=999)
        _run(streamer.start())

        long_text = "A" * 4000 + "\n\n" + "B" * 500
        _run(streamer.finalize(long_text))

        # First chunk edited
        assert mock_context.bot.edit_message_text.called
        # Second chunk sent
        assert mock_context.bot.send_message.call_count >= 2


class TestHandleTextMessageStreamingIntegration:
    def test_handle_text_message_uses_streamer(self, mock_context):
        """handle_text_message uses TelegramStreamer and completes with agent reply."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "Jelaskan arsitektur bot"
        update.effective_user.id = 111
        update.effective_chat.id = 222

        with patch("alfa.bot.telegram_bot.is_authorized", return_value=True), \
             patch("alfa.bot.telegram_bot.run_agent_turn", new_callable=AsyncMock) as mock_agent_turn, \
             patch("alfa.bot.telegram_bot.check_and_send_media_artifacts", new_callable=AsyncMock), \
             patch("alfa.bot.telegram_bot.database.get_user_settings", new_callable=AsyncMock, return_value={"voice_reply": False}):

            mock_agent_turn.return_value = "Arsitektur bot menggunakan arsitektur modular event-driven."

            _run(handle_text_message(update, mock_context))

            # Verify run_agent_turn was called with user_prompt and streamer
            mock_agent_turn.assert_called_once()
            _, kwargs = mock_agent_turn.call_args
            assert kwargs.get("user_prompt") == "Jelaskan arsitektur bot"
            assert "streamer" in kwargs
            streamer_arg = kwargs.get("streamer")
            assert isinstance(streamer_arg, TelegramStreamer)
            assert streamer_arg.is_done is True
            # edit_message_text was called with final text
            assert mock_context.bot.edit_message_text.called
            edit_text = mock_context.bot.edit_message_text.call_args[1]["text"]
            assert "Arsitektur bot menggunakan arsitektur modular event-driven." in edit_text

    def test_handle_text_message_fallback_on_streamer_failure(self, mock_context):
        """If TelegramStreamer fails, handle_text_message gracefully falls back to safe_send_message."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "Tes error streamer"
        update.effective_user.id = 111
        update.effective_chat.id = 222

        mock_context.bot.send_message.side_effect = [
            Exception("Cannot send placeholder"),  # Streamer.start() fails
            MagicMock(message_id=888),  # Fallback safe_send_message
        ]

        with patch("alfa.bot.telegram_bot.is_authorized", return_value=True), \
             patch("alfa.bot.telegram_bot.run_agent_turn", new_callable=AsyncMock) as mock_agent_turn, \
             patch("alfa.bot.telegram_bot.check_and_send_media_artifacts", new_callable=AsyncMock), \
             patch("alfa.bot.telegram_bot.database.get_user_settings", new_callable=AsyncMock, return_value={"voice_reply": False}):

            mock_agent_turn.return_value = "Jawaban berhasil via jalur fallback."

            _run(handle_text_message(update, mock_context))

            # The fallback message should have been sent
            assert mock_context.bot.send_message.call_count >= 2
            final_call = mock_context.bot.send_message.call_args_list[-1]
            assert "Jawaban berhasil via jalur fallback." in final_call[1]["text"]


class TestRunAgentTurnStreaming:
    def test_run_agent_turn_streams_to_streamer(self):
        """run_agent_turn streams chunks into streamer.push_chunk when streamer is passed."""
        chunk1 = MagicMock()
        chunk1.text = "Selamat "
        chunk1.candidates = []
        chunk2 = MagicMock()
        chunk2.text = "pagi!"
        chunk2.candidates = []

        async def fake_stream(*args, **kwargs):
            for c in [chunk1, chunk2]:
                yield c

        mock_gemini = MagicMock()
        mock_gemini.aio.models.generate_content_stream = AsyncMock(side_effect=fake_stream)

        mock_streamer = MagicMock()
        mock_streamer.push_chunk = AsyncMock()

        with patch("alfa.bot.telegram_bot.resolve_main_gemini", return_value=(mock_gemini, 1, "vault#1")), \
             patch("alfa.bot.telegram_bot.main_brain.get_main_brain", return_value={"provider": "gemini", "model": "gemini-3.6-flash", "label": "test"}), \
             patch("alfa.bot.telegram_bot.database.get_recent_chat_history", new_callable=AsyncMock, return_value=[]), \
             patch("alfa.bot.telegram_bot.database.get_all_memories", new_callable=AsyncMock, return_value=[]), \
             patch("alfa.bot.telegram_bot.database.get_all_knowledge_graph_sync", return_value=[]), \
             patch("alfa.bot.telegram_bot.database.get_user_settings", new_callable=AsyncMock, return_value={}), \
             patch("alfa.bot.telegram_bot.database.save_chat_message", new_callable=AsyncMock), \
             patch("alfa.bot.telegram_bot.permission_gate.make_gate", return_value=None):

            result = _run(run_agent_turn(
                user_id=101,
                user_prompt="Halo bot",
                streamer=mock_streamer
            ))

            assert "Selamat pagi!" in result
            assert mock_streamer.push_chunk.call_count == 2
            assert mock_streamer.push_chunk.call_args_list[0][0][0] == "Selamat "
            assert mock_streamer.push_chunk.call_args_list[1][0][0] == "pagi!"

    def test_run_agent_turn_streaming_fallback_to_generate_content(self):
        """If generate_content_stream fails, it falls back to non-streaming generate_content."""
        mock_gemini = MagicMock()
        mock_gemini.aio.models.generate_content_stream = AsyncMock(side_effect=Exception("Stream connection reset"))

        mock_resp = MagicMock()
        mock_resp.text = "Jawaban dari generate_content fallback"
        mock_resp.candidates = []
        mock_gemini.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        mock_streamer = MagicMock()
        mock_streamer.push_chunk = AsyncMock()

        with patch("alfa.bot.telegram_bot.resolve_main_gemini", return_value=(mock_gemini, 1, "vault#1")), \
             patch("alfa.bot.telegram_bot.main_brain.get_main_brain", return_value={"provider": "gemini", "model": "gemini-3.6-flash", "label": "test"}), \
             patch("alfa.bot.telegram_bot.database.get_recent_chat_history", new_callable=AsyncMock, return_value=[]), \
             patch("alfa.bot.telegram_bot.database.get_all_memories", new_callable=AsyncMock, return_value=[]), \
             patch("alfa.bot.telegram_bot.database.get_all_knowledge_graph_sync", return_value=[]), \
             patch("alfa.bot.telegram_bot.database.get_user_settings", new_callable=AsyncMock, return_value={}), \
             patch("alfa.bot.telegram_bot.database.save_chat_message", new_callable=AsyncMock), \
             patch("alfa.bot.telegram_bot.permission_gate.make_gate", return_value=None):

            result = _run(run_agent_turn(
                user_id=101,
                user_prompt="Halo bot",
                streamer=mock_streamer
            ))

            assert "Jawaban dari generate_content fallback" in result
            mock_gemini.aio.models.generate_content.assert_called_once()

