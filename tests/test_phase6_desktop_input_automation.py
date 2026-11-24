"""Phase 6 coverage: desktop input automation (opener browser, klik, ketik, launch, vision loop).

Hermetic: subprocess/Popen, shutil.which, pyautogui, google.genai, dan screenshot
di-mock ke ``tmp_path``; tidak ada interaksi GUI atau jaringan nyata.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture
def ia():
    from alfa.tools.desktop import input_automation as mod

    return mod


# ---------------------------------------------------------------------------
# _normalize_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/path",
        "example.com",
        "example.com/path?x=1#frag",
        "HTTP://Example.com",
        "localhost:8080/app",
        "localhost",
        "192.168.1.1:3000",
        "ftp://files.example.com/pub",
    ],
)
def test_normalize_url_valid(ia, url):
    out = ia._normalize_url(url)
    assert out.startswith(("http://", "https://", "ftp://"))


@pytest.mark.parametrize(
    "url",
    [
        "",
        None,
        "   ",
        "bad host.com",
        "nodot",
        "foo!bar",
        "//example.com",
        "?query=1",
        "http://",
        "with space.com/x",
    ],
)
def test_normalize_url_invalid(ia, url):
    assert ia._normalize_url(url) == ""


def test_normalize_url_keeps_scheme_and_host_casing(ia):
    # Scheme diturunkan ke huruf kecil, host/port dipertahankan apa adanya.
    assert ia._normalize_url("HTTP://Example.com:8080") == "http://Example.com:8080"


# ---------------------------------------------------------------------------
# _browser_openers
# ---------------------------------------------------------------------------


def test_browser_openers_order_env_and_extras(ia, monkeypatch):
    available = {"xdg-open", "firefox", "mybrowser"}
    monkeypatch.setattr(
        ia.shutil, "which", lambda name: name if name in available else None
    )
    monkeypatch.setenv("BROWSER", "mybrowser")
    assert ia._browser_openers() == ["xdg-open", "mybrowser", "firefox"]

    monkeypatch.setenv("BROWSER", "belum-terpasang")
    assert ia._browser_openers() == ["xdg-open", "firefox"]

    monkeypatch.delenv("BROWSER", raising=False)
    assert ia._browser_openers() == ["xdg-open", "firefox"]

    monkeypatch.setattr(ia.shutil, "which", lambda name: None)
    assert ia._browser_openers() == []


# ---------------------------------------------------------------------------
# open_url_in_default_browser
# ---------------------------------------------------------------------------


class BrowserProc:
    """Fake Popen untuk opener browser."""

    def __init__(self, rc=0, err=b"", hang=False):
        self.returncode = rc
        self._err = err
        self._hang = hang
        self.pid = 4242

    def communicate(self, timeout=None):  # noqa: ARG002
        if self._hang:
            raise subprocess.TimeoutExpired(cmd="open", timeout=timeout or 0)
        return b"", self._err


def _patch_openers(monkeypatch, ia, names):
    monkeypatch.setattr(ia, "_browser_openers", lambda: list(names))


def test_open_url_invalid(ia):
    assert ia.open_url_in_default_browser("  ") == (
        False,
        "URL kosong/tidak valid.",
    )


def test_open_url_first_opener_success(ia, monkeypatch):
    _patch_openers(monkeypatch, ia, ["xdg-open"])
    calls: list[list] = []

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return BrowserProc(rc=0)

    monkeypatch.setattr(ia.subprocess, "Popen", fake_popen)
    ok, how = ia.open_url_in_default_browser("example.com")
    assert ok is True
    assert calls[0] == ["xdg-open", "https://example.com"]
    assert how == "xdg-open https://example.com"


def test_open_url_gio_uses_open_subcommand(ia, monkeypatch):
    _patch_openers(monkeypatch, ia, ["gio"])
    calls: list[list] = []
    monkeypatch.setattr(
        ia.subprocess,
        "Popen",
        lambda cmd, **kw: calls.append(cmd) or BrowserProc(rc=0),
    )
    ok, how = ia.open_url_in_default_browser("https://a.test/x")
    assert ok is True
    assert calls[0] == ["gio", "open", "https://a.test/x"]
    assert "gio open" in how


def test_open_url_timeout_means_browser_running(ia, monkeypatch):
    _patch_openers(monkeypatch, ia, ["firefox"])
    monkeypatch.setattr(
        ia.subprocess, "Popen", lambda cmd, **kw: BrowserProc(hang=True)
    )
    ok, how = ia.open_url_in_default_browser("example.com")
    assert ok is True
    assert "(browser berjalan)" in how


def test_open_url_all_openers_fail(ia, monkeypatch):
    _patch_openers(monkeypatch, ia, ["xdg-open", "gio", "firefox"])
    attempts = {"n": 0}

    def fake_popen(cmd, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise FileNotFoundError("xdg-open hilang")  # noqa: TRY003
        if attempts["n"] == 2:
            raise OSError("gio rusak")  # noqa: TRY003
        return BrowserProc(rc=1, err=b"permission denied")

    monkeypatch.setattr(ia.subprocess, "Popen", fake_popen)
    ok, how = ia.open_url_in_default_browser("example.com")
    assert ok is False
    assert "Tidak ada opener browser yang berhasil" in how
    assert "xdg-open https://example.com" in how
    assert "gio open https://example.com" in how


def test_open_url_no_openers(ia, monkeypatch):
    _patch_openers(monkeypatch, ia, [])
    ok, how = ia.open_url_in_default_browser("example.com")
    assert ok is False
    assert how.endswith("Dicoba: -")


# ---------------------------------------------------------------------------
# open_url_in_system_browser
# ---------------------------------------------------------------------------


def test_system_browser_invalid_url(ia):
    out = ia.open_url_in_system_browser("bukan url valid")
    assert out["status"] == "error"
    assert "tidak valid" in out["message"]


def test_system_browser_success(ia, monkeypatch):
    monkeypatch.setattr(
        ia, "open_url_in_default_browser", lambda url: (True, "xdg-open " + url)
    )
    out = ia.open_url_in_system_browser("github.com")
    assert out["status"] == "success"
    assert out["url"] == "https://github.com"
    assert out["mechanism"].startswith("xdg-open")


def test_system_browser_failure(ia, monkeypatch):
    monkeypatch.setattr(
        ia,
        "open_url_in_default_browser",
        lambda url: (False, "Tidak ada opener browser yang berhasil."),
    )
    out = ia.open_url_in_system_browser("example.com")
    assert out["status"] == "error"
    assert "Gagal membuka" in out["message"]
    assert out["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# desktop_click_coordinate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("button", "code"), [("left", "0xC0"), ("right", "0xC1"), ("middle", "0xC2")]
)
def test_click_ydotool_success(ia, monkeypatch, button, code):
    commands: list = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ia.subprocess, "run", fake_run)
    out = ia.desktop_click_coordinate(10, 20, button=button, clicks=2)
    assert out["status"] == "success"
    assert f"ydotool click {code}" in commands[0]
    assert "(10, 20)" in out["message"]


@pytest.mark.parametrize(("button", "btn"), [("left", "1"), ("right", "3")])
def test_click_xdotool_fallback(ia, monkeypatch, button, btn):
    commands: list = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        rc = 1 if "ydotool" in cmd else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(ia.subprocess, "run", fake_run)
    out = ia.desktop_click_coordinate(5, 6, button=button)
    assert out["status"] == "success"
    assert "xdotool" in out["message"]
    assert f"click {btn}" in commands[1]


def test_click_pyautogui_fallback(ia, monkeypatch):
    monkeypatch.setattr(
        ia.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    fake = types.ModuleType("pyautogui")
    clicks: list[dict] = []
    fake.click = lambda **kwargs: clicks.append(kwargs)
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    out = ia.desktop_click_coordinate(7, 8, button="right", clicks=2)
    assert out["status"] == "success"
    assert "PyAutoGUI" in out["message"]
    assert clicks == [{"x": 7, "y": 8, "button": "right", "clicks": 2}]


def test_click_error_path(ia, monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("ydotool tidak ada")  # noqa: TRY003

    monkeypatch.setattr(ia.subprocess, "run", boom)
    monkeypatch.setitem(sys.modules, "pyautogui", None)
    out = ia.desktop_click_coordinate(1, 1)
    assert out["status"] == "error"
    assert out["message"].startswith("Gagal melakukan klik mouse")


# ---------------------------------------------------------------------------
# desktop_type_keys
# ---------------------------------------------------------------------------


def test_type_hotkey_via_pyautogui(ia, monkeypatch):
    fake = types.ModuleType("pyautogui")
    pressed: list[tuple] = []
    fake.hotkey = lambda *keys: pressed.append(keys)
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    out = ia.desktop_type_keys(hotkey=" ctrl + c ")
    assert out["status"] == "success"
    assert pressed == [("ctrl", "c")]
    assert "ctrl + c" in out["message"]


def test_type_hotkey_import_error(ia, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyautogui", None)
    out = ia.desktop_type_keys(hotkey="alt+tab")
    assert out["status"] == "error"
    assert "Gagal mengetik tombol" in out["message"]


def test_type_text_ydotool_success(ia, monkeypatch):
    commands: list = []
    monkeypatch.setattr(
        ia.subprocess,
        "run",
        lambda cmd, **kw: commands.append(cmd)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    out = ia.desktop_type_keys(text="halo dunia")
    assert out["status"] == "success"
    assert commands[0] == ["ydotool", "type", "halo dunia"]
    assert "halo dunia" in out["message"]


def test_type_text_pyautogui_fallback(ia, monkeypatch):
    monkeypatch.setattr(
        ia.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    fake = types.ModuleType("pyautogui")
    typed: list[str] = []
    fake.write = typed.append
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    out = ia.desktop_type_keys(text="tes")
    assert out["status"] == "success"
    assert "PyAutoGUI" in out["message"]
    assert typed == ["tes"]


def test_type_requires_text_or_hotkey(ia):
    out = ia.desktop_type_keys()
    assert out["status"] == "error"
    assert "Harus menyertakan text atau hotkey" in out["message"]


# ---------------------------------------------------------------------------
# desktop_launch_app
# ---------------------------------------------------------------------------


class AppProc:
    """Fake Popen untuk peluncuran aplikasi."""

    def __init__(self, rc=None, err=b""):
        self.pid = 4242
        self._rc = rc
        self.stderr = io.BytesIO(err)

    def poll(self):
        return self._rc


def test_launch_empty_command(ia):
    out = ia.desktop_launch_app("   ")
    assert out["status"] == "error"
    assert "kosong" in out["message"]


@pytest.mark.parametrize("arg", ["https://youtube.com", "www.site.test", "example.com"])
def test_launch_url_delegates_to_browser(ia, monkeypatch, arg):
    seen: list[str] = []

    def fake_open(url):
        seen.append(url)
        return {"status": "success", "message": "dibuka", "url": url}

    monkeypatch.setattr(ia, "open_url_in_system_browser", fake_open)
    out = ia.desktop_launch_app(arg)
    assert out["status"] == "success"
    assert seen == [arg]


def test_launch_missing_binary(ia, monkeypatch):
    monkeypatch.setattr(ia.shutil, "which", lambda name: None)
    out = ia.desktop_launch_app("aplikasitidakada")
    assert out["status"] == "error"
    assert "tidak ditemukan di PATH" in out["message"]


def test_launch_relative_script_exists(ia, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "skrip-lokal.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ia.shutil, "which", lambda name: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=None))
    monkeypatch.setattr(
        ia.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(stdout="999\n", stderr=""),
    )
    out = ia.desktop_launch_app("./skrip-lokal.sh")
    assert out["status"] == "success"
    assert out["pid"] == "999"


def test_launch_running_process_with_pids(ia, monkeypatch):
    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=None))
    monkeypatch.setattr(
        ia.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(stdout="111 222\n", stderr=""),
    )
    out = ia.desktop_launch_app("spotify")
    assert out["status"] == "success"
    assert out["pid"] == "111"
    assert out["pids"] == ["111", "222"]
    assert "berjalan di background" in out["message"]


def test_launch_exited_zero_without_pids(ia, monkeypatch):
    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=0))
    monkeypatch.setattr(
        ia.subprocess,
        "run",
        lambda cmd, **kw: SimpleNamespace(stdout="", stderr=""),
    )
    out = ia.desktop_launch_app("aplikasi-keluar-cepat")
    assert out["status"] == "success"
    assert out["confidence"] == "low"


def test_launch_exited_nonzero_reports_stderr(ia, monkeypatch):
    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(
        ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=2, err=b"bin rusak")
    )
    out = ia.desktop_launch_app("aplikasirusak")
    assert out["status"] == "error"
    assert "exit code 2" in out["message"]
    assert "bin rusak" in out["message"]


def test_launch_nonzero_without_stderr_detail(ia, monkeypatch):
    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=3))
    out = ia.desktop_launch_app("senyap")
    assert out["status"] == "error"
    assert out["message"].endswith(".")


def test_launch_shell_meta_skips_path_check(ia, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=None))

    def fake_run(cmd, **kwargs):
        raise OSError("pgrep tidak ada")  # noqa: TRY003

    monkeypatch.setattr(ia.subprocess, "run", fake_run)
    out = ia.desktop_launch_app("echo halo | tee /tmp/x")
    assert out["status"] == "success"
    assert out["pid"] == 4242
    assert out["pids"] == []


def test_launch_probe_error_returns_empty_pids(ia, monkeypatch):
    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: AppProc(rc=0))

    def fake_run(cmd, **kwargs):
        raise ValueError("timeout")  # noqa: TRY003

    monkeypatch.setattr(ia.subprocess, "run", fake_run)
    out = ia.desktop_launch_app("keluar-tanpa-pid")
    assert out["status"] == "success"
    assert out["confidence"] == "low"


def test_launch_unexpected_exception(ia, monkeypatch):
    def boom(cmd, **kwargs):
        raise RuntimeError("disk penuh")  # noqa: TRY003

    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(ia.subprocess, "Popen", boom)
    out = ia.desktop_launch_app("code")
    assert out["status"] == "error"
    assert out["message"].startswith("Gagal meluncurkan aplikasi")


def test_launch_stderr_read_failure_ignored(ia, monkeypatch):
    class BadStderrProc(AppProc):
        def __init__(self, rc=None):
            self.pid = 4242
            self._rc = rc

        @property
        def stderr(self):
            raise OSError("pipe tertutup")  # noqa: TRY003

    monkeypatch.setattr(ia.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ia.subprocess, "Popen", lambda cmd, **kw: BadStderrProc(rc=2))
    out = ia.desktop_launch_app("gagalcilik")
    assert out["status"] == "error"
    assert "exit code 2" in out["message"]
    assert out["message"].endswith(".")


# ---------------------------------------------------------------------------
# vision_click_target
# ---------------------------------------------------------------------------


def _install_genai(monkeypatch, *, texts=None, handler=None, client_error=None):
    """Pasang modul google.genai palsu; kembalikan daftar panggilan generate."""
    calls: list[dict] = []

    class _Models:
        def generate_content(self, model=None, contents=None):
            idx = len(calls)
            calls.append({"model": model, "contents": contents})
            if handler is not None:
                text = handler(idx, contents)
            else:
                seq = list(texts or [])
                text = seq[min(idx, len(seq) - 1)]
            return SimpleNamespace(text=text)

    class _Client:
        def __init__(self, api_key=None):
            if client_error is not None:
                raise client_error
            self.api_key = api_key
            self.models = _Models()

    fake_types = types.ModuleType("google.genai.types")
    fake_types.Part = SimpleNamespace(
        from_bytes=lambda data, mime_type: SimpleNamespace(
            data=data, mime_type=mime_type
        )
    )
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = _Client
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    return calls


@pytest.fixture
def vision_env(ia, monkeypatch, tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setattr(ia, "SANDBOX_DIR", str(sandbox))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-model-uji")

    captures: list[int] = []
    clicks: list[dict] = []

    def fake_capture():
        captures.append(1)
        (sandbox / "desktop_screen.png").write_bytes(b"png-bytes")

    monkeypatch.setattr(ia, "capture_desktop_screenshot", fake_capture)
    monkeypatch.setattr(
        ia,
        "desktop_click_coordinate",
        lambda **kwargs: clicks.append(kwargs) or {"status": "success"},
    )
    return SimpleNamespace(
        sandbox=sandbox, captures=captures, clicks=clicks, module=ia
    )


def test_vision_missing_screenshot_triggers_env_loader(
    vision_env, monkeypatch
):
    from alfa.core import config as config_mod

    loaded: list[int] = []
    monkeypatch.setattr(config_mod, "ensure_env_loaded", lambda: loaded.append(1))

    def no_shot():
        return {"status": "error"}

    monkeypatch.setattr(vision_env.module, "capture_desktop_screenshot", no_shot)
    _install_genai(monkeypatch, texts=["{}"])

    out = vision_env.module.vision_click_target("tombol merah")
    assert out["status"] == "error"
    assert "screenshot desktop" in out["message"]
    assert loaded == [1]


def test_vision_empty_screenshot(vision_env, monkeypatch):
    def empty_shot():
        (vision_env.sandbox / "desktop_screen.png").write_bytes(b"")

    monkeypatch.setattr(vision_env.module, "capture_desktop_screenshot", empty_shot)
    _install_genai(monkeypatch, texts=["{}"])
    out = vision_env.module.vision_click_target("ikon")
    assert out["status"] == "error"
    assert "screenshot desktop" in out["message"]


def test_vision_identify_only(vision_env, monkeypatch):
    payload = {
        "found": True,
        "x": 100,
        "y": 200,
        "element_description": "Tombol Close",
        "confidence": "high",
    }
    calls = _install_genai(
        monkeypatch, texts=[json.dumps(payload)]
    )

    out = vision_env.module.vision_click_target(
        "tombol close", max_attempts=1, action="identify_only"
    )
    assert out["status"] == "success"
    assert out["coordinates"] == {"x": 100, "y": 200}
    assert out["element_description"] == "Tombol Close"
    assert out["confidence"] == "high"
    assert out["attempt"] == 1
    assert vision_env.clicks == []
    # Screenshot sebelum klik dihapus agar tidak ikut terkirim.
    assert not (vision_env.sandbox / "desktop_screen.png").exists()

    assert calls[0]["model"] == "gemini-model-uji"
    prompt = calls[0]["contents"][1]
    assert "tombol close" in prompt
    assert calls[0]["contents"][0].mime_type == "image/png"
    assert calls[0]["contents"][0].data == b"png-bytes"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("click", {"clicks": 1, "button": "left"}),
        ("double_click", {"clicks": 2, "button": "left"}),
        ("right_click", {"clicks": 1, "button": "right"}),
    ],
)
def test_vision_click_actions(vision_env, monkeypatch, action, expected):
    payload = {
        "found": True,
        "x": 10,
        "y": 20,
        "element_description": "target",
        "confidence": "medium",
    }
    _install_genai(monkeypatch, texts=[json.dumps(payload)])

    out = vision_env.module.vision_click_target(
        "target", max_attempts=2, action=action
    )
    assert out["status"] == "success"
    assert out["action_performed"] == action
    assert vision_env.clicks == [
        {"x": 10, "y": 20, "button": expected["button"], "clicks": expected["clicks"]}
    ]
    # Screenshot awal + screenshot verifikasi.
    assert len(vision_env.captures) == 2
    assert (vision_env.sandbox / "desktop_screen.png").exists()


def test_vision_retry_after_found_false(vision_env, monkeypatch):
    payloads = [
        json.dumps({"found": False, "element_description": "belum ada", "x": 0, "y": 0}),
        json.dumps(
            {
                "found": True,
                "x": 5,
                "y": 6,
                "element_description": "ketemu",
                "confidence": "low",
            }
        ),
    ]
    _install_genai(monkeypatch, texts=payloads)
    out = vision_env.module.vision_click_target("elemen", max_attempts=3)
    assert out["status"] == "success"
    assert out["attempt"] == 2
    assert out["confidence"] == "low"


def test_vision_not_found_after_all_attempts(vision_env, monkeypatch):
    payload = json.dumps(
        {"found": False, "element_description": "tidak ada", "x": 0, "y": 0}
    )
    _install_genai(monkeypatch, texts=[payload])
    out = vision_env.module.vision_click_target("hantu", max_attempts=2)
    assert out["status"] == "error"
    assert "tidak ditemukan di layar setelah 2 percobaan" in out["message"]
    assert out["vision_response"] == "tidak ada"
    assert vision_env.clicks == []


def test_vision_no_json_loops_until_clamped_attempts(vision_env, monkeypatch):
    calls = _install_genai(monkeypatch, texts=["maaf, bukan json"])
    out = vision_env.module.vision_click_target("target", max_attempts=9)
    assert out["status"] == "error"
    # min(max(1, 9), 5) -> 5 percobaan.
    assert "setelah 5 percobaan vision loop" in out["message"]
    assert len(calls) == 5


def test_vision_json_wrapped_in_markdown(vision_env, monkeypatch):
    payload = json.dumps(
        {
            "found": True,
            "x": 1,
            "y": 2,
            "element_description": "dibalik markdown",
            "confidence": "high",
        }
    )
    _install_genai(monkeypatch, texts=[f"```json\n{payload}\n```"])
    out = vision_env.module.vision_click_target("x", action="identify_only")
    assert out["status"] == "success"
    assert out["coordinates"] == {"x": 1, "y": 2}


def test_vision_client_failure(vision_env, monkeypatch):
    _install_genai(
        monkeypatch, client_error=RuntimeError("kunci API rusak")
    )
    out = vision_env.module.vision_click_target("target")
    assert out["status"] == "error"
    assert out["message"].startswith("Vision loop error")
    assert "kunci API rusak" in out["message"]


def test_vision_invalid_json_body(vision_env, monkeypatch):
    _install_genai(monkeypatch, texts=["{found: tanpa-kutip}"])
    out = vision_env.module.vision_click_target("target")
    assert out["status"] == "error"
    assert out["message"].startswith("Vision loop error")


def test_vision_missing_coordinate_keys(vision_env, monkeypatch):
    _install_genai(monkeypatch, texts=[json.dumps({"found": True})])
    out = vision_env.module.vision_click_target("target")
    assert out["status"] == "error"
    assert out["message"].startswith("Vision loop error")
    assert vision_env.clicks == []


class _OsProxy:
    """Delegasi modul ``os`` dengan ``remove`` yang selalu gagal."""

    def __init__(self, fail_remove: bool = True):
        self._real = os
        self._fail_remove = fail_remove

    def __getattr__(self, name):
        return getattr(self._real, name)

    def remove(self, path):
        if self._fail_remove:
            raise OSError("sandbox read-only")  # noqa: TRY003
        return self._real.remove(path)


def _vision_found_payload():
    return json.dumps(
        {
            "found": True,
            "x": 3,
            "y": 4,
            "element_description": "target",
            "confidence": "high",
        }
    )


def test_vision_identify_only_survives_remove_failure(vision_env, monkeypatch):
    _install_genai(monkeypatch, texts=[_vision_found_payload()])
    monkeypatch.setattr(vision_env.module, "os", _OsProxy())

    out = vision_env.module.vision_click_target(
        "target", max_attempts=1, action="identify_only"
    )
    assert out["status"] == "success"
    assert (vision_env.sandbox / "desktop_screen.png").exists()


def test_vision_click_survives_remove_failure(vision_env, monkeypatch):
    _install_genai(monkeypatch, texts=[_vision_found_payload()])
    monkeypatch.setattr(vision_env.module, "os", _OsProxy())

    out = vision_env.module.vision_click_target("target", action="click")
    assert out["status"] == "success"
    assert vision_env.clicks == [{"x": 3, "y": 4, "button": "left", "clicks": 1}]
    assert (vision_env.sandbox / "desktop_screen.png").exists()
