"""Phase 6 coverage: cloud AI video engines (Google Veo & Gemini Omni Flash).

Hermetic: semua HTTP, ffmpeg, voiceover, dan overlay di-mock; file media hanya
berada di ``tmp_path``. Tidak ada API atau proses eksternal yang dijalankan.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest


@pytest.fixture
def ae(monkeypatch, tmp_path):
    from alfa.video import ai_engines

    monkeypatch.setattr(ai_engines, "VIDEO_OUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        ai_engines,
        "time",
        SimpleNamespace(sleep=lambda seconds: None, time=lambda: 1000.0),
    )
    (tmp_path / "Frames").mkdir()
    return ai_engines


class FakeResponse:
    """Context manager minimal untuk urllib response."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        data, self._payload = self._payload, b""
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _record_requests(ae, monkeypatch, responses):
    calls: list[tuple] = []

    def fake_request(url, payload=None, api_key="", method="GET"):
        calls.append((url, payload, api_key, method))
        return responses.pop(0)

    monkeypatch.setattr(ae, "_veo_api_request", fake_request)
    return calls


def _patch_compositor(ae, monkeypatch, tmp_path):
    overlays: list[dict] = []
    subprocess_calls: list[list] = []

    def fake_run(cmd, **kwargs):
        subprocess_calls.append(cmd)
        with open(cmd[-1], "wb") as handle:
            handle.write(b"x" * (1024 * 1024))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ae.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ae,
        "generate_voiceover",
        lambda text, voice="": str(tmp_path / "voice.mp3"),
    )
    monkeypatch.setattr(ae, "get_audio_duration", lambda path: 4.0)
    monkeypatch.setattr(
        ae,
        "create_ui_overlay_layer",
        lambda **kwargs: overlays.append(kwargs),
    )
    return overlays, subprocess_calls


# ---------------------------------------------------------------------------
# Google Veo
# ---------------------------------------------------------------------------


def test_veo_success_with_reference_image(ae, monkeypatch, tmp_path):
    ref = tmp_path / "produk.png"
    ref.write_bytes(b"gambar-produk")
    responses = [
        {"name": "operations/veo-1"},
        {"done": False},
        {
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [
                        {"video": {"uri": "https://cdn.test/video/veo.mp4"}}
                    ]
                }
            },
        },
    ]
    calls = _record_requests(ae, monkeypatch, responses)
    overlays, ffmpeg_calls = _patch_compositor(ae, monkeypatch, tmp_path)

    downloaded: list[str] = []

    def fake_urlopen(req, timeout=0):
        downloaded.append(req.full_url)
        return FakeResponse(b"raw-veo-mp4")

    monkeypatch.setattr(ae.urllib.request, "urlopen", fake_urlopen)

    out = ae._generate_google_veo_video(
        "google_veo_fast",
        "KEY",
        [str(ref), str(tmp_path / "missing.png")],
        "Produk Uji!",
        "",
        "narasi promosi",
        "100000",
        "75000",
        "id-ID-Wavenet-A",
        badge_text="PROMO",
        call_to_action="BELI",
    )

    assert out["status"] == "success"
    assert out["engine"] == "google_veo"
    assert out["model"] == "veo-3.1-fast-generate-preview"
    assert out["video_filename"] == "Produk_Uji__veo_1000.mp4"
    assert out["duration_seconds"] == 4.0
    assert out["file_size_mb"] > 0
    assert out["visual_prompt"].startswith("Cinematic 8K commercial studio video")
    assert calls[0][3] == "POST"
    assert calls[0][1]["instances"][0]["image"]["bytesBase64Encoded"]
    assert calls[0][1]["instances"][0]["image"]["mimeType"] == "image/png"
    assert downloaded == ["https://cdn.test/video/veo.mp4"]
    assert overlays[0]["badge_text"] == "PROMO"
    assert overlays[0]["call_to_action"] == "BELI"
    assert ffmpeg_calls and ffmpeg_calls[0][-1].endswith(".mp4")
    assert not list(tmp_path.glob("veo_raw_*.mp4"))


def test_veo_success_custom_filename(ae, monkeypatch, tmp_path):
    responses = [
        {"name": "operations/veo-2"},
        {
            "done": True,
            "response": {
                "videos": [{"uri": "https://cdn.test/video/two.mp4"}],
            },
        },
    ]
    _record_requests(ae, monkeypatch, responses)
    _patch_compositor(ae, monkeypatch, tmp_path)
    monkeypatch.setattr(
        ae.urllib.request, "urlopen", lambda req, timeout=0: FakeResponse(b"mp4")
    )

    out = ae._generate_google_veo_video(
        "google_veo",
        "KEY",
        [],
        "Produk",
        "prompt khusus",
        "narasi",
        "1",
        "2",
        "voice",
        output_filename="hasil final",
    )
    assert out["video_filename"] == "hasil final.mp4"
    assert out["visual_prompt"] == "prompt khusus"


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([{}], "gagal membuat operasi"),
        ([{"name": "op"}, {"error": {"code": 500}}], "Veo error"),
        ([{"name": "op"}, {"done": True, "response": {}}], "selesai tanpa video"),
    ],
)
def test_veo_error_paths(ae, monkeypatch, responses, message):
    _record_requests(ae, monkeypatch, responses)
    with pytest.raises(RuntimeError, match=message):
        ae._generate_google_veo_video(
            "google_veo", "KEY", [], "P", "", "v", "1", "2", "voice"
        )


def test_veo_timeout(ae, monkeypatch):
    _record_requests(ae, monkeypatch, [{"name": "op"}] + [{"done": False}] * 60)
    sleeps: list[int] = []
    monkeypatch.setattr(
        ae,
        "time",
        SimpleNamespace(sleep=sleeps.append, time=lambda: 1000.0),
    )
    with pytest.raises(RuntimeError, match="Veo timeout"):
        ae._generate_google_veo_video(
            "google_veo", "KEY", [], "P", "", "v", "1", "2", "voice"
        )
    assert sleeps == [10] * 60


# ---------------------------------------------------------------------------
# Gemini Omni Flash
# ---------------------------------------------------------------------------


def test_omni_success_inline_with_image(ae, monkeypatch, tmp_path):
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"jpg")
    blob = base64.b64encode(b"z" * 200).decode()
    responses = [
        {"id": "interactions/omni-1"},
        {"status": "running"},
        {
            "status": "completed",
            "output": [{"mime_type": "video/mp4", "data": blob}],
        },
    ]
    calls = _record_requests(ae, monkeypatch, responses)
    _patch_compositor(ae, monkeypatch, tmp_path)

    out = ae._generate_gemini_omni_video(
        "google_omni_flash",
        "KEY",
        [str(ref)],
        "Produk Omni",
        "",
        "narasi",
        "10",
        "5",
        "voice",
    )

    assert out["status"] == "success"
    assert out["engine"] == "google_omni_flash"
    assert out["model"] == "gemini-omni-flash-preview"
    assert out["task"] == "image_to_video"
    assert out["video_filename"] == "Produk_Omni_omni_1000.mp4"
    assert calls[0][0].endswith("/interactions")
    assert calls[0][1]["input"][0]["type"] == "image"
    assert calls[0][1]["background"] is True


def test_omni_success_download_uri(ae, monkeypatch, tmp_path):
    responses = [
        {"name": "interactions/omni-2"},
        {"done": True, "output": [{"uri": "https://cdn.test/video/omni.mp4"}]},
    ]
    _record_requests(ae, monkeypatch, responses)
    _patch_compositor(ae, monkeypatch, tmp_path)
    downloaded: list[str] = []

    def fake_urlopen(req, timeout=0):
        downloaded.append(req.full_url)
        return FakeResponse(b"raw-omni")

    monkeypatch.setattr(ae.urllib.request, "urlopen", fake_urlopen)

    out = ae._generate_gemini_omni_video(
        "google_omni_flash",
        "KEY",
        [],
        "Produk",
        "",
        "narasi",
        "1",
        "2",
        "voice",
        output_filename="omni/hasil",
    )
    assert out["task"] == "text_to_video"
    assert out["video_filename"] == "hasil.mp4"
    assert downloaded == ["https://cdn.test/video/omni.mp4"]


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([{}], "gagal membuat interaksi"),
        (
            [{"name": "op"}, {"error": {"message": "quota"}}],
            "Omni Flash error",
        ),
        ([{"name": "op"}, {"done": True}], "Omni Flash timeout"),
    ],
)
def test_omni_error_paths(ae, monkeypatch, responses, message):
    _record_requests(ae, monkeypatch, responses)
    with pytest.raises(RuntimeError, match=message):
        ae._generate_gemini_omni_video(
            "google_omni_flash", "KEY", [], "P", "", "v", "1", "2", "voice"
        )


def test_omni_timeout_pending(ae, monkeypatch):
    _record_requests(
        ae, monkeypatch, [{"name": "op"}] + [{"status": "pending"}] * 60
    )
    with pytest.raises(RuntimeError, match="Omni Flash timeout"):
        ae._generate_gemini_omni_video(
            "google_omni_flash", "KEY", [], "P", "", "v", "1", "2", "voice"
        )


# ---------------------------------------------------------------------------
# Cloud dispatcher
# ---------------------------------------------------------------------------


def test_cloud_ai_dispatcher(ae):
    out = ae._generate_cloud_ai_video(
        "kling", "KEY", [], "Produk", "prompt", "narasi", "1", "2", "voice", None
    )
    assert out["status"] == "pending_api_dispatch"
    assert out["engine"] == "kling"
    assert "KLING" in out["message"]
