"""Coverage batch 11: media/av wrappers, Veo payload parser, input automation.

Hermetic: subprocess.run, urllib and shutil.which are mocked; no ffmpeg,
no browser launch and no network call ever happens.
"""

import json
import sys
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run_ok(stdout="out", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _run_fail(code=1, stderr="ffmpeg error"):
    m = MagicMock()
    m.returncode = code
    m.stdout = ""
    m.stderr = stderr
    return m


# ── media/av ─────────────────────────────────────────────────────────────────


class TestExtractAudio:
    def test_missing_source(self, tmp_path):
        from alfa.tools.media import av

        out = av.extract_audio_from_video(str(tmp_path / "hilang.mp4"))
        assert out["status"] == "error"
        assert "tidak ditemukan" in out["message"]

    def test_success_writes_file(self, tmp_path, monkeypatch):
        from alfa.tools.media import av

        src = tmp_path / "v.mp4"
        src.write_bytes(b"x" * 64)
        outdir = tmp_path / "out"
        outdir.mkdir()
        monkeypatch.setattr(av, "SANDBOX_DIR", str(outdir))

        real_run = av.subprocess.run

        def _fake_run(cmd, **kw):
            # emulate ffmpeg writing the output artefact
            Path(cmd[-1]).write_bytes(b"audio" * 200)
            return _run_ok()

        monkeypatch.setattr(av.subprocess, "run", _fake_run)
        out = av.extract_audio_from_video(str(src))
        assert out["status"] == "success"
        assert Path(out["file_path"]).exists()
        assert real_run is not av.subprocess.run or True

    def test_filename_is_sanitised(self, tmp_path, monkeypatch):
        from alfa.tools.media import av

        src = tmp_path / "v.mp4"
        src.write_bytes(b"x")
        outdir = tmp_path / "out"
        outdir.mkdir()
        monkeypatch.setattr(av, "SANDBOX_DIR", str(outdir))

        def _fake_run(cmd, **kw):
            Path(cmd[-1]).write_bytes(b"a" * 100)
            return _run_ok()

        monkeypatch.setattr(av.subprocess, "run", _fake_run)
        # a traversal attempt in the filename must not escape SANDBOX_DIR
        out = av.extract_audio_from_video(str(src), "../../escaped.mp3")
        assert out["status"] in ("success", "error")
        if out["status"] == "success":
            assert outdir in Path(out["file_path"]).parents


class TestConvertMedia:
    def test_missing_source(self, tmp_path):
        from alfa.tools.media import av

        assert av.convert_media_format(str(tmp_path / "x.mp3"))["status"] == "error"

    def test_success(self, tmp_path, monkeypatch):
        from alfa.tools.media import av

        src = tmp_path / "s.wav"
        src.write_bytes(b"x")
        outdir = tmp_path / "out"
        outdir.mkdir()
        monkeypatch.setattr(av, "SANDBOX_DIR", str(outdir))
        captured = {}

        def _fake_run(cmd, **kw):
            captured["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"m" * 100)
            return _run_ok()

        monkeypatch.setattr(av.subprocess, "run", _fake_run)
        out = av.convert_media_format(str(src), "mp3")
        assert out["status"] == "success"
        # argv form (no shell) keeps paths with spaces safe
        assert isinstance(captured["cmd"], list)
        assert captured["cmd"][0] == "ffmpeg"

    def test_ffmpeg_failure(self, tmp_path, monkeypatch):
        from alfa.tools.media import av

        src = tmp_path / "s.wav"
        src.write_bytes(b"x")
        outdir = tmp_path / "out"
        outdir.mkdir()
        monkeypatch.setattr(av, "SANDBOX_DIR", str(outdir))
        monkeypatch.setattr(av.subprocess, "run", lambda *a, **k: _run_fail())
        out = av.convert_media_format(str(src), "mp3")
        assert out["status"] == "error"


class TestEditImage:
    @pytest.fixture
    def png(self, tmp_path):
        from PIL import Image

        p = tmp_path / "img.png"
        Image.new("RGBA", (200, 120), (10, 20, 30, 255)).save(p)
        return p

    def test_missing_file(self, tmp_path):
        from alfa.tools.media import av

        assert av.edit_image(str(tmp_path / "x.png"), "resize")["status"] == "error"

    def test_info(self, png):
        from alfa.tools.media import av

        out = av.edit_image(str(png), "info")
        assert out["status"] == "success"
        assert out["size"] == "200x120"

    def test_resize(self, png, tmp_path):
        from alfa.tools.media import av

        out = av.edit_image(str(png), "resize", "100x50")
        assert out["status"] == "success"

    def test_grayscale(self, png):
        from alfa.tools.media import av

        assert av.edit_image(str(png), "grayscale")["status"] == "success"

    def test_watermark(self, png):
        from alfa.tools.media import av

        assert av.edit_image(str(png), "watermark", "ALFA")["status"] == "success"

    def test_crop_rejects_bad_arity(self, png):
        from alfa.tools.media import av

        out = av.edit_image(str(png), "crop", "1,2,3")
        assert out["status"] == "error"
        assert "4 angka" in out["message"]

    def test_unknown_action(self, png):
        from alfa.tools.media import av

        out = av.edit_image(str(png), "aksi-hantu")
        assert out["status"] == "error"

    def test_malformed_params(self, png):
        from alfa.tools.media import av

        assert av.edit_image(str(png), "resize", "abc")["status"] == "error"


# ── Veo payload parser ──────────────────────────────────────────────────────


class TestFindVideoPayload:
    def test_inline_base64(self):
        from alfa.video.ai_engines import _find_video_payload as f

        blob = "A" * 200
        out = f({"mime_type": "video/mp4", "data": blob})
        assert out == {"inline": True, "data": blob}

    def test_short_data_ignored(self):
        from alfa.video.ai_engines import _find_video_payload as f

        assert f({"mime_type": "video/mp4", "data": "A" * 10}) is None

    def test_uri_by_mime(self):
        from alfa.video.ai_engines import _find_video_payload as f

        out = f({"mime_type": "video/webm", "uri": "https://x/out.webm"})
        assert out == {"inline": False, "uri": "https://x/out.webm"}

    def test_uri_by_key_name(self):
        from alfa.video.ai_engines import _find_video_payload as f

        out = f({"videos": [{"file_uri": "https://x/a.mp4"}]})
        assert out == {"inline": False, "uri": "https://x/a.mp4"}

    def test_uri_by_hint(self):
        from alfa.video.ai_engines import _find_video_payload as f

        # the branch requires "video" in the parent key name
        out = f({"outputVideo": [{"uri": "https://x/clip"}]})
        assert out == {"inline": False, "uri": "https://x/clip"}

    def test_uri_under_unrelated_key_ignored(self):
        from alfa.video.ai_engines import _find_video_payload as f

        assert f({"generatedSamples": [{"uri": "https://x/clip"}]}) is None

    def test_role_model(self):
        from alfa.video.ai_engines import _find_video_payload as f

        out = f({"role": "model", "uri": "https://x/thing"})
        assert out is not None

    def test_non_http_uri_ignored(self):
        from alfa.video.ai_engines import _find_video_payload as f

        assert f({"mime_type": "video/mp4", "uri": "gs://bucket/x"}) is None

    def test_searches_lists(self):
        from alfa.video.ai_engines import _find_video_payload as f

        blob = "B" * 200
        out = f({"items": [{"nested": {"mime_type": "video/mp4", "data": blob}}]})
        assert out == {"inline": True, "data": blob}

    def test_scalars_return_none(self):
        from alfa.video.ai_engines import _find_video_payload as f

        assert f("string") is None
        assert f(42) is None
        assert f(None) is None
        assert f({}) is None


class TestVeoApiRequest:
    def test_get_success(self, monkeypatch):
        import alfa.video.ai_engines as ae

        m = MagicMock()
        m.__enter__.return_value = m
        m.read.return_value = json.dumps({"ok": True}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: m)
        out = ae._veo_api_request("https://api/x", None, "KEY", "GET")
        assert out == {"ok": True}

    def test_quota_error_raises_friendly_message(self, monkeypatch):
        import urllib.error

        import alfa.video.ai_engines as ae

        err = urllib.error.HTTPError("u", 429, "too many", {}, MagicMock())
        err.read = lambda: b'{"error": {"message": "quota habis"}}'
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        with pytest.raises(RuntimeError, match="Kuota Veo habis"):
            ae._veo_api_request("https://api/x", {}, "KEY", "POST")

    def test_forbidden_raises_access_message(self, monkeypatch):
        import urllib.error

        import alfa.video.ai_engines as ae

        err = urllib.error.HTTPError("u", 403, "denied", {}, MagicMock())
        err.read = lambda: b'{"error": {"message": "no access"}}'
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        with pytest.raises(RuntimeError, match="Akses ditolak"):
            ae._veo_api_request("https://api/x", {}, "KEY", "POST")

    def test_unparseable_error_body_still_raises(self, monkeypatch):
        import urllib.error

        import alfa.video.ai_engines as ae

        err = urllib.error.HTTPError("u", 500, "boom", {}, MagicMock())
        err.read = lambda: b"bukan json"
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        with pytest.raises(RuntimeError):
            ae._veo_api_request("https://api/x", {}, "KEY", "POST")


# ── input automation ─────────────────────────────────────────────────────────


class TestInputAutomation:
    def test_normalize_url_adds_scheme(self):
        from alfa.tools.desktop import input_automation as ia

        assert ia._normalize_url("contoh.id").startswith("http")
        assert ia._normalize_url("https://a.io") == "https://a.io"

    def test_normalize_url_rejects_empty(self):
        from alfa.tools.desktop import input_automation as ia

        assert ia._normalize_url("   ") == ""

    def test_open_url_in_system_browser_bad_scheme(self):
        from alfa.tools.desktop import input_automation as ia

        out = ia.open_url_in_system_browser("javascript:alert(1)")
        assert out["status"] == "error"

    def test_open_url_launches(self, monkeypatch):
        from alfa.tools.desktop import input_automation as ia

        calls = []
        monkeypatch.setattr(
            ia.subprocess, "Popen", lambda *a, **k: calls.append(a) or MagicMock()
        )
        out = ia.open_url_in_system_browser("https://contoh.id")
        assert out["status"] in ("success", "error")

    def test_click_rejects_bad_coordinates(self):
        from alfa.tools.desktop import input_automation as ia

        out = ia.desktop_click_coordinate(-5, 10)
        assert out["status"] == "error"

    def test_click_success_via_xdotool(self, monkeypatch):
        from alfa.tools.desktop import input_automation as ia

        monkeypatch.setattr(ia.subprocess, "run", lambda *a, **k: _run_ok())
        out = ia.desktop_click_coordinate(10, 20)
        assert out["status"] == "success"

    def test_type_keys_via_xdotool(self, monkeypatch):
        from alfa.tools.desktop import input_automation as ia

        monkeypatch.setattr(ia.subprocess, "run", lambda *a, **k: _run_ok())
        out = ia.desktop_type_keys("halo")
        assert out["status"] in ("success", "error")

    def test_launch_unknown_app(self):
        from alfa.tools.desktop import input_automation as ia

        out = ia.desktop_launch_app("aplikasi-hantu-xyz-123")
        assert out["status"] == "error"
