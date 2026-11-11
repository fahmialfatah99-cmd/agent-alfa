"""Tes untuk `alfa/bot/handlers/messages.py` (jalur pesan utama bot).

Hermetik: tidak ada jaringan, tidak ada Telegram API nyata. Semua titik
potong dipatch pada modul sumbernya (import di dalam fungsi = lazy import,
jadi patch pada atribut modul sumber tetap berlaku).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _mk_msg(text: str = "tes", *, has_document: bool = False, has_voice: bool = False):
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = 222
    msg.from_user = MagicMock()
    msg.from_user.id = 111
    msg.document = MagicMock() if has_document else None
    msg.voice = MagicMock() if has_voice else None
    msg.message_id = 7
    # pesan biasa (bukan terusan) — atribut forward harus None, bukan mock
    msg.forward_from = None
    msg.forward_from_chat = None
    msg.forward_sender_name = None
    msg.forward_date = None
    msg.forward_origin = None
    return msg


def _mk_update(text: str = "tes", **kw):
    up = MagicMock()
    up.message = _mk_msg(text, **kw)
    up.effective_chat = MagicMock()
    up.effective_chat.id = 222
    up.effective_user = MagicMock()
    up.effective_user.id = 111
    return up


def _mk_context():
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


class TestTryHandleFastWA:
    async def test_wamasuk_trigger_invokes_command(self, monkeypatch):
        from alfa.bot.handlers import messages as m

        called = {}

        async def _fake_wamasuk(update, context):
            called["yes"] = True

        monkeypatch.setattr("alfa.bot.advanced_commands.wamasuk_command", _fake_wamasuk)
        monkeypatch.setattr("alfa.bot.handlers.database.save_chat_message", AsyncMock())

        handled = await m.try_handle_fast_wa(_mk_update("cek wa masuk"), _mk_context(), "cek wa masuk")
        assert handled is True
        assert called.get("yes") is True

    async def test_clear_history_clears_buffer_and_notifies(self, monkeypatch):
        from alfa.bot.handlers import messages as m

        cleared = {}

        def _fake_clear(**kwargs):
            cleared.update(kwargs)

        sent: list[str] = []

        async def _fake_send(context, chat_id, text, **kw):
            sent.append(text)

        monkeypatch.setattr("alfa.tools.wa_clear_history", _fake_clear)
        monkeypatch.setattr("alfa.bot.handlers.safe_send_message", _fake_send)
        monkeypatch.setattr("alfa.bot.handlers.database.save_chat_message", AsyncMock())

        handled = await m.try_handle_fast_wa(
            _mk_update("hapus riwayat wa"), _mk_context(), "hapus riwayat wa"
        )
        assert handled is True
        assert cleared.get("target") == "all"
        assert sent and "Riwayat pesan WhatsApp" in sent[0]

    async def test_unrelated_text_is_not_handled(self):
        from alfa.bot.handlers import messages as m

        handled = await m.try_handle_fast_wa(_mk_update("halo"), _mk_context(), "halo")
        assert handled is False


class TestHandleTextMessage:
    async def test_unauthorized_user_gets_denial(self, monkeypatch):
        from alfa.bot.handlers import messages as m

        sent: list[str] = []

        async def _fake_send(context, chat_id, text, **kw):
            sent.append(text)

        monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda uid: False)
        monkeypatch.setattr("alfa.bot.handlers.safe_send_message", _fake_send)

        await m.handle_text_message(_mk_update("halo"), _mk_context())
        assert sent and "ditolak" in sent[0].lower()

    async def test_greeting_is_answered_instantly(self, monkeypatch):
        """Sapaan dijawab tanpa agent turn (hemat token)."""
        from alfa.bot.handlers import messages as m

        sent: list[str] = []
        agent_called = []

        async def _fake_send(context, chat_id, text, **kw):
            sent.append(text)

        async def _fake_turn(*args, **kwargs):
            agent_called.append(kwargs)
            return "jawaban agent"

        monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda uid: True)
        monkeypatch.setattr("alfa.bot.handlers.safe_send_message", _fake_send)
        monkeypatch.setattr("alfa.bot.handlers._run_agent_turn", _fake_turn)
        monkeypatch.setattr("alfa.bot.handlers.database.save_chat_message", AsyncMock())

        await m.handle_text_message(_mk_update("halo"), _mk_context())
        assert sent, "sapaan tidak dijawab"
        assert "ALFA" in sent[0], "balasan harus sapaan, bukan penolakan/guguran"
        assert not agent_called, "sapaan seharusnya tidak lewat agent turn"

    async def test_rekap_material_fastpath_uses_tool(self, monkeypatch):
        """'rekap material lahat' memakai tool rekap + menyertakan catatan basi."""
        from alfa.bot.handlers import messages as m

        sent: list[dict] = []

        async def _fake_send(context, chat_id, text, **kw):
            sent.append({"chat_id": chat_id, "text": text})

        def _fake_rekap(**kwargs):
            return {
                "status": "success",
                "total_net": 160,
                "total_bruto": 175,
                "total_retur": 15,
                "mandors": ["Mandor Mugi"],
                "breakdown": {"T73": 94},
                "total_cable_m": 0,
                "cable_breakdown": {},
                "accessories_breakdown": {},
                "excel_file": "/tmp/rekap.xlsx",
                "data_freshness": {
                    "stale": True,
                    "newest_message_at": "2026-11-01T10:00:00",
                    "reasons": ["pesan terakhir berumur 200 jam"],
                },
                "warning": "⚠️ DATA BERIKUTNYA MUNGKIN BASI",
            }

        monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda uid: True)
        monkeypatch.setattr("alfa.bot.handlers.safe_send_message", _fake_send)
        monkeypatch.setattr(
            "alfa.tools.telecom_tools.reconcile_whatsapp_material_group", _fake_rekap
        )
        monkeypatch.setattr("alfa.bot.handlers.database.save_chat_message", AsyncMock())

        await m.handle_text_message(_mk_update("rekap material lahat"), _mk_context())
        assert sent, "kartu rekap tidak terkirim"
        card = sent[-1]["text"]
        assert "REKAPITULASI MATERIAL MASTER LAHAT" in card
        assert "MUNGKIN BASI" in card

    async def test_normal_message_goes_through_agent(self, monkeypatch):
        from alfa.bot.handlers import messages as m

        sent: list[str] = []
        prompts: list[str] = []

        async def _fake_send(context, chat_id, text, **kw):
            sent.append(text)

        async def _fake_turn(*args, **kwargs):
            prompts.append(str(kwargs.get("user_prompt", "")))
            return "jawaban dari agent"

        class _Streamer:
            def __init__(self, context=None, chat_id=None, initial_text=None):
                self.chat_id = chat_id

            async def start(self):
                return None

            async def push(self, chunk):
                return None

            async def finalize(self, text):
                sent.append(text)

        monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda uid: True)
        monkeypatch.setattr("alfa.bot.handlers.safe_send_message", _fake_send)
        monkeypatch.setattr("alfa.bot.handlers._run_agent_turn", _fake_turn)
        monkeypatch.setattr("alfa.bot.handlers.TelegramStreamer", _Streamer)
        monkeypatch.setattr("alfa.bot.handlers.database.save_chat_message", AsyncMock())
        monkeypatch.setattr(
            "alfa.core.apex.try_execute_compiled_fastpath", lambda text: None
        )
        monkeypatch.setattr(
            "alfa.core.apex.analyze_field_event_preemptively", lambda text, **kw: {}
        )
        monkeypatch.setattr("alfa.core.apex.ingest_text_to_temporal_graph", lambda text: None)

        await m.handle_text_message(_mk_update("berapa total tiang?"), _mk_context())
        assert prompts, "agent turn tidak dipanggil"
        assert any("jawaban dari agent" in s for s in sent)


class TestStaleNotice:
    def test_no_warning_returns_empty(self):
        from alfa.bot.handlers.messages import _wa_stale_notice

        assert _wa_stale_notice({}) == ""
        assert _wa_stale_notice({"warning": ""}) == ""

    def test_warning_is_formatted_with_timestamp(self):
        from alfa.bot.handlers.messages import _wa_stale_notice

        notice = _wa_stale_notice(
            {
                "warning": "⚠️ DATA BERIKUTNYA MUNGKIN BASI",
                "data_freshness": {"newest_message_at": "2026-11-01T10:20:30"},
            }
        )
        assert "MUNGKIN BASI" in notice
        assert "2026-11-01 10:20" in notice


class TestHandleVoiceMessage:
    async def test_missing_voice_file_returns_error(self, monkeypatch):
        from alfa.bot.handlers import messages as m

        sent: list[str] = []

        async def _fake_send(context, chat_id, text, **kw):
            sent.append(text)

        monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda uid: True)
        monkeypatch.setattr("alfa.bot.handlers.safe_send_message", _fake_send)

        update = _mk_update("voice", has_voice=True)
        update.message.voice.file_id = "tidak-ada"
        update.message.voice.get_file = AsyncMock(
            side_effect=FileNotFoundError("tidak ada")
        )
        await m.handle_voice_message(update, _mk_context())
        assert sent, "user tidak diberi tahu voice gagal"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
