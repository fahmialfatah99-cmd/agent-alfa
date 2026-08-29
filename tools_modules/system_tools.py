"""System & Infrastructure Tools for ALFA Agent."""

import datetime
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


def get_system_stats() -> Dict[str, Any]:
    """
    Get real-time Linux system health metrics including CPU cores/frequencies, RAM, Swap,
    Disk usage, Network interfaces, Battery/Thermal status, Uptime, and Top Processes.
    Use this tool when the user asks about laptop/server specs, resource usage, or performance.
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        freq_str = f"{round(cpu_freq.current, 1)} MHz" if cpu_freq else "N/A"

        mem = psutil.virtual_memory()
        ram_total_gb = round(mem.total / (1024 ** 3), 2)
        ram_used_gb = round(mem.used / (1024 ** 3), 2)
        ram_free_gb = round(mem.available / (1024 ** 3), 2)
        ram_percent = mem.percent

        swap = psutil.swap_memory()
        swap_total_gb = round(swap.total / (1024 ** 3), 2)
        swap_used_gb = round(swap.used / (1024 ** 3), 2)

        disk = psutil.disk_usage('/')
        disk_total_gb = round(disk.total / (1024 ** 3), 2)
        disk_used_gb = round(disk.used / (1024 ** 3), 2)
        disk_percent = disk.percent

        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = str(datetime.datetime.now() - boot_time).split('.')[0]

        # Network stats
        net_addrs = psutil.net_if_addrs()
        ip_summary = []
        for iface, addrs in net_addrs.items():
            if iface.startswith("lo"):
                continue
            for a in addrs:
                if a.family.name == "AF_INET":
                    ip_summary.append(f"{iface}: {a.address}")

        # Battery stats if available
        battery = psutil.sensors_battery()
        battery_str = "N/A (Desktop/Server)"
        if battery:
            plugged = "🔌 Mengisi daya" if battery.power_plugged else "🔋 Baterai"
            battery_str = f"{battery.percent}% ({plugged})"

        # Top processes by RAM and CPU
        processes = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(p.info)
            except Exception:
                pass

        top_ram = sorted(processes, key=lambda p: p.get('memory_percent') or 0, reverse=True)[:4]
        top_cpu = sorted(processes, key=lambda p: p.get('cpu_percent') or 0, reverse=True)[:4]

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
                for p in top_cpu if (p.get('cpu_percent') or 0) > 0
            ]
        }
    except Exception as e:
        logger.error(f"Error in get_system_stats: {e}")
        return {"status": "error", "message": str(e)}


_BASH_BLOCK_PATTERNS = [
    # (regex, alasan) — dicocokkan terhadap perintah mentah
    (r":\s*\(\s*\)\s*\{.*\}\s*;", "fork bomb"),
    (r"\bdd\s+[^\n]*of=/dev/(sd|hd|vd|nvme|mmcblk)", "tulis mentah ke disk fisik"),
    (r"\bmkfs(\.\w+)?\b", "format filesystem"),
    (r"chmod\s+-R\s+777\s+/", "chmod 777 rekursif pada root"),
    (r"chown\s+-R\b[^\n]*(\s/|\s~|\s\$HOME)(\s|$)", "chown rekursif pada root/home"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "mematikan/menyalakan ulang sistem"),
    (r"(history\s+-c\b|>\s*~/\.bash_history|shred\s+[^;\n]*history|unset\s+HISTFILE)",
     "menghapus jejak riwayat shell"),
    (r"(curl|wget|fetch)[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe skrip internet langsung ke shell"),
    (r"base64\s+[^;\n|&]*(?:-d\b|--decode)[^;\n|&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
     "pipe payload base64 ke shell"),
    (r"/(dev/tcp/|proc/sysrq-trigger)", "teknik reverse-shell/kernel trigger"),
    (r"\.(ssh/id_(rsa|ed25519|ecdsa)|aws/credentials|gnupg)", "akses berkas kredensial privat"),
    (r"\b(useradd|userdel|usermod|visudo)\b", "manipulasi akun pengguna sistem"),
    (r"(iptables|nft)\s+(-F|--flush)", "flush firewall"),
    (r">\s*/dev/(sd|hd|vd|nvme)", "overwrite perangkat blok"),
]

# Target penghapusan yang dianggap destruktif saat dipadukan dgn rm rekursif
_RM_DANGER_TARGETS = (
    r"(?:(?:/{1, 2})|(?:~)|(?:\$HOME)|\*|(?:/(?:home|etc|usr|var|boot|lib|opt|bin|sbin|srv|root))"
    r"|(?:\.\./)+(?:home|etc|usr))?(?:\s|$|/)"
)


def _bash_blocked_reason(command: str) -> Optional[str]:
    """Kembalikan alasan pemblokiran bila perintah cocok pola berbahaya."""
    for pattern, reason in _BASH_BLOCK_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def execute_bash_command(command: str, working_dir: str = "", backend: str = "") -> Dict[str, Any]:
    """Execute a bash command with security checks."""
    # Check for blocked commands
    blocked = _bash_blocked_reason(command)
    if blocked:
        return {
            "status": "blocked",
            "message": f"Command blocked: {blocked}",
            "command": command
        }
    
    try:
        cwd = working_dir if working_dir else os.getcwd()
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=cwd
        )
        
        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command timed out"}
    except Exception as e:
        logger.error(f"Bash command error: {e}")
        return {"status": "error", "message": str(e)}


def execute_python_sandbox(code: str) -> Dict[str, Any]:
    """Execute Python code in a sandboxed environment."""
    try:
        # Create a restricted environment
        restricted_globals = {"__builtins__": {}}
        
        # Execute code with timeout
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Code execution timed out")
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)  # 30 second timeout
        
        try:
            # Capture output
            import io
            import sys
            
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            
            exec(code, restricted_globals)
            
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
            signal.alarm(0)  # Cancel alarm
            
            return {
                "status": "success",
                "output": output
            }
        except TimeoutError:
            signal.alarm(0)
            return {"status": "error", "message": "Code execution timed out"}
        except Exception as e:
            signal.alarm(0)
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Python sandbox error: {e}")
        return {"status": "error", "message": str(e)}
