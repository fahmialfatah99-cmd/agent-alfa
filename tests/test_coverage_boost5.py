"""Coverage boost batch 5: brain helpers, scrapers (mocked HTTP),
CLI app flows.

All hermetic: no network (mocked urlopen), tmp files, mocked input.
"""

import sys
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_cli():
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone", attached_files=[])
    cli._save_config = lambda *a, **k: None
    cli._update_prompt = lambda *a, **k: None
    return cli


# ── brain pure helpers ───────────────────────────────────────────────────────


class TestBrainHelpers:
    def test_parse_args_docstring(self):
        from alfa.core import brain as br

        assert br._parse_args_docstring("Args:\n    x: nilai x\n    y: nilai y") == {
            "x": "nilai x",
            "y": "nilai y",
        }
        assert br._parse_args_docstring("tanpa args") == {}

    def test_fn_to_openai_tool(self):
        from alfa.core import brain as br

        def _contoh(x: str, n: int = 3) -> str:
            """Contoh.

            Args:
                x: teks.
                n: angka.
            """
            return x

        spec = br._fn_to_openai_tool(_contoh)
        assert spec["function"]["name"] == "_contoh"
        assert "x" in spec["function"]["parameters"]["properties"]

    def test_build_openai_tools(self):
        from alfa.core import brain as br

        assert isinstance(br.build_openai_tools(safe_only=True), list)
        assert isinstance(br.build_openai_tools(safe_only=False), list)

    def test_find_and_execute_tool(self):
        from alfa.core import brain as br

        assert br._find_tool("tidak_ada_tool_xyz") is None
        out = br._execute_tool("tidak_ada_tool_xyz", "{}")
        assert isinstance(out, str)

    def test_clean_json_args(self):
        from alfa.core import brain as br

        assert br._clean_json_args('{"a": 1}') == {"a": 1}
        assert isinstance(br._clean_json_args("```json\n{\"a\": 1}\n```"), dict)
        with pytest.raises(ValueError):
            br._clean_json_args("bukan json{{{")

    def test_convo_helpers(self):
        from alfa.core import brain as br

        convo = [{"role": "user", "content": "x" * 5000}]
        assert br._convo_size(convo) > 0
        assert isinstance(br._compact_convo(convo), list)

    def test_get_main_brain(self, monkeypatch):
        import alfa.core.brain as br

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(
            "alfa.core.database.get_active_api_key_sync", lambda *a, **k: None
        )
        assert isinstance(br.get_main_brain(), dict)


# ── scrapers with mocked HTTP ────────────────────────────────────────────────


_HTML = (
    b"<html><head><title>Uji</title></head><body>"
    b"<h1>Judul</h1><p>Harga Rp 100</p>"
    b'<a href="/x">tautan</a></body></html>'
)


class _FakeResp:
    def __init__(self, body=_HTML, status=200):
        self._body = body
        self.status = status
        self.headers = {}

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _mock_urlopen(monkeypatch, body=_HTML, status=200):
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=15: _FakeResp(body, status)
    )


class TestScrapersMocked:
    def test_require_http_url(self):
        from alfa.tools.web import scrapers as sc

        assert sc._require_http_url("https://contoh.id") is None
        assert sc._require_http_url("file:///etc/passwd")["status"] == "error"
        assert sc._require_http_url("gopher://x")["status"] == "error"

    def test_scrapy_spider(self, monkeypatch):
        from alfa.tools.web import scrapers as sc

        _mock_urlopen(monkeypatch)
        res = sc.scrapy_spider_quick_scrape(
            "https://contoh.id", '{"judul": "h1::text"}'
        )
        assert res["status"] == "success"
        bad = sc.scrapy_spider_quick_scrape("file:///etc/passwd", "{}")
        assert bad["status"] == "error"

    def test_crawl4ai(self, monkeypatch):
        from alfa.tools.web import scrapers as sc

        _mock_urlopen(monkeypatch)
        res = sc.crawl4ai_web_crawler("https://contoh.id")
        assert res["status"] == "success"
        assert sc.crawl4ai_web_crawler("ftp://x")["status"] == "error"

    def test_firecrawl_no_key(self, monkeypatch):
        from alfa.tools.web import scrapers as sc

        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        res = sc.firecrawl_scrape_and_crawl("https://contoh.id")
        assert res["status"] in ("success", "error")


# ── CLI app flows ────────────────────────────────────────────────────────────


class TestAppFlows:
    def test_show_config(self, capsys):
        from alfa.core.cli import app as app_mod

        app_mod.show_config()
        assert len(capsys.readouterr().out) > 0

    def test_handle_ask_mocked(self, monkeypatch, capsys):
        import alfa.core.cli.app as app_mod

        fake_direct = MagicMock()
        fake_direct.generate.return_value = "jawaban mock"
        monkeypatch.setattr(
            "alfa.core.cli.app.DirectAIClient",
            lambda **k: fake_direct,
        )
        args = MagicMock(
            question="apa ini?",
            file=[],
            model=None,
            provider=None,
            server="http://localhost:8080",
            standalone=True,
            mode="standalone",
            stream=False,
            agent=False,
        )
        try:
            app_mod.handle_ask_command(args)
        except SystemExit:
            pass
        assert "jawaban mock" in capsys.readouterr().out

    def test_run_config_wizard(self, monkeypatch, capsys, tmp_path):
        import alfa.core.cli.app as app_mod

        monkeypatch.setattr("builtins.input", lambda *a, **k: "")
        monkeypatch.setattr("getpass.getpass", lambda *a, **k: "")
        try:
            app_mod.run_config_wizard()
        except (SystemExit, EOFError, KeyboardInterrupt):
            pass
        capsys.readouterr()

    def test_main_help(self, monkeypatch, capsys):
        import alfa.core.cli.app as app_mod

        monkeypatch.setattr(sys, "argv", ["alfa", "--help"])
        with pytest.raises(SystemExit):
            app_mod.main()
