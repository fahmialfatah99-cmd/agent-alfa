"""Tes hermetik `alfa/bot/turn_executor.py` — jantung setiap giliran chat.

Seluruh dependensi eksternal di-mock: Telegram, database, Gemini, permission
gate, router model, dan pipeline. Yang diuji adalah *kontrak perilaku*:

- kunci API hilang → pesan jelas (bukan crash),
- provider non-Gemini → jalur OpenAI-compat,
- fast-path konversi berkas → 0 token dan riwayat tersimpan,
- riwayat panjang dipangkas & kegagalan compaction tidak mematikan giliran,
- tool loop: eksekusi, penolakan gate, gate error (fail-closed), paralel, timeout,
- streaming + fallback saat stream gagal,
- wrap-up saat model tidak mengirim teks,
- fallback kunci vault & pesan error terakhir,
- telemetri wrapper `run_agent_turn`.
"""

from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from alfa.bot import turn_executor as te


class _TurnError(RuntimeError):
    """Kegagalan tiruan di dalam giliran."""


class _StreamDownError(_TurnError):
    def __init__(self) -> None:
        super().__init__("stream mati")


class _ModelDownError(_TurnError):
    def __init__(self) -> None:
        super().__init__("model mati")


class _ExhaustedError(_TurnError):
    def __init__(self) -> None:
        super().__init__("429 RESOURCE_EXHAUSTED")


class _GateBrokenError(ValueError):
    def __init__(self) -> None:
        super().__init__("gate rusak")


class _RetryParseError(ValueError):
    def __init__(self) -> None:
        super().__init__("format delay aneh")


def _response(text: str = "", fcs: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        function_calls=list(fcs or []),
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
    )


def _fc(name: str, args: dict | None = None, fc_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, args=args or {}, id=fc_id)


class _FakeModels:
    """Model Gemini palsu: perilaku ditentukan handler per giliran."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return await self.handler(model, contents, config)


class _FakeDB:
    def __init__(self, history: list | None = None, brain_model: str | None = None) -> None:
        self.history = list(history or [])
        self.brain_model = brain_model
        self.saved: list[tuple] = []

    async def save_chat_message(self, user_id, role, content):
        self.saved.append((user_id, role, content))

    async def get_recent_chat_history(self, user_id, limit=24):
        return self.history

    async def get_all_memories(self, user_id):
        return ["memori A"]

    def get_all_knowledge_graph_sync(self, user_id):
        return []

    def get_main_brain_model(self):
        return self.brain_model


class _FakeBrain:
    MAX_ITERATIONS = 5
    TOOL_EXEC_TIMEOUT = 0.5

    def __init__(self, provider: str = "gemini", exec_fn=None) -> None:
        self.provider = provider
        self.exec_fn = exec_fn or (lambda name, _args: f"ok:{name}")
        self.executed: list[tuple[str, str]] = []

    def get_main_brain(self, override_key_id=None, override_model=None):
        return {"provider": self.provider}

    def _execute_tool(self, name, args_json):
        self.executed.append((name, args_json))
        return self.exec_fn(name, args_json)


class _Env:
    def __init__(self, *, gate_decision=None, gate_raises=None, provider="gemini"):
        self.user_id = 42
        self.chat_id = 99
        self.db = _FakeDB()
        self.brain = _FakeBrain(provider=provider)
        self.config = object()
        self.config_force = object()
        self.config_wrapup = object()
        self.streamer = SimpleNamespace(push_chunk=AsyncMock())
        self.models = _FakeModels(self._default_handler)
        self.client = SimpleNamespace(aio=SimpleNamespace(models=self.models))
        self.resolve = lambda key_id=None: (self.client, 7, "vault")

        async def _gate(_name, _args):
            if gate_raises is not None:
                raise gate_raises
            return gate_decision

        self.gate = _gate
        self.gate_is_interactive = lambda _g: False
        self.pg = SimpleNamespace(
            make_gate=lambda _cid: self.gate,
            ALLOW_ALL_GATE=object(),
            gate_is_interactive=self.gate_is_interactive,
        )
        self.responses: list[SimpleNamespace] = []

    async def _default_handler(self, _model, _contents, _config):
        if self.responses:
            return self.responses.pop(0)
        return _response("jawaban model")

    def bot(self):
        return SimpleNamespace(
            database=self.db,
            main_brain=self.brain,
            permission_gate=self.pg,
            resolve_main_gemini=self.resolve,
        )


async def _fake_compact(_db, _uid, gemini_client=None):
    return ""


async def _fake_audit(_client, **kwargs):
    return kwargs["reply_text"]


@pytest.fixture()
def env(monkeypatch):
    e = _Env()
    monkeypatch.setattr(te, "_get_bot", e.bot)
    monkeypatch.setattr(te, "_maybe_compact_history", _fake_compact)
    monkeypatch.setattr(te, "_build_memory_block", lambda *a, **k: "MEMORI")
    monkeypatch.setattr(
        te,
        "_build_system_instruction",
        AsyncMock(return_value=("SISTEM", "model-pref", "model-aktif")),
    )
    monkeypatch.setattr(
        te,
        "_prepare_tools_and_configs",
        lambda *_a, **_k: ([], e.config, e.config_force, e.config_wrapup),
    )
    monkeypatch.setattr(te, "_audit_correction_pass", _fake_audit)
    monkeypatch.setattr(te, "_meetings_count", lambda: 0)
    monkeypatch.setattr(te, "_artifact_signature", lambda: "sig")
    monkeypatch.setattr(te.token_usage, "from_gemini_response", lambda *a, **k: None)
    monkeypatch.setattr(te, "_try_alt_provider_keys", AsyncMock(return_value=""))
    monkeypatch.setattr(
        "alfa.core.brain.model_router.route_candidate_models",
        lambda **_kw: ["gemini-test"],
    )
    monkeypatch.setattr("alfa.tools.rag.is_action_request", lambda _p: False)
    monkeypatch.setattr(
        "alfa.bot.helpers.clean_telegram_markdown", lambda text: text
    )
    monkeypatch.setattr(
        "alfa.core.brain.agentic._parallel_tools_allowed", lambda _g: False
    )
    return e


# ── dasar ──────────────────────────────────────────────────────────────────


class TestTurnBasics:
    async def test_missing_gemini_key_returns_warning(self, env):
        env.resolve = lambda key_id=None: (None, None, "")
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert "API key belum tersedia" in reply
        assert env.db.saved == []  # tidak menyimpan apa pun

    async def test_non_gemini_provider_short_circuits(self, env, monkeypatch):
        env.brain.provider = "openrouter"
        compat = AsyncMock(return_value="jawaban openrouter")
        monkeypatch.setattr(te, "_openai_compat_turn", compat)
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "jawaban openrouter"
        compat.assert_awaited_once()
        assert env.models.calls == []  # Gemini tidak dipanggil

    async def test_non_gemini_empty_falls_through_to_gemini(self, env, monkeypatch):
        env.brain.provider = "openrouter"
        monkeypatch.setattr(te, "_openai_compat_turn", AsyncMock(return_value=""))
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "jawaban model"
        assert env.models.calls

    async def test_plain_reply_is_saved(self, env):
        env.responses = [_response("Halo dari model")]
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "Halo dari model"
        assert env.db.saved[0] == (42, "user", "halo")
        assert env.db.saved[-1] == (42, "model", "Halo dari model")
        assert env.models.calls[0]["config"] is env.config_force

    async def test_history_long_content_trimmed(self, env):
        env.db.history = [{"id": 1, "role": "user", "content": "A" * 6000}]
        await te._run_agent_turn_impl(42, "halo", chat_id=99)
        trimmed = env.db.history[0]["content"]
        assert len(trimmed) < 6000
        assert "diringkas dari riwayat chat" in trimmed

    async def test_compaction_failure_is_ignored(self, env, monkeypatch):
        async def boom(*_a, **_k):
            raise _TurnError()

        monkeypatch.setattr(te, "_maybe_compact_history", boom)
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "jawaban model"

    async def test_fast_path_success_skips_llm(self, env, monkeypatch, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2", encoding="utf-8")
        def fast(*_a, **_k):
            return {
                "status": "success",
                "reply": "hasil konversi",
                "tool_name": "convert",
                "execution_time_ms": 5,
            }
        monkeypatch.setattr("alfa.core.fast_path_executor.try_execute_fast_path", fast)
        reply = await te._run_agent_turn_impl(
            42, f"[FILE TERSIMPAN DI DISK: {f}] tolong konversi", chat_id=99
        )
        assert reply == "hasil konversi"
        assert env.models.calls == []
        assert env.db.saved[-1] == (42, "model", "hasil konversi")

    async def test_fast_path_error_continues(self, env, monkeypatch, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2", encoding="utf-8")

        def boom(*_a, **_k):
            raise _TurnError()

        monkeypatch.setattr("alfa.core.fast_path_executor.try_execute_fast_path", boom)
        reply = await te._run_agent_turn_impl(
            42, f"[FILE TERSIMPAN DI DISK: {f}] konversi", chat_id=99
        )
        assert reply == "jawaban model"


# ── tool loop ──────────────────────────────────────────────────────────────


class TestToolLoop:
    async def test_tool_executed_then_final_reply(self, env):
        env.responses = [
            _response("", [_fc("baca_file", {"path": "/x"}, "fc-1")]),
            _response("Selesai membaca"),
        ]
        reply = await te._run_agent_turn_impl(42, "baca file", chat_id=99)
        assert reply == "Selesai membaca"
        assert env.brain.executed == [("baca_file", '{"path": "/x"}')]
        # respons fungsi dikirim kembali ke model pada panggilan kedua
        second_parts = env.models.calls[1]["contents"][-1].parts
        assert second_parts[0].function_response.name == "baca_file"

    async def test_gate_denial_reaches_model(self, env, monkeypatch):
        e = _Env(gate_decision="DITOLAK oleh Fahmi")
        monkeypatch.setattr(te, "_get_bot", e.bot)
        e.responses = [_response("", [_fc("hapus", {})]), _response("Oke, dibatalkan")]
        reply = await te._run_agent_turn_impl(42, "hapus", chat_id=99)
        assert reply == "Oke, dibatalkan"
        assert e.brain.executed == []
        result = e.models.calls[1]["contents"][-1].parts[0].function_response.response["result"]
        assert "DITOLAK oleh Fahmi" in result

    async def test_gate_exception_fails_closed(self, env, monkeypatch):
        e = _Env(gate_raises=_GateBrokenError())
        monkeypatch.setattr(te, "_get_bot", e.bot)
        e.responses = [_response("", [_fc("tulis", {})]), _response("Dibatalkan")]
        reply = await te._run_agent_turn_impl(42, "tulis", chat_id=99)
        assert reply == "Dibatalkan"
        assert e.brain.executed == []
        result = e.models.calls[1]["contents"][-1].parts[0].function_response.response["result"]
        assert "permission gate gagal" in result

    async def test_parallel_tools(self, env, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.brain.agentic._parallel_tools_allowed", lambda _g: True
        )
        env.responses = [
            _response("", [_fc("a", {}), _fc("b", {})]),
            _response("dua tool selesai"),
        ]
        reply = await te._run_agent_turn_impl(42, "kerjakan", chat_id=99)
        assert reply == "dua tool selesai"
        assert len(env.brain.executed) == 2
        parts = env.models.calls[1]["contents"][-1].parts
        assert len(parts) == 2

    async def test_tool_timeout_message(self, env):
        env.brain.TOOL_EXEC_TIMEOUT = -4.9  # limit = 0.1s

        def slow(_name, _args):
            time.sleep(0.3)
            return "terlambat"

        env.brain.exec_fn = slow
        env.responses = [
            _response("", [_fc("lambat", {})]),
            _response("Tool timeout dilaporkan"),
        ]
        reply = await te._run_agent_turn_impl(42, "jalankan", chat_id=99)
        assert reply == "Tool timeout dilaporkan"
        result = (
            env.models.calls[1]["contents"][-1]
            .parts[0]
            .function_response.response["result"]
        )
        assert "timeout" in result.lower()


# ── streaming & wrap-up ────────────────────────────────────────────────────


class TestStreamingAndWrapup:
    async def test_streaming_pushes_chunks(self, env):
        chunks = [_response("Ha"), _response("i")]

        async def stream(*, model, contents, config):
            async def _it():
                for c in chunks:
                    yield c

            return _it()

        env.models.generate_content_stream = stream
        env.responses = []
        reply = await te._run_agent_turn_impl(
            42, "halo", chat_id=99, streamer=env.streamer
        )
        assert reply == "Hai"
        assert env.streamer.push_chunk.await_count == 2
        assert env.models.calls == []  # tidak ada generate_content biasa

    async def test_stream_error_falls_back(self, env):
        async def stream(**_kw):
            raise _StreamDownError()

        env.models.generate_content_stream = stream
        env.responses = [_response("fallback biasa")]
        reply = await te._run_agent_turn_impl(
            42, "halo", chat_id=99, streamer=env.streamer
        )
        assert reply == "fallback biasa"
        assert env.models.calls

    async def test_action_intent_disables_streaming(self, env, monkeypatch):
        monkeypatch.setattr("alfa.tools.rag.is_action_request", lambda _p: True)
        env.models.generate_content_stream = AsyncMock(
            side_effect=AssertionError("streaming tidak boleh dipakai")
        )
        env.responses = [_response("dikerjakan")]
        reply = await te._run_agent_turn_impl(
            42, "kirim pesan", chat_id=99, streamer=env.streamer
        )
        assert reply == "dikerjakan"
        env.models.generate_content_stream.assert_not_awaited()

    async def test_empty_reply_triggers_wrapup(self, env):
        async def handler(_model, _contents, config):
            if config is env.config_wrapup:
                return _response("ringkasan akhir")
            return _response("")

        env.models.handler = handler
        reply = await te._run_agent_turn_impl(42, "kerjakan", chat_id=99)
        assert reply == "ringkasan akhir"
        assert len(env.models.calls) == 2
        assert env.models.calls[1]["config"] is env.config_wrapup

    async def test_wrapup_failure_uses_tool_summary(self, env):
        async def handler(_model, _contents, config):
            if config is env.config_wrapup:
                raise _ModelDownError()
            return _response("")

        env.models.handler = handler
        reply = await te._run_agent_turn_impl(42, "kerjakan", chat_id=99)
        assert "Tool sudah dijalankan" in reply
        assert "tidak ada" in reply


# ── fallback & kegagalan total ─────────────────────────────────────────────


class TestFallbacks:
    async def test_model_failure_then_alt_provider(self, env, monkeypatch):
        env.models.handler = AsyncMock(side_effect=_ModelDownError())
        alt = AsyncMock(return_value="jawaban kunci cadangan")
        monkeypatch.setattr(te, "_try_alt_provider_keys", alt)
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "jawaban kunci cadangan"
        alt.assert_awaited_once()

    async def test_all_fail_returns_error_reply(self, env):
        env.models.handler = AsyncMock(side_effect=_ModelDownError())
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply.startswith("❌ Terjadi kesalahan")
        assert "model mati" in reply
        assert env.db.saved[-1][1] == "model"
        assert env.db.saved[-1][2].startswith("❌")

    async def test_429_marks_circuit_breaker(self, env, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.brain.model_router.route_candidate_models",
            lambda **_kw: ["m1", "m2"],
        )
        marked: list[tuple] = []

        def mark(model, cooldown_seconds=0, reason=""):
            marked.append((model, cooldown_seconds, reason))

        monkeypatch.setattr(
            "alfa.core.brain.circuit_breaker.mark_model_exhausted", mark
        )
        monkeypatch.setattr(
            "alfa.core.brain.circuit_breaker.parse_retry_delay", lambda _e: 60
        )

        async def handler(model, _contents, _config):
            if model == "m1":
                raise _ExhaustedError()
            return _response("sukses di m2")

        env.models.handler = handler
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "sukses di m2"
        assert marked and marked[0][0] == "m1" and marked[0][1] == 60



# ── cabang pertahanan tambahan ─────────────────────────────────────────────


class TestDefensiveBranches:
    async def test_no_gate_at_all_denies_tool(self, env, monkeypatch):
        e = _Env()
        e.pg = SimpleNamespace(
            make_gate=lambda _cid: None,
            ALLOW_ALL_GATE=None,
            gate_is_interactive=lambda _g: False,
        )
        monkeypatch.setattr(te, "_get_bot", e.bot)
        e.responses = [_response("", [_fc("tulis", {})]), _response("Ditolak sistem")]
        reply = await te._run_agent_turn_impl(42, "tulis", chat_id=99)
        assert reply == "Ditolak sistem"
        assert e.brain.executed == []
        result = e.models.calls[1]["contents"][-1].parts[0].function_response.response["result"]
        assert "tidak ada permission gate" in result

    async def test_multimodal_attachment_is_forwarded(self, env):
        from google.genai import types

        part = types.Part.from_text(text="lampiran gambar")
        reply = await te._run_agent_turn_impl(
            42, "", multimodal_parts=[part], chat_id=99
        )
        assert reply == "jawaban model"
        assert env.db.saved[0] == (42, "user", "[Lampiran Media]")
        first_contents = env.models.calls[0]["contents"][-1]
        assert first_contents.parts[0] is part

    async def test_non_gemini_resolve_error_recovers_on_second_try(
        self, env, monkeypatch
    ):
        env.brain.provider = "openrouter"
        monkeypatch.setattr(te, "_openai_compat_turn", AsyncMock(return_value=""))
        calls = {"n": 0}

        def resolve(key_id=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _ModelDownError()
            return (env.client, 7, "vault")

        env.resolve = resolve
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "jawaban model"
        assert calls["n"] >= 2

    async def test_all_brains_unavailable_returns_warning(self, env, monkeypatch):
        env.brain.provider = "openrouter"
        monkeypatch.setattr(te, "_openai_compat_turn", AsyncMock(return_value=""))
        env.resolve = lambda key_id=None: (None, None, "")
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert "Semua otak AI gagal merespons" in reply

    async def test_non_numeric_tool_timeout_falls_back_to_config(self, env):
        env.brain.TOOL_EXEC_TIMEOUT = "bukan angka"
        env.responses = [
            _response("", [_fc("cek", {})]),
            _response("selesai"),
        ]
        reply = await te._run_agent_turn_impl(42, "cek", chat_id=99)
        assert reply == "selesai"
        assert env.brain.executed

    async def test_response_without_candidates_is_tolerated(self, env):
        first = SimpleNamespace(text="", function_calls=[_fc("x", {})])
        env.responses = [first, _response("lanjut")]
        reply = await te._run_agent_turn_impl(42, "kerjakan", chat_id=99)
        assert reply == "lanjut"

    async def test_parallel_tool_exception_becomes_error_payload(
        self, env, monkeypatch
    ):
        monkeypatch.setattr(
            "alfa.core.brain.agentic._parallel_tools_allowed", lambda _g: True
        )

        def exec_fn(name, _args):
            if name == "gagal":
                raise _TurnError()
            return "ok"

        env.brain.exec_fn = exec_fn
        env.responses = [
            _response("", [_fc("gagal", {}), _fc("sukses", {})]),
            _response("dilaporkan"),
        ]
        reply = await te._run_agent_turn_impl(42, "kerjakan", chat_id=99)
        assert reply == "dilaporkan"
        parts = env.models.calls[1]["contents"][-1].parts
        assert "ERROR eksekusi" in parts[0].function_response.response["result"]

    async def test_circuit_breaker_mark_error_is_ignored(self, env, monkeypatch):
        monkeypatch.setattr(
            "alfa.core.brain.model_router.route_candidate_models",
            lambda **_kw: ["m1", "m2"],
        )
        monkeypatch.setattr(
            "alfa.core.brain.circuit_breaker.mark_model_exhausted",
            lambda *a, **k: None,
        )

        def broken_parse(_e):
            raise _RetryParseError()

        monkeypatch.setattr(
            "alfa.core.brain.circuit_breaker.parse_retry_delay", broken_parse
        )

        async def handler(model, _contents, _config):
            if model == "m1":
                raise _ExhaustedError()
            return _response("selamat di m2")

        env.models.handler = handler
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply == "selamat di m2"

    async def test_error_reply_survives_save_failure(self, env, monkeypatch):
        env.models.handler = AsyncMock(side_effect=_ModelDownError())

        # panggilan save pertama (user) harus sukses, kedua (model/error) gagal
        calls = {"n": 0}
        real_save = env.db.save_chat_message

        async def flaky_save(uid, role, content):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise sqlite3.OperationalError()
            await real_save(uid, role, content)

        monkeypatch.setattr(env.db, "save_chat_message", flaky_save, raising=False)
        reply = await te._run_agent_turn_impl(42, "halo", chat_id=99)
        assert reply.startswith("❌ Terjadi kesalahan")


# ── wrapper publik & telemetri ─────────────────────────────────────────────


class TestWrapperMetrics:
    async def test_metrics_ok(self, monkeypatch):
        started = []
        finished = []
        monkeypatch.setattr("alfa.core.metrics.note_turn_started", lambda: started.append(1))
        monkeypatch.setattr(
            "alfa.core.metrics.note_turn_finished", lambda ok: finished.append(ok)
        )
        monkeypatch.setattr(
            te, "_run_agent_turn_impl", AsyncMock(return_value="jawaban")
        )
        assert await te.run_agent_turn(42, "halo") == "jawaban"
        assert started == [1]
        assert finished == [True]

    async def test_metrics_failed_prefix(self, monkeypatch):
        finished = []
        monkeypatch.setattr("alfa.core.metrics.note_turn_started", lambda: None)
        monkeypatch.setattr(
            "alfa.core.metrics.note_turn_finished", lambda ok: finished.append(ok)
        )
        monkeypatch.setattr(
            te, "_run_agent_turn_impl", AsyncMock(return_value="❌ gagal")
        )
        await te.run_agent_turn(42, "halo")
        assert finished == [False]

    async def test_exception_marks_failed_and_reraises(self, monkeypatch):
        finished = []
        monkeypatch.setattr("alfa.core.metrics.note_turn_started", lambda: None)
        monkeypatch.setattr(
            "alfa.core.metrics.note_turn_finished", lambda ok: finished.append(ok)
        )

        async def boom(*_a, **_k):
            raise _ModelDownError()

        monkeypatch.setattr(te, "_run_agent_turn_impl", boom)
        with pytest.raises(_ModelDownError):
            await te.run_agent_turn(42, "halo")
        assert finished == [False]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
