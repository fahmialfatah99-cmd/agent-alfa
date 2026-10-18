"""Upgrade coverage batch 1: docs, CLI shims, affiliate engine (mocked),
and DirectAI HTTP backends (mocked). All hermetic — no network, no prod DB.
"""

import sys

import pytest


class TestToolsDocs:
    def test_descriptions_sane(self):
        from alfa.tools.docs import TOOL_DESCRIPTIONS

        assert len(TOOL_DESCRIPTIONS) > 100
        for key in (
            "execute_bash_command",
            "affiliate_hunt_trending_products",
            "read_local_file",
        ):
            assert TOOL_DESCRIPTIONS[key].strip()
        assert all(isinstance(v, str) for v in TOOL_DESCRIPTIONS.values())


class TestCliShims:
    def test_cli_shim_import(self):
        import alfa.core.cli as root_cli


        assert hasattr(root_cli, "main")

    def test_personas_data(self):
        from alfa.swarm import personas

        prompts = personas.build_prompts()
        assert len(prompts) == 6
        assert all(isinstance(v, str) and v for v in prompts.values())

    def test_apply_personas_consts(self):
        import alfa.swarm.apply_personas as ap

        assert "TIM SWARM" in ap.TEAM_SECTION
        assert ap.PROMPT_FILE.endswith("system_prompt.txt")


@pytest.fixture()
def affiliate_mod(tmp_path, monkeypatch):
    import alfa.tools.web.affiliate_engine as ae

    monkeypatch.setattr(ae, "DB_PATH", str(tmp_path / "aff_test.db"))
    ae.init_affiliate_tables()
    return ae


class TestAffiliateEngine:
    def test_research_mocked(self, affiliate_mod, monkeypatch):
        import alfa.tools as tools

        monkeypatch.setattr(
            tools,
            "web_search",
            lambda q: {
                "results": [
                    {"title": "Powerbank Viral", "snippet": "murah", "link": "http://x"}
                ]
            },
        )
        res = affiliate_mod.research_trending_niche("powerbank")
        assert res["status"] == "success"
        assert res["total_found"] == 1

    def test_research_error_path(self, affiliate_mod, monkeypatch):
        import alfa.tools as tools

        def boom(q):
            raise RuntimeError("offline")

        monkeypatch.setattr(tools, "web_search", boom)
        res = affiliate_mod.research_trending_niche("powerbank")
        assert res["status"] == "error"

    def test_campaigns_empty_and_missing(self, affiliate_mod):
        assert affiliate_mod.list_affiliate_campaigns() == []
        assert affiliate_mod.get_affiliate_campaign_detail(9999) is None

    def test_broadcast_no_allowlist(self, affiliate_mod, monkeypatch):
        monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
        res = affiliate_mod.broadcast_affiliate_deal(
            product_name="P", message_text="M", affiliate_link="http://x"
        )
        assert isinstance(res, dict)


class _FakeBackend:
    def __init__(self):
        from alfa.core.cli.backends import ClientBackendsMixin

        self._mixin = ClientBackendsMixin
        self.provider = "google"
        self.model = "m1"
        self.base_url = "http://127.0.0.1:9"
        self.system_prompt = "sys"
        self.temperature = 0.1
        self.max_tokens = 32
        self.history = []
        self._keys = {"key": "K"}

    def get_api_key(self):
        return self._keys.get("key", "")

    def _record_history(self, prompt, response):
        self.history.append({"role": "user", "content": prompt})


def _bind(fn, fake):
    return fn.__get__(fake, _FakeBackend)


class _Resp:
    def __init__(self, code=200, payload=None, text=""):
        self.status_code = code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class TestBackendsRest:
    def test_google_rest(self, monkeypatch):
        import alfa.core.cli.backends as be

        monkeypatch.setitem(sys.modules, "google", None)
        monkeypatch.setattr(
            be.requests,
            "post",
            lambda *a, **k: _Resp(
                200, {"candidates": [{"content": {"parts": [{"text": "halo"}]}}]}
            ),
        )
        fake = _FakeBackend()
        assert (
            _bind(be.ClientBackendsMixin._call_google, fake)("hai", False, None)
            == "halo"
        )

    def test_google_no_key(self):
        import alfa.core.cli.backends as be

        fake = _FakeBackend()
        fake._keys = {}
        with pytest.raises(ValueError):
            _bind(be.ClientBackendsMixin._call_google, fake)("hai", False, None)

    def test_google_http_error(self, monkeypatch):
        import alfa.core.cli.backends as be

        monkeypatch.setitem(sys.modules, "google", None)
        monkeypatch.setattr(be.requests, "post", lambda *a, **k: _Resp(500, {}, "boom"))
        fake = _FakeBackend()
        with pytest.raises(RuntimeError):
            _bind(be.ClientBackendsMixin._call_google, fake)("hai", False, None)

    def test_openai_rest(self, monkeypatch):
        import alfa.core.cli.backends as be

        monkeypatch.setitem(sys.modules, "openai", None)
        monkeypatch.setattr(
            be.requests,
            "post",
            lambda *a, **k: _Resp(200, {"choices": [{"message": {"content": "halo"}}]}),
        )
        fake = _FakeBackend()
        fake.provider = "openai"
        assert (
            _bind(be.ClientBackendsMixin._call_openai_compatible, fake)(
                "hai", False, None
            )
            == "halo"
        )

    def test_anthropic_rest(self, monkeypatch):
        import alfa.core.cli.backends as be

        monkeypatch.setitem(sys.modules, "anthropic", None)
        monkeypatch.setattr(
            be.requests,
            "post",
            lambda *a, **k: _Resp(200, {"content": [{"text": "halo"}]}),
        )
        fake = _FakeBackend()
        assert (
            _bind(be.ClientBackendsMixin._call_anthropic, fake)("hai", False, None)
            == "halo"
        )

    def test_ollama_rest(self, monkeypatch):
        import alfa.core.cli.backends as be

        monkeypatch.setattr(
            be.requests,
            "post",
            lambda *a, **k: _Resp(200, {"message": {"content": "halo"}}),
        )
        fake = _FakeBackend()
        assert (
            _bind(be.ClientBackendsMixin._call_ollama, fake)("hai", False, None)
            == "halo"
        )

    def test_ollama_conn_error(self, monkeypatch):
        import requests as _rq

        import alfa.core.cli.backends as be

        def boom(*a, **k):
            raise _rq.exceptions.ConnectionError("down")

        monkeypatch.setattr(be.requests, "post", boom)
        fake = _FakeBackend()
        with pytest.raises(ConnectionError):
            _bind(be.ClientBackendsMixin._call_ollama, fake)("hai", False, None)
