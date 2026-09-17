import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite
import psutil
from dotenv import dotenv_values
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from alfa import tools
from alfa.core import database
from alfa.dashboard.common import REPO_ROOT, get_primary_user_id, logger, safe_int

router = APIRouter()

# ==================== HEALTH & STATS ENDPOINTS ====================


@router.get("/health")
async def health_check():
    """Standard health check endpoint."""
    return {
        "status": "ok",
        "service": "alfa-dashboard",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/api/system/home-dir")
async def get_home_dir():
    """Return server-side home directory so frontend path regex works for any Linux username."""
    return {
        "home_dir": os.path.expanduser("~"),
        "username": os.environ.get("USER", "unknown"),
    }


@router.get("/api/stats")
async def get_stats():
    """Live Linux system telemetry."""
    try:
        raw_stats = tools.get_system_stats()
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        battery = psutil.sensors_battery()

        uptime_secs = int(time.time() - psutil.boot_time())
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(remainder, 60)

        if os.name == "nt":

            def _svc_active(script_hint):
                for p in psutil.process_iter(["cmdline"]):
                    try:
                        cl = p.info.get("cmdline") or []
                        if any(script_hint in str(c) for c in cl):
                            return True
                    except Exception:
                        continue
                return False

            tb_active = _svc_active("bot.py")
            wa_active = _svc_active("wa_sheets")
            dash_active = _svc_active("web_dashboard.py")
        else:
            tb_res = subprocess.run(
                ["systemctl", "--user", "is-active", "telegram-ai-bot.service"],
                capture_output=True,
                text=True,
            )
            wa_res = subprocess.run(
                ["systemctl", "--user", "is-active", "wa-sheets-bot.service"],
                capture_output=True,
                text=True,
            )
            dash_res = subprocess.run(
                ["systemctl", "--user", "is-active", "alfa-dashboard.service"],
                capture_output=True,
                text=True,
            )
            tb_active = tb_res.stdout.strip() == "active"
            wa_active = wa_res.stdout.strip() == "active"
            dash_active = dash_res.stdout.strip() == "active"

        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "uptime": f"{hours}j {minutes}m {seconds}d",
            "uptime_seconds": uptime_secs,
            "cpu": {
                "percent": cpu_pct,
                "cores": cpu_count,
                "freq_mhz": round(
                    psutil.cpu_freq().current if psutil.cpu_freq() else 0, 1
                ),
            },
            "ram": {
                "percent": ram.percent,
                "used_gb": round(ram.used / (1024**3), 2),
                "total_gb": round(ram.total / (1024**3), 2),
                "free_gb": round(ram.available / (1024**3), 2),
            },
            "swap": {
                "percent": swap.percent,
                "used_mb": round(swap.used / (1024**2), 1),
                "total_mb": round(swap.total / (1024**2), 1),
            },
            "disk": {
                "percent": disk.percent,
                "used_gb": round(disk.used / (1024**3), 1),
                "total_gb": round(disk.total / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1),
            },
            "battery": {
                "percent": battery.percent if battery else 100,
                "plugged": battery.power_plugged if battery else True,
                "status": (
                    "Charging ⚡"
                    if (battery and battery.power_plugged)
                    else "Discharging 🔋"
                ),
            },
            "services": {
                "telegram_bot": tb_active,
                "wa_sheets_bot": wa_active,
                "dashboard": dash_active,
            },
            "top_ram_processes": raw_stats.get("top_ram_processes", [])[:8],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/api/system/cli-exec")
async def execute_cli_terminal_command(payload: Dict[str, Any]):
    """Execute arbitrary bash/linux terminal command directly in the host system with timing and exit codes."""
    command = (payload.get("command") or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")

    start_t = time.time()
    res = tools.execute_bash_command(command=command)
    elapsed_ms = round((time.time() - start_t) * 1000, 1)

    return {
        "status": "success",
        "result": res,
        "execution_time_ms": elapsed_ms,
        "current_dir": os.getcwd(),
    }


# ==================== SERVICES ORCHESTRATION ====================


@router.get("/api/services")
async def get_services_status():
    """Get detailed status of all ecosystem services."""
    services = [
        {
            "name": "telegram-ai-bot.service",
            "title": "ALFA Telegram AI Agent (God Mode)",
        },
        {"name": "wa-sheets-bot.service", "title": "WhatsApp Google Sheets Bot"},
        {
            "name": "alfa-dashboard.service",
            "title": "ALFA Web Command Center (Port 8080)",
        },
    ]
    results = []
    for s in services:
        svc = s["name"]
        if os.name == "nt":

            def _svc_active(hint):
                for p in psutil.process_iter(["cmdline"]):
                    try:
                        cl = p.info.get("cmdline") or []
                        if any(hint in str(c) for c in cl):
                            return True
                    except Exception:
                        continue
                return False

            hint_map = {
                "telegram-ai-bot.service": "bot.py",
                "wa-sheets-bot.service": "wa_sheets",
                "alfa-dashboard.service": "web_dashboard.py",
            }
            active = _svc_active(hint_map.get(svc, ""))
            results.append(
                {
                    "name": svc,
                    "title": s["title"],
                    "is_active": active,
                    "state": "active (process)" if active else "inactive",
                    "is_enabled": active,
                    "details": "systemd tidak tersedia di Windows; status dideteksi dari proses berjalan.",
                }
            )
            continue
        res_act = subprocess.run(
            ["systemctl", "--user", "is-active", svc], capture_output=True, text=True
        )
        res_enb = subprocess.run(
            ["systemctl", "--user", "is-enabled", svc], capture_output=True, text=True
        )
        res_stat = subprocess.run(
            ["systemctl", "--user", "status", svc, "--no-pager", "-n", "8"],
            capture_output=True,
            text=True,
        )

        results.append(
            {
                "name": svc,
                "title": s["title"],
                "is_active": res_act.stdout.strip() == "active",
                "state": res_act.stdout.strip(),
                "is_enabled": res_enb.stdout.strip() == "enabled",
                "details": res_stat.stdout.strip(),
            }
        )
    return {"status": "success", "services": results}


@router.post("/api/services/action")
async def service_action(payload: Dict[str, Any]):
    """Start, stop, or restart a systemd user service."""
    service_name = payload.get("service")
    action = payload.get("action", "status")

    if action not in ["start", "stop", "restart", "enable", "disable"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    allowed_services = [
        "telegram-ai-bot.service",
        "wa-sheets-bot.service",
        "alfa-dashboard.service",
    ]
    if service_name not in allowed_services:
        raise HTTPException(status_code=403, detail="Unauthorized service management")

    res = subprocess.run(
        ["systemctl", "--user", action, service_name], capture_output=True, text=True
    )
    time.sleep(1)
    res_act = subprocess.run(
        ["systemctl", "--user", "is-active", service_name],
        capture_output=True,
        text=True,
    )

    return {
        "status": "success" if res.returncode == 0 else "error",
        "service": service_name,
        "action": action,
        "current_state": res_act.stdout.strip(),
        "output": res.stderr or res.stdout,
    }


@router.get("/api/services/logs")
async def get_service_logs(service: str = "telegram-ai-bot.service", lines: int = 50):
    """Fetch live service logs (journalctl di Linux, file log lokal di Windows)."""
    lines = max(10, min(int(lines), 500))
    if os.name == "nt":
        log_file = (
            "bot_err.log"
            if "telegram" in service
            else ("dash_err.log" if "dashboard" in service else "wa_bot.log")
        )
        path = os.path.join(REPO_ROOT, log_file)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-lines:]
            return {
                "status": "success",
                "service": service,
                "logs": "".join(tail).strip(),
            }
        except FileNotFoundError:
            return {
                "status": "success",
                "service": service,
                "logs": f"(file log '{log_file}' belum ada)",
            }
    res = subprocess.run(
        ["journalctl", "--user", "-u", service, "-n", str(lines), "--no-pager"],
        capture_output=True,
        text=True,
    )
    return {"status": "success", "service": service, "logs": res.stdout.strip()}
