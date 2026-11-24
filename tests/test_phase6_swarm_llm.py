"""Phase 6 coverage: swarm llm_client — routing provider, fallback, tool loop.

Hermetic: SDK Gemini/HTTP di-mock, DB helper di-mock, tidak ada panggilan jaringan.
"""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from alfa.swarm import llm_client as llm


@pytest.fixture(autouse=True)
def _no_circuit_breaker(monkeypatch):
    monkeypatch.setattr(llm, "_filter_cooled_down_models", lambda models: models)
    monkeypatch.setattr(llm, "_mark_model_exhausted", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Defaults dan resolusi client
# ---------------------------------------------------------------------------


def test_default_gemini_model_from_brain(monkeypatch):
    monkeypatch.setattr(llm.database, "get_main_brain_model", lambda: "brain-model")
    assert llm._default_gemini_model() == "brain-model"


def test_default_gemini_model_from_key(monkeypatch):
    monkeypatch.setattr(llm.database, "get_main_brain_model", lambda: "")
    monkeypatch.setattr(
        llm.database,
        "get_active_api_key_sync",
        lambda provider: {"default_model": "key-model"},
    )
    assert llm._default_gemini_model() == "key-model"


def test_default_gemini_model_fallback(monkeypatch):
    monkeypatch.setattr(llm.database, "get_main_brain_model", lambda: (_ for _ in ()).throw(TypeError()))
    monkeypatch.setattr(
        llm.database,
        "get_active_api_key_sync",
        lambda provider: (_ for _ in ()).throw(ValueError()),
    )
    assert llm._default_gemini_model() == "gemini-flash-latest"


def test_get_agent_api_client_env_fallbacks(monkeypatch):
    monkeypatch.setattr(llm.database, "get_active_api_key_sync", lambda provider: None)
    for env, provider in [
        ("GEMINI_API_KEY", "gemini"),
        ("OPENAI_API_KEY", "openai"),
        ("GROQ_API_KEY", "groq"),
        ("NVIDIA_API_KEY", "nvidia"),
        ("DEEPSEEK_API_KEY", "deepseek"),
        ("OPENROUTER_API_KEY", "openrouter"),
        ("MINIMAX_API_KEY", "minimax"),
        ("MOONSHOT_API_KEY", "kimi"),
        ("DASHSCOPE_API_KEY", "qwen"),
        ("NINEROUTER_API_KEY", "9router"),
    ]:
        monkeypatch.setenv(env, f"key-{provider}")
    for provider in (
        "gemini",
        "openai",
        "groq",
        "nvidia",
        "deepseek",
        "openrouter",
        "minimax",
        "kimi",
        "qwen",
        "9router",
    ):
        out_provider, key, model, base_url, key_id = llm.get_agent_api_client(
            {"provider": provider, "model": "m"}
        )
        assert out_provider == provider
        assert key
        if provider != "gemini":
            assert base_url
        assert key_id is None


def test_get_agent_api_client_active_key(monkeypatch):
    monkeypatch.setattr(
        llm.database,
        "get_active_api_key_sync",
        lambda provider: {
            "api_key": " vault-key ",
            "base_url": "https://vault",
            "id": 7,
            "default_model": "vault-model",
        },
    )
    provider, key, model, base_url, key_id = llm.get_agent_api_client(
        {"provider": "openai", "model": "m"}
    )
    assert (provider, key, model, base_url, key_id) == (
        "openai",
        " vault-key ",
        "m",
        "https://vault",
        7,
    )


def test_get_agent_api_client_by_key_id(monkeypatch):
    row = {
        "id": 9,
        "provider": "groq",
        "api_key": "cipher",
        "default_model": "llama",
        "base_url": "https://groq",
    }

    class FakeConn:
        def execute(self, *a, **k):
            return self

        def fetchone(self):
            return row

    class FakeDB:
        def __enter__(self):
            return FakeConn()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(llm.database, "get_sync_db", lambda: FakeDB())
    monkeypatch.setattr(llm.database, "decrypt_key", lambda value: "plain-key")
    provider, key, model, base_url, key_id = llm.get_agent_api_client(
        {"api_key_id": 9, "provider": "gemini"}
    )
    assert (provider, key, model, base_url, key_id) == (
        "groq",
        "plain-key",
        "llama",
        "https://groq",
        9,
    )


def test_get_agent_api_client_unknown_provider_fallback_cycle(monkeypatch):
    monkeypatch.setattr(
        llm.database,
        "get_active_api_key_sync",
        lambda provider: (
            {"api_key": "fb", "id": 3, "default_model": "fb-model"}
            if provider == "gemini"
            else None
        ),
    )
    provider, key, model, base_url, key_id = llm.get_agent_api_client(
        {"provider": "custom", "name": "Agen", "id": 1}
    )
    assert provider == "gemini"
    assert key == "fb"
    assert model == "fb-model"
    assert key_id == 3


def test_get_agent_api_client_9router_local_db(monkeypatch, tmp_path):
    import sqlite3

    monkeypatch.setattr(llm.database, "get_active_api_key_sync", lambda provider: None)
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER_API_KEY", raising=False)
    fake_db = tmp_path / "data.sqlite"
    with sqlite3.connect(fake_db) as conn:
        conn.execute("CREATE TABLE apiKeys (key TEXT, isActive INTEGER)")
        conn.execute("INSERT INTO apiKeys VALUES ('local-key', 1)")
    monkeypatch.setattr(
        llm.os.path,
        "expanduser",
        lambda p: str(fake_db) if "9router" in p else p,
    )
    provider, key, model, base_url, key_id = llm.get_agent_api_client(
        {"provider": "9router", "id": 1}
    )
    assert provider == "9router"
    assert key == "local-key"
    assert base_url == "http://127.0.0.1:20128/v1"
    assert model == "all"


def test_get_agent_api_client_9router_db_error(monkeypatch):
    monkeypatch.setattr(llm.database, "get_active_api_key_sync", lambda provider: None)
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER_API_KEY", raising=False)
    monkeypatch.setattr(llm.os.path, "expanduser", lambda p: "/nonexistent/db.sqlite")
    provider, key, model, base_url, key_id = llm.get_agent_api_client(
        {"provider": "9router", "model": "x"}
    )
    assert key == ""
    assert model == "x"


# ---------------------------------------------------------------------------
# Gemini path
# ---------------------------------------------------------------------------


class _FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


class _FakeAio:
    def __init__(self, models):
        self.models = models


class _FakeClient:
    def __init__(self, models):
        self.aio = _FakeAio(models)


def _install_genai(monkeypatch, outcomes):
    models = _FakeModels(outcomes)
    fake_genai = SimpleNamespace(Client=lambda api_key: _FakeClient(models))
    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kw: SimpleNamespace(**kw),
        ThinkingConfig=lambda **kw: SimpleNamespace(**kw),
    )
    monkeypatch.setattr(llm, "genai", fake_genai)
    monkeypatch.setattr(llm, "types", fake_types)
    return models


def test_generate_with_gemini_success(monkeypatch):
    response = SimpleNamespace(text="  jawaban  ")
    models = _install_genai(monkeypatch, [response])
    recorded = []
    monkeypatch.setattr(
        llm.token_usage,
        "from_gemini_response",
        lambda resp, **kw: recorded.append(kw),
    )
    out = asyncio.run(
        llm._generate_with_gemini(
            "Agen",
            "key",
            ["gemini-3-pro"],
            "prompt",
            "system",
            key_id=1,
            key_label="lbl",
        )
    )
    assert out == "jawaban"
    assert recorded[0]["model"] == "gemini-3-pro"
    assert models.calls[0][0] == "gemini-3-pro"


def test_generate_with_gemini_skips_empty_and_falls_back(monkeypatch):
    models = _install_genai(
        monkeypatch, [SimpleNamespace(text=""), SimpleNamespace(text="kedua")]
    )
    monkeypatch.setattr(llm.token_usage, "from_gemini_response", lambda *a, **k: None)
    out = asyncio.run(
        llm._generate_with_gemini("Agen", "key", ["m1", "m2"], "p", "s")
    )
    assert out == "kedua"
    assert len(models.calls) == 2


def test_generate_with_gemini_exception_then_success(monkeypatch):
    _install_genai(
        monkeypatch, [RuntimeError("429 quota"), SimpleNamespace(text="ok")]
    )
    monkeypatch.setattr(llm.token_usage, "from_gemini_response", lambda *a, **k: None)
    out = asyncio.run(
        llm._generate_with_gemini("Agen", "key", ["m1", "m2"], "p", "s")
    )
    assert out == "ok"


def test_generate_with_gemini_all_fail(monkeypatch):
    _install_genai(monkeypatch, [RuntimeError("boom")])
    assert asyncio.run(
        llm._generate_with_gemini("Agen", "key", ["m1"], "p", "s")
    ) is None


def test_generate_with_gemini_timeout(monkeypatch):
    async def slow():
        await asyncio.sleep(0.05)
        return SimpleNamespace(text="late")

    _install_genai(monkeypatch, [slow])
    out = asyncio.run(
        llm._generate_with_gemini("Agen", "key", ["m1"], "p", "s", timeout_s=0.001)
    )
    assert out is None


def test_generate_with_gemini_client_init_failure(monkeypatch):
    monkeypatch.setattr(llm, "genai", SimpleNamespace(Client=lambda **k: (_ for _ in ()).throw(RuntimeError("sdk"))))
    monkeypatch.setattr(llm, "types", SimpleNamespace())
    assert asyncio.run(
        llm._generate_with_gemini("Agen", "key", ["m1"], "p", "s")
    ) is None


# ---------------------------------------------------------------------------
# OpenAI-compatible path
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, data=None, text="", headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._data, BaseException):
            raise self._data
        return self._data


class _FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    async def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _FakeHTTPClient:
    response_sets = []

    def __init__(self, *a, **k):
        self.http = _FakeHTTP(self.response_sets.pop(0))

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _make_http_client(http):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return http

        async def __aexit__(self, *a):
            return False

    return _Client


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeHTTPClient)
    monkeypatch.setattr(llm.token_usage, "from_openai_json", lambda *a, **k: None)
    monkeypatch.setattr(llm.asyncio, "sleep", AsyncMock())
    return _FakeHTTPClient


def _run_openai(responses, **kwargs):
    _FakeHTTPClient.response_sets.append(responses)
    return asyncio.run(
        llm._generate_with_openai_compat(
            agent_name="Agen",
            provider=kwargs.pop("provider", "groq"),
            api_key="key",
            model="model",
            base_url=kwargs.pop("base_url", "https://api.test/v1"),
            prompt="prompt",
            final_instruction="system",
            **kwargs,
        )
    )


def test_openai_success(fake_http):
    out = _run_openai(
        [_FakeResponse(data={"choices": [{"message": {"content": " jawaban "}}]})]
    )
    assert out == "jawaban"


def test_openai_reasoning_fallback(fake_http):
    out = _run_openai(
        [
            _FakeResponse(
                data={"choices": [{"message": {"reasoning_content": "nalar"}}]}
            )
        ]
    )
    assert out == "nalar"


def test_openai_reasoning_rejected_when_content_required(fake_http):
    out = _run_openai(
        [
            _FakeResponse(
                data={"choices": [{"message": {"reasoning_content": "nalar"}}]}
            )
        ],
        require_content=True,
    )
    assert out is None


def test_openai_empty_content(fake_http):
    out = _run_openai([_FakeResponse(data={"choices": [{"message": {}}]})])
    assert out is None


def test_openai_sse_fallback(fake_http):
    text = "\n".join(
        [
            'data: {"choices": [{"delta": {"content": "ha"}}]}',
            'data: {"choices": [{"delta": {"content": "lo"}}]}',
            "data: [DONE]",
        ]
    )
    out = _run_openai(
        [_FakeResponse(data=ValueError("not json"), text=text)]
    )
    assert out == "halo"


def test_openai_402_retry_success(fake_http):
    out = _run_openai(
        [
            _FakeResponse(status_code=402, text="can only afford 500 tokens"),
            _FakeResponse(data={"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    assert out == "ok"


def test_openai_402_retry_http_error(fake_http):
    out = _run_openai(
        [
            _FakeResponse(status_code=402, text="can only afford 500"),
            RuntimeError("network"),
        ]
    )
    assert out is None


def test_openai_402_retry_still_fails(fake_http):
    out = _run_openai(
        [
            _FakeResponse(status_code=402, text="can only afford 500"),
            _FakeResponse(status_code=500, text="still bad"),
        ]
    )
    assert out is None


def test_openai_429_retry_success(fake_http):
    out = _run_openai(
        [
            _FakeResponse(status_code=429, headers={"Retry-After": "abc"}),
            _FakeResponse(data={"choices": [{"message": {"content": "setelah"}}]}),
        ]
    )
    assert out == "setelah"


def test_openai_429_retry_exception(fake_http):
    out = _run_openai(
        [
            _FakeResponse(status_code=429, headers={"Retry-After": "1"}),
            RuntimeError("retry down"),
        ]
    )
    assert out is None


def test_openai_other_status(fake_http):
    out = _run_openai([_FakeResponse(status_code=503, text="unavailable")])
    assert out is None


def test_openai_exception(fake_http):
    out = _run_openai([OSError("connection refused")])
    assert out is None


def test_openai_default_urls_and_openrouter_headers(fake_http):
    cases = [
        ("nvidia", "https://integrate.api.nvidia.com/v1"),
        ("deepseek", "https://api.deepseek.com/v1"),
        ("minimax", "https://api.minimax.chat/v1"),
        ("moonshot", "https://api.moonshot.cn/v1"),
        ("qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        ("openai", "https://api.openai.com/v1"),
        ("groq", "https://api.groq.com/openai/v1"),
        ("openrouter", "https://openrouter.ai/api/v1"),
        ("9router", "http://127.0.0.1:20128/v1"),
        ("ollama", "http://localhost:11434/v1"),
    ]
    for provider, expected_url in cases:
        http = _FakeHTTP([_FakeResponse(data={"choices": [{"message": {"content": "x"}}]})])

        httpx.AsyncClient = _make_http_client(http)  # type: ignore[assignment]
        out = asyncio.run(
            llm._generate_with_openai_compat(
                "Agen", provider, "key", "model", "", "p", "s"
            )
        )
        assert out == "x"
        assert http.posts[0]["url"] == f"{expected_url}/chat/completions"
        if provider == "openrouter":
            assert http.posts[0]["headers"]["HTTP-Referer"]


# ---------------------------------------------------------------------------
# generate_agent_response
# ---------------------------------------------------------------------------


def _agent(**kwargs):
    base = {"name": "Agen", "provider": "gemini", "model": "gemini-3-pro"}
    base.update(kwargs)
    return base


def test_generate_agent_response_gemini(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("gemini", "key", "model", "", 1)
    )
    gemini = AsyncMock(return_value="hasil")
    monkeypatch.setattr(llm, "_generate_with_gemini", gemini)
    out = asyncio.run(
        llm.generate_agent_response(_agent(), "prompt", "system", max_tokens=123)
    )
    assert out == "hasil"
    assert gemini.await_args.kwargs["max_tokens"] == 123


def test_generate_agent_response_openai(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    compat = AsyncMock(return_value="jawab")
    monkeypatch.setattr(llm, "_generate_with_openai_compat", compat)
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq"), "prompt", "system")
    )
    assert out == "jawab"


def test_generate_agent_response_cache_hit(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    from alfa.core.brain import cache

    monkeypatch.setattr(cache, "lookup_for", lambda *a, **k: "cached")
    compat = AsyncMock(return_value="tidak dipakai")
    monkeypatch.setattr(llm, "_generate_with_openai_compat", compat)
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq"), "prompt", "system")
    )
    assert out == "cached"
    compat.assert_not_awaited()


def test_generate_agent_response_stores_cache(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    from alfa.core.brain import cache

    monkeypatch.setattr(cache, "lookup_for", lambda *a, **k: None)
    stored = []
    monkeypatch.setattr(cache, "store_for", lambda *a, **k: stored.append(a))
    monkeypatch.setattr(llm, "_generate_with_openai_compat", AsyncMock(return_value="baru"))
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq"), "prompt", "system")
    )
    assert out == "baru"
    assert stored


def test_generate_agent_response_tools_gemini(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("gemini", "key", "model", "", 1)
    )
    gemini = AsyncMock(return_value="tool-result")
    monkeypatch.setattr(llm, "_generate_with_gemini", gemini)
    out = asyncio.run(
        llm.generate_agent_response(
            _agent(enable_tools=1), "prompt", "system"
        )
    )
    assert out == "tool-result"
    assert gemini.await_args.kwargs["tools"] is not None or gemini.await_args.kwargs["tools"] is None


def test_generate_agent_response_tools_openai_without_key_falls_back(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    gemini = AsyncMock(return_value="fallback")
    monkeypatch.setattr(llm, "_generate_with_gemini", gemini)
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq", enable_tools=1), "p", "s")
    )
    assert out == "fallback"
    assert gemini.await_count == 1


def test_generate_agent_response_tools_openai_agentic(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    from alfa.core import brain

    agentic = AsyncMock(return_value="agentic-ok")
    monkeypatch.setattr(brain, "run_openai_agentic_turn", agentic)
    monkeypatch.setattr(brain, "build_openai_tools", lambda **k: [])
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq", enable_tools=1), "p", "s")
    )
    assert out == "agentic-ok"
    assert agentic.await_args.kwargs["approval_gate"] is llm.swarm_headless_gate


def test_generate_agent_response_tools_agentic_empty_then_fallback(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    from alfa.core import brain

    monkeypatch.setattr(
        brain, "run_openai_agentic_turn", AsyncMock(return_value="(provider tidak mengirim teks)")
    )
    monkeypatch.setattr(brain, "build_openai_tools", lambda **k: [])
    compat = AsyncMock(return_value="compat-fallback")
    monkeypatch.setattr(llm, "_generate_with_openai_compat", compat)
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq", enable_tools=1), "p", "s")
    )
    assert out == "compat-fallback"
    assert compat.await_args.kwargs["require_content"] is True


def test_generate_agent_response_all_fail(monkeypatch):
    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda agent: ("groq", "key", "model", "https://g", 1)
    )
    monkeypatch.setattr(llm, "_generate_with_openai_compat", AsyncMock(return_value=None))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = asyncio.run(
        llm.generate_agent_response(_agent(provider="groq"), "p", "s")
    )
    assert out is None


def test_generate_agent_response_patched_module(monkeypatch):
    fake_module = types.ModuleType("swarm_engine")
    fake_module.generate_agent_response = AsyncMock(return_value="patched")
    monkeypatch.setitem(sys.modules, "swarm_engine", fake_module)
    out = asyncio.run(llm.generate_agent_response(_agent(), "p", "s"))
    assert out == "patched"


def test_swarm_headless_gate_allowed_and_denied(monkeypatch):
    from alfa.core.perm import gate

    monkeypatch.setattr(gate, "check_headless_approval", lambda *a: "denied")
    assert asyncio.run(llm.swarm_headless_gate("execute_bash_command")) is None
    assert asyncio.run(llm.swarm_headless_gate("vault_get")) == "denied"


def test_known_openai_providers_nonempty():
    assert "openai" in llm.KNOWN_OPENAI_PROVIDERS
    assert "ollama" in llm.KNOWN_OPENAI_PROVIDERS
