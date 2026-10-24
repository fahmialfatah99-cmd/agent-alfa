"""Unit tests for debounced Telegram forward-message batch collector in ALFA."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alfa.bot.handlers import (
    _FORWARD_BATCHES,
    _RECENT_FORWARD_BATCHES,
    get_forward_info,
    handle_forward_action_callback,
    handle_text_message,
)


class TestForwardInfoDetection:
    def test_normal_message_returns_none(self):
        msg = MagicMock()
        msg.forward_origin = None
        msg.forward_date = None
        msg.forward_from = None
        msg.forward_from_chat = None
        msg.forward_sender_name = None
        assert get_forward_info(msg) is None

    def test_modern_origin_user(self):
        msg = MagicMock()
        origin = MagicMock()
        origin.type = "user"
        origin.sender_user.full_name = "Pak Budi"
        origin.sender_user.username = "budi_test"
        msg.forward_origin = origin
        info = get_forward_info(msg)
        assert info is not None
        assert info["sender"] == "Pak Budi"

    def test_modern_origin_hidden_user(self):
        msg = MagicMock()
        origin = MagicMock()
        origin.type = "hidden_user"
        origin.sender_user = None
        origin.sender_user_name = "Pengguna Rahasia"
        msg.forward_origin = origin
        info = get_forward_info(msg)
        assert info is not None
        assert info["sender"] == "Pengguna Rahasia"

    def test_modern_origin_chat_or_channel(self):
        msg = MagicMock()
        origin = MagicMock()
        origin.type = "channel"
        origin.sender_user = None
        origin.sender_user_name = None
        origin.chat.title = "Grup Koordinasi Proyek"
        msg.forward_origin = origin
        info = get_forward_info(msg)
        assert info is not None
        assert info["sender"] == "Grup Koordinasi Proyek"

    def test_legacy_forward(self):
        msg = MagicMock()
        msg.forward_origin = None
        msg.forward_date = 1700000000
        msg.forward_from.full_name = "Mas Agus"
        info = get_forward_info(msg)
        assert info is not None
        assert info["sender"] == "Mas Agus"


@pytest.mark.asyncio
class TestForwardBatchCollector:
    async def test_debounced_batching_sends_only_one_question(self):
        chat_id = 998877
        user_id = 123456

        # Clear state
        _FORWARD_BATCHES.pop(chat_id, None)
        _RECENT_FORWARD_BATCHES.pop(chat_id, None)

        sent_messages = []

        async def mock_safe_send(ctx, cid, text, reply_markup=None, **kwargs):
            sent_messages.append({"chat_id": cid, "text": text, "reply_markup": reply_markup})

        # Create 3 mock forwarded messages arriving in rapid succession
        context = MagicMock()

        with patch("alfa.bot.handlers._is_authorized", return_value=True), \
             patch("alfa.bot.handlers.safe_send_message", side_effect=mock_safe_send):

            for i in range(1, 4):
                up = MagicMock()
                up.effective_chat.id = chat_id
                up.effective_user.id = user_id
                up.message.text = f"Pesan penting bagian ke-{i}"
                up.message.message_id = 1000 + i
                origin = MagicMock()
                origin.type = "user"
                origin.sender_user.full_name = "Pak Budi"
                up.message.forward_origin = origin

                await handle_text_message(up, context)

            # Sesaat setelah pesan masuk: belum ada balasan terkirim karena sedang debounce
            assert len(sent_messages) == 0
            assert chat_id in _FORWARD_BATCHES
            assert len(_FORWARD_BATCHES[chat_id]["items"]) == 3

            # Tunggu waktu debounce selesai (1.8s + toleransi)
            await asyncio.sleep(2.0)

            # Setelah debounce selesai: tepat 1 pesan pertanyaan dengan 4 tombol inline terkirim
            assert len(sent_messages) == 1
            sent = sent_messages[0]
            assert "3 pesan terusan" in sent["text"]
            assert "Pak Budi" in sent["text"]
            assert "Mau diapakan nih?" in sent["text"]
            assert sent["reply_markup"] is not None

            # Pastikan tersimpan di _RECENT_FORWARD_BATCHES
            assert chat_id in _RECENT_FORWARD_BATCHES
            assert _RECENT_FORWARD_BATCHES[chat_id]["count"] == 3

    async def test_clicking_action_button_runs_agent(self):
        chat_id = 998877
        user_id = 123456

        _RECENT_FORWARD_BATCHES[chat_id] = {
            "count": 2,
            "senders": ["Pak Budi"],
            "senders_str": "Pak Budi",
            "full_text": "[1. Dari: Pak Budi]\nHalo rapat besok\n\n[2. Dari: Pak Budi]\nJam 9 pagi di kantor",
            "user_id": user_id,
            "context": MagicMock(),
            "created_at": asyncio.get_event_loop().time(),
            "consumed": False,
        }

        up = MagicMock()
        up.effective_chat.id = chat_id
        up.effective_user.id = user_id
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock())

        with patch("alfa.bot.handlers._run_agent_turn", new_callable=AsyncMock) as mock_run, \
             patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock) as mock_send, \
             patch("alfa.bot.handlers._check_and_send_media_artifacts", new_callable=AsyncMock):
            mock_run.return_value = "Ini ringkasan rapat jam 9 pagi."

            res = await handle_forward_action_callback(up, context, "fwdact:summarize")
            assert res is True
            assert mock_run.called
            call_kwargs = mock_run.call_args.kwargs
            assert "Rangkum seluruh poin penting" in call_kwargs["user_prompt"]
            assert "Jam 9 pagi di kantor" in call_kwargs["user_prompt"]
            assert mock_send.called
            assert _RECENT_FORWARD_BATCHES[chat_id]["consumed"] is True

    async def test_user_types_text_during_forward_debounce(self):
        chat_id = 998878
        user_id = 123456

        _FORWARD_BATCHES.pop(chat_id, None)
        _RECENT_FORWARD_BATCHES.pop(chat_id, None)

        context = MagicMock()

        with patch("alfa.bot.handlers._is_authorized", return_value=True), \
             patch("alfa.bot.handlers._run_agent_turn", new_callable=AsyncMock) as mock_run, \
             patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock), \
             patch("alfa.bot.handlers._check_and_send_media_artifacts", new_callable=AsyncMock), \
             patch("alfa.bot.handlers.TelegramStreamer") as mock_streamer_cls:

            mock_streamer = AsyncMock()
            mock_streamer_cls.return_value = mock_streamer
            mock_run.return_value = "Ini hasil analisis pesan terusan."

            # 1. Kirim pesan terusan
            up_fwd = MagicMock()
            up_fwd.effective_chat.id = chat_id
            up_fwd.effective_user.id = user_id
            up_fwd.message.text = "Harga per unit 50rb minimal order 10"
            up_fwd.message.message_id = 2001
            origin = MagicMock()
            origin.type = "user"
            origin.sender_user.full_name = "Supplier A"
            up_fwd.message.forward_origin = origin

            await handle_text_message(up_fwd, context)
            assert chat_id in _FORWARD_BATCHES

            # 2. Pengguna langsung mengetik pesan instruksi tanpa menunggu 1.8s
            up_text = MagicMock()
            up_text.effective_chat.id = chat_id
            up_text.effective_user.id = user_id
            up_text.message.text = "Tolong rangkumkan penawaran di atas"
            up_text.message.message_id = 2002
            up_text.message.forward_origin = None
            up_text.message.forward_date = None
            up_text.message.forward_from = None
            up_text.message.forward_from_chat = None
            up_text.message.forward_sender_name = None

            await handle_text_message(up_text, context)

            # Debounce harus langsung dibatalkan, batch di-merge ke prompt agent
            assert chat_id not in _FORWARD_BATCHES
            assert mock_run.called
            call_prompt = mock_run.call_args.kwargs["user_prompt"]
            assert "Supplier A" in call_prompt
            assert "Harga per unit 50rb minimal order 10" in call_prompt
            assert "Tolong rangkumkan penawaran di atas" in call_prompt

    async def test_normal_text_message_unaffected(self):
        chat_id = 998879
        user_id = 123456

        _FORWARD_BATCHES.pop(chat_id, None)
        _RECENT_FORWARD_BATCHES.pop(chat_id, None)

        context = MagicMock()

        with patch("alfa.bot.handlers._is_authorized", return_value=True), \
             patch("alfa.bot.handlers._run_agent_turn", new_callable=AsyncMock) as mock_run, \
             patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock), \
             patch("alfa.bot.handlers._check_and_send_media_artifacts", new_callable=AsyncMock), \
             patch("alfa.bot.handlers.TelegramStreamer") as mock_streamer_cls:

            mock_streamer = AsyncMock()
            mock_streamer_cls.return_value = mock_streamer
            mock_run.return_value = "Cuaca besok cerah berawan."

            up = MagicMock()
            up.effective_chat.id = chat_id
            up.effective_user.id = user_id
            up.message.text = "Bagaimana perkiraan cuaca besok?"
            up.message.message_id = 3001
            up.message.forward_origin = None
            up.message.forward_date = None
            up.message.forward_from = None
            up.message.forward_from_chat = None
            up.message.forward_sender_name = None

            await handle_text_message(up, context)

            assert chat_id not in _FORWARD_BATCHES
            assert mock_run.called
            call_prompt = mock_run.call_args.kwargs["user_prompt"]
            # Normal prompt murni tanpa prefix pesan terusan
            assert call_prompt == "Bagaimana perkiraan cuaca besok?"

    async def test_debounced_photo_batching(self):
        from alfa.bot.handlers import _PHOTO_BATCHES, handle_photo_message

        chat_id = 998880
        user_id = 123456
        _PHOTO_BATCHES.pop(chat_id, None)

        context = MagicMock()
        context.bot.get_file = AsyncMock()
        mock_file = AsyncMock()
        mock_file.download_to_memory = AsyncMock()
        context.bot.get_file.return_value = mock_file

        with patch("alfa.bot.handlers._is_authorized", return_value=True), \
             patch("alfa.bot.handlers._run_agent_turn", new_callable=AsyncMock) as mock_run, \
             patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock) as mock_send, \
             patch("alfa.bot.handlers._check_and_send_media_artifacts", new_callable=AsyncMock), \
             patch("alfa.tools.filesystem.universal_file_extractor.process_uploaded_attachment", return_value=("ctx", None)):

            mock_run.return_value = "Ini laporan 3 foto gabungan."

            # Kirim 3 foto beruntun
            for i in range(1, 4):
                up = MagicMock()
                up.effective_chat.id = chat_id
                up.effective_user.id = user_id
                photo_obj = MagicMock()
                photo_obj.file_id = f"file_id_{i}"
                up.message.photo = [photo_obj]
                up.message.caption = f"Foto dokumen {i}"

                await handle_photo_message(up, context)

            # Sedang debounce
            assert chat_id in _PHOTO_BATCHES
            assert len(_PHOTO_BATCHES[chat_id]["photos"]) == 3

            # Tunggu debounce selesai (1.8s + toleransi)
            await asyncio.sleep(2.0)

            # Setelah debounce selesai: tepat 1 turn dieksekusi dengan prompt multi-foto
            assert mock_run.call_count == 1
            prompt_called = mock_run.call_args.kwargs["user_prompt"]
            assert "KUMPULAN 3 FOTO/GAMBAR DIUNGGAH SEKALIGUS" in prompt_called
            assert mock_send.called

