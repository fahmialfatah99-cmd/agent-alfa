"""ALFA Sovereign AI - Server Lifecycle & Ecosystem Manager.

Ensures all background servers (Web Command Center Dashboard, Swarm Engine,
Telegram AI Bot, and 9Router Gateway) are automatically verified and running
when the CLI is launched.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

from alfa.core.cli.constants import Colors, print_status


def get_repo_root() -> Path:
    """Find the root directory of the agent alfa repository."""
    # From alfa/core/cli/server_manager.py -> parents[3] is repository root
    try:
        p = Path(__file__).resolve().parents[3]
        if (p / "web_dashboard.py").exists():
            return p
    except Exception:
        pass
    # Fallback to current working directory or known location
    candidates = [
        Path.cwd(),
        Path.home() / "agent alfa",
        Path("/home/fahmial/agent alfa"),
    ]
    for c in candidates:
        if (c / "web_dashboard.py").exists():
            return c
    return Path.cwd()


def get_venv_python(repo_root: Path | None = None) -> str:
    """Get the path to python inside the virtual environment."""
    root = repo_root or get_repo_root()
    venv_py = root / "venv" / "bin" / "python3"
    if venv_py.exists():
        return str(venv_py)
    venv_py2 = root / "venv" / "bin" / "python"
    if venv_py2.exists():
        return str(venv_py2)
    return sys.executable


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently open and bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_http_health(url: str, timeout: float = 1.2) -> bool:
    """Check if an HTTP service responds successfully."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code in (200, 204, 301, 302, 401)
    except Exception:
        return False


def start_dashboard_server(
    repo_root: Path | None = None, wait_timeout: float = 5.0
) -> tuple[bool, str]:
    """Start the ALFA Web Command Center (FastAPI & Swarm on port 8080) in background."""
    root = repo_root or get_repo_root()
    health_url = "http://127.0.0.1:8080/health"

    # 1. Already running
    if check_http_health(health_url):
        return True, "http://localhost:8080 (Aktif)"

    py_bin = get_venv_python(root)
    dash_script = root / "web_dashboard.py"
    if not dash_script.exists():
        return False, f"File {dash_script} tidak ditemukan."

    log_dir = Path.home() / ".alfa" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "dashboard.log"

    try:
        with open(log_file, "a", encoding="utf-8") as out:
            out.write(f"\n--- ALFA Web Dashboard Started at {time.ctime()} ---\n")
            subprocess.Popen(
                [py_bin, str(dash_script)],
                cwd=str(root),
                stdout=out,
                stderr=out,
                start_new_session=True,
            )

        # Poll until healthy
        start_time = time.time()
        while time.time() - start_time < wait_timeout:
            if check_http_health(health_url):
                return True, "http://localhost:8080 (Berhasil Dinyalakan Otomatis)"
            time.sleep(0.4)

        if check_http_health(health_url):
            return True, "http://localhost:8080"
        return False, "Server dinyalakan namun melebihi batas waktu inisialisasi (cek ~/.alfa/logs/dashboard.log)"
    except Exception as e:
        return False, f"Gagal menyalakan dashboard server: {e}"


def start_telegram_bot(repo_root: Path | None = None) -> tuple[bool, str]:
    """Start Telegram AI Bot in background if token is configured."""
    root = repo_root or get_repo_root()
    env_file = root / ".env"
    token = ""
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            pass

    if not token or token == "your_telegram_bot_token_here":
        return False, "Token belum disetel di .env (Opsional)"

    # Check if bot process is already running
    try:
        res = subprocess.run(["pgrep", "-f", "bot.py"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return True, "Aktif di latar belakang"
    except Exception:
        pass

    py_bin = get_venv_python(root)
    bot_script = root / "bot.py"
    if not bot_script.exists():
        return False, "bot.py tidak ditemukan"

    log_dir = Path.home() / ".alfa" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bot.log"

    try:
        with open(log_file, "a", encoding="utf-8") as out:
            out.write(f"\n--- ALFA Telegram Bot Started at {time.ctime()} ---\n")
            subprocess.Popen(
                [py_bin, str(bot_script)],
                cwd=str(root),
                stdout=out,
                stderr=out,
                start_new_session=True,
            )
        return True, "Berhasil dinyalakan di latar belakang"
    except Exception as e:
        return False, f"Gagal menjalankan bot: {e}"


def check_9router_gateway() -> tuple[bool, str]:
    """Check status of 9Router Gateway on port 20128."""
    models_url = "http://127.0.0.1:20128/v1/models"
    if check_http_health(models_url):
        return True, "http://127.0.0.1:20128 (Aktif & Siap)"

    # Try starting 9router if binary exists
    router_bin = shutil.which("9router")
    if router_bin:
        try:
            subprocess.Popen([router_bin, "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(1.5)
            if check_http_health(models_url):
                return True, "http://127.0.0.1:20128 (Dinyalakan Otomatis)"
        except Exception:
            pass

    return False, "Offline (Gunakan '/menu' -> Switch Model -> 9Router untuk detail)"


def get_servers_status() -> dict[str, Any]:
    """Get status of all background services without starting them."""
    root = get_repo_root()
    dash_url = "http://127.0.0.1:8080/health"
    dash_ok = check_http_health(dash_url)
    dash_msg = "http://localhost:8080 (Aktif & Sehat)" if dash_ok else "Offline (Mati)"

    r9_url = "http://127.0.0.1:20128/v1/models"
    r9_ok = check_http_health(r9_url)
    r9_msg = "http://127.0.0.1:20128 (Aktif & Siap)" if r9_ok else "Offline"

    bot_ok = False
    bot_msg = "Offline"
    try:
        res = subprocess.run(["pgrep", "-f", "bot.py"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            bot_ok = True
            bot_msg = f"Aktif di latar belakang (PID: {res.stdout.split()[0]})"
    except Exception:
        pass

    return {
        "dashboard": {"ok": dash_ok, "status": dash_msg, "url": "http://localhost:8080"},
        "9router": {"ok": r9_ok, "status": r9_msg, "url": "http://127.0.0.1:20128"},
        "bot": {"ok": bot_ok, "status": bot_msg},
    }


def stop_all_servers() -> dict[str, bool]:
    """Gracefully stop background ALFA servers."""
    results = {}
    # Stop web dashboard
    try:
        res = subprocess.run(["pkill", "-f", "web_dashboard.py"], capture_output=True, text=True)
        results["dashboard"] = res.returncode == 0
    except Exception:
        results["dashboard"] = False

    # Stop telegram bot
    try:
        res = subprocess.run(["pkill", "-f", "bot.py"], capture_output=True, text=True)
        results["bot"] = res.returncode == 0
    except Exception:
        results["bot"] = False

    return results


def auto_start_all_servers(verbose: bool = True) -> dict[str, Any]:
    """Verify and automatically start all ecosystem servers.

    Returns dict of server statuses.
    """
    root = get_repo_root()
    dash_ok, dash_msg = start_dashboard_server(root)
    bot_ok, bot_msg = start_telegram_bot(root)
    r9_ok, r9_msg = check_9router_gateway()

    results = {
        "dashboard": {"ok": dash_ok, "status": dash_msg},
        "bot": {"ok": bot_ok, "status": bot_msg},
        "9router": {"ok": r9_ok, "status": r9_msg},
    }

    if verbose:
        dash_icon = "🟢" if dash_ok else "🟡"
        r9_icon = "🔀" if r9_ok else "⚪"
        bot_icon = "🤖" if bot_ok else "⚪"

        print(f"\n{Colors.BOLD}🚀 ALFA Ecosystem Server Autostart:{Colors.ENDC}")
        print(f"  {dash_icon} Web Command Center : {Colors.CYAN}{dash_msg}{Colors.ENDC}")
        print(f"  {r9_icon} 9Router AI Gateway : {Colors.CYAN}{r9_msg}{Colors.ENDC}")
        print(f"  {bot_icon} Telegram AI Bot    : {Colors.CYAN}{bot_msg}{Colors.ENDC}\n")

    return results

