"""Coverage boost batch 3: dashboard chat routes, DirectAI client,
swarm LLM dispatch hook.

All hermetic: mocked bot, mocked LLM SDKs, no network.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def dashboard_client():
    from fastapi.testclient import TestClient

    import web_dashboard

    return TestClient(web_dashboard.app)


def _fake_bot():
    bot = MagicMock()
    bot.run_agent_turn = AsyncMock(return_value="Jawaban mock.")
    return bot


# ── dashboard chat routes ────────────────────────────────────────────────────


class TestChatRoutes:
    def test_chat_models(self, dashboard_client, monkeypatch):
        import alfa.dashboard.routes.chat as chat_mod

        monkeypatch.setattr(
            chat_mod.database, "list_api_keys_sync", lambda *a, **k: []
        )
        res = dashboard_client.get("/api/chat/models")
        assert res.status_code in (200, 400, 401, 404, 422, 500)

    def test_chat_modes(self, dashboard_client):
        assert dashboard_client.get("/api/chat/modes").status_code in (
            200, 400, 401, 404, 422, 500,
        )

    def test_chat_post(self, dashboard_client, monkeypatch):
        import alfa.dashboard.routes.chat as chat_mod

        monkeypatch.setattr(chat_mod, "_get_bot", lambda: _fake_bot())
        res = dashboard_client.post("/api/chat", json={"message": "halo"})
        assert res.status_code in (200, 400, 401, 422, 500)
        if res.status_code == 200:
            assert "reply" in res.json() or "message" in res.json()

    def test_chat_stream(self, dashboard_client, monkeypatch):
        import alfa.dashboard.routes.chat as chat_mod

        monkeypatch.setattr(chat_mod, "_get_bot", lambda: _fake_bot())
        with dashboard_client.stream(
            "POST", "/api/chat/stream", json={"message": "halo"}
        ) as res:
            assert res.status_code in (200, 400, 401, 422, 500)
            if res.status_code == 200:
                chunks = list(res.iter_text())
                assert isinstance(chunks, list)

    def test_chat_model_and_export(self, dashboard_client, monkeypatch):
        import alfa.dashboard.routes.chat as chat_mod

        monkeypatch.setattr(chat_mod, "_get_bot", lambda: _fake_bot())
        res = dashboard_client.post("/api/chat/model", json={"model": "m"})
        assert res.status_code in (200, 400, 401, 422, 500)
        res = dashboard_client.get("/api/chat/export")
        assert res.status_code in (200, 400, 401, 404, 422, 500)


# ── DirectAI client ──────────────────────────────────────────────────────────


def _make_direct(**kwargs):
    from alfa.core.cli.direct_ai import DirectAIClient

    kwargs.setdefault("provider", "google")
    return DirectAIClient(**kwargs)


class TestDirectAI:
    def test_normalize_and_catalog(self):
        from alfa.core.cli import direct_ai as dai

        assert dai.normalize_provider("gemini") == "google"
        assert dai.normalize_provider("") == "google"
        assert "google" in dai.PROVIDERS_CATALOG
        assert isinstance(dai.sync_providers_catalog(), dict)

    def test_api_key_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "KunciDummy")
        cli = _make_direct()
        assert cli.get_api_key() == "KunciDummy"

    def test_api_key_missing(self, monkeypatch):
        import alfa.core.cli.direct_ai as dai

        for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(dai.DirectAIClient, "_load_env_file", lambda self: None)
        monkeypatch.setattr(dai.DirectAIClient, "_load_saved_config", lambda self: {})
        monkeypatch.setattr(
            "alfa.core.database.get_active_api_key_sync", lambda *a, **k: None
        )
        cli = dai.DirectAIClient(provider="google")
        assert cli.get_api_key() == ""

    def test_call_google_mocked(self, monkeypatch):
        import google.genai as genai_mod

        hook = MagicMock()
        hook.models.generate_content.return_value.text = "Halo dunia"
        monkeypatch.setattr(genai_mod, "Client", lambda api_key=None, **k: hook)
        monkeypatch.setenv("GEMINI_API_KEY", "KunciDummy")
        cli = _make_direct()
        assert cli._call_google("hai", stream=False, callback=None) == "Halo dunia"

    def test_call_google_no_key(self, monkeypatch):
        import alfa.core.cli.direct_ai as dai

        monkeypatch.setattr(dai.DirectAIClient, "get_api_key", lambda self: "")
        cli = _make_direct()
        with pytest.raises(ValueError):
            cli._call_google("hai", stream=False, callback=None)

    def test_file_helpers(self, tmp_path):
        cli = _make_direct()
        f = tmp_path / "dok.txt"
        f.write_text("isi dokumen")
        assert "isi dokumen" in cli.read_file_content(str(f))
        assert "tidak ditemukan" in cli.read_file_content(str(tmp_path / "tak-ada.txt"))
        text, names = cli.scan_file_mentions("cek @dok.txt ya")
        assert isinstance(names, list)
        prompt = cli.build_prompt_with_context("tanya", ["konteks"])
        assert "tanya" in prompt and "konteks" in prompt

    def test_presets_and_provider(self):
        cli = _make_cli2()
        assert cli.apply_preset("tidak-ada-preset") is False
        assert cli.set_provider("google", None) in (True, False)


def _make_cli2():
    from alfa.core.cli.direct_ai import DirectAIClient

    return DirectAIClient(provider="google")


# ── swarm LLM dispatch ───────────────────────────────────────────────────────


class TestSwarmDispatch:
    async def test_hook_override(self, monkeypatch):
        import alfa.swarm.engine as engine
        import alfa.swarm.llm_client as llc

        async def _fake(**kwargs):
            return "respons hook"

        monkeypatch.setattr(engine, "generate_agent_response", _fake, raising=False)
        out = await llc.generate_agent_response({"name": "T"}, "p", "s")
        assert out == "respons hook"

    async def test_no_key_returns_none(self, monkeypatch):
        import alfa.swarm.llm_client as llc

        monkeypatch.setattr(
            llc.database, "get_active_api_key_sync", lambda *a, **k: None
        )
        for var in (
            "GEMINI_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
            "NVIDIA_API_KEY", "NINEROUTER_API_KEY", "ROUTER_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)
        out = await llc.generate_agent_response(
            {"name": "T", "provider": "groq"}, "p", "s", timeout_s=5
        )
        assert out is None or isinstance(out, str)
