"""System monitoring, process management, diagnostics, and hardware control tools."""

import datetime
import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional
import psutil

from alfa.tools.registry import register_tool
from alfa.tools.system.constants import SANDBOX_DIR

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def get_system_stats() -> Dict[str, Any]:
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


@register_tool(category="system")
def control_linux_hardware(action: str, value: str = "") -> Dict[str, Any]:
    """
    Control Linux laptop/server hardware, audio, screen lock, power, Wi-Fi, and media from Telegram.
    """
    try:
        act = action.strip().lower()
        if act == "lock_screen":
            subprocess.run("loginctl lock-session 2>/dev/null || gnome-screensaver-command -l", shell=True, capture_output=True, text=True)
            return {"status": "success", "message": "🔒 Layar desktop Linux telah berhasil dikunci."}

        elif act == "set_volume":
            vol_val = value.replace("%", "").strip() or "50"
            try:
                frac = float(vol_val) / 100.0
                subprocess.run(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {frac}", shell=True, capture_output=True, timeout=3)
            except Exception:
                subprocess.run(f"amixer set Master {vol_val}%", shell=True, capture_output=True, timeout=3)
            return {"status": "success", "message": f"🔊 Volume speaker berhasil diubah ke {vol_val}%."}

        elif act == "mute_toggle":
            subprocess.run("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle || amixer set Master toggle", shell=True, capture_output=True, timeout=3)
            return {"status": "success", "message": "🔇 Status mute audio berhasil dialihkan (toggle)."}

        elif act in ["media_play_pause", "media_next", "media_prev"]:
            cmd = "playerctl play-pause" if act == "media_play_pause" else "playerctl next" if act == "media_next" else "playerctl previous"
            subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
            return {"status": "success", "message": f"🎵 Perintah media '{act}' berhasil dieksekusi."}

        elif act == "wifi_scan":
            res = subprocess.run("nmcli -f SSID,SIGNAL,SECURITY dev wifi list | head -n 12", shell=True, capture_output=True, text=True, timeout=8)
            return {"status": "success", "wifi_networks": res.stdout.strip() or "Tidak ada jaringan Wi-Fi ditemukan."}

        elif act == "bluetooth_status":
            res = subprocess.run("bluetoothctl show 2>/dev/null | grep -E 'Name|Powered|Discoverable'; bluetoothctl devices 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            return {"status": "success", "bluetooth": res.stdout.strip() or "Bluetooth tidak aktif."}

        elif act == "battery_status":
            bat = psutil.sensors_battery()
            if not bat:
                return {"status": "success", "battery": "Perangkat tidak menggunakan baterai (Desktop PC / Server)."}
            plugged = "🔌 Sedang Mengisi Daya (Charging)" if bat.power_plugged else "🔋 Berjalan dengan Baterai (Discharging)"
            time_left = f"{round(bat.secsleft / 60)} menit" if bat.secsleft > 0 else "N/A"
            return {
                "status": "success",
                "percentage": f"{bat.percent}%",
                "power_state": plugged,
                "estimated_time_remaining": time_left
            }

        return {"status": "error", "message": f"Aksi hardware '{action}' tidak dikenal."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def list_running_processes(filter_name: str = "") -> Dict[str, Any]:
    """
    List currently running processes on the system, sorted by memory usage.
    """
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status', 'username']):
            try:
                info = p.info
                mem_mb = round(info['memory_info'].rss / (1024 * 1024), 1) if info.get('memory_info') else 0
                if filter_name and filter_name.lower() not in (info.get('name') or '').lower():
                    continue
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "cpu_percent": info.get('cpu_percent', 0),
                    "memory_mb": mem_mb,
                    "status": info.get('status', ''),
                    "user": info.get('username', '')
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x['memory_mb'], reverse=True)
        top = procs[:30]
        total_mem = sum(p['memory_mb'] for p in procs)

        return {
            "status": "success",
            "total_processes": len(procs),
            "total_memory_mb": round(total_mem, 1),
            "top_processes": top
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def kill_process(pid_or_name: str) -> Dict[str, Any]:
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
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if pid_or_name.lower() in p.info['name'].lower():
                        p.terminate()
                        killed.append(f"PID {p.info['pid']} ({p.info['name']})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if killed:
            return {"status": "success", "message": f"Proses berhasil dihentikan: {', '.join(killed)}"}
        return {"status": "error", "message": f"Proses '{pid_or_name}' tidak ditemukan."}
    except psutil.NoSuchProcess:
        return {"status": "error", "message": f"Proses dengan PID/nama '{pid_or_name}' tidak ditemukan."}
    except psutil.AccessDenied:
        return {"status": "error", "message": "Akses ditolak. Coba jalankan dengan sudo."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def clean_system_storage(dry_run: bool = True) -> Dict[str, Any]:
    """
    GOD MODE: Smart Linux Storage Cleaner & Optimizer.
    """
    try:
        cleanup_targets = [
            ("Thumbnail Cache", os.path.expanduser("~/.cache/thumbnails")),
            ("Sandbox Temp Files", SANDBOX_DIR),
            ("Python Cache", os.path.expanduser("~/.cache/pip"))
        ]

        report = []
        total_freed_mb = 0.0

        for name, path in cleanup_targets:
            if os.path.exists(path):
                size_b = sum(os.path.getsize(os.path.join(dirpath, f)) for dirpath, _, filenames in os.walk(path) for f in filenames if not os.path.islink(os.path.join(dirpath, f)))
                size_mb = round(size_b / (1024*1024), 2)
                report.append({"target": name, "path": path, "size_mb": size_mb})
                total_freed_mb += size_mb

                if not dry_run and size_mb > 0:
                    subprocess.run(f'rm -rf "{path}"/*', shell=True, timeout=10)

        if not dry_run:
            subprocess.run("journalctl --user --vacuum-time=2d 2>/dev/null", shell=True, timeout=10)

        action_msg = "ANALISIS (Dry Run)" if dry_run else "PEMBERSIHAN SELESAI"
        return {
            "status": "success",
            "mode": action_msg,
            "total_space_mb": round(total_freed_mb, 2),
            "details": report,
            "message": f"{action_msg}: Potensi ruang dibersihkan: {round(total_freed_mb, 2)} MB. Jalankan dengan dry_run=False untuk eksekusi pembersihan nyata." if dry_run else f"Pembersihan berhasil! {round(total_freed_mb, 2)} MB ruang disk berhasil dikembalikan."
        }
    except Exception as e:
        return {"status": "error", "message": f"Storage cleanup error: {str(e)}"}


@register_tool(category="system")
def manage_system_services(service_name: str, action: str = "status", scope: str = "user") -> Dict[str, Any]:
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
            for p in psutil.process_iter(['cmdline']):
                try:
                    cl = p.info.get('cmdline') or []
                    if any(hint in str(c) for c in cl):
                        running = True
                        break
                except Exception:
                    continue
            if act in ("status", "is-active"):
                return {"status": "success", "service": service_name, "action": "status",
                        "scope": scope, "exit_code": 0,
                        "output": f"{name}: {'RUNNING (proses terdeteksi)' if running else 'STOPPED'} (Windows: systemd tidak tersedia)"}
            return {"status": "error", "service": service_name, "action": act,
                    "message": f"Aksi '{act}' untuk '{name}' tidak didukung di Windows."}

        flag = "--user" if scope == "user" else ""
        valid_actions = ["status", "restart", "start", "stop", "enable", "disable", "is-active"]
        if act not in valid_actions:
            return {"status": "error", "message": f"Aksi '{action}' tidak valid. Pilihan: {', '.join(valid_actions)}"}

        cmd = f"systemctl {flag} {act} {service_name}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        output = (res.stdout.strip() or res.stderr.strip())[:2500]

        return {
            "status": "success" if res.returncode == 0 or act == "status" else "error",
            "service": service_name,
            "action": act,
            "scope": scope,
            "exit_code": res.returncode,
            "output": output
        }
    except Exception as e:
        return {"status": "error", "message": f"Systemd control error: {str(e)}"}


@register_tool(category="system")
def manage_crontab_jobs(action: str = "list", cron_line: str = "", search_pattern: str = "") -> Dict[str, Any]:
    """
    GOD MODE: Real Linux OS Crontab Manager.
    """
    try:
        if os.name == "nt":
            return {"status": "error", "message": "Crontab hanya tersedia di Linux."}
        if action == "list":
            res = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            entries = res.stdout.strip()
            return {"status": "success", "crontab_entries": entries if entries else "(Crontab kosong)"}
        elif action == "add":
            if not cron_line:
                return {"status": "error", "message": "Parameter cron_line harus diisi."}
            res_curr = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            curr = res_curr.stdout.strip()
            new_cron = (curr + "\n" + cron_line.strip()).strip() + "\n"
            proc = subprocess.Popen("crontab -", shell=True, stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_cron, timeout=5)
            return {"status": "success", "message": f"Entri crontab berhasil ditambahkan: '{cron_line}'"}
        elif action == "remove":
            if not search_pattern:
                return {"status": "error", "message": "Parameter search_pattern harus diisi untuk menghapus entri crontab."}
            res_curr = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            lines = [ln for ln in res_curr.stdout.splitlines() if search_pattern not in ln]
            new_cron = "\n".join(lines).strip() + "\n"
            proc = subprocess.Popen("crontab -", shell=True, stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_cron, timeout=5)
            return {"status": "success", "message": f"Entri crontab yang cocok dengan pola '{search_pattern}' berhasil dihapus."}
        return {"status": "error", "message": f"Aksi '{action}' tidak dikenal. Gunakan: list, add, remove."}
    except Exception as e:
        return {"status": "error", "message": f"Crontab error: {str(e)}"}


@register_tool(category="system")
def auto_diagnose_and_heal_system(fix_issues: bool = False) -> Dict[str, Any]:
    """
    GOD MODE: Autonomous System Diagnostic & Self-Healing Engine.
    """
    try:
        diagnosis = {}
        healing_actions = []

        res_failed = subprocess.run("systemctl --user list-units --failed --no-legend 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
        failed_user_units = [line.strip().split()[0] for line in res_failed.stdout.strip().splitlines() if line.strip()]
        diagnosis["failed_user_services"] = failed_user_units

        res_journal = subprocess.run("journalctl --user -p 3 -n 15 --no-pager 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
        diagnosis["recent_critical_logs"] = res_journal.stdout.strip()[:1500] if res_journal.stdout.strip() else "Tidak ada critical error log terbaru."

        zombies = []
        for p in psutil.process_iter(['pid', 'name', 'status']):
            try:
                if p.info['status'] == psutil.STATUS_ZOMBIE:
                    zombies.append(f"PID {p.info['pid']} ({p.info['name']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        diagnosis["zombie_processes"] = zombies

        disk = psutil.disk_usage('/')
        swap = psutil.swap_memory()
        diagnosis["disk_health"] = f"Root: {disk.percent}% used ({round(disk.free / (1024**3), 1)} GB free)"
        diagnosis["swap_health"] = f"Swap: {swap.percent}% used"

        if fix_issues:
            for unit in failed_user_units:
                if "telegram-ai-bot" not in unit:
                    subprocess.run(f"systemctl --user reset-failed {unit} && systemctl --user restart {unit}", shell=True, timeout=10)
                    healing_actions.append(f"Restarted failed unit: {unit}")

            if disk.percent > 85:
                subprocess.run("journalctl --user --vacuum-time=2d", shell=True, timeout=10)
                healing_actions.append("Cleaned old user journal logs")

            diagnosis["healing_executed"] = healing_actions if healing_actions else "Tidak ada tindakan perbaikan yang diperlukan saat ini."

        return {
            "status": "success",
            "diagnosis": diagnosis,
            "fix_mode": fix_issues
        }
    except Exception as e:
        return {"status": "error", "message": f"Diagnostic error: {str(e)}"}


@register_tool(category="system")
def self_restart_service() -> Dict[str, Any]:
    """
    GOD MODE: Self-Restart the bot service to apply code changes.
    """
    try:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        tools_path = os.path.join(repo_root, "tools.py")
        compile_check = subprocess.run(
            [sys.executable, "-m", "py_compile", tools_path],
            capture_output=True, text=True
        )
        if compile_check.returncode != 0:
            return {"status": "error", "message": f"Tidak bisa restart — tools.py memiliki error: {compile_check.stderr}"}

        bot_path = os.path.join(repo_root, "bot.py")
        compile_check2 = subprocess.run(
            [sys.executable, "-m", "py_compile", bot_path],
            capture_output=True, text=True
        )
        if compile_check2.returncode != 0:
            return {"status": "error", "message": f"Tidak bisa restart — bot.py memiliki error: {compile_check2.stderr}"}

        subprocess.Popen(
            "sleep 2 && systemctl --user restart telegram-ai-bot.service",
            shell=True, start_new_session=True
        )

        return {
            "status": "success",
            "message": "🔄 Bot akan restart dalam 2 detik... Semua pembaruan dan tool baru akan aktif setelah restart. Bot akan kembali online dalam ~3 detik."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def proactive_system_guardian_config(action: str = "status", cpu_threshold: int = 90, ram_threshold: int = 85, disk_threshold: int = 90, battery_critical: int = 10, auto_kill_ram_hogs: bool = False) -> Dict[str, Any]:
    """
    GOD MODE: Configure the Proactive System Guardian daemon.
    """
    try:
        config_path = os.path.join(os.path.expanduser("~"), ".alfa", "guardian_config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        if action == "status":
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                return {"status": "success", "guardian": config}
            return {"status": "success", "guardian": {"enabled": False, "message": "Guardian belum dikonfigurasi."}}

        elif action == "enable":
            config = {
                "enabled": True,
                "cpu_threshold": cpu_threshold,
                "ram_threshold": ram_threshold,
                "disk_threshold": disk_threshold,
                "battery_critical": battery_critical,
                "auto_kill_ram_hogs": auto_kill_ram_hogs,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": f"🛡️ System Guardian AKTIF! Monitoring: CPU>{cpu_threshold}%, RAM>{ram_threshold}%, Disk>{disk_threshold}%, Battery<{battery_critical}%. Auto-kill: {'ON' if auto_kill_ram_hogs else 'OFF'}."
            }

        elif action == "disable":
            config = {"enabled": False, "updated_at": datetime.datetime.now().isoformat()}
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {"status": "success", "message": "🛡️ System Guardian dinonaktifkan."}

        return {"status": "error", "message": f"Action '{action}' tidak dikenal. Gunakan: status, enable, disable."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def proactive_ambient_agent_config(action: str = "status", enabled: bool = True, min_hours_between_pings: int = 3, quiet_hours_start: int = 23, quiet_hours_end: int = 7) -> Dict[str, Any]:
    """
    GOD MODE: Configure Ambient Proactive Autonomous Engagement.
    """
    try:
        config_path = os.path.join(os.path.expanduser("~"), ".alfa", "proactive_config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        if action == "status":
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                return {"status": "success", "proactive_config": config}
            return {
                "status": "success",
                "proactive_config": {
                    "enabled": True,
                    "min_hours_between_pings": 3,
                    "quiet_hours_start": 23,
                    "quiet_hours_end": 7,
                    "message": "Mode Proaktif default aktif."
                }
            }

        elif action in ["enable", "set"]:
            config = {
                "enabled": True,
                "min_hours_between_pings": max(1, min_hours_between_pings),
                "quiet_hours_start": quiet_hours_start,
                "quiet_hours_end": quiet_hours_end,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": f"🤖 Mode Proaktif Otonom AKTIF! Bot akan berinisiatif menyapa/mengecek kondisi setiap ~{min_hours_between_pings} jam di luar jam tenang ({quiet_hours_start}:00 - {quiet_hours_end}:00)."
            }

        elif action == "disable":
            config = {
                "enabled": False,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return {"status": "success", "message": "🤖 Mode Proaktif Otonom dinonaktifkan."}

        return {"status": "error", "message": f"Action '{action}' tidak dikenal. Gunakan: status, enable, disable."}
    except Exception as e:
        return {"status": "error", "message": f"Proactive config error: {str(e)}"}
