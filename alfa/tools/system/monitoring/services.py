"""System services, cron, and restart tools."""

import logging
import os
import subprocess
import sys
from typing import Any

import psutil

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def manage_system_services(
    service_name: str, action: str = "status", scope: str = "user"
) -> dict[str, Any]:
    """
    GOD MODE: Linux Systemd Services Controller.
    """
    try:
        act = action.strip().lower()
        if os.name == "nt":
            svc_map = {
                "telegram-ai-bot.service": ("ALFA Telegram Bot", "bot.py"),
                "alfa-dashboard.service": ("ALFA Dashboard", "web_dashboard.py"),
                "wa-sheets-bot.service": ("WA Sheets Bot", "wa_sheets_bot"),
            }
            name, hint = svc_map.get(service_name, (service_name, service_name))
            running = False
            for p in psutil.process_iter(["cmdline"]):
                try:
                    cl = p.info.get("cmdline") or []
                    if any(hint in str(c) for c in cl):
                        running = True
                        break
                except Exception:
                    continue
            if act in ("status", "is-active"):
                return {
                    "status": "success",
                    "service": service_name,
                    "action": "status",
                    "scope": scope,
                    "exit_code": 0,
                    "output": f"{name}: {'RUNNING (proses terdeteksi)' if running else 'STOPPED'} (Windows: systemd tidak tersedia)",
                }
            return {
                "status": "error",
                "service": service_name,
                "action": act,
                "message": f"Aksi '{act}' untuk '{name}' tidak didukung di Windows.",
            }

        flag = "--user" if scope == "user" else ""
        valid_actions = [
            "status",
            "restart",
            "start",
            "stop",
            "enable",
            "disable",
            "is-active",
        ]
        if act not in valid_actions:
            return {
                "status": "error",
                "message": f"Aksi '{action}' tidak valid. Pilihan: {', '.join(valid_actions)}",
            }
        import re as _re

        if not _re.fullmatch(r"[A-Za-z0-9_.@:\-]+", service_name or ""):
            return {
                "status": "error",
                "message": f"Nama service '{service_name}' tidak valid.",
            }

        cmd = f"systemctl {flag} {act} {service_name}"  # nosec B602 - act allowlisted, service_name charset-validated above
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,  # nosec B602 - act allowlisted, service_name charset-validated above
        )
        output = (res.stdout.strip() or res.stderr.strip())[:2500]

        return {
            "status": "success" if res.returncode == 0 or act == "status" else "error",
            "service": service_name,
            "action": act,
            "scope": scope,
            "exit_code": res.returncode,
            "output": output,
        }
    except Exception as e:
        return {"status": "error", "message": f"Systemd control error: {str(e)}"}


@register_tool(category="system")
def manage_crontab_jobs(
    action: str = "list", cron_line: str = "", search_pattern: str = ""
) -> dict[str, Any]:
    """
    GOD MODE: Real Linux OS Crontab Manager.
    """
    try:
        if os.name == "nt":
            return {"status": "error", "message": "Crontab hanya tersedia di Linux."}
        if action == "list":
            res = subprocess.run(
                "crontab -l 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            entries = res.stdout.strip()
            return {
                "status": "success",
                "crontab_entries": entries if entries else "(Crontab kosong)",
            }
        elif action == "add":
            if not cron_line:
                return {
                    "status": "error",
                    "message": "Parameter cron_line harus diisi.",
                }
            res_curr = subprocess.run(
                "crontab -l 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            curr = res_curr.stdout.strip()
            new_cron = (curr + "\n" + cron_line.strip()).strip() + "\n"
            proc = subprocess.Popen(
                "crontab -", shell=True, stdin=subprocess.PIPE, text=True
            )
            proc.communicate(input=new_cron, timeout=5)
            return {
                "status": "success",
                "message": f"Entri crontab berhasil ditambahkan: '{cron_line}'",
            }
        elif action == "remove":
            if not search_pattern:
                return {
                    "status": "error",
                    "message": "Parameter search_pattern harus diisi untuk menghapus entri crontab.",
                }
            res_curr = subprocess.run(
                "crontab -l 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [
                ln for ln in res_curr.stdout.splitlines() if search_pattern not in ln
            ]
            new_cron = "\n".join(lines).strip() + "\n"
            proc = subprocess.Popen(
                "crontab -", shell=True, stdin=subprocess.PIPE, text=True
            )
            proc.communicate(input=new_cron, timeout=5)
            return {
                "status": "success",
                "message": f"Entri crontab yang cocok dengan pola '{search_pattern}' berhasil dihapus.",
            }
        return {
            "status": "error",
            "message": f"Aksi '{action}' tidak dikenal. Gunakan: list, add, remove.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Crontab error: {str(e)}"}


@register_tool(category="system")
def self_restart_service() -> dict[str, Any]:
    """
    GOD MODE: Self-Restart the bot service to apply code changes.
    """
    try:
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        tools_path = os.path.join(repo_root, "tools.py")
        compile_check = subprocess.run(
            [sys.executable, "-m", "py_compile", tools_path],
            capture_output=True,
            text=True,
        )
        if compile_check.returncode != 0:
            return {
                "status": "error",
                "message": f"Tidak bisa restart — tools.py memiliki error: {compile_check.stderr}",
            }

        bot_path = os.path.join(repo_root, "bot.py")
        compile_check2 = subprocess.run(
            [sys.executable, "-m", "py_compile", bot_path],
            capture_output=True,
            text=True,
        )
        if compile_check2.returncode != 0:
            return {
                "status": "error",
                "message": f"Tidak bisa restart — bot.py memiliki error: {compile_check2.stderr}",
            }

        subprocess.Popen(
            "sleep 2 && systemctl --user restart telegram-ai-bot.service",
            shell=True,
            start_new_session=True,
        )

        return {
            "status": "success",
            "message": "🔄 Bot akan restart dalam 2 detik... Semua pembaruan dan tool baru akan aktif setelah restart. Bot akan kembali online dalam ~3 detik.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
