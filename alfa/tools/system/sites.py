"""Registry + kontrol situs hasil kerja agent (websites/ & projects/).

Setiap folder arsip harvest dipindai: jenis stack dideteksi, port dialokasikan,
proses server dikelola (start/stop/status) dengan state persisten.
Dipakai agent (tools) dan menu Telegram /sites.
"""

import json
import logging
import os
import signal
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("SitesRegistry")

OUTPUTS_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
STATE_DIR = os.path.join(os.path.expanduser("~"), ".alfa")
REGISTRY_FILE = os.path.join(STATE_DIR, "sites_registry.json")
LOGS_DIR = os.path.join(STATE_DIR, "sites_logs")
BACKEND_PORT_BASE = 8100
FRONTEND_PORT_BASE = 3110


def _load_registry() -> dict:
    try:
        with open(REGISTRY_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _save_registry(reg: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(REGISTRY_FILE, "w") as f:
            json.dump(reg, f, indent=2)
    except (OSError, TypeError, ValueError) as e:
        logger.debug(f"[sites] simpan registry gagal: {e}")


def _free_port(base: int, used: set[int]) -> int:
    port = base
    while port in used:
        port += 1
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                port += 1
                continue
            if port in used:
                port += 1
                continue
            return port


def _detect_stack(path: str) -> dict[str, Any]:
    """Deteksi komponen situs dari isi folder."""
    info: dict[str, Any] = {"has_backend": False, "has_frontend": False,
                            "has_static": False, "has_php": False,
                            "title": os.path.basename(path)}
    try:
        if os.path.isfile(os.path.join(path, "app.py")):
            with open(os.path.join(path, "app.py"), errors="ignore") as f:
                head = f.read(4000)
            if "FastAPI" in head or "uvicorn" in head or "Flask" in head:
                info["has_backend"] = True
                for line in head.splitlines()[:30]:
                    if "<title>" in line:
                        info["title"] = line.split("<title>")[1].split("<")[0].strip() or info["title"]
        fe_pkg = os.path.join(path, "frontend", "package.json")
        if not os.path.isfile(fe_pkg):
            fe_pkg = os.path.join(path, "package.json")
        if os.path.isfile(fe_pkg):
            try:
                pkg = json.load(open(fe_pkg))
                deps = {**(pkg.get("dependencies", {})), **(pkg.get("devDependencies", {}))}
                if "next" in deps:
                    info["has_frontend"] = True
            except (OSError, TypeError, ValueError):
                pass
        if os.path.isfile(os.path.join(path, "artisan")):
            info["has_php"] = True
        for cand in ("static/index.html", "index.html", "frontend/index.html"):
            if os.path.isfile(os.path.join(path, cand)):
                info["has_static"] = True
                break
        if not info["has_static"]:
            try:
                for _root, _dirs, _files in os.walk(path):
                    _dirs[:] = [d for d in _dirs if d not in ("node_modules", "__pycache__", ".git")]
                    if any(f.endswith((".html", ".htm")) for f in _files):
                        info["has_static"] = True
                        break
            except OSError:
                pass
        idx = None
        for cand in ("static/index.html", "index.html"):
            p = os.path.join(path, cand)
            if os.path.isfile(p):
                idx = p
                break
        if idx:
            try:
                with open(idx, errors="ignore") as f:
                    html = f.read(6000)
                import re as _re

                m = _re.search(r"<title>(.*?)</title>", html, _re.S)
                if m and m.group(1).strip():
                    info["title"] = m.group(1).strip()[:60]
            except OSError:
                pass
    except (OSError, TypeError, ValueError) as e:
        logger.debug(f"[sites] deteksi gagal {path}: {e}")
    return info



def _pick_frontend_dir(path: str) -> str:
    """Pilih folder frontend yang benar-benar bisa di-start (ada next + script start)."""
    cands = [os.path.join(path, "frontend"), os.path.join(path, "apps", "web"), path]
    fallback = path
    for c in cands:
        pkg = os.path.join(c, "package.json")
        if not os.path.isfile(pkg):
            continue
        try:
            data = json.load(open(pkg))
        except (OSError, TypeError, ValueError):
            continue
        deps = {**(data.get("dependencies", {})), **(data.get("devDependencies", {}))}
        if "next" not in deps:
            continue
        fallback = c
        if "start" in (data.get("scripts", {}) or {}):
            return c
    return fallback



def refresh_registry() -> dict:
    """Pindai ulang folder outputs; pertahankan port/pid yang sudah ada."""
    reg = _load_registry()
    seen: set[str] = set()
    used_ports: set[int] = set()
    for _slug, ent in reg.items():
        for k in ("backend_port", "frontend_port"):
            if ent.get(k):
                used_ports.add(int(ent[k]))
    scan_roots = [
        ("websites", os.path.join(OUTPUTS_DIR, "websites")),
        ("projects", os.path.join(OUTPUTS_DIR, "projects")),
        ("projects", os.path.expanduser("~/alfa_projects")),
    ]
    for cat, parent in scan_roots:
        if not os.path.isdir(parent):
            continue
        for slug in sorted(os.listdir(parent)):
            if slug.startswith(".") or slug in ("ALFA_WORKSPACE", "ALFA_SWARM_OUTPUTS", "alfa_projects", "output", "__pycache__", "node_modules"):
                continue
            path = os.path.join(parent, slug)
            if not os.path.isdir(path):
                continue
            seen.add(slug)
            stack = _detect_stack(path)
            ent = reg.get(slug, {})
            fe_dir = None
            if stack.get("has_frontend"):
                fe_dir = _pick_frontend_dir(path)
            ent.update({
                "slug": slug, "category": cat, "path": path,
                "title": stack["title"], "stack": {k: v for k, v in stack.items() if k != "title"},
                "frontend_dir": fe_dir,
            })
            if (stack["has_backend"] or stack.get("has_php")) and not ent.get("backend_port"):
                ent["backend_port"] = _free_port(BACKEND_PORT_BASE, used_ports)
                used_ports.add(ent["backend_port"])
            if stack["has_frontend"] and not ent.get("frontend_port"):
                ent["frontend_port"] = _free_port(FRONTEND_PORT_BASE, used_ports)
                used_ports.add(ent["frontend_port"])
            reg[slug] = ent
    for slug in [s for s in reg if s not in seen]:
        _stop_entry(reg, slug)
        reg.pop(slug, None)
    _save_registry(reg)
    return reg


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _stop_entry(reg: dict, slug: str) -> None:
    # Matikan pohon proses (npm wrapper + anak next-server/uvicorn sering yatim bila hanya kill induk).
    ent = reg.get(slug, {})
    for k in ("pid_backend", "pid_frontend"):
        pid = ent.get(k)
        if not pid:
            continue
        try:
            import psutil as _ps

            try:
                proc = _ps.Process(int(pid))
                for child in proc.children(recursive=True):
                    try:
                        child.terminate()
                    except (OSError, _ps.Error):
                        pass
                proc.terminate()
            except (OSError, TypeError, ValueError, _ps.Error):
                pass
        except ImportError:
            pass
        try:
            if _pid_alive(pid):
                os.kill(int(pid), signal.SIGTERM)
        except (OSError, TypeError, ValueError):
            pass
    time.sleep(2)
    for k in ("pid_backend", "pid_frontend"):
        pid = ent.get(k)
        if pid and _pid_alive(pid):
            try:
                import psutil as _ps

                try:
                    proc = _ps.Process(int(pid))
                    for child in proc.children(recursive=True):
                        try:
                            child.kill()
                        except (OSError, _ps.Error):
                            pass
                    proc.kill()
                except (OSError, TypeError, ValueError, _ps.Error):
                    os.kill(int(pid), signal.SIGKILL)
            except ImportError:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (OSError, TypeError, ValueError):
                    pass
    ent.pop("pid_backend", None)
    ent.pop("pid_frontend", None)


def _wait_http(url: str, timeout: float = 20.0) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            # Skema URL telah divalidasi hanya http/https untuk health-check port lokal
            urllib.request.urlopen(url, timeout=3)  # nosec B310
            return True
        except OSError:
            time.sleep(1)
    return False


def start_site(slug: str) -> dict[str, Any]:
    """Hidupkan backend (+ frontend bila ada). Return info URL/status."""
    reg = refresh_registry()
    ent = reg.get(slug)
    if not ent:
        keys = ", ".join(sorted(reg)) or "-"
        return {"status": "error", "message": f"Situs '{slug}' tak dikenal. Pilih: {keys}"}
    stack = ent.get("stack", {})
    out: dict[str, Any] = {"status": "success", "slug": slug, "title": ent.get("title", slug)}
    os.makedirs(LOGS_DIR, exist_ok=True)
    if stack.get("has_backend"):
        if ent.get("pid_backend") and _pid_alive(ent["pid_backend"]):
            out["backend"] = f"sudah jalan (PID {ent['pid_backend']})"
        else:
            port = int(ent.get("backend_port") or _free_port(BACKEND_PORT_BASE, set()))
            logf = open(os.path.join(LOGS_DIR, f"{slug}-backend.log"), "ab")
            try:
                proc = subprocess.Popen(
                    ["uvicorn", "app:app", "--port", str(port)],
                    cwd=ent["path"], stdout=logf, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except FileNotFoundError:
                import sys as _sys

                proc = subprocess.Popen(
                    [_sys.executable, "-m", "uvicorn", "app:app", "--port", str(port)],
                    cwd=ent["path"], stdout=logf, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            ent["pid_backend"] = proc.pid
            ent["backend_port"] = port
            ok = _wait_http(f"http://127.0.0.1:{port}/api/health")
            if not ok:
                ok = _wait_http(f"http://127.0.0.1:{port}/")
            out["backend"] = f"http://127.0.0.1:{port} ({'OK' if ok else 'proses jalan, health belum merespons'})"
    if stack.get("has_frontend"):
        if ent.get("pid_frontend") and _pid_alive(ent["pid_frontend"]):
            out["frontend"] = f"sudah jalan (PID {ent['pid_frontend']})"
        else:
            port = int(ent.get("frontend_port") or _free_port(FRONTEND_PORT_BASE, set()))
            logf = open(os.path.join(LOGS_DIR, f"{slug}-frontend.log"), "ab")
            env = dict(os.environ, PORT=str(port))
            fe_cwd = ent.get("frontend_dir") or os.path.join(ent["path"], "frontend")
            if not os.path.isfile(os.path.join(fe_cwd, "package.json")):
                fe_cwd = ent["path"]
            proc = subprocess.Popen(
                ["npm", "run", "start", "--", "-p", str(port)],
                cwd=fe_cwd,
                stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True, env=env,
            )
            ent["pid_frontend"] = proc.pid
            ent["frontend_port"] = port
            ok = _wait_http(f"http://127.0.0.1:{port}/")
            out["frontend"] = f"http://127.0.0.1:{port} ({'OK' if ok else 'proses jalan, masih build/start'})"
    if stack.get("has_php") and not stack.get("has_backend"):
        if ent.get("pid_backend") and _pid_alive(ent["pid_backend"]):
            out["backend"] = f"sudah jalan (PID {ent['pid_backend']})"
        else:
            port = int(ent.get("backend_port") or _free_port(BACKEND_PORT_BASE, set()))
            logf = open(os.path.join(LOGS_DIR, f"{slug}-backend.log"), "ab")
            proc = subprocess.Popen(
                ["php", "artisan", "serve", f"--port={port}", "--host=127.0.0.1"],
                cwd=ent["path"], stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            ent["pid_backend"] = proc.pid
            ent["backend_port"] = port
            ok = _wait_http(f"http://127.0.0.1:{port}/")
            out["backend"] = f"http://127.0.0.1:{port} ({'OK' if ok else 'proses jalan, health belum merespons'})"
    if stack.get("has_static") and not stack.get("has_backend") and not stack.get("has_frontend") and not stack.get("has_php"):
        if ent.get("pid_backend") and _pid_alive(ent["pid_backend"]):
            out["static"] = f"sudah jalan (PID {ent['pid_backend']})"
        else:
            port = int(ent.get("backend_port") or _free_port(BACKEND_PORT_BASE, set()))
            logf = open(os.path.join(LOGS_DIR, f"{slug}-static.log"), "ab")
            import sys as _sys

            proc = subprocess.Popen(
                [_sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                cwd=ent["path"], stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            ent["pid_backend"] = proc.pid
            ent["backend_port"] = port
            ok = _wait_http(f"http://127.0.0.1:{port}/")
            out["static"] = f"http://127.0.0.1:{port} ({'OK' if ok else 'proses jalan, tunggu sebentar'})"
        _save_registry(reg)
        return out
    if not stack.get("has_backend") and not stack.get("has_frontend") and not stack.get("has_php"):
        if stack.get("has_static"):
            out["note"] = "situs statis — buka folder/file index.html langsung (tak perlu server)"
        else:
            out["note"] = "proyek non-web (skrip/tools) — terdaftar, tak perlu server"
    _save_registry(reg)
    return out


def stop_site(slug: str) -> dict[str, Any]:
    reg = _load_registry()
    if slug not in reg:
        return {"status": "error", "message": f"Situs '{slug}' tak dikenal."}
    _stop_entry(reg, slug)
    _save_registry(reg)
    time.sleep(1)
    return {"status": "success", "message": f"Situs '{slug}' dimatikan."}


def site_status() -> list[dict[str, Any]]:
    reg = refresh_registry()
    rows = []
    for slug in sorted(reg):
        ent = reg[slug]
        rows.append({
            "slug": slug, "title": ent.get("title", slug),
            "category": ent.get("category", "?"),
            "backend_on": bool(ent.get("pid_backend") and _pid_alive(ent["pid_backend"])),
            "frontend_on": bool(ent.get("pid_frontend") and _pid_alive(ent["pid_frontend"])),
            "backend_port": ent.get("backend_port"), "frontend_port": ent.get("frontend_port"),
            "stack": ent.get("stack", {}),
        })
    return rows




@register_tool(category="system")
def list_managed_sites() -> dict[str, Any]:
    """Daftar semua website/proyek hasil kerja agent (registry situs).

    Return slug, judul, stack (backend/frontend/statis), port, dan status jalan/mati.
    Pakai serve_site untuk menghidupkan/mematikan.
    """
    try:
        rows = site_status()
        return {"status": "success", "total": len(rows), "sites": rows}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def serve_site(action: str = "status", slug: str = "") -> dict[str, Any]:
    """Hidupkan/matikan/cek situs hasil kerja agent.

    Args:
        action: 'start' | 'stop' | 'status' | 'logs'.
        slug: nama folder situs (lihat list_managed_sites). Wajib untuk start/stop/logs.
    """
    try:
        a = (action or "status").lower()
        if a == "status":
            return {"status": "success", "sites": site_status()}
        if not slug:
            return {"status": "error", "message": "Parameter slug wajib untuk start/stop/logs."}
        if a == "start":
            return start_site(slug)
        if a == "stop":
            return stop_site(slug)
        if a == "logs":
            reg = _load_registry()
            ent = reg.get(slug, {})
            out: dict[str, Any] = {"status": "success", "slug": slug, "logs": {}}
            for k in ("backend", "frontend"):
                lf = os.path.join(LOGS_DIR, f"{slug}-{k}.log")
                if os.path.isfile(lf):
                    try:
                        with open(lf, errors="ignore") as f:
                            out["logs"][k] = "".join(f.readlines()[-25:])
                    except OSError as e:
                        out["logs"][k] = f"(gagal baca: {e})"
            out["running"] = {
                "backend": bool(ent.get("pid_backend") and _pid_alive(ent["pid_backend"])),
                "frontend": bool(ent.get("pid_frontend") and _pid_alive(ent["pid_frontend"])),
            }
            return out
        return {"status": "error", "message": f"Aksi '{action}' tak dikenal (start|stop|status|logs)."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
