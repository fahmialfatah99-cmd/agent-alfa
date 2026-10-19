"""Otak agentik (`alfa/core/brain/agentic.py`) — loop, error handling, gate.

Ini inti reasoning engine: satu turn agentik penuh (permintaan → tool call →
eksekusi → umpan balik → jawaban akhir). Dipakai dengan HTTP client palsu
sehingga tidak ada panggilan jaringan sungguhan.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeResponse:
    """Respons httpx palsu."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload

    async def aread(self):
        return self.text.encode("utf-8")


class _FakeStreamResponse:
    """Respons streaming httpx palsu."""

    def __init__(self, lines, status_code=200):
        self.status_code = status_code
        self._lines = lines

    async def aread(self):
        return b"".join(x.encode() for x in self._lines)

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    """AsyncClient palsu: mengembalikan respons berurutan."""

    calls: list = []
    responses: list = []
    stream_lines: list = []
    stream_status: int = 200

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.calls.append({"url": url, "headers": headers, "json": json})
        if not _FakeClient.responses:
            return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
        return _FakeClient.responses.pop(0)

    def stream(self, method, url, headers=None, json=None):
        _FakeClient.calls.append({"url": url, "headers": headers, "json": json})
        if _FakeClient.stream_status != 200:
            return _FakeStreamResponse(
                ["data: error"], status_code=_FakeClient.stream_status
            )
        return _FakeStreamResponse(_FakeClient.stream_lines)


@pytest.fixture(autouse=True)
def _reset_fake(tmp_path, monkeypatch):
    # DB terisolasi + kuota longgar supaya test tidak terpengaruh pemakaian
    # token nyata di mesin.
    monkeypatch.setenv("ALFA_DB_PATH", str(tmp_path / "brain.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALFA_DAILY_TOKEN_LIMIT", "999999999")
    monkeypatch.setenv("ALFA_DAILY_CALL_LIMIT", "999999")
    import alfa.core.rate_limiter as rl

    monkeypatch.setattr(rl, "DEFAULT_TOKEN_LIMIT", 999999999)
    monkeypatch.setattr(rl, "DEFAULT_CALL_LIMIT", 999999)
    try:
        from alfa.core.db import connection as conn_mod

        conn_mod.init_db_sync()
    except Exception:  # noqa: BLE001 - DB mungkin sudah ada
        pass
    _FakeClient.calls = []
    _FakeClient.responses = []
    _FakeClient.stream_lines = []
    _FakeClient.stream_status = 200
    yield
    _FakeClient.calls = []
    _FakeClient.responses = []
    _FakeClient.stream_lines = []
    _FakeClient.stream_status = 200


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return _FakeClient


def _text_response(content):
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def _tool_response(name, args, call_id="call_1"):
    return _FakeResponse(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args),
                                },
                            }
                        ],
                    }
                }
            ]
        },
    )


async def _allow_gate(_name, _args=""):
    return None


async def _deny_gate(_name, _args=""):
    return "[DITOLAK] tidak boleh"


class TestRunAgenticTurn:
    @pytest.mark.asyncio
    async def test_jawaban_teks_sederhana(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_text_response("Halo, saya membantu.")]
        out = await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="halo",
        )
        assert out == "Halo, saya membantu."
        assert fake_httpx.calls[0]["url"] == "http://x/v1/chat/completions"
        assert fake_httpx.calls[0]["headers"]["Authorization"] == "Bearer k"

    @pytest.mark.asyncio
    async def test_tool_call_dijalankan_lalu_diumpan_kembali(self, fake_httpx, monkeypatch):
        from alfa.core.brain import agentic as ag

        executed = []
        monkeypatch.setattr(
            ag, "_execute_tool", lambda n, a: executed.append((n, a)) or "HASIL-TOOL"
        )
        fake_httpx.responses = [
            _tool_response("get_system_stats", {}),
            _text_response("Selesai."),
        ]
        out = await ag.run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="cek sistem",
            approval_gate=_allow_gate,
        )
        assert out == "Selesai."
        assert executed and executed[0][0] == "get_system_stats"
        # Percakapan kedua harus memuat hasil tool.
        roles = [msg["role"] for msg in fake_httpx.calls[1]["json"]["messages"]]
        assert "tool" in roles

    @pytest.mark.asyncio
    async def test_tanpa_gate_tool_ditolak(self, fake_httpx, monkeypatch):
        from alfa.core.brain import agentic as ag

        executed = []
        monkeypatch.setattr(
            ag, "_execute_tool", lambda n, a: executed.append(n) or "HARUS-NOT"
        )
        fake_httpx.responses = [_tool_response("execute_bash_command", {}), _text_response("ok")]
        await ag.run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="jalankan",
        )
        assert not executed
        # Tool ditolak → hasil penolakan masuk ke percakapan.
        tool_msgs = [
            m
            for m in fake_httpx.calls[1]["json"]["messages"]
            if m.get("role") == "tool"
        ]
        assert tool_msgs and "DITOLAK" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_gate_menolak_menghasilkan_teks_penolakan(self, fake_httpx, monkeypatch):
        from alfa.core.brain import agentic as ag

        executed = []
        monkeypatch.setattr(
            ag, "_execute_tool", lambda n, a: executed.append(n) or "HARUS-NOT"
        )
        fake_httpx.responses = [_tool_response("get_system_stats", {}), _text_response("ok")]
        await ag.run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="cek",
            approval_gate=_deny_gate,
        )
        assert not executed
        tool_msgs = [
            m
            for m in fake_httpx.calls[1]["json"]["messages"]
            if m.get("role") == "tool"
        ]
        assert tool_msgs and "DITOLAK" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_http_402_pesan_kredit(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_FakeResponse(402, text="no credit")]
        out = await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        )
        assert "402" in out and "Kredit" in out

    @pytest.mark.asyncio
    async def test_http_404_pesan_model(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_FakeResponse(404, text="nf")]
        out = await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        )
        assert "404" in out and "ditemukan" in out

    @pytest.mark.asyncio
    async def test_http_429_pesan_rate_limit(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_FakeResponse(429, text="slow down")]
        out = await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        )
        assert "429" in out and "Rate Limit" in out

    @pytest.mark.asyncio
    async def test_error_lain_kembalikan_none(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_FakeResponse(500, text="boom")]
        out = await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_raw_errors_kembalikan_none(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_FakeResponse(500, text="boom")]
        out = await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
            raw_errors=True,
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_kuota_habis_menghentikan_turn(self, fake_httpx, monkeypatch):
        import alfa.core.rate_limiter as rl
        from alfa.core.brain import agentic as ag

        monkeypatch.setattr(
            rl, "check_rate_limit", lambda user_id=0, provider="": (False, "Daily token limit")
        )
        monkeypatch.setattr(ag, "check_rate_limit", rl.check_rate_limit, raising=False)
        out = await ag.run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        )
        assert out and "Kuota" in out
        assert not fake_httpx.calls

    @pytest.mark.asyncio
    async def test_tools_schema_kosong_tidak_mengirim_tools(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_text_response("halo")]
        await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="halo",
            tools_schema=[],
        )
        assert "tools" not in fake_httpx.calls[0]["json"]

    @pytest.mark.asyncio
    async def test_sapaan_sederhana_tanpa_tools(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_text_response("halo")]
        await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="halo",
        )
        assert "tools" not in fake_httpx.calls[0]["json"]

    @pytest.mark.asyncio
    async def test_riwayat_diteruskan(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn

        fake_httpx.responses = [_text_response("ok")]
        await run_openai_agentic_turn(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="lanjutan",
            history=[{"role": "user", "content": "sebelumnya"}],
        )
        msgs = fake_httpx.calls[0]["json"]["messages"]
        assert any("sebelumnya" in str(m.get("content")) for m in msgs)


class TestRunAgenticTurnStreaming:
    @pytest.mark.asyncio
    async def test_stream_menghasilkan_chunk(self, fake_httpx):
        from alfa.core.brain.agentic import run_openai_agentic_turn_streaming

        fake_httpx.stream_lines = [
            'data: {"choices":[{"delta":{"content":"Halo"}}]}',
            'data: {"choices":[{"delta":{"content":" dunia"}}]}',
            "data: [DONE]",
        ]
        chunks = []
        async for c in run_openai_agentic_turn_streaming(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        ):
            chunks.append(c)
        assert "".join(chunks) == "Halo dunia"

    @pytest.mark.asyncio
    async def test_stream_http_error_fallback_non_streaming(self, fake_httpx):
        from alfa.core.brain import agentic as ag

        fake_httpx.stream_status = 500
        fake_httpx.responses = [_text_response("fallback works")]
        out = []
        async for c in ag.run_openai_agentic_turn_streaming(
            provider="openai",
            base_url="http://x/v1",
            api_key="k",
            model="m",
            system_instruction="s",
            user_text="hi",
        ):
            out.append(c)
        assert "fallback works" in "".join(out)
