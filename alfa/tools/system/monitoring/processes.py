"""Process listing and termination tools."""

import logging
from typing import Any

import psutil

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def list_running_processes(filter_name: str = "") -> dict[str, Any]:
    """
    List currently running processes on the system, sorted by memory usage.
    """
    try:
        procs = []
        for p in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_info", "status", "username"]
        ):
            try:
                info = p.info
                mem_mb = (
                    round(info["memory_info"].rss / (1024 * 1024), 1)
                    if info.get("memory_info")
                    else 0
                )
                if (
                    filter_name
                    and filter_name.lower() not in (info.get("name") or "").lower()
                ):
                    continue
                procs.append(
                    {
                        "pid": info["pid"],
                        "name": info["name"],
                        "cpu_percent": info.get("cpu_percent", 0),
                        "memory_mb": mem_mb,
                        "status": info.get("status", ""),
                        "user": info.get("username", ""),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        top = procs[:30]
        total_mem = sum(p["memory_mb"] for p in procs)

        return {
            "status": "success",
            "total_processes": len(procs),
            "total_memory_mb": round(total_mem, 1),
            "top_processes": top,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def kill_process(pid_or_name: str) -> dict[str, Any]:
    """
    Terminate/kill a running process by PID number or process name.
    """
    try:
        killed = []
        if pid_or_name.isdigit():
            pid = int(pid_or_name)
            p = psutil.Process(pid)
            name = p.name()
            p.terminate()
            killed.append(f"PID {pid} ({name})")
        else:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if pid_or_name.lower() in p.info["name"].lower():
                        p.terminate()
                        killed.append(f"PID {p.info['pid']} ({p.info['name']})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if killed:
            return {
                "status": "success",
                "message": f"Proses berhasil dihentikan: {', '.join(killed)}",
            }
        return {
            "status": "error",
            "message": f"Proses '{pid_or_name}' tidak ditemukan.",
        }
    except psutil.NoSuchProcess:
        return {
            "status": "error",
            "message": f"Proses dengan PID/nama '{pid_or_name}' tidak ditemukan.",
        }
    except psutil.AccessDenied:
        return {
            "status": "error",
            "message": "Akses ditolak. Coba jalankan dengan sudo.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
