"""Phase 6 coverage: desktop screenshot, webcam, dan screen recorder.

Hermetic: tidak ada display, kamera, atau ffmpeg nyata. Semua subprocess dan
modul opsional (cv2/PIL) di-mock, output hanya di ``tmp_path``.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def cap(monkeypatch, tmp_path):
    from alfa.tools.desktop import capture

    monkeypatch.setattr(capture, "SANDBOX_DIR", str(tmp_path))
    return capture


def _fake_pil_grab(monkeypatch, succeed: bool = True):
    fake_grab = types.ModuleType("PIL.ImageGrab")

    class FakeImage:
        def save(self, path):
            if not succeed:
                raise OSError("grab gagal")  # noqa: TRY003
            Path(path).write_bytes(b"x" * 1500)

    fake_grab.grab = lambda: FakeImage()
    fake_pil = types.ModuleType("PIL")
    fake_pil.ImageGrab = fake_grab
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", fake_grab)


def _screenshot_runner(cap, tmp_path, success_at: str):
    target = str(tmp_path / "desktop_screen.png")

    def fake_run(cmd, **kwargs):
        text = cmd if isinstance(cmd, str) else " ".join(str(part) for part in cmd)
        matched = (
            (success_at == "portal" and "/usr/bin/python3" in text)
            or (success_at == "grim" and text.startswith("grim"))
            or (success_at == "import" and text.startswith("import -window root"))
            or (success_at == "scrot" and text.startswith("scrot"))
        )
        if matched:
            Path(target).write_bytes(b"x" * 1500)
            return SimpleNamespace(returncode=0, stderr=b"")
        return SimpleNamespace(returncode=1, stderr=b"gagal")

    return fake_run


# ---------------------------------------------------------------------------
# capture_desktop_screenshot
# ---------------------------------------------------------------------------


def test_screenshot_portal_success_and_old_file_removed(cap, monkeypatch, tmp_path):
    old = tmp_path / "desktop_screen.png"
    old.write_bytes(b"old")
    monkeypatch.setattr(
        cap.subprocess, "run", _screenshot_runner(cap, tmp_path, "portal")
    )
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "success"
    assert "Wayland Portal" in out["message"]
    assert Path(out["file_path"]).read_bytes() != b"old"


@pytest.mark.parametrize(
    ("success_at", "message"),
    [
        ("grim", "via grim"),
        ("import", "via ImageMagick"),
        ("scrot", "via scrot"),
    ],
)
def test_screenshot_linux_fallback_chain(cap, monkeypatch, tmp_path, success_at, message):
    monkeypatch.setattr(
        cap.subprocess, "run", _screenshot_runner(cap, tmp_path, success_at)
    )
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "success"
    assert message in out["message"]


def test_screenshot_imagegrab_fallback(cap, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cap.subprocess, "run", _screenshot_runner(cap, tmp_path, "tidak-ada")
    )
    _fake_pil_grab(monkeypatch)
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "success"
    assert "ImageGrab" in out["message"]


def test_screenshot_all_methods_fail(cap, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cap.subprocess, "run", _screenshot_runner(cap, tmp_path, "tidak-ada")
    )
    _fake_pil_grab(monkeypatch, succeed=False)
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "error"
    assert "Gagal mengambil screenshot" in out["message"]


def test_screenshot_outer_exception(cap, monkeypatch):
    def boom(*a, **k):
        raise OSError("sandbox tidak bisa dibuat")  # noqa: TRY003

    monkeypatch.setattr(cap.os, "makedirs", boom)
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "error"
    assert "sandbox" in out["message"]


def test_screenshot_windows_without_windll(cap, monkeypatch, tmp_path):
    class FakeOS:
        name = "nt"

        def __getattr__(self, item):
            import os as real_os

            return getattr(real_os, item)

    monkeypatch.setattr(cap, "os", FakeOS())
    monkeypatch.setattr(
        cap.subprocess, "run", _screenshot_runner(cap, tmp_path, "tidak-ada")
    )
    _fake_pil_grab(monkeypatch, succeed=False)
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "error"


def _fake_windows_env(monkeypatch, cap, tmp_path, width=100, height=50, save_ok=True):
    """Patch ctypes + PIL Image untuk meniru jalan Win32 GDI di Linux."""

    class FakeOS:
        name = "nt"

        def __getattr__(self, item):
            import os as real_os

            return getattr(real_os, item)

    fake_ctypes = types.ModuleType("ctypes")

    class FakeCChar:
        def __mul__(self, count):  # noqa: N802 - meniru ctypes.c_char * n
            return lambda: bytearray(count)

    fake_ctypes.c_char = FakeCChar()
    fake_ctypes.byref = lambda obj: obj
    fake_ctypes.c_char_p = lambda data: data
    fake_ctypes.windll = SimpleNamespace(
        user32=SimpleNamespace(
            SetProcessDPIAware=lambda: None,
            GetSystemMetrics=lambda idx: {
                76: -10,
                77: -5,
                78: width,
                79: height,
                0: width,
                1: height,
            }[idx],
            GetDesktopWindow=lambda: 1,
            GetWindowDC=lambda handle: 2,
            ReleaseDC=lambda handle, dc: None,
        ),
        gdi32=SimpleNamespace(
            CreateCompatibleDC=lambda dc: 3,
            CreateCompatibleBitmap=lambda dc, w, h: 4,
            SelectObject=lambda dc, bmp: None,
            BitBlt=lambda *a: None,
            GetDIBits=lambda *a: None,
            DeleteObject=lambda obj: None,
            DeleteDC=lambda dc: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    class FakeImage:
        def convert(self, mode):
            return self

        def save(self, path, quality=None):
            if not save_ok:
                raise OSError("GDI save gagal")  # noqa: TRY003
            Path(path).write_bytes(b"x" * 1500)

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = SimpleNamespace(
        frombuffer=lambda *a, **k: FakeImage(),
        fromstring=lambda *a, **k: FakeImage(),
    )
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)

    monkeypatch.setattr(cap, "os", FakeOS())
    return fake_pil


@pytest.mark.parametrize(("width", "height"), [(100, 50), (0, 0)])
def test_screenshot_windows_gdi_success(
    cap, monkeypatch, tmp_path, width, height
):
    _fake_windows_env(monkeypatch, cap, tmp_path, width=width, height=height)
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "success"
    assert "resolusi penuh" in out["message"]


def test_screenshot_all_fallbacks_raise(cap, monkeypatch, tmp_path):
    _fake_windows_env(
        monkeypatch, cap, tmp_path, save_ok=False
    )

    def boom(cmd, **kwargs):
        raise OSError("tool screenshot tidak ada")  # noqa: TRY003

    monkeypatch.setattr(cap.subprocess, "run", boom)
    out = cap.capture_desktop_screenshot()
    assert out["status"] == "error"
    assert "Gagal mengambil screenshot" in out["message"]


# ---------------------------------------------------------------------------
# capture_webcam_frame
# ---------------------------------------------------------------------------


def _fake_cv2(monkeypatch, opened=True, read_ok=True):
    fake = types.ModuleType("cv2")
    released: list[bool] = []

    class FakeCapture:
        def isOpened(self):  # noqa: N802 - mengikuti API cv2
            return opened

        def read(self):
            return (True, "frame") if read_ok else (False, None)

        def release(self):
            released.append(True)

    fake.VideoCapture = lambda index: FakeCapture()
    fake.imwrite = lambda path, frame: Path(path).write_bytes(b"jpg")
    monkeypatch.setitem(sys.modules, "cv2", fake)
    return released


def test_webcam_success(cap, monkeypatch, tmp_path):
    released = _fake_cv2(monkeypatch)
    out = cap.capture_webcam_frame()
    assert out["status"] == "success"
    assert Path(out["file_path"]).exists()
    assert released == [True]


def test_webcam_not_opened(cap, monkeypatch):
    _fake_cv2(monkeypatch, opened=False)
    out = cap.capture_webcam_frame()
    assert out["status"] == "error"
    assert "tidak dapat diakses" in out["message"]


def test_webcam_read_failure(cap, monkeypatch):
    _fake_cv2(monkeypatch, read_ok=False)
    out = cap.capture_webcam_frame()
    assert out["status"] == "error"
    assert "Gagal membaca frame" in out["message"]


def test_webcam_import_and_runtime_error(cap, monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    out = cap.capture_webcam_frame()
    assert out["status"] == "error"

    fake = types.ModuleType("cv2")

    def boom(index):
        raise OSError("kamera rusak")  # noqa: TRY003

    fake.VideoCapture = boom
    monkeypatch.setitem(sys.modules, "cv2", fake)
    out = cap.capture_webcam_frame()
    assert out["status"] == "error"
    assert "kamera rusak" in out["message"]


def test_webcam_existing_file_cleanup_ignored(cap, monkeypatch, tmp_path):
    (tmp_path / "webcam_frame.jpg").write_bytes(b"lama")

    def boom(path):
        raise OSError("read-only")  # noqa: TRY003

    _fake_cv2(monkeypatch)
    monkeypatch.setattr(cap.os, "remove", boom)
    out = cap.capture_webcam_frame()
    assert out["status"] == "success"


# ---------------------------------------------------------------------------
# record_desktop_screen
# ---------------------------------------------------------------------------


def _recording_runner(cap, tmp_path, wf_ok=True, ffmpeg_ok=True):
    target = tmp_path / "screen_recording.mp4"

    def fake_run(cmd, **kwargs):
        if "wf-recorder" in cmd:
            if wf_ok:
                target.write_bytes(b"video")
                return SimpleNamespace(returncode=0, stderr="")
            return SimpleNamespace(returncode=1, stderr="wf gagal")
        if ffmpeg_ok:
            target.write_bytes(b"video")
        return SimpleNamespace(returncode=0 if ffmpeg_ok else 1, stderr="ffmpeg gagal")

    return fake_run


def test_record_screen_wf_recorder_success(cap, monkeypatch, tmp_path):
    monkeypatch.setattr(cap.subprocess, "run", _recording_runner(cap, tmp_path))
    out = cap.record_desktop_screen(0)
    assert out["status"] == "success"
    assert "Rekaman layar 1s" in out["message"]


def test_record_screen_ffmpeg_fallback(cap, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cap.subprocess, "run", _recording_runner(cap, tmp_path, wf_ok=False)
    )
    out = cap.record_desktop_screen(999)
    assert out["status"] == "success"
    assert "Rekaman layar 60s" in out["message"]
    assert "via ffmpeg" in out["message"]


def test_record_screen_both_fail(cap, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cap.subprocess,
        "run",
        _recording_runner(cap, tmp_path, wf_ok=False, ffmpeg_ok=False),
    )
    out = cap.record_desktop_screen(5)
    assert out["status"] == "error"
    assert "Gagal merekam layar" in out["message"]


def test_record_screen_timeout_with_and_without_file(cap, monkeypatch, tmp_path):
    target = tmp_path / "screen_recording.mp4"

    def timeout_with_file(cmd, **kwargs):
        target.write_bytes(b"video")
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(cap.subprocess, "run", timeout_with_file)
    out = cap.record_desktop_screen(3)
    assert out["status"] == "success"
    assert "timeout graceful" in out["message"]

    target.unlink()

    def timeout_without_file(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(cap.subprocess, "run", timeout_without_file)
    out = cap.record_desktop_screen(3)
    assert out["status"] == "error"
    assert "Timeout saat merekam" in out["message"]


def test_record_screen_generic_exception(cap, monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("ffmpeg hilang")  # noqa: TRY003

    monkeypatch.setattr(cap.subprocess, "run", boom)
    out = cap.record_desktop_screen(2)
    assert out["status"] == "error"
    assert "ffmpeg hilang" in out["message"]


def test_record_screen_windows_branch(cap, monkeypatch, tmp_path):
    class FakeOS:
        name = "nt"

        def __getattr__(self, item):
            import os as real_os

            return getattr(real_os, item)

    target = tmp_path / "screen_recording.mp4"

    def success(cmd, **kwargs):
        target.write_bytes(b"video")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(cap, "os", FakeOS())
    monkeypatch.setattr(cap.subprocess, "run", success)
    out = cap.record_desktop_screen(4)
    assert out["status"] == "success"

    target.unlink()

    def failure(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stderr="gdigrab error")

    monkeypatch.setattr(cap.subprocess, "run", failure)
    out = cap.record_desktop_screen(4)
    assert out["status"] == "error"
    assert "gdigrab" in out["message"]
