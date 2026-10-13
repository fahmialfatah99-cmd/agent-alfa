"""Proactive guardian/ambient-agent configuration tools."""

import datetime
import json
import logging
import os
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def proactive_system_guardian_config(
    action: str = "status",
    cpu_threshold: int = 90,
    ram_threshold: int = 85,
    disk_threshold: int = 90,
    battery_critical: int = 10,
    auto_kill_ram_hogs: bool = False,
) -> dict[str, Any]:
    """
    GOD MODE: Configure the Proactive System Guardian daemon.
    """
    try:
        config_path = os.path.join(
            os.path.expanduser("~"), ".alfa", "guardian_config.json"
        )
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        if action == "status":
            if os.path.exists(config_path):
                with open(config_path) as f:
                    config = json.load(f)
                return {"status": "success", "guardian": config}
            return {
                "status": "success",
                "guardian": {
                    "enabled": False,
                    "message": "Guardian belum dikonfigurasi.",
                },
            }

        elif action == "enable":
            config = {
                "enabled": True,
                "cpu_threshold": cpu_threshold,
                "ram_threshold": ram_threshold,
                "disk_threshold": disk_threshold,
                "battery_critical": battery_critical,
                "auto_kill_ram_hogs": auto_kill_ram_hogs,
                "updated_at": datetime.datetime.now().isoformat(),
            }
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": f"🛡️ System Guardian AKTIF! Monitoring: CPU>{cpu_threshold}%, RAM>{ram_threshold}%, Disk>{disk_threshold}%, Battery<{battery_critical}%. Auto-kill: {'ON' if auto_kill_ram_hogs else 'OFF'}.",
            }

        elif action == "disable":
            config = {
                "enabled": False,
                "updated_at": datetime.datetime.now().isoformat(),
            }
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {"status": "success", "message": "🛡️ System Guardian dinonaktifkan."}

        return {
            "status": "error",
            "message": f"Action '{action}' tidak dikenal. Gunakan: status, enable, disable.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def proactive_ambient_agent_config(
    action: str = "status",
    enabled: bool = True,
    min_hours_between_pings: int = 3,
    quiet_hours_start: int = 23,
    quiet_hours_end: int = 7,
) -> dict[str, Any]:
    """
    GOD MODE: Configure Ambient Proactive Autonomous Engagement.
    """
    try:
        config_path = os.path.join(
            os.path.expanduser("~"), ".alfa", "proactive_config.json"
        )
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        if action == "status":
            if os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                return {"status": "success", "proactive_config": config}
            return {
                "status": "success",
                "proactive_config": {
                    "enabled": True,
                    "min_hours_between_pings": 3,
                    "quiet_hours_start": 23,
                    "quiet_hours_end": 7,
                    "message": "Mode Proaktif default aktif.",
                },
            }

        elif action in ["enable", "set"]:
            config = {
                "enabled": True,
                "min_hours_between_pings": max(1, min_hours_between_pings),
                "quiet_hours_start": quiet_hours_start,
                "quiet_hours_end": quiet_hours_end,
                "updated_at": datetime.datetime.now().isoformat(),
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": f"🤖 Mode Proaktif Otonom AKTIF! Bot akan berinisiatif menyapa/mengecek kondisi setiap ~{min_hours_between_pings} jam di luar jam tenang ({quiet_hours_start}:00 - {quiet_hours_end}:00).",
            }

        elif action == "disable":
            config = {
                "enabled": False,
                "updated_at": datetime.datetime.now().isoformat(),
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": "🤖 Mode Proaktif Otonom dinonaktifkan.",
            }

        return {
            "status": "error",
            "message": f"Action '{action}' tidak dikenal. Gunakan: status, enable, disable.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Proactive config error: {str(e)}"}
