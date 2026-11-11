"""Tes untuk jalur berisiko yang sebelumnya belum ter-cover.

Modul yang dituju:
- ``alfa/tools/web/search.py``   (36% cover) — jalur scraping/pencarian web.
- ``alfa/video/orchestrator.py``  (12% cover) — orkestrasi render video.
- ``alfa/video/ai_engines.py``   (29% cover) — parser payload video.

Semua tester bersifat hermetik: tidak ada jaringan nyata, tidak ada ffmpeg,
tidak menyentuh berkas di luar tmp_path.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

# ── Web search ───────────────────────────────────────────────────────────────


_ERR_DDGS = "SSL reset by peer"
_ERR_OMNI = "API video gagal"
_ERR_FFMPEG = "ffmpeg tidak tersedia"


class TestWebSearch:
    def test_ssl_verify_honours_env(self, monkeypatch):
        from alfa.tools.web import search as s

        monkeypatch.setenv("ALFA_VERIFY_SSL", "true")
        assert s._ssl_verify() is True
        monkeypatch.setenv("ALFA_VERIFY_SSL", "false")
        assert s._ssl_verify() is False
        monkeypatch.delenv("ALFA_VERIFY_SSL", raising=False)
        assert s._ssl_verify() is True

    def test_web_search_formats_ddgs_results(self, monkeypatch):
        from alfa.tools.web import search as s

        class _FakeDDGS:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def text(self, query, max_results=5):
                return [
                    {"title": "Judul A", "body": "Ringkasan A", "href": "https://a.test"},
                    {"title": "Judul B", "body": "Ringkasan B", "href": "https://b.test"},
                ]

        monkeypatch.setattr(s, "DDGS", _FakeDDGS)
        monkeypatch.setattr(s, "_ddgs_circuit_open", lambda: False)
        res = s.web_search("kabar terbaru", max_results=2)
        assert res["status"] == "success"
        assert len(res["results"]) == 2
        assert res["results"][0]["title"] == "Judul A"
        assert res["results"][0]["link"] == "https://a.test"

    def test_web_search_falls_back_when_ddgs_fails(self, monkeypatch):
        from alfa.tools.web import search as s

        class _BrokenDDGS:
            def __init__(self, **kwargs):
                pass

            def text(self, query, max_results=5):
                raise RuntimeError(_ERR_DDGS)

        monkeypatch.setattr(s, "DDGS", _BrokenDDGS)
        monkeypatch.setattr(s, "_ddgs_circuit_open", lambda: False)
        fallback = MagicMock(return_value={"status": "success", "results": [], "engine": "browser"})
        monkeypatch.setattr(s, "_browser_search_fallback", fallback)
        res = s.web_search("apa kabar")
        assert res["status"] == "success"
        assert fallback.called

    def test_circuit_breaker_opens_after_repeated_failures(self, monkeypatch):
        from alfa.tools.web import search as s

        monkeypatch.setitem(s._DDGS_BREAKER, "fails", s._DDGS_FAIL_LIMIT)
        monkeypatch.setitem(s._DDGS_BREAKER, "skip_until", 9e12)
        assert s._ddgs_circuit_open() is True

    def test_fetch_page_blocks_internal_url(self):
        from alfa.tools.web import search as s

        res = s.fetch_web_page_content("http://127.0.0.1:8080/admin")
        assert res["status"] == "error"
        assert "message" in res


# ── Video: orkestrator & engine ─────────────────────────────────────────────


class TestVideoOrchestrator:
    def test_cloud_engine_dispatch_omni(self, monkeypatch):
        from alfa.video import orchestrator as o

        called = {}

        def _fake_omni(**kwargs):
            called.update(kwargs)
            return {"status": "success", "engine": kwargs.get("engine")}

        monkeypatch.setattr(o, "_generate_gemini_omni_video", _fake_omni)
        res = o.generate_video_from_images(
            image_paths=["/tmp/a.png"],
            product_name="Produk",
            voiceover_text=" narrated ",
            engine=next(iter(o.OMNI_MODEL_MAP)),
        )
        assert res["status"] == "success"
        assert called["product_name"] == "Produk"

    def test_cloud_engine_error_is_reported(self, monkeypatch):
        from alfa.video import orchestrator as o

        def _boom(**kwargs):
            raise RuntimeError(_ERR_OMNI)

        monkeypatch.setattr(o, "_generate_gemini_omni_video", _boom)
        res = o.generate_video_from_images(
            image_paths=["/tmp/a.png"],
            product_name="Produk",
            voiceover_text="n",
            engine=next(iter(o.OMNI_MODEL_MAP)),
        )
        assert res["status"] == "error"
        assert "API video gagal" in res["message"]

    def test_veo_dispatch(self, monkeypatch):
        from alfa.video import orchestrator as o

        monkeypatch.setattr(
            o, "_generate_google_veo_video", lambda **kw: {"status": "success", "engine": kw["engine"]}
        )
        res = o.generate_video_from_images(
            image_paths=["/tmp/a.png"],
            product_name="Produk",
            voiceover_text="n",
            engine=next(iter(o.VEO_MODEL_MAP)),
        )
        assert res["status"] == "success"

    def test_cloud_ai_engine_requires_api_key(self, monkeypatch):
        from alfa.video import orchestrator as o

        monkeypatch.setattr(
            o, "_generate_cloud_ai_video", lambda **kw: {"status": "success", "engine": kw["engine"]}
        )
        res = o.generate_video_from_images(
            image_paths=["/tmp/a.png"],
            product_name="Produk",
            voiceover_text="n",
            engine="kling",
            api_key="k",
        )
        assert res["status"] == "success"

    def test_local_render_error_is_reported(self, tmp_path, monkeypatch):
        """Kegagalan ffmpeg harus jadi error terstruktur, bukan crash."""
        from alfa.video import orchestrator as o

        (tmp_path / "Frames").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(o, "VIDEO_OUT_DIR", str(tmp_path))
        monkeypatch.setattr(o, "create_product_stage_layer", lambda *a, **k: None)
        monkeypatch.setattr(o, "generate_voiceover", lambda *a, **k: "")
        monkeypatch.setattr(o, "get_audio_duration", lambda p: 1.0)

        def _boom(*a, **k):
            raise RuntimeError(_ERR_FFMPEG)

        monkeypatch.setattr(o.subprocess, "run", _boom)
        res = o.generate_video_from_images(
            image_paths=[str(tmp_path / "nope.png")],
            product_name="Produk",
            voiceover_text="n",
            engine="local_pro",
        )
        assert res["status"] == "error"
        assert "ffmpeg" in res["message"]


class TestVideoPayloadParsing:
    def test_finds_inline_base64_video(self):
        from alfa.video.ai_engines import _find_video_payload

        payload = {
            "parts": [
                {"mime_type": "video/mp4", "data": "A" * 200},
            ]
        }
        found = _find_video_payload(payload)
        assert found is not None
        assert found["inline"] is True
        assert found["data"].startswith("AAA")

    def test_finds_remote_video_uri(self):
        from alfa.video.ai_engines import _find_video_payload

        found = _find_video_payload({"videos": [{"uri": "https://cdn.test/out.mp4"}]})
        assert found is not None
        assert found["inline"] is False
        assert found["uri"] == "https://cdn.test/out.mp4"

    def test_ignores_non_video_payload(self):
        from alfa.video.ai_engines import _find_video_payload

        assert _find_video_payload({"mime_type": "text/plain", "data": "halo"}) is None
        assert _find_video_payload({"uri": "https://cdn.test/file.txt"}) is None

    def test_serialised_payload_is_scanned_recursively(self):
        """Payload video di dalam kunci 'generatedVideos' tetap dikenali."""
        from alfa.video.ai_engines import _find_video_payload

        blob = json.dumps({"generatedVideos": [{"uri": "https://cdn.test/clip.mp4"}]})
        found = _find_video_payload(json.loads(blob))
        assert found is not None
        assert found["uri"].endswith("clip.mp4")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
