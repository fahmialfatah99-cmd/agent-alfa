"""System telemetry (CPU/RAM/disk) tool."""

import datetime
import logging
from typing import Any

import psutil

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def get_system_stats() -> dict[str, Any]:
    """
    Get real-time Linux system health metrics including CPU cores/frequencies, RAM, Swap,
    Disk usage, Network interfaces, Battery/Thermal status, Uptime, and Top Processes.
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        freq_str = f"{round(cpu_freq.current, 1)} MHz" if cpu_freq else "N/A"

        mem = psutil.virtual_memory()
        ram_total_gb = round(mem.total / (1024**3), 2)
        ram_used_gb = round(mem.used / (1024**3), 2)
        ram_free_gb = round(mem.available / (1024**3), 2)
        ram_percent = mem.percent

        swap = psutil.swap_memory()
        swap_total_gb = round(swap.total / (1024**3), 2)
        swap_used_gb = round(swap.used / (1024**3), 2)

        disk = psutil.disk_usage("/")
        disk_total_gb = round(disk.total / (1024**3), 2)
        disk_used_gb = round(disk.used / (1024**3), 2)
        disk_percent = disk.percent

        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = str(datetime.datetime.now() - boot_time).split(".")[0]

        net_addrs = psutil.net_if_addrs()
        ip_summary = []
        for iface, addrs in net_addrs.items():
            if iface.startswith("lo"):
                continue
            for a in addrs:
                if a.family.name == "AF_INET":
                    ip_summary.append(f"{iface}: {a.address}")

        battery = psutil.sensors_battery()
        battery_str = "N/A (Desktop/Server)"
        if battery:
            plugged = "🔌 Mengisi daya" if battery.power_plugged else "🔋 Baterai"
            battery_str = f"{battery.percent}% ({plugged})"

        processes = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                processes.append(p.info)
            except Exception:
                pass

        top_ram = sorted(
            processes, key=lambda p: p.get("memory_percent") or 0, reverse=True
        )[:4]
        top_cpu = sorted(
            processes, key=lambda p: p.get("cpu_percent") or 0, reverse=True
        )[:4]

        return {
            "status": "success",
            "cpu": f"{cpu_percent}% ({cpu_count} cores @ {freq_str})",
            "ram": f"{ram_used_gb} GB / {ram_total_gb} GB ({ram_percent}%, free: {ram_free_gb} GB)",
            "swap": f"{swap_used_gb} GB / {swap_total_gb} GB",
            "disk": f"{disk_used_gb} GB / {disk_total_gb} GB ({disk_percent}%)",
            "battery": battery_str,
            "ip_addresses": ", ".join(ip_summary) or "127.0.0.1",
            "uptime": uptime,
            "top_ram_processes": [
                f"{p['name']} (PID {p['pid']}: {round(p['memory_percent'] or 0, 1)}% RAM)"
                for p in top_ram
            ],
            "top_cpu_processes": [
                f"{p['name']} (PID {p['pid']}: {round(p['cpu_percent'] or 0, 1)}% CPU)"
                for p in top_cpu
                if (p.get("cpu_percent") or 0) > 0
            ],
        }
    except Exception as e:
        logger.error(f"Error in get_system_stats: {e}")
        return {"status": "error", "message": str(e)}
