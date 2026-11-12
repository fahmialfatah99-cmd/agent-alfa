"""Tes alur `alfa/bot/handlers/messages.py` — router pesan utama bot.

Melengkapi `tests/test_handlers_messages.py` (jalur dasar) dengan cabang yang
paling berisiko diam bila rusak:

- batching pesan terusan (debounce + merge + pemakaian batch terbaru),
- kartu rekap Lahat/Curup & briefing (sukses maupun gagal),
- pintasan menu/hub/status,
- learning loop (koreksi & reinforcement, error ditelan),
- Apex compiled fast-path,
- reset kuota,
- mode SWARM (sukses, dibatalkan, gagal, pembatalan paksa),
- kegagalan turn tunggal, fallback typing/streamer,
- mode balasan suara (TTS) dan pembersihan berkas sementara.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from alfa.bot.handlers import messages as m


class _FlowError(RuntimeError):
    """Kegagalan tiruan pada alur pesan."""


class _StreamStartError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("streamer gagal start")


class _FinalizeError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("finalize gagal")


class _ReporterError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("reporter gagal")


def _mk_update(text: str = "tes") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = 222
    msg.from_user = MagicMock()
    msg.from_user.id = 111
    msg.message_id = 7
    msg.document = None
    msg.voice = None
    msg.forward_from = None
    msg.forward_from_chat = None
    msg.forward_sender_name = None
    msg.forward_date = None
    msg.forward_origin = None
    msg.reply_voice = AsyncMock()
    up = MagicMock()
    up.message = msg
    up.effective_chat = MagicMock()
    up.effective_chat.id = 222
    up.effective_user = MagicMock()
    up.effective_user.id = 111
    return up


def _mk_context() -> MagicMock:
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


class _Streamer:
    instances: list[_Streamer] = []
    sink: list[dict] | None = None

    def __init__(self, context=None, chat_id=None, initial_text=None):
        self.chat_id = chat_id
        self.finalized: list[str] = []
        _Streamer.instances.append(self)

    async def start(self):
        return None

    async def finalize(self, text):
        self.finalized.append(text)
        if _Streamer.sink is not None:
            _Streamer.sink.append({"chat_id": self.chat_id, "text": text, "markup": None})


class _BrokenStreamer(_Streamer):
    async def start(self):
        raise _StreamStartError()


class _FinalizeBrokenStreamer(_Streamer):
    async def finalize(self, text):
        raise _FinalizeError()


class _Reporter:
    instances: list[_Reporter] = []

    def __init__(self, context, chat_id, text):
        self.chat_id = chat_id
        self.stopped: list[str] = []
        _Reporter.instances.append(self)

    async def start(self):
        return None

    async def stop(self, message):
        self.stopped.append(message)


@pytest.fixture()
def harness(monkeypatch):
    from alfa.bot.handlers import _state

    _state._FORWARD_BATCHES.clear()
    _state._RECENT_FORWARD_BATCHES.clear()
    _state.ACTIVE_CHAT_TASKS.clear()
    _Streamer.instances.clear()
    _Reporter.instances.clear()

    state = SimpleNamespace(sends=[], typing_loops=[], turns=[], nudge_calls=[])
    _Streamer.sink = state.sends

    async def fake_send(context, chat_id, text, **kw):
        state.sends.append({"chat_id": chat_id, "text": text, "markup": kw.get("reply_markup")})

    async def fake_typing(chat_id, context, stop_event, action):
        state.typing_loops.append(stop_event)
        await stop_event.wait()

    async def fake_nudge(context, chat_id, task, streamer):
        state.nudge_calls.append(chat_id)
        await asyncio.sleep(0)

    async def fake_turn(**kwargs):
        state.turns.append(kwargs)
        return "jawaban agent"

    monkeypatch.setattr("alfa.bot.handlers.safe_send_message", fake_send)
    monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda _uid: True)
    monkeypatch.setattr("alfa.bot.handlers._check_and_send_media_artifacts", AsyncMock())
    monkeypatch.setattr("alfa.bot.handlers._get_bot_module", lambda: None)
    monkeypatch.setattr("alfa.bot.handlers._run_agent_turn", fake_turn)
    monkeypatch.setattr("alfa.bot.handlers.send_typing_loop", fake_typing)
    monkeypatch.setattr("alfa.bot.handlers.TelegramStreamer", _Streamer)
    monkeypatch.setattr("alfa.core.database.save_chat_message", AsyncMock())
    monkeypatch.setattr(
        "alfa.core.database.get_user_settings", AsyncMock(return_value={})
    )
    monkeypatch.setattr(m, "get_forward_info", lambda _msg: None)
    monkeypatch.setattr(m, "_long_turn_nudge", fake_nudge)
    monkeypatch.setattr(m, "should_reply_with_text_instead_of_voice", lambda _t: False)
    monkeypatch.setattr("alfa.core.apex.try_execute_compiled_fastpath", lambda _t: None)
    monkeypatch.setattr(
        "alfa.core.apex.analyze_field_event_preemptively", lambda *_a, **_k: {}
    )
    monkeypatch.setattr("alfa.core.apex.ingest_text_to_temporal_graph", lambda _t: None)
    monkeypatch.setattr(
        "alfa.core.brain.learning_loop.is_user_correction_signal", lambda _t: False
    )
    monkeypatch.setattr(
        "alfa.core.brain.learning_loop.is_positive_reinforcement_signal",
        lambda _t: False,
    )
    monkeypatch.setattr(
        "alfa.core.brain.learning_loop.detect_and_process_user_correction",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "alfa.core.brain.learning_loop.record_trajectory", lambda **_k: None
    )
    yield state
    _state._FORWARD_BATCHES.clear()
    _state._RECENT_FORWARD_BATCHES.clear()
    _state.ACTIVE_CHAT_TASKS.clear()


# ── batching pesan terusan ─────────────────────────────────────────────────


class TestForwardBatching:
    async def test_forwarded_message_creates_debounced_batch(self, harness, monkeypatch):
        monkeypatch.setattr(
            m, "get_forward_info", lambda _msg: {"sender": "Mandor Mugi"}
        )
        await m.handle_text_message(_mk_update("T73 20 btg"), _mk_context())
        from alfa.bot.handlers import _state

        batch = _state._FORWARD_BATCHES[222]
        assert batch["items"][0]["sender"] == "Mandor Mugi"
        assert batch["items"][0]["text"] == "T73 20 btg"
        task = batch["task"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert harness.sends == []

    async def test_direct_text_merges_waiting_batch(self, harness, monkeypatch):
        from alfa.bot.handlers import _state

        _state._FORWARD_BATCHES[222] = {
            "items": [
                {"text": "T73 20", "sender": "Mugi", "msg_id": 1},
                {"text": "T72 10", "sender": "Budi", "msg_id": 2},
            ],
            "task": None,
            "user_id": 111,
            "context": _mk_context(),
            "latest_update": _mk_update(),
            "turn_start_time": 0.0,
        }
        await m.handle_text_message(_mk_update("jumlahkan"), _mk_context())
        assert harness.turns, "turn tidak dipanggil"
        prompt = harness.turns[-1]["user_prompt"]
        assert "[Kumpulan 2 Pesan Terusan dari Mugi, Budi]" in prompt
        assert "Instruksi Pengguna: jumlahkan" in prompt
        assert _state._RECENT_FORWARD_BATCHES[222]["count"] == 2

    async def test_recent_batch_is_attached_once(self, harness, monkeypatch):
        import time as _time

        from alfa.bot.handlers import _state

        _state._RECENT_FORWARD_BATCHES[222] = {
            "count": 1,
            "senders": ["Mugi"],
            "senders_str": "Mugi",
            "full_text": "[1. Dari: Mugi]\nT73 20 btg",
            "items": [],
            "user_id": 111,
            "context": _mk_context(),
            "created_at": _time.time(),
            "consumed": False,
        }
        await m.handle_text_message(_mk_update("rekap"), _mk_context())
        prompt = harness.turns[-1]["user_prompt"]
        assert "[Kumpulan 1 Pesan Terusan dari Mugi]" in prompt
        assert _state._RECENT_FORWARD_BATCHES[222]["consumed"] is True

    async def test_expired_recent_batch_is_ignored(self, harness, monkeypatch):
        from alfa.bot.handlers import _state

        _state._RECENT_FORWARD_BATCHES[222] = {
            "count": 1,
            "senders": ["Mugi"],
            "senders_str": "Mugi",
            "full_text": "lama",
            "items": [],
            "user_id": 111,
            "context": _mk_context(),
            "created_at": 0.0,
            "consumed": False,
        }
        await m.handle_text_message(_mk_update("rekap"), _mk_context())
        assert harness.turns[-1]["user_prompt"] == "rekap"


# ── kartu rekap & briefing ─────────────────────────────────────────────────


class TestTelecomCards:
    async def test_rekap_lahat_success_with_cable_and_accessories(
        self, harness, monkeypatch
    ):
        monkeypatch.setattr(
            "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
            lambda **_kw: {
                "status": "success",
                "total_net": 160,
                "total_bruto": 175,
                "total_retur": 15,
                "mandors": ["Mugi"],
                "total_cable_m": 1200,
                "accessories_breakdown": {
                    "ACC-STOPING": 4,
                    "ACC-BELT": 2,
                },
                "excel_file": "/tmp/master.xlsx",
            },
        )
        await m.handle_text_message(_mk_update("rekap material lahat"), _mk_context())
        card = harness.sends[-1]["text"]
        assert "REKAPITULASI MATERIAL MASTER LAHAT" in card
        assert "Kabel Udara (KU 24)" in card and "1,200" in card
        assert "Stoping: 4 pcs" in card
        assert harness.sends[-1]["markup"] is not None

    async def test_rekap_lahat_failure(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
            lambda **_kw: {"status": "error", "message": "grup tidak ada"},
        )
        await m.handle_text_message(_mk_update("rekap material lahat"), _mk_context())
        assert "Gagal merekap material: grup tidak ada" in harness.sends[-1]["text"]

    async def test_rekap_curup_success_with_breakdown(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
            lambda **_kw: {
                "status": "success",
                "total_net": 90,
                "total_bruto": 95,
                "total_retur": 5,
                "mandors": ["Budi"],
                "breakdown": {"T73": 60, "T72": 30, "T70": 0},
                "accessories_breakdown": {
                    "ACC-BUAYA": 3,
                    "ACC-BELT": 1,
                    "ACC-HANGER": 0,
                },
                "excel_file": "/tmp/curup.xlsx",
            },
        )
        await m.handle_text_message(_mk_update("rekap material curup"), _mk_context())
        card = harness.sends[-1]["text"]
        assert "REKAPITULASI MATERIAL MASTER CURUP" in card
        assert "T73: 60 btg" in card and "T70" not in card.split("Total Bruto")[1]
        assert "Clamp Buaya: 3 pcs" in card
        assert "Stainless Belt: 1 roll" in card

    async def test_briefing_success_and_failure(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.tools.telecom_tools.generate_daily_executive_briefing",
            lambda **_kw: {"status": "success", "briefing_card": "KARTU BRIEFING"},
        )
        await m.handle_text_message(_mk_update("daily briefing"), _mk_context())
        assert harness.sends[-1]["text"] == "KARTU BRIEFING"

        monkeypatch.setattr(
            "alfa.tools.telecom_tools.generate_daily_executive_briefing",
            lambda **_kw: {"status": "error", "message": "database kosong"},
        )
        await m.handle_text_message(_mk_update("briefing"), _mk_context())
        assert "Gagal menyusun briefing: database kosong" in harness.sends[-1]["text"]

    async def test_menu_hub_status_shortcuts(self, harness, monkeypatch):
        calls: list[str] = []

        async def menu(update, context):
            calls.append("menu")

        async def wa(update, context):
            calls.append("wa")

        async def stats(update, context):
            calls.append("stats")

        monkeypatch.setattr("alfa.bot.basic_commands.menu_command", menu)
        monkeypatch.setattr("alfa.bot.advanced_commands.wa_command", wa)
        monkeypatch.setattr("alfa.bot.basic_commands.stats_command", stats)

        await m.handle_text_message(_mk_update("menu utama"), _mk_context())
        await m.handle_text_message(_mk_update("whatsapp hub"), _mk_context())
        await m.handle_text_message(_mk_update("status server"), _mk_context())
        assert calls == ["menu", "wa", "stats"]


# ── learning loop & fast paths ─────────────────────────────────────────────


class TestLearningAndFastPaths:
    async def test_correction_signal_records_rule(self, harness, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "alfa.core.brain.learning_loop.is_user_correction_signal", lambda _t: True
        )
        monkeypatch.setattr(
            "alfa.core.brain.learning_loop.detect_and_process_user_correction",
            lambda text, user_id=0: captured.append((text, user_id)) or {"topic": "format"},
        )
        await m.handle_text_message(_mk_update("bukan begitu, harusnya tabel"), _mk_context())
        assert captured and captured[0][1] == 111

    async def test_positive_signal_records_trajectory(self, harness, monkeypatch):
        recorded = []
        monkeypatch.setattr(
            "alfa.core.brain.learning_loop.is_positive_reinforcement_signal",
            lambda _t: True,
        )
        monkeypatch.setattr(
            "alfa.core.brain.learning_loop.record_trajectory",
            lambda **kw: recorded.append(kw),
        )
        await m.handle_text_message(_mk_update("mantap, terima kasih"), _mk_context())
        assert recorded and recorded[0]["feedback"] == "positive"

    async def test_learning_loop_error_is_swallowed(self, harness, monkeypatch):
        def boom(_t):
            raise _FlowError()

        monkeypatch.setattr(
            "alfa.core.brain.learning_loop.is_user_correction_signal", boom
        )
        await m.handle_text_message(_mk_update("pesan biasa yang panjang"), _mk_context())
        assert harness.turns, "turn harus tetap berjalan"

    async def test_greeting_db_failure_is_swallowed(self, harness, monkeypatch):
        async def boom(*_a, **_k):
            raise sqlite3.OperationalError()

        monkeypatch.setattr("alfa.core.database.save_chat_message", boom)
        await m.handle_text_message(_mk_update("halo"), _mk_context())
        assert "ALFA" in harness.sends[-1]["text"]
        assert harness.turns == []

    async def test_compiled_fastpath_hit_skips_turn(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.apex.try_execute_compiled_fastpath",
            lambda _t: {"response": "jawaban instan"},
        )
        await m.handle_text_message(_mk_update("cek stok tiang"), _mk_context())
        assert harness.sends[-1]["text"] == "jawaban instan"
        assert harness.turns == []

    async def test_apex_error_is_swallowed(self, harness, monkeypatch):
        def boom(_t):
            raise _FlowError()

        monkeypatch.setattr("alfa.core.apex.try_execute_compiled_fastpath", boom)
        await m.handle_text_message(_mk_update("cek stok tiang"), _mk_context())
        assert harness.turns, "turn harus tetap berjalan"

    async def test_reset_kuota_message(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.rate_limiter.reset_user_usage_today", lambda _uid: 3
        )
        monkeypatch.setattr(
            "alfa.core.rate_limiter.get_user_usage_today",
            lambda _uid: {"budget_limit": 100000, "call_limit": 50},
        )
        await m.handle_text_message(_mk_update("reset kuota"), _mk_context())
        text = harness.sends[-1]["text"]
        assert "Kuota harian berhasil di-reset" in text
        assert "3 entri" in text


# ── mode SWARM ─────────────────────────────────────────────────────────────


class TestSwarmMode:
    def _swarm(self, monkeypatch, result_fn):
        monkeypatch.setattr(
            "alfa.bot.mode_commands.get_telegram_mode_sync", lambda: "swarm"
        )
        monkeypatch.setattr("alfa.bot.progress.SwarmProgressReporter", _Reporter)
        monkeypatch.setattr(
            "alfa.bot.mode_commands.run_swarm_task", result_fn
        )

    async def test_swarm_success_sends_steps_and_files(self, harness, monkeypatch):
        async def run(_text):
            return {"status": "success"}

        self._swarm(monkeypatch, run)
        monkeypatch.setattr(
            "alfa.bot.mode_commands.format_swarm_result",
            lambda _r: ("LANGKAH", "HASIL AKHIR", ["/tmp/deliverable.txt"]),
        )
        await m.handle_text_message(_mk_update("bangun laporan lengkap"), _mk_context())
        assert harness.sends[-1]["text"] == "HASIL AKHIR"
        assert any(s["text"] == "LANGKAH" for s in harness.sends)
        reporter = _Reporter.instances[-1]
        assert any("Selesai" in s for s in reporter.stopped)

    async def test_swarm_short_message_stays_single(self, harness, monkeypatch):
        self._swarm(monkeypatch, AsyncMock())
        await m.handle_text_message(_mk_update("berapa stok"), _mk_context())
        assert harness.turns, "pesan pendek harus tetap single-agent"

    async def test_swarm_cancelled_result(self, harness, monkeypatch):
        async def run(_text):
            return {"status": "cancelled"}

        self._swarm(monkeypatch, run)
        await m.handle_text_message(_mk_update("bangun laporan lengkap"), _mk_context())
        assert "Misi swarm telah dihentikan" in harness.sends[-1]["text"]

    async def test_swarm_failure_returns_error(self, harness, monkeypatch):
        async def run(_text):
            raise _FlowError()

        self._swarm(monkeypatch, run)
        await m.handle_text_message(_mk_update("bangun laporan lengkap"), _mk_context())
        assert "Misi swarm gagal diproses" in harness.sends[-1]["text"]

    async def test_swarm_forced_cancel_requests_stop_and_reraises(
        self, harness, monkeypatch
    ):
        async def run(_text):
            raise asyncio.CancelledError()

        self._swarm(monkeypatch, run)
        requested = []
        monkeypatch.setattr(
            "alfa.swarm.workspace_hygiene.request_cancel_swarm",
            lambda: requested.append(True),
        )
        with pytest.raises(asyncio.CancelledError):
            await m.handle_text_message(
                _mk_update("bangun laporan lengkap"), _mk_context()
            )
        assert requested == [True]

    async def test_swarm_file_send_failure_is_swallowed(self, harness, monkeypatch):
        async def run(_text):
            return {"status": "success"}

        self._swarm(monkeypatch, run)
        monkeypatch.setattr(
            "alfa.bot.mode_commands.format_swarm_result",
            lambda _r: ("LANGKAH", "HASIL", ["/tmp/tidak-ada.txt"]),
        )
        ctx = _mk_context()
        ctx.bot.send_document = AsyncMock(side_effect=_FlowError())
        await m.handle_text_message(_mk_update("bangun laporan lengkap"), ctx)
        assert harness.sends[-1]["text"] == "HASIL"


# ── kegagalan turn & fallback pengiriman ───────────────────────────────────


class TestTurnFailureModes:
    async def test_turn_failure_returns_apology(self, harness, monkeypatch):
        async def boom(**_kw):
            raise _FlowError()

        monkeypatch.setattr("alfa.bot.handlers._run_agent_turn", boom)
        await m.handle_text_message(_mk_update("kerjakan sesuatu"), _mk_context())
        assert "gagal diproses" in harness.sends[-1]["text"]
        assert "_FlowError" in harness.sends[-1]["text"]

    async def test_turn_cancelled_returns_notice(self, harness, monkeypatch):
        async def boom(**_kw):
            raise asyncio.CancelledError()

        monkeypatch.setattr("alfa.bot.handlers._run_agent_turn", boom)
        await m.handle_text_message(_mk_update("kerjakan sesuatu"), _mk_context())
        assert "dibatalkan" in harness.sends[-1]["text"]

    async def test_streamer_start_failure_uses_typing_loop(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.bot.handlers.TelegramStreamer", _BrokenStreamer
        )
        await m.handle_text_message(_mk_update("kerjakan sesuatu"), _mk_context())
        assert len(harness.typing_loops) == 1
        assert harness.typing_loops[0].is_set()
        assert harness.sends[-1]["text"] == "jawaban agent"

    async def test_finalize_failure_falls_back_to_send(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.bot.handlers.TelegramStreamer", _FinalizeBrokenStreamer
        )
        await m.handle_text_message(_mk_update("kerjakan sesuatu"), _mk_context())
        assert harness.sends[-1]["text"] == "jawaban agent"

    async def test_artifacts_are_checked_even_after_reply(self, harness):
        checked = AsyncMock()
        import alfa.bot.handlers as pkg

        # fixture sudah memasang AsyncMock; ganti untuk memeriksa panggilan
        pkg._check_and_send_media_artifacts = checked
        await m.handle_text_message(_mk_update("kerjakan sesuatu"), _mk_context())
        checked.assert_awaited_once()

    async def test_voice_reply_sends_voice_and_removes_temp(
        self, harness, monkeypatch, tmp_path
    ):
        voice_file = tmp_path / "balasan.ogg"
        voice_file.write_bytes(b"OggS")
        monkeypatch.setattr(
            "alfa.core.database.get_user_settings",
            AsyncMock(return_value={"voice_reply": True}),
        )
        monkeypatch.setattr(
            "alfa.media.tts_engine.text_to_speech_ogg",
            AsyncMock(return_value=str(voice_file)),
        )
        update = _mk_update("kerjakan sesuatu")
        ctx = _mk_context()
        await m.handle_text_message(update, ctx)
        update.message.reply_voice.assert_awaited_once()
        assert not voice_file.exists()

    async def test_voice_tts_error_is_swallowed(self, harness, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.database.get_user_settings",
            AsyncMock(return_value={"voice_reply": True}),
        )
        monkeypatch.setattr(
            "alfa.media.tts_engine.text_to_speech_ogg",
            AsyncMock(side_effect=_FlowError()),
        )
        await m.handle_text_message(_mk_update("kerjakan sesuatu"), _mk_context())
        # balasan teks tetap terkirim sebelumnya
        assert harness.sends[-1]["text"] == "jawaban agent"


# ── voice note: transkripsi & balasan adaptif ──────────────────────────────


def _voice_update() -> MagicMock:
    up = _mk_update("voice")
    up.message.voice = SimpleNamespace(file_id="f1", mime_type="audio/ogg")
    up.message.audio = None
    return up


def _voice_context(payload: bytes = b"OggS") -> MagicMock:
    ctx = _mk_context()
    file_obj = SimpleNamespace()

    async def download(buf):
        buf.write(payload)

    file_obj.download_to_memory = AsyncMock(side_effect=download)
    ctx.bot.get_file = AsyncMock(return_value=file_obj)
    return ctx


def _gemini_client(handler) -> SimpleNamespace:
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=handler)))

class TestVoiceMessageFlows:
    async def test_unauthorized_voice_is_denied(self, harness, monkeypatch):
        monkeypatch.setattr("alfa.bot.handlers._is_authorized", lambda _uid: False)
        await m.handle_voice_message(_voice_update(), _voice_context())
        assert "Akses ditolak" in harness.sends[-1]["text"]

    async def test_no_voice_object_returns_silently(self, harness):
        up = _mk_update("bukan voice")
        up.message.voice = None
        up.message.audio = None
        await m.handle_voice_message(up, _voice_context())
        assert harness.sends == []

    async def test_transcribed_greeting_replies_with_voice(
        self, harness, monkeypatch, tmp_path
    ):
        async def gen(**_kw):
            return SimpleNamespace(text="halo")

        monkeypatch.setattr(m, "resolve_main_gemini", lambda: (_gemini_client(gen), 1, "vault"))
        voice_file = tmp_path / "balasan.ogg"
        voice_file.write_bytes(b"OggS")
        monkeypatch.setattr(
            "alfa.media.tts_engine.text_to_speech_ogg",
            AsyncMock(return_value=str(voice_file)),
        )
        up = _voice_update()
        await m.handle_voice_message(up, _voice_context())
        up.message.reply_voice.assert_awaited_once()
        assert not voice_file.exists()
        assert harness.turns == []  # sapaan tidak lewat agent

    async def test_transcribed_instruction_goes_to_agent(
        self, harness, monkeypatch
    ):
        async def gen(**_kw):
            return SimpleNamespace(text="berapa stok tiang")

        monkeypatch.setattr(m, "resolve_main_gemini", lambda: (_gemini_client(gen), 1, "vault"))
        monkeypatch.setattr(m, "should_reply_with_text_instead_of_voice", lambda _t: True)
        await m.handle_voice_message(_voice_update(), _voice_context())
        assert harness.turns, "agent tidak dipanggil"
        kw = harness.turns[-1]
        assert "berapa stok tiang" in kw["user_prompt"]
        assert kw["multimodal_parts"]
        assert harness.sends[-1]["text"] == "jawaban agent"

    async def test_missing_transcription_uses_generic_prompt(
        self, harness, monkeypatch
    ):
        monkeypatch.setattr(m, "resolve_main_gemini", lambda: (None, None, ""))
        monkeypatch.setattr(m, "should_reply_with_text_instead_of_voice", lambda _t: True)
        await m.handle_voice_message(_voice_update(), _voice_context())
        kw = harness.turns[-1]
        assert "Dengarkan rekaman suara" in kw["user_prompt"]

    async def test_transcription_model_failure_falls_to_next(
        self, harness, monkeypatch
    ):
        calls = {"n": 0}

        async def gen(**_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _FlowError()
            return SimpleNamespace(text="halo")

        monkeypatch.setattr(m, "resolve_main_gemini", lambda: (_gemini_client(gen), 1, "vault"))
        monkeypatch.setattr(m, "should_reply_with_text_instead_of_voice", lambda _t: True)
        up = _voice_update()
        await m.handle_voice_message(up, _voice_context())
        assert calls["n"] >= 2
        assert "ALFA" in harness.sends[-1]["text"]

    async def test_greeting_save_failure_still_replies(self, harness, monkeypatch):
        async def gen(**_kw):
            return SimpleNamespace(text="halo")

        async def boom(*_a, **_k):
            raise sqlite3.OperationalError()

        monkeypatch.setattr(m, "resolve_main_gemini", lambda: (_gemini_client(gen), 1, "vault"))
        monkeypatch.setattr("alfa.core.database.save_chat_message", boom)
        monkeypatch.setattr(m, "should_reply_with_text_instead_of_voice", lambda _t: True)
        await m.handle_voice_message(_voice_update(), _voice_context())
        assert "ALFA" in harness.sends[-1]["text"]

    async def test_tts_failure_falls_back_to_text(self, harness, monkeypatch):
        async def gen(**_kw):
            return SimpleNamespace(text="halo")

        monkeypatch.setattr(m, "resolve_main_gemini", lambda: (_gemini_client(gen), 1, "vault"))
        monkeypatch.setattr(
            "alfa.media.tts_engine.text_to_speech_ogg",
            AsyncMock(side_effect=_FlowError()),
        )
        monkeypatch.setattr(m, "should_reply_with_text_instead_of_voice", lambda _t: False)
        up = _voice_update()
        await m.handle_voice_message(up, _voice_context())
        up.message.reply_voice.assert_not_awaited()
        assert "ALFA" in harness.sends[-1]["text"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
