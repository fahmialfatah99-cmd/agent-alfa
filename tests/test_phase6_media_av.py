"""Phase 6 coverage: tool media AV (upscale, promo video, ekstrak audio, TTS, konversi, edit, subtitle).

Hermetic: PIL/ffmpeg/edge_tts/faster_whisper/alfa.video di-mock, semua berkas
hanya di ``tmp_path``; home dan sandbox diarahkan sementara.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def av():
    from alfa.tools.media import av as mod

    return mod


# ---------------------------------------------------------------------------
# Fake PIL
# ---------------------------------------------------------------------------


class FakeImg:
    def __init__(self, size=(100, 50), mode="RGB", fmt="PNG"):
        self.size = size
        self.mode = mode
        self.format = fmt

    @property
    def width(self):
        return self.size[0]

    @property
    def height(self):
        return self.size[1]

    def convert(self, mode):
        self.mode = mode
        return self

    def resize(self, size, resample=None):
        self.size = size
        return self

    def crop(self, box):
        self.size = (box[2] - box[0], box[3] - box[1])
        return self

    def rotate(self, degrees, expand=False):
        return self

    def transpose(self, op):
        return self

    def thumbnail(self, size, resample=None):
        self.size = size

    def filter(self, filt):
        self.last_filter = filt
        return self

    def save(self, path, format=None, quality=None):
        Path(path).write_bytes(b"x" * 2048)
        self.saved_as = (path, format)


def _install_pil(
    monkeypatch, *, fmt="PNG", mode="RGB", truetype_raises=False, size=(100, 50)
):
    opened: list[str] = []
    filters: list = []
    draws: list[tuple] = []

    def fake_open(path):
        opened.append(str(path))
        return FakeImg(size=size, mode=mode, fmt=fmt)

    class FakeDraw:
        def __init__(self, img):
            self.img = img

        def textbbox(self, xy, text, font=None):
            return (0, 0, 60, 20)

        def text(self, xy, text, fill=None, font=None):
            draws.append((xy, text, fill, font))

    def unsharp(**kwargs):
        item = ("unsharp", kwargs)
        filters.append(item)
        return item

    def gaussian(**kwargs):
        item = ("blur", kwargs)
        filters.append(item)
        return item

    def truetype(path, size):
        if truetype_raises:
            raise OSError("file font tidak ada")  # noqa: TRY003
        return "font-dejavu"

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = SimpleNamespace(
        open=fake_open,
        Resampling=SimpleNamespace(NEAREST=0, LANCZOS=1),
        FLIP_LEFT_RIGHT="flip_lr",
        FLIP_TOP_BOTTOM="flip_tb",
    )
    fake_pil.ImageFilter = SimpleNamespace(
        UnsharpMask=unsharp, GaussianBlur=gaussian, SHARPEN="sharpen"
    )
    fake_pil.ImageDraw = SimpleNamespace(Draw=FakeDraw)
    fake_pil.ImageFont = SimpleNamespace(
        truetype=truetype, load_default=lambda: "font-default"
    )
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    return SimpleNamespace(opened=opened, filters=filters, draws=draws)


class _PathProxy:
    def __init__(self, home):
        self._home = str(home)

    def expanduser(self, path):
        if path == "~":
            return self._home
        if path.startswith("~/"):
            return self._home + path[1:]
        return os.path.expanduser(path)

    def __getattr__(self, name):
        return getattr(os.path, name)


class _OsProxy:
    """``os`` yang mengarahkan ``~`` ke rumah sementara di ``tmp_path``."""

    def __init__(self, home):
        self.path = _PathProxy(home)

    def __getattr__(self, name):
        return getattr(os, name)


@pytest.fixture
def sandbox(av, monkeypatch, tmp_path):
    box = tmp_path / "sandbox"
    box.mkdir()
    monkeypatch.setattr(av, "SANDBOX_DIR", str(box))
    return box


# ---------------------------------------------------------------------------
# upscale_image_hd
# ---------------------------------------------------------------------------


def test_upscale_missing_file(av, monkeypatch, tmp_path):
    out = av.upscale_image_hd(str(tmp_path / "hilang.png"))
    assert out["status"] == "error"
    assert "tidak ditemukan" in out["message"]


def _prep_upscale(av, monkeypatch, tmp_path, name="foto.png"):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(av, "os", _OsProxy(home))
    src = tmp_path / name
    src.write_bytes(b"png")
    return src, home


def test_upscale_waifu2x_anime_success(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "foto.png")
    waifu = tmp_path / "waifu"
    waifu.mkdir()
    (waifu / "waifu2x-ncnn-vulkan").write_bytes(b"bin")
    monkeypatch.setenv("ALFA_WAIFU2X_DIR", str(waifu))
    _install_pil(monkeypatch)

    calls: list[list] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[4]).write_bytes(b" hasil ")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(av.subprocess, "run", fake_run)
    out = av.upscale_image_hd(str(src), scale=4, mode="waifu2x_anime", denoise=99)
    assert out["status"] == "success"
    assert "Waifu2x AI (models-upconv_7_anime_style_art_rgb)" in out["engine"]
    assert calls[0][0] == str(waifu / "waifu2x-ncnn-vulkan")
    assert calls[0][calls[0].index("-s") + 1] == "4"
    assert calls[0][calls[0].index("-n") + 1] == "3"
    assert calls[0][calls[0].index("-m") + 1].endswith(
        "models-upconv_7_anime_style_art_rgb"
    )
    assert out["scale"] == 4
    assert out["new_resolution"] == "100x50"
    assert out["original_resolution"] == "25x12"


def test_upscale_waifu2x_photo_model(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path)
    waifu = tmp_path / "waifu"
    waifu.mkdir()
    (waifu / "waifu2x-ncnn-vulkan").write_bytes(b"bin")
    monkeypatch.setenv("ALFA_WAIFU2X_DIR", str(waifu))
    _install_pil(monkeypatch)
    calls: list[list] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[4]).write_bytes(b" hasil ")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(av.subprocess, "run", fake_run)
    out = av.upscale_image_hd(str(src), scale=8, mode="waifu2x_photo", denoise=-5)
    assert out["engine"] == "Waifu2x AI (models-upconv_7_photo)"
    assert calls[0][calls[0].index("-n") + 1] == "0"
    assert out["scale"] == 8


def test_upscale_waifu2x_no_output_falls_back_to_lanczos(
    av, monkeypatch, tmp_path
):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "foto.png")
    waifu = tmp_path / "waifu"
    waifu.mkdir()
    (waifu / "waifu2x-ncnn-vulkan").write_bytes(b"bin")
    monkeypatch.setenv("ALFA_WAIFU2X_DIR", str(waifu))
    pil = _install_pil(monkeypatch, mode="RGBA")
    monkeypatch.setattr(
        av.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="gagal"),
    )
    out = av.upscale_image_hd(str(src), scale=2, mode="auto")
    assert out["status"] == "success"
    assert out["engine"] == "Lanczos High-Fidelity + Edge Sharpener"
    # PNG + RGBA -> tanpa unsharp mask.
    assert pil.filters == []
    assert Path(out["file_path"]).exists()


def test_upscale_waifu2x_raises_then_lanczos(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "foto.png")
    waifu = tmp_path / "waifu"
    waifu.mkdir()
    (waifu / "waifu2x-ncnn-vulkan").write_bytes(b"bin")
    monkeypatch.setenv("ALFA_WAIFU2X_DIR", str(waifu))
    _install_pil(monkeypatch, mode="RGBA")

    def boom(cmd, **kwargs):
        raise OSError("vulkan tidak tersedia")  # noqa: TRY003

    monkeypatch.setattr(av.subprocess, "run", boom)
    out = av.upscale_image_hd(str(src), mode="auto")
    assert out["status"] == "success"
    assert "Lanczos" in out["engine"]


def test_upscale_pixel_art_nearest(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "gambar.bmp")
    _install_pil(monkeypatch, mode="RGB")
    out = av.upscale_image_hd(str(src), scale=2, mode="pixel_art")
    assert out["engine"] == "Nearest Neighbor (Pixel Art)"
    # .bmp tidak didukung -> ekstensi dipaksa .png
    assert out["filename"].endswith(".png")


def test_upscale_jpg_lanczos_with_unsharp(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "foto.jpg")
    pil = _install_pil(monkeypatch, mode="RGB")
    out = av.upscale_image_hd(
        str(src), scale=3, mode="lanczos_hd", output_filename="hasil"
    )
    # scale di luar (2, 4, 8) -> kembali ke 2; nama tanpa ekstensi -> ditambah.
    assert out["scale"] == 2
    assert out["filename"] == "hasil.jpg"
    assert out["engine"] == "Lanczos High-Fidelity + Edge Sharpener"
    assert len(pil.filters) == 1
    assert pil.filters[0][0] == "unsharp"


def test_upscale_output_filename_keeps_extension(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "foto.webp")
    _install_pil(monkeypatch, mode="RGB")
    out = av.upscale_image_hd(str(src), output_filename="kena-dong.webp")
    assert out["filename"] == "kena-dong.webp"


def test_upscale_default_waifu_dir_absent(av, monkeypatch, tmp_path):
    src, _ = _prep_upscale(av, monkeypatch, tmp_path, "foto.png")
    # Tanpa ALFA_WAIFU2X_DIR -> jalur default di rumah sementara (tidak ada).
    _install_pil(monkeypatch, mode="RGBA")
    out = av.upscale_image_hd(str(src), mode="auto")
    assert out["status"] == "success"
    assert out["engine"] == "Lanczos High-Fidelity + Edge Sharpener"


def test_upscale_import_error(av, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "PIL", None)
    out = av.upscale_image_hd(str(tmp_path / "foto.png"))
    assert out["status"] == "error"
    assert "Gagal memperbesar resolusi gambar" in out["message"]


# ---------------------------------------------------------------------------
# generate_promo_video_from_images
# ---------------------------------------------------------------------------


def test_promo_video_passthrough(av, monkeypatch):
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "message": "video jadi"}

    monkeypatch.setattr("alfa.video.generate_video_from_images", fake_generate)
    out = av.generate_promo_video_from_images(
        image_paths=["/tmp/a.png"],
        product_name="Kopi",
        voiceover_text="Buruan beli",
        orig_price="Rp 10.000",
        disc_price="Rp 5.000",
        voice="id-ID-Ardi",
        theme="sale",
        motion_style="pan",
        badge_text="DISKON",
        call_to_action="Beli sekarang",
        visual_prompt="kopi estetik",
        output_filename="promo.mp4",
    )
    assert out == {"status": "success", "message": "video jadi"}
    assert captured["image_paths"] == ["/tmp/a.png"]
    assert captured["product_name"] == "Kopi"
    assert captured["voice"] == "id-ID-Ardi"
    assert captured["output_filename"] == "promo.mp4"
    assert captured["visual_prompt"] == "kopi estetik"


def test_promo_video_error(av, monkeypatch):
    def boom(**kwargs):
        raise ValueError("generator rusak")  # noqa: TRY003

    monkeypatch.setattr("alfa.video.generate_video_from_images", boom)
    out = av.generate_promo_video_from_images(
        image_paths=[], product_name="X", voiceover_text="Y"
    )
    assert out == {"status": "error", "message": "generator rusak"}


# ---------------------------------------------------------------------------
# extract_audio_from_video
# ---------------------------------------------------------------------------


def test_extract_audio_missing_file(av, sandbox, tmp_path):
    out = av.extract_audio_from_video(str(tmp_path / "hilang.mp4"))
    assert out["status"] == "error"
    assert "tidak ditemukan" in out["message"]


def test_extract_audio_success_and_append_ext(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"mp4")
    calls: list[list] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"mp3" * 4000)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(av.subprocess, "run", fake_run)
    out = av.extract_audio_from_video(str(src), output_filename="lagu")
    assert out["status"] == "success"
    assert out["file_path"] == str(sandbox / "lagu.mp3")
    assert "-vn" in calls[0]
    assert "libmp3lame" in calls[0]
    assert calls[0][-1] == out["file_path"]
    assert "MB" in out["message"]


def test_extract_audio_failure_reports_stderr(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"mp4")
    monkeypatch.setattr(
        av.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="ffmpeg: codec not found"
        ),
    )
    out = av.extract_audio_from_video(str(src))
    assert out["status"] == "error"
    assert "ffmpeg: codec not found" in out["message"]


def test_extract_audio_exception(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"mp4")

    def boom(cmd, **kwargs):
        raise OSError("ffmpeg hilang")  # noqa: TRY003

    monkeypatch.setattr(av.subprocess, "run", boom)
    out = av.extract_audio_from_video(str(src))
    assert out["status"] == "error"
    assert "Extract audio error" in out["message"]


# ---------------------------------------------------------------------------
# text_to_audio_file
# ---------------------------------------------------------------------------


def _install_edge_tts(monkeypatch, *, fail=False, empty=False):
    records: list[tuple] = []

    class Communicate:
        def __init__(self, text, voice):
            records.append((text, voice))

        async def save(self, path):
            if fail:
                raise OSError("jaringan TTS mati")  # noqa: TRY003
            Path(path).write_bytes(b"" if empty else b"mp3" * 300)

    fake = types.ModuleType("edge_tts")
    fake.Communicate = Communicate
    monkeypatch.setitem(sys.modules, "edge_tts", fake)
    return records


class FakeLoop:
    def __init__(self, running):
        self._running = running
        self.ran: list = []

    def is_running(self):
        return self._running

    def run_until_complete(self, coro):
        self.ran.append(coro)
        asyncio.run(coro)


def _patch_av_asyncio(monkeypatch, av, get_event_loop):
    monkeypatch.setattr(
        av,
        "asyncio",
        SimpleNamespace(get_event_loop=get_event_loop, run=asyncio.run),
    )


def test_tts_running_loop_uses_executor(av, sandbox, monkeypatch):
    records = _install_edge_tts(monkeypatch)
    loop = FakeLoop(running=True)
    _patch_av_asyncio(monkeypatch, av, lambda: loop)

    out = av.text_to_audio_file("a" * 6000, filename="suara")
    assert out["status"] == "success"
    assert out["file_path"] == str(sandbox / "suara.mp3")
    # Teks dipotong ke 5000 karakter.
    assert len(records[0][0]) == 5000
    assert records[0][1] == "id-ID-GadisNeural"
    assert out["voice"] == "id-ID-GadisNeural"
    assert "KB" in out["message"]


def test_tts_idle_loop_run_until_complete(av, sandbox, monkeypatch):
    _install_edge_tts(monkeypatch)
    loop = FakeLoop(running=False)
    _patch_av_asyncio(monkeypatch, av, lambda: loop)
    out = av.text_to_audio_file(
        "halo", filename="bicara.mp3", voice="id-ID-Ardi"
    )
    assert out["status"] == "success"
    assert loop.ran, "run_until_complete harus dipanggil"
    assert out["file_path"] == str(sandbox / "bicara.mp3")


def test_tts_no_event_loop_falls_back_to_asyncio_run(
    av, sandbox, monkeypatch
):
    records = _install_edge_tts(monkeypatch)

    def raising_loop():
        raise RuntimeError("tidak ada event loop")  # noqa: TRY003

    _patch_av_asyncio(monkeypatch, av, raising_loop)
    out = av.text_to_audio_file("halo")
    assert out["status"] == "success"
    assert out["file_path"] == str(sandbox / "audio_speech.mp3")
    assert records


def test_tts_synthesis_error(av, sandbox, monkeypatch):
    _install_edge_tts(monkeypatch, fail=True)
    loop = FakeLoop(running=False)
    _patch_av_asyncio(monkeypatch, av, lambda: loop)
    out = av.text_to_audio_file("halo")
    assert out["status"] == "error"
    assert "Audio synthesis error" in out["message"]


def test_tts_empty_output(av, sandbox, monkeypatch):
    _install_edge_tts(monkeypatch, empty=True)
    loop = FakeLoop(running=False)
    _patch_av_asyncio(monkeypatch, av, lambda: loop)
    out = av.text_to_audio_file("halo")
    assert out["status"] == "error"
    assert out["message"] == "Gagal membuat file audio speech."


# ---------------------------------------------------------------------------
# convert_media_format
# ---------------------------------------------------------------------------


def test_convert_missing_source(av, sandbox, tmp_path):
    out = av.convert_media_format(str(tmp_path / "hilang.wav"))
    assert out["status"] == "error"
    assert "tidak ditemukan" in out["message"]


def test_convert_success_with_extra_params(
    av, sandbox, monkeypatch, tmp_path
):
    src = tmp_path / "lagu.wav"
    src.write_bytes(b"wav")
    calls: list[list] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x" * 4096)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(av.subprocess, "run", fake_run)
    out = av.convert_media_format(str(src), output_format=".MP3", extra_params="-vn -ac 2")
    assert out["status"] == "success"
    assert out["file_path"] == str(sandbox / "lagu_converted.mp3")
    assert "-vn" in calls[0] and "-ac" in calls[0]
    assert calls[0][-1] == out["file_path"]


def test_convert_failure_and_exception(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "lagu.wav"
    src.write_bytes(b"wav")
    monkeypatch.setattr(
        av.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="format aneh"),
    )
    out = av.convert_media_format(str(src))
    assert out["status"] == "error"
    assert "format aneh" in out["message"]

    def boom(cmd, **kwargs):
        raise OSError("ffmpeg hilang")  # noqa: TRY003

    monkeypatch.setattr(av.subprocess, "run", boom)
    out = av.convert_media_format(str(src))
    assert out["status"] == "error"
    assert "Media conversion error" in out["message"]


# ---------------------------------------------------------------------------
# edit_image
# ---------------------------------------------------------------------------


def test_edit_missing_file(av, sandbox, tmp_path):
    out = av.edit_image(str(tmp_path / "hilang.png"), "info")
    assert out["status"] == "error"
    assert "tidak ditemukan" in out["message"]


def test_edit_info(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p" * 4096)
    _install_pil(monkeypatch, fmt="PNG", mode="RGBA")
    out = av.edit_image(str(src), "  INFO  ")
    assert out["status"] == "success"
    assert out["format"] == "PNG"
    assert out["size"] == "100x50"
    assert out["mode"] == "RGBA"
    assert out["file_size_kb"] == 4.0


def test_edit_resize_and_rotate(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p" * 4096)
    _install_pil(monkeypatch, fmt="PNG", mode="RGB")

    out = av.edit_image(str(src), "resize", "100x50")
    assert out["status"] == "success"
    assert out["file_path"].endswith("foto_edited.png")

    out = av.edit_image(str(src), "rotate", "90")
    assert out["status"] == "success"
    assert "rotate" in out["message"]


def test_edit_bad_resize_params(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    _install_pil(monkeypatch)
    out = av.edit_image(str(src), "resize", "besar")
    assert out["status"] == "error"
    assert "Gagal mengedit gambar" in out["message"]


def test_edit_crop_variants(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    _install_pil(monkeypatch)

    out = av.edit_image(str(src), "crop", "10, 20, 30, 40")
    assert out["status"] == "success"

    out = av.edit_image(str(src), "crop", "1,2,3")
    assert out["status"] == "error"
    assert "Format crop harus x,y,w,h" in out["message"]


@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("grayscale", ""),
        ("flip_horizontal", ""),
        ("flip_vertical", ""),
        ("thumbnail", "80x80"),
        ("blur", ""),
        ("sharpen", ""),
        ("convert", "png"),
    ],
)
def test_edit_simple_actions(
    av, sandbox, monkeypatch, tmp_path, action, params
):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    _install_pil(monkeypatch, fmt="PNG", mode="RGB")
    out = av.edit_image(str(src), action, params)
    assert out["status"] == "success", out
    assert f"di-{action}" in out["message"]


def test_edit_convert_jpeg(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    _install_pil(monkeypatch, fmt="PNG", mode="RGBA")
    out = av.edit_image(str(src), "convert", "jpeg")
    assert out["status"] == "success"
    assert out["file_path"].endswith("foto_edited.jpg")
    assert "convert" in out["message"]


def test_edit_rgba_jpeg_gets_flattened(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    pil = _install_pil(monkeypatch, fmt="JPEG", mode="RGBA")
    out = av.edit_image(str(src), "rotate", "180")
    assert out["status"] == "success"
    # fmt JPEG dari img.format -> ekstensi jpg; RGBA dipaksa ke RGB.
    assert out["file_path"].endswith("foto_edited.jpg")
    assert pil.opened[0] == str(src)


def test_edit_watermark_font_fallback(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    pil = _install_pil(monkeypatch, fmt="PNG", mode="RGB", truetype_raises=True)
    out = av.edit_image(str(src), "watermark", "Merek Kita")
    assert out["status"] == "success"
    assert pil.draws, "watermark harus menggambar teks"
    assert pil.draws[0][1] == "Merek Kita"
    assert pil.draws[0][3] == "font-default"


def test_edit_watermark_default_text(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    pil = _install_pil(monkeypatch, fmt="PNG", mode="RGB")
    out = av.edit_image(str(src), "watermark")
    assert out["status"] == "success"
    assert pil.draws[0][1] == "AI Agent Watermark"
    assert pil.draws[0][3] == "font-dejavu"


def test_edit_unknown_action(av, sandbox, monkeypatch, tmp_path):
    src = tmp_path / "foto.png"
    src.write_bytes(b"p")
    _install_pil(monkeypatch)
    out = av.edit_image(str(src), "mekanik")
    assert out["status"] == "error"
    assert "tidak dikenal" in out["message"]


def test_edit_import_error(av, sandbox, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    out = av.edit_image(str(tmp_path / "foto.png"), "info")
    assert out["status"] == "error"
    assert "Gagal mengedit gambar" in out["message"]


# ---------------------------------------------------------------------------
# Timestamp subtitle
# ---------------------------------------------------------------------------


def test_format_srt_timestamp(av):
    assert av._format_srt_timestamp(0.0) == "00:00:00,000"
    assert av._format_srt_timestamp(3661.5) == "01:01:01,500"
    assert av._format_srt_timestamp(7325.75) == "02:02:05,750"


def test_format_vtt_timestamp(av):
    assert av._format_vtt_timestamp(0.0) == "00:00:00.000"
    assert av._format_vtt_timestamp(3661.5) == "01:01:01.500"
    assert av._format_vtt_timestamp(7325.75) == "02:02:05.750"


# ---------------------------------------------------------------------------
# media_generate_subtitles_srt
# ---------------------------------------------------------------------------


def _install_whisper(monkeypatch, *, fail=False):
    ctor_calls: list[dict] = []

    class WhisperModel:
        def __init__(self, model_size, device=None, compute_type=None):
            if fail:
                raise RuntimeError("model corup")  # noqa: TRY003
            ctor_calls.append(
                {"size": model_size, "device": device, "compute_type": compute_type}
            )

        def transcribe(self, fpath, language=None, beam_size=None):
            segments = [
                SimpleNamespace(text="  Halo dunia  ", start=0.0, end=1.5),
                SimpleNamespace(text="   ", start=1.0, end=2.0),
                SimpleNamespace(text="Kalimat kedua", start=2.25, end=3.75),
            ]
            info = SimpleNamespace(language="id")
            return iter(segments), info

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    return ctor_calls


def test_subtitles_missing_media(tmp_path):
    from alfa.tools.media import av as mod

    out = mod.media_generate_subtitles_srt(str(tmp_path / "hilang.mp4"))
    assert out["status"] == "error"
    assert "tidak ditemukan" in out["message"]


def test_subtitles_srt_success(monkeypatch, tmp_path):
    from alfa.tools.media import av as mod

    media = tmp_path / "rapat.mp4"
    media.write_bytes(b"mp4")
    ctor_calls = _install_whisper(monkeypatch)
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "small")

    out = mod.media_generate_subtitles_srt(str(media), language="id")

    assert out["status"] == "success"
    assert ctor_calls[0]["size"] == "small"
    assert out["total_segments"] == 3
    assert out["subtitle_file"] == str(tmp_path / "rapat.srt")
    content = Path(out["subtitle_file"]).read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\nHalo dunia" in content
    # Segmen kosong tidak menghasilkan blok, tapi tetap terhitung.
    assert "3\n00:00:02,250 --> 00:00:03,750\nKalimat kedua" in content
    assert out["preview"].startswith("1\n")
    assert out["detected_language"] == "id"
    assert out["format"] == "srt"
    assert "(3 segmen)" in out["message"]


def test_subtitles_vtt_and_bad_format(monkeypatch, tmp_path):
    from alfa.tools.media import av as mod

    media = tmp_path / "video.mkv"
    media.write_bytes(b"mkv")
    _install_whisper(monkeypatch)

    out = mod.media_generate_subtitles_srt(str(media), output_format="vtt")
    assert out["format"] == "vtt"
    content = Path(out["subtitle_file"]).read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500" in content

    out2 = mod.media_generate_subtitles_srt(str(media), output_format="ass")
    assert out2["format"] == "srt"


def test_subtitles_whisper_failure(monkeypatch, tmp_path):
    from alfa.tools.media import av as mod

    media = tmp_path / "audio.wav"
    media.write_bytes(b"wav")
    _install_whisper(monkeypatch, fail=True)
    out = mod.media_generate_subtitles_srt(str(media))
    assert out["status"] == "error"
    assert "Subtitle generator error" in out["message"]
    assert "model corup" in out["message"]
