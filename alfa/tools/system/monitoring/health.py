"""Self-diagnostics and healing tool."""

import logging
import subprocess
from typing import Any

import psutil

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")

@register_tool(category="system")
def auto_diagnose_and_heal_system(fix_issues: bool = False) -> dict[str, Any]:
    """
    GOD MODE: Autonomous System Diagnostic & Self-Healing Engine.
    """
    try:
        diagnosis: dict[str, Any] = {}
        healing_actions: list[str] = []

        res_failed = subprocess.run(
            "systemctl --user list-units --failed --no-legend 2>/dev/null",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        failed_user_units = [
            line.strip().split()[0]
            for line in res_failed.stdout.strip().splitlines()
            if line.strip()
        ]
        diagnosis["failed_user_services"] = failed_user_units

        res_journal = subprocess.run(
            "journalctl --user -p 3 -n 15 --no-pager 2>/dev/null",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        diagnosis["recent_critical_logs"] = (
            res_journal.stdout.strip()[:1500]
            if res_journal.stdout.strip()
            else "Tidak ada critical error log terbaru."
        )

        zombies = []
        for p in psutil.process_iter(["pid", "name", "status"]):
            try:
                if p.info["status"] == psutil.STATUS_ZOMBIE:
                    zombies.append(f"PID {p.info['pid']} ({p.info['name']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        diagnosis["zombie_processes"] = zombies

        disk = psutil.disk_usage("/")
        swap = psutil.swap_memory()
        diagnosis["disk_health"] = (
            f"Root: {disk.percent}% used ({round(disk.free / (1024**3), 1)} GB free)"
        )
        diagnosis["swap_health"] = f"Swap: {swap.percent}% used"

        if fix_issues:
            for unit in failed_user_units:
                if "telegram-ai-bot" not in unit:
                    subprocess.run(
                        f"systemctl --user reset-failed {unit} && systemctl --user restart {unit}",
                        shell=True,  # nosec B602 - unit names from systemctl output, telegram-ai-bot excluded
                        timeout=10,
                    )
                    healing_actions.append(f"Restarted failed unit: {unit}")

            if disk.percent > 85:
                subprocess.run(
                    "journalctl --user --vacuum-time=2d", shell=True, timeout=10
                )
                healing_actions.append("Cleaned old user journal logs")

            diagnosis["healing_executed"] = (
                healing_actions
                if healing_actions
                else "Tidak ada tindakan perbaikan yang diperlukan saat ini."
            )

        return {"status": "success", "diagnosis": diagnosis, "fix_mode": fix_issues}
    except Exception as e:
        return {"status": "error", "message": f"Diagnostic error: {str(e)}"}
