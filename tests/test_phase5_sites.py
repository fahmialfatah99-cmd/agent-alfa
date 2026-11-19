"""Phase 5 coverage: sites registry, stack detection, and process control.

Hermetic: seluruh Popen/os.kill/psutil di-mock; registry, output, dan log
diarahkan ke tmp_path sehingga tidak ada proses nyata yang dijalankan.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from alfa.tools.system import sites


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    state = tmp_path / ".alfa"
    outputs = tmp_path / "outputs"
    monkeypatch.setattr(sites, "STATE_DIR", str(state))
    monkeypatch.setattr(sites, "REGISTRY_FILE", str(state / "sites_registry.json"))
    monkeypatch.setattr(sites, "LOGS_DIR", str(state / "sites_logs"))
    monkeypatch.setattr(sites, "OUTPUTS_DIR", str(outputs))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return SimpleNamespace(state=state, outputs=outputs, home=home)


# ── registry persistence ─────────────────────────────────────────────────────


def test_load_registry_variants(_isolated):
    assert sites._load_registry() == {}
    _isolated.state.mkdir(parents=True, exist_ok=True)
    ( _isolated.state / "sites_registry.json").write_text("[]", encoding="utf-8")
    assert sites._load_registry() == {}
    ( _isolated.state / "sites_registry.json").write_text("{rusak", encoding="utf-8")
    assert sites._load_registry() == {}
    ( _isolated.state / "sites_registry.json").write_text(
        '{"a": {"slug": "a"}}', encoding="utf-8"
    )
    assert sites._load_registry()["a"]["slug"] == "a"


def test_save_registry_creates_state_and_ignores_errors(_isolated, monkeypatch):
    sites._save_registry({"a": {"slug": "a"}})
    saved = json.loads((_isolated.state / "sites_registry.json").read_text())
    assert saved["a"]["slug"] == "a"

    def boom(*args, **kwargs):
        msg = "disk penuh"
        raise OSError(msg)

    monkeypatch.setattr(sites.json, "dump", boom)
    sites._save_registry({"b": {}})


def test_free_port_skips_used_ports():
    port = sites._free_port(8100, {8100, 8101})
    assert port >= 8102


# ── stack detection ──────────────────────────────────────────────────────────


def test_detect_stack_backend_frontend_php_static(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (backend / "index.html").write_text(
        "<html><title>Toko Backend</title></html>", encoding="utf-8"
    )
    info = sites._detect_stack(str(backend))
    assert info["has_backend"] is True
    assert info["has_static"] is True
    assert info["title"] == "Toko Backend"

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15"}}), encoding="utf-8"
    )
    assert sites._detect_stack(str(frontend))["has_frontend"] is True

    php = tmp_path / "php"
    php.mkdir()
    (php / "artisan").write_text("", encoding="utf-8")
    assert sites._detect_stack(str(php))["has_php"] is True

    nested = tmp_path / "nested"
    (nested / "sub").mkdir(parents=True)
    (nested / "sub" / "halo.htm").write_text("<html></html>", encoding="utf-8")
    assert sites._detect_stack(str(nested))["has_static"] is True

    kosong = tmp_path / "kosong"
    kosong.mkdir()
    out = sites._detect_stack(str(kosong))
    assert out["has_backend"] is False
    assert out["title"] == "kosong"


def test_detect_stack_ignores_broken_package_json(tmp_path):
    site = tmp_path / "sitrus"
    site.mkdir()
    (site / "package.json").write_text("{rusak", encoding="utf-8")
    assert sites._detect_stack(str(site))["has_frontend"] is False


def test_pick_frontend_dir_prefers_next_with_start(tmp_path):
    root = tmp_path / "situs"
    web = root / "apps" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15"}, "scripts": {"start": "next start"}}),
        encoding="utf-8",
    )
    assert sites._pick_frontend_dir(str(root)) == str(web)

    (web / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15"}, "scripts": {}}), encoding="utf-8"
    )
    assert sites._pick_frontend_dir(str(root)) == str(web)

    (web / "package.json").write_text("{rusak", encoding="utf-8")
    assert sites._pick_frontend_dir(str(root)) == str(root)


# ── refresh registry ─────────────────────────────────────────────────────────


def _make_site_tree(outputs):
    static = outputs / "websites" / "static-site"
    static.mkdir(parents=True)
    (static / "index.html").write_text(
        "<html><title>Situs Statis</title></html>", encoding="utf-8"
    )
    nxt = outputs / "websites" / "next-site"
    nxt.mkdir(parents=True)
    (nxt / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15"}, "scripts": {"start": "next start"}}),
        encoding="utf-8",
    )
    backend = outputs / "projects" / "backend-site"
    backend.mkdir(parents=True)
    (backend / "app.py").write_text("FastAPI()", encoding="utf-8")
    php = outputs / "projects" / "php-site"
    php.mkdir(parents=True)
    (php / "artisan").write_text("", encoding="utf-8")
    nonweb = outputs / "projects" / "nonweb"
    nonweb.mkdir(parents=True)
    (nonweb / "catatan.txt").write_text("x", encoding="utf-8")
    (outputs / "websites" / ".hidden").mkdir()
    (outputs / "websites" / "node_modules").mkdir()
    (outputs / "websites" / "berkas.txt").write_text("x", encoding="utf-8")


def test_refresh_registry_builds_entries_and_removes_stale(_isolated, monkeypatch):
    _make_site_tree(_isolated.outputs)
    _isolated.state.mkdir(parents=True, exist_ok=True)
    (_isolated.state / "sites_registry.json").write_text(
        json.dumps(
            {
                "hilang": {"slug": "hilang", "pid_backend": 999},
                "backend-site": {"slug": "backend-site", "backend_port": 9999},
            }
        ),
        encoding="utf-8",
    )
    stopped = []
    monkeypatch.setattr(
        sites, "_stop_entry", lambda reg, slug: stopped.append(slug)
    )

    reg = sites.refresh_registry()
    assert stopped == ["hilang"]
    assert "hilang" not in reg
    assert reg["static-site"]["stack"]["has_static"] is True
    assert reg["static-site"]["title"] == "Situs Statis"
    assert reg["next-site"]["stack"]["has_frontend"] is True
    assert reg["next-site"]["frontend_dir"] == str(
        _isolated.outputs / "websites" / "next-site"
    )
    assert reg["next-site"]["frontend_port"] >= sites.FRONTEND_PORT_BASE
    assert reg["backend-site"]["backend_port"] == 9999
    assert reg["php-site"]["backend_port"] >= sites.BACKEND_PORT_BASE
    assert reg["nonweb"]["stack"]["has_static"] is False
    assert "berkas.txt" not in reg

    saved = json.loads((_isolated.state / "sites_registry.json").read_text())
    assert set(saved) == set(reg)


# ── pid helpers & stop ───────────────────────────────────────────────────────


def test_pid_alive_and_stop_without_pid(monkeypatch):
    assert sites._pid_alive(os.getpid()) is True
    assert sites._pid_alive(99999999) is False
    assert sites._pid_alive(None) is False
    reg = {"a": {}}
    sites._stop_entry(reg, "a")
    assert reg == {"a": {}}


def test_stop_entry_terminates_tree(monkeypatch):
    terminated, killed = [], []

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=True):
            child = SimpleNamespace(
                terminate=lambda: terminated.append("child"),
                kill=lambda: killed.append("child"),
            )
            return [child]

        def terminate(self):
            terminated.append("parent")

        def kill(self):
            killed.append("parent")

    import psutil

    monkeypatch.setattr(psutil, "Process", FakeProc)
    monkeypatch.setattr(sites, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(sites.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(sites.time, "sleep", lambda seconds: None)
    reg = {"a": {"pid_backend": 111, "pid_frontend": 222}}
    sites._stop_entry(reg, "a")
    assert "parent" in terminated
    assert "parent" in killed
    assert "pid_backend" not in reg["a"]
    assert "pid_frontend" not in reg["a"]


def test_stop_entry_falls_back_to_os_kill(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "psutil", None)
    signals = []
    monkeypatch.setattr(sites.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(sites, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(sites.time, "sleep", lambda seconds: None)
    sites._stop_entry({"a": {"pid_backend": 111}}, "a")
    import signal

    assert signals == [(111, signal.SIGTERM), (111, signal.SIGKILL)]


# ── http wait ────────────────────────────────────────────────────────────────


def test_wait_http_rejects_invalid_scheme():
    assert sites._wait_http("ftp://127.0.0.1:1") is False
    assert sites._wait_http("http://") is False


def test_wait_http_success_and_timeout(monkeypatch):
    monkeypatch.setattr(sites.urllib.request, "urlopen", lambda url, timeout=3: object())
    assert sites._wait_http("http://127.0.0.1:9999/") is True

    def boom(*args, **kwargs):
        msg = "refused"
        raise OSError(msg)

    monkeypatch.setattr(sites.urllib.request, "urlopen", boom)
    monkeypatch.setattr(sites.time, "sleep", lambda seconds: None)
    ticks = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(sites.time, "time", lambda: next(ticks))
    assert sites._wait_http("http://127.0.0.1:9999/", timeout=0.5) is False


# ── start / stop / status ────────────────────────────────────────────────────


def _start(monkeypatch, entries, slug):
    saved = {}
    monkeypatch.setattr(sites, "refresh_registry", lambda: entries)
    monkeypatch.setattr(sites, "_save_registry", lambda reg: saved.update(reg=reg))
    out = sites.start_site(slug)
    return out, entries.get(slug, {}), saved


def test_start_site_unknown(monkeypatch):
    out, _, _ = _start(monkeypatch, {}, "tidak-ada")
    assert out["status"] == "error"
    assert "tak dikenal" in out["message"]


def test_start_site_backend_uvicorn_and_existing(monkeypatch, tmp_path):
    path = tmp_path / "backend"
    path.mkdir()
    (path / "app.py").write_text("FastAPI()", encoding="utf-8")
    commands = []

    def popen(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(pid=4321)

    monkeypatch.setattr(sites.subprocess, "Popen", popen)
    monkeypatch.setattr(sites, "_wait_http", lambda url, timeout=20.0: True)
    entry = {
        "slug": "backend",
        "path": str(path),
        "stack": {"has_backend": True},
        "backend_port": 8123,
    }
    out, ent, saved = _start(monkeypatch, {"backend": entry}, "backend")
    assert out["status"] == "success"
    assert "OK" in out["backend"]
    assert ent["pid_backend"] == 4321
    assert commands[0][:3] == [commands[0][0], "-m", "uvicorn"]

    monkeypatch.setattr(sites, "_pid_alive", lambda pid: True)
    out, _, _ = _start(monkeypatch, {"backend": entry}, "backend")
    assert "sudah jalan" in out["backend"]


def test_start_site_backend_flask(monkeypatch, tmp_path):
    path = tmp_path / "flask"
    path.mkdir()
    (path / "app.py").write_text("from flask import Flask\napp = Flask(__name__)", encoding="utf-8")
    commands = []

    def popen(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(pid=11)

    monkeypatch.setattr(sites.subprocess, "Popen", popen)
    monkeypatch.setattr(sites, "_wait_http", lambda url, timeout=20.0: False)
    entry = {
        "slug": "flask",
        "path": str(path),
        "stack": {"has_backend": True},
        "backend_port": 8124,
    }
    out, _, _ = _start(monkeypatch, {"flask": entry}, "flask")
    assert "flask" in commands[0]
    assert "health belum merespons" in out["backend"]


def test_start_site_backend_uvicorn_path_fallback(monkeypatch, tmp_path):
    path = tmp_path / "fallback"
    path.mkdir()
    commands = []

    def popen(cmd, **kwargs):
        if len(commands) == 0:
            commands.append(cmd)
            msg = "uvicorn tidak ada"
            raise FileNotFoundError(msg)
        commands.append(cmd)
        return SimpleNamespace(pid=12)

    monkeypatch.setattr(sites.subprocess, "Popen", popen)
    monkeypatch.setattr(sites, "_wait_http", lambda url, timeout=20.0: True)
    entry = {
        "slug": "fallback",
        "path": str(path),
        "stack": {"has_backend": True},
        "backend_port": 8125,
    }
    out, _, _ = _start(monkeypatch, {"fallback": entry}, "fallback")
    assert commands[-1][0] == "uvicorn"
    assert out["status"] == "success"


def test_start_site_frontend_and_existing(monkeypatch, tmp_path):
    path = tmp_path / "web"
    fe = path / "frontend"
    fe.mkdir(parents=True)
    (fe / "package.json").write_text("{}", encoding="utf-8")
    commands = []

    def popen(cmd, **kwargs):
        commands.append((cmd, kwargs))
        return SimpleNamespace(pid=22)

    monkeypatch.setattr(sites.subprocess, "Popen", popen)
    monkeypatch.setattr(sites, "_wait_http", lambda url, timeout=20.0: True)
    entry = {
        "slug": "web",
        "path": str(path),
        "frontend_dir": str(fe),
        "stack": {"has_frontend": True},
        "frontend_port": 3111,
    }
    out, ent, _ = _start(monkeypatch, {"web": entry}, "web")
    assert commands[0][0][:2] == ["npm", "run"]
    assert commands[0][1]["cwd"] == str(fe)
    assert ent["pid_frontend"] == 22
    assert "OK" in out["frontend"]

    monkeypatch.setattr(sites, "_pid_alive", lambda pid: True)
    out, _, _ = _start(monkeypatch, {"web": entry}, "web")
    assert "sudah jalan" in out["frontend"]


def test_start_site_frontend_falls_back_to_site_root(monkeypatch, tmp_path):
    path = tmp_path / "web2"
    path.mkdir()
    monkeypatch.setattr(sites.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=23))
    monkeypatch.setattr(sites, "_wait_http", lambda url, timeout=20.0: False)
    entry = {
        "slug": "web2",
        "path": str(path),
        "frontend_dir": str(path / "hilang"),
        "stack": {"has_frontend": True},
        "frontend_port": 3112,
    }
    out, _, _ = _start(monkeypatch, {"web2": entry}, "web2")
    assert "masih build" in out["frontend"]


def test_start_site_php_and_static(monkeypatch, tmp_path):
    php_path = tmp_path / "php"
    php_path.mkdir()
    (php_path / "artisan").write_text("", encoding="utf-8")
    commands = []
    monkeypatch.setattr(
        sites.subprocess,
        "Popen",
        lambda cmd, **k: commands.append(cmd) or SimpleNamespace(pid=33),
    )
    monkeypatch.setattr(sites, "_wait_http", lambda url, timeout=20.0: True)
    php = {
        "slug": "php",
        "path": str(php_path),
        "stack": {"has_php": True},
        "backend_port": 8126,
    }
    out, _, _ = _start(monkeypatch, {"php": php}, "php")
    assert commands[0][:2] == ["php", "artisan"]
    assert "OK" in out["backend"]

    static_path = tmp_path / "static"
    static_path.mkdir()
    static = {
        "slug": "static",
        "path": str(static_path),
        "stack": {"has_static": True},
        "backend_port": 8127,
    }
    out, ent, saved = _start(monkeypatch, {"static": static}, "static")
    assert "static" in out
    assert ent["pid_backend"] == 33
    assert saved["reg"]["static"]["pid_backend"] == 33


def test_start_site_non_web_note(monkeypatch, tmp_path):
    path = tmp_path / "tool"
    path.mkdir()
    entry = {"slug": "tool", "path": str(path), "stack": {}}
    out, _, _ = _start(monkeypatch, {"tool": entry}, "tool")
    assert "non-web" in out["note"]


def test_stop_site_and_status(monkeypatch):
    out = sites.stop_site("tidak-ada")
    assert out["status"] == "error"

    stopped = []
    saved = {}
    monkeypatch.setattr(sites, "_stop_entry", lambda reg, slug: stopped.append(slug))
    monkeypatch.setattr(sites, "_save_registry", lambda reg: saved.update(reg=reg))
    monkeypatch.setattr(sites.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sites, "_load_registry", lambda: {"a": {"slug": "a"}})
    out = sites.stop_site("a")
    assert out["status"] == "success"
    assert stopped == ["a"]
    assert "a" in saved["reg"]

    monkeypatch.setattr(
        sites,
        "refresh_registry",
        lambda: {
            "on": {"title": "On", "pid_backend": 1, "pid_frontend": 2},
            "off": {"title": "Off"},
        },
    )
    monkeypatch.setattr(sites, "_pid_alive", lambda pid: True)
    rows = {row["slug"]: row for row in sites.site_status()}
    assert rows["on"]["backend_on"] is True
    assert rows["on"]["frontend_on"] is True
    assert rows["off"]["backend_on"] is False


def test_tool_wrappers(monkeypatch, tmp_path):
    monkeypatch.setattr(sites, "site_status", lambda: [{"slug": "a"}])
    assert sites.list_managed_sites()["total"] == 1

    def boom():
        msg = "gagal"
        raise OSError(msg)

    monkeypatch.setattr(sites, "site_status", boom)
    assert sites.list_managed_sites()["status"] == "error"

    monkeypatch.setattr(sites, "site_status", lambda: [{"slug": "a"}])
    assert sites.serve_site("status")["status"] == "success"
    assert sites.serve_site("start", "")["status"] == "error"
    assert sites.serve_site("hapus", "a")["status"] == "error"

    monkeypatch.setattr(sites, "start_site", lambda slug: {"status": "success", "slug": slug})
    monkeypatch.setattr(sites, "stop_site", lambda slug: {"status": "success", "slug": slug})
    assert sites.serve_site("start", "a")["slug"] == "a"
    assert sites.serve_site("stop", "a")["slug"] == "a"

    log = tmp_path / "sites_logs" / "a-backend.log"
    log.parent.mkdir(parents=True)
    log.write_text("baris1\nbaris2\n", encoding="utf-8")
    monkeypatch.setattr(sites, "LOGS_DIR", str(log.parent))
    monkeypatch.setattr(sites, "_load_registry", lambda: {"a": {"pid_backend": 9}})
    monkeypatch.setattr(sites, "_pid_alive", lambda pid: False)
    out = sites.serve_site("logs", "a")
    assert "baris2" in out["logs"]["backend"]
    assert out["running"]["backend"] is False
