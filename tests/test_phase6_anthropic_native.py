"""Phase 6 coverage: Anthropic Messages API native — tool loop & streaming.

Hermetic: HTTP di-mock penuh; tidak ada panggilan jaringan atau eksekusi tool nyata.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from alfa.core.brain import anthropic_native as an


@pytest.fixture(autouse=True)
def _mock_usage(monkeypatch):
    monkeypatch.setattr(an, "MAX_ITERATIONS", 3) if hasattr(an, "MAX_ITERATIONS") else None
    from alfa.core import token_usage

    monkeypatch.setattr(token_usage, "from_anthropic_json", lambda *a, **k: None)
    monkeypatch.setattr(token_usage, "record", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _allow_rate_limit(monkeypatch):
    from alfa.core import rate_limiter

    monkeypatch.setattr(rate_limiter, "check_rate_limit", lambda **k: (True, ""))


def _gate_ok(monkeypatch, outputs=("ok",)):
    from alfa.core.brain import agentic

    async def fake_gate(approval_gate, tool_calls):
        return ["ok"] * len(tool_calls)

    mock = AsyncMock(side_effect=fake_gate)
    monkeypatch.setattr(agentic, "_run_tool_calls", mock)
    return mock


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------


def test_max_tokens_and_temperature(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "512")
    assert an._max_tokens() == 512
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "abc")
    assert an._max_tokens() == 8192
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "1")
    assert an._max_tokens() == 256
    monkeypatch.setenv("ANTHROPIC_TEMPERATURE", "2.5")
    assert an._temperature() == 1.0
    monkeypatch.setenv("ANTHROPIC_TEMPERATURE", "-1")
    assert an._temperature() == 0.0
    monkeypatch.setenv("ANTHROPIC_TEMPERATURE", "nope")
    assert an._temperature() == 0.7


def test_messages_url_variants():
    assert an.messages_url(None) == "https://api.anthropic.com/v1/messages"
    assert an.messages_url("https://x/v1") == "https://x/v1/messages"
    assert an.messages_url("https://x/v1/") == "https://x/v1/messages"
    assert an.messages_url("https://x/v1/messages") == "https://x/v1/messages"
    assert an.messages_url("https://x") == "https://x/v1/messages"


def test_resolve_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert an._resolve_model(None) == an._DEFAULT_MODEL
    assert an._resolve_model("gemini-3-pro") == an._DEFAULT_MODEL
    assert an._resolve_model("gemma-2") == an._DEFAULT_MODEL
    assert an._resolve_model("claude-x") == "claude-x"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-env")
    assert an._resolve_model("") == "claude-env"


def test_headers():
    headers = an._headers("key")
    assert headers["x-api-key"] == "key"
    assert headers["anthropic-version"] == an._ANTHROPIC_VERSION


def test_to_anthropic_tools():
    schema = [
        {
            "type": "function",
            "function": {
                "name": "do_it",
                "description": "desc",
                "parameters": {"type": "object", "properties": {"a": {"type": "string"}}},
            },
        },
        {"type": "function", "function": {"name": ""}},
        {"type": "function", "function": {"name": "no_params"}},
        {},
    ]
    out = an.to_anthropic_tools(schema)
    assert out[0]["name"] == "do_it"
    assert out[0]["input_schema"]["properties"]["a"]
    assert out[1]["name"] == "no_params"
    assert out[1]["input_schema"] == {"type": "object", "properties": {}}
    assert an.to_anthropic_tools(None) == []


def test_history_messages_drops_empty_and_leading_assistant():
    history = [
        {"role": "assistant", "content": "pembuka"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "halo"},
        {"role": "model", "content": "jawab"},
        {"role": "tool", "content": "hasil"},
    ]
    out = an._history_messages(history)
    assert out == [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "jawab"},
        {"role": "user", "content": "hasil"},
    ]
    assert an._history_messages(None) == []


def test_default_tools_greeting_and_rag(monkeypatch):
    assert an._default_tools("halo", None) == []
    schema = [{"type": "function", "function": {"name": "t"}}]

    from alfa.core.brain import tool_schema
    from alfa.tools import rag

    monkeypatch.setattr(tool_schema, "build_openai_tools", lambda: schema)
    monkeypatch.setattr(rag, "select_relevant_tools", lambda tools, text, history=None: [])
    assert an._default_tools("tolong tulis file", None) == []


def test_default_tools_rag_failure_fails_open(monkeypatch):
    schema = [{"type": "function", "function": {"name": "t"}}]

    from alfa.core.brain import tool_schema
    from alfa.tools import rag

    monkeypatch.setattr(tool_schema, "build_openai_tools", lambda: schema)
    monkeypatch.setattr(
        rag, "select_relevant_tools", lambda *a, **k: (_ for _ in ()).throw(ValueError())
    )
    assert an._default_tools("tolong tulis file", None) == schema


def test_text_of_and_tool_uses():
    content = [
        {"type": "text", "text": "ha"},
        {"type": "text", "text": "lo"},
        {"type": "tool_use", "name": "t"},
        "bukan-dict",
        {"type": "text"},
    ]
    assert an._text_of(content) == "halo"
    assert an._tool_uses(content) == [{"type": "tool_use", "name": "t"}]
    assert an._text_of([]) == ""


def test_finalize_stream_blocks():
    blocks = {
        0: {"type": "text", "text": "halo"},
        1: {"type": "text", "text": ""},
        2: {"type": "tool_use", "id": "x", "_json": '{"a": 1}'},
        3: {"type": "tool_use", "id": "y", "_json": "bukan-json"},
    }
    out = an._finalize_stream_blocks(blocks)
    assert out[0] == {"type": "text", "text": "halo"}
    assert out[1]["input"] == {"a": 1}
    assert out[2]["input"] == {}
    assert "_json" not in out[1]


# ---------------------------------------------------------------------------
# HTTP request / wrap-up
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, data=None, status=200, error=None):
        self._data = data
        self.status_code = status
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._data


class _Client:
    response = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        return _Client.response


def test_request_messages_success(monkeypatch):
    import asyncio

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    _Client.response = _Response({"content": []})
    assert asyncio.run(an._request_messages("https://x", {}, {}, 5)) is not None


def test_request_messages_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    _Client.response = _Response(error=httpx.HTTPError("bad"))
    with pytest.raises(httpx.HTTPError):
        import asyncio

        asyncio.run(an._request_messages("https://x", {}, {}, 5))


def test_wrap_up_success(monkeypatch):
    import asyncio

    async def fake_request(*a, **k):
        return {"content": [{"type": "text", "text": "progres"}]}

    monkeypatch.setattr(an, "_request_messages", fake_request)
    out = asyncio.run(
        an._wrap_up(
            url="u",
            headers={},
            model="m",
            system_instruction="s",
            messages=[],
            timeout=5,
            key_id=1,
            key_label="k",
            context="c",
        )
    )
    assert "progres" in out


def test_wrap_up_failure(monkeypatch):
    import asyncio

    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(an, "_request_messages", boom)
    out = asyncio.run(
        an._wrap_up(
            url="u",
            headers={},
            model="m",
            system_instruction="s",
            messages=[],
            timeout=5,
            key_id=None,
            key_label="k",
            context="c",
        )
    )
    assert out is None


def test_wrap_up_empty_text(monkeypatch):
    import asyncio

    async def fake_request(*a, **k):
        return {"content": []}

    monkeypatch.setattr(an, "_request_messages", fake_request)
    out = asyncio.run(
        an._wrap_up(
            url="u",
            headers={},
            model="m",
            system_instruction="s",
            messages=[],
            timeout=5,
            key_id=None,
            key_label="k",
            context="c",
        )
    )
    assert out is None


# ---------------------------------------------------------------------------
# Agentic non-streaming
# ---------------------------------------------------------------------------


def _run(**kwargs):
    import asyncio

    params = dict(
        api_key="key",
        model="claude-x",
        system_instruction="system",
        user_text="user",
        history=None,
        base_url="",
        key_id=1,
        key_label="lbl",
        context="ctx",
        tools_schema=[],
        approval_gate=None,
        timeout=5,
    )
    params.update(kwargs)
    return asyncio.run(an.run_anthropic_agentic_turn(**params))


def test_agentic_no_key():
    assert _run(api_key="") is None


def test_agentic_rate_limited(monkeypatch):
    from alfa.core import rate_limiter

    monkeypatch.setattr(rate_limiter, "check_rate_limit", lambda **k: (False, "habis"))
    out = _run()
    assert "Kuota harian" in out
    assert "habis" in out


def test_agentic_returns_text(monkeypatch):
    async def fake_request(*a, **k):
        return {"content": [{"type": "text", "text": " jawaban "}]}

    monkeypatch.setattr(an, "_request_messages", fake_request)
    assert _run() == "jawaban"


def test_agentic_empty_text(monkeypatch):
    async def fake_request(*a, **k):
        return {"content": []}

    monkeypatch.setattr(an, "_request_messages", fake_request)
    assert _run() == "(provider tidak mengirim teks)"


def test_agentic_tool_loop_then_text(monkeypatch):
    calls = _gate_ok(monkeypatch, ["tool-output"])
    responses = [
        {
            "content": [
                {"type": "tool_use", "id": "tu1", "name": "do", "input": {"a": 1}}
            ]
        },
        {"content": [{"type": "text", "text": "selesai"}]},
    ]

    async def fake_request(*a, **k):
        return responses.pop(0)

    monkeypatch.setattr(an, "_request_messages", fake_request)
    assert _run() == "selesai"
    assert calls.await_count == 1
    args = calls.await_args.args
    assert args[1][0]["function"]["name"] == "do"


def test_agentic_repeated_tool_calls_trigger_wrap_up(monkeypatch):
    _gate_ok(monkeypatch, ["out", "out"])
    use = {"content": [{"type": "tool_use", "id": "1", "name": "do", "input": {}}]}

    async def fake_request(*a, **k):
        return use

    async def fake_wrap(**k):
        return "ringkasan"

    monkeypatch.setattr(an, "_request_messages", fake_request)
    monkeypatch.setattr(an, "_wrap_up", fake_wrap)
    assert _run() == "ringkasan"


def test_agentic_max_iterations_wrap_up(monkeypatch):
    _gate_ok(monkeypatch, ["out"] * 10)
    counter = {"i": 0}

    async def fake_request(*a, **k):
        counter["i"] += 1
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": str(counter["i"]),
                    "name": "do",
                    "input": {"i": counter["i"]},
                }
            ]
        }

    async def fake_wrap(**k):
        return "akhir"

    monkeypatch.setattr(an, "_request_messages", fake_request)
    monkeypatch.setattr(an, "_wrap_up", fake_wrap)
    assert _run() == "akhir"


def test_agentic_exception_returns_none(monkeypatch):
    async def boom(*a, **k):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(an, "_request_messages", boom)
    assert _run() is None


def test_agentic_default_tools_used(monkeypatch):
    captured = {}

    async def fake_request(url, headers, payload, timeout):
        captured["payload"] = payload
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(an, "_request_messages", fake_request)
    monkeypatch.setattr(an, "_default_tools", lambda text, history: [
        {"type": "function", "function": {"name": "t"}}
    ])
    assert _run(tools_schema=None) == "ok"
    assert captured["payload"]["tools"][0]["name"] == "t"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class _StreamResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    async def aread(self):
        return b"error body"

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamCtx:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *a):
        return False


class _StreamClient:
    lines = []
    status = 200

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None, json=None):
        return _StreamCtx(_StreamResponse(self.lines, self.status))


def _events(*events):
    return [f"data: {json.dumps(e)}" for e in events]


async def _collect(gen):
    return [chunk async for chunk in gen]


def _stream(**kwargs):
    import asyncio

    params = dict(
        api_key="key",
        model="claude-x",
        system_instruction="s",
        user_text="u",
        tools_schema=[],
    )
    params.update(kwargs)
    return asyncio.run(_collect(an.run_anthropic_agentic_turn_streaming(**params)))


def test_stream_no_key():
    assert _stream(api_key="") == []


def test_stream_rate_limited(monkeypatch):
    from alfa.core import rate_limiter

    monkeypatch.setattr(rate_limiter, "check_rate_limit", lambda **k: (False, "quota"))
    chunks = _stream()
    assert chunks and "Kuota" in chunks[0]


def test_stream_text_and_stop(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StreamClient)
    _StreamClient.status = 200
    _StreamClient.lines = _events(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "Ha"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
    )
    assert _stream() == ["Ha", "lo"]


def test_stream_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StreamClient)
    _StreamClient.status = 500
    _StreamClient.lines = []
    assert _stream() == []


def test_stream_ignores_bad_lines(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StreamClient)
    _StreamClient.status = 200
    _StreamClient.lines = [
        "",
        "event: ping",
        "data: not-json",
        "data: [DONE]",
        json.dumps({"type": "content_block_delta"}),
    ]
    assert _stream() == []


def test_stream_tool_use_loop(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StreamClient)
    _StreamClient.status = 200
    _StreamClient.lines = _events(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tu", "name": "do"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"a": 1}'}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    )
    calls = _gate_ok(monkeypatch, ["out"])
    assert _stream() == []
    assert calls.await_count == 2


def test_stream_tool_repeat_stops(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StreamClient)
    _StreamClient.status = 200
    _StreamClient.lines = _events(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tu", "name": "do"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    )
    calls = _gate_ok(monkeypatch, ["out", "out", "out"])
    # Setiap iterasi memanggil 1 tool call; pengulangan ke-2 harus berhenti.
    assert _stream() == []
    assert calls.await_count == 2


def test_stream_exception(monkeypatch):
    class BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            raise httpx.HTTPError("down")

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    assert _stream() == []


def test_stream_default_tools(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StreamClient)
    _StreamClient.status = 200
    _StreamClient.lines = _events(
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
    )
    monkeypatch.setattr(an, "_default_tools", lambda text, history: [
        {"type": "function", "function": {"name": "t"}}
    ])
    assert _stream(tools_schema=None) == []
