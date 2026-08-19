"""
Ultra-Advanced Agent Tools Module for Telegram AI Bot.
Provides deep system monitoring, bash command execution, Python code sandbox & plotter,
live web search, web page content extraction, file & workspace intelligence,
persistent isolated long-term memory, proactive reminders, and desktop/webcam vision.
"""

import os
import sys
import subprocess
import psutil
import datetime
import logging
import re
import glob
from contextvars import ContextVar
from typing import Dict, Any, List, Optional

import database
from ddgs import DDGS

logger = logging.getLogger("AgentTools")

# Context Variables for Multi-user Dynamic Context Isolation
current_user_id_var: ContextVar[int] = ContextVar("current_user_id", default=0)
current_chat_id_var: ContextVar[int] = ContextVar("current_chat_id", default=0)

SANDBOX_DIR = "/dev/shm/alfa_sandbox"
os.makedirs(SANDBOX_DIR, exist_ok=True)


def get_current_user_id() -> int:
    """Get active Telegram User ID for the current agent turn."""
    uid = current_user_id_var.get()
    return uid if uid else 0


def get_current_chat_id() -> int:
    """Get active Telegram Chat ID for the current agent turn."""
    cid = current_chat_id_var.get()
    return cid if cid else get_current_user_id()


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


def execute_bash_command(command: str, working_dir: str = "") -> Dict[str, Any]:
    """
    Execute a Linux shell command safely on the host system and return its output.
    Use this tool when the user asks to run commands, check files, test code, or manage the system.
    
    Args:
        command: The bash command string to execute (e.g. 'ls -la', 'uptime', 'docker ps', 'git status').
        working_dir: Optional working directory (defaults to user home directory).
    """
    # Block catastrophic destructive commands
    dangerous_keywords = ["rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:", "chmod -R 777 /"]
    for kw in dangerous_keywords:
        if kw in command:
            return {"status": "error", "message": f"Perintah diblokir demi keamanan sistem: '{kw}'"}

    target_dir = os.path.expanduser(working_dir) if working_dir else os.path.expanduser("~")
    if not os.path.exists(target_dir):
        target_dir = os.path.expanduser("~")

    try:
        logger.info(f"Executing bash command: {command} in {target_dir}")
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=50,
            cwd=target_dir
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        # Truncate if output is extremely long
        if len(stdout) > 3500:
            stdout = stdout[:3500] + "\n...[Output terpotong karena terlalu panjang]"
        if len(stderr) > 1200:
            stderr = stderr[:1200] + "\n...[Stderr terpotong]"

        return {
            "status": "success" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "stdout": stdout or "(tidak ada output standar)",
            "stderr": stderr or None
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command execution timed out (50s)."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def execute_python_sandbox(code: str) -> Dict[str, Any]:
    """
    Execute a Python script safely in a subprocess sandbox with data analytics and chart generation capabilities.
    If matplotlib/seaborn creates a plot (e.g. plt.savefig or plt.show), it automatically captures the chart image
    and dispatches it directly to the Telegram user chat!
    
    Args:
        code: Complete Python code string to execute.
    """
    try:
        script_path = os.path.join(SANDBOX_DIR, "sandbox_run.py")
        plot_path = os.path.join(SANDBOX_DIR, "generated_plot.png")
        
        # Remove previous plot if any
        if os.path.exists(plot_path):
            try:
                os.remove(plot_path)
            except OSError:
                pass

        # Wrap code to auto-configure headless matplotlib and save plots
        preamble = (
            "import os\n"
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            f"_plot_target = '{plot_path}'\n"
            "def _auto_save():\n"
            "    if plt.get_fignums():\n"
            "        plt.savefig(_plot_target, bbox_inches='tight', dpi=150)\n"
            "        plt.close('all')\n"
            "import atexit\n"
            "atexit.register(_auto_save)\n\n"
        )
        
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(preamble + code)

        res = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=SANDBOX_DIR
        )

        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        has_plot = os.path.exists(plot_path) and os.path.getsize(plot_path) > 0

        return {
            "status": "success" if res.returncode == 0 else "error",
            "exit_code": res.returncode,
            "stdout": stdout or "(tidak ada print output)",
            "stderr": stderr or None,
            "generated_chart_photo": has_plot,
            "message": "Grafik visual berhasil dibuat dan akan dikirim ke Telegram!" if has_plot else "Eksekusi kode selesai."
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Eksekusi Python melebihi batas waktu (30 detik)."}
    except Exception as e:
        return {"status": "error", "message": f"Python runner error: {str(e)}"}


def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Perform a live web search using DuckDuckGo to get up-to-date real-time information, news, or facts.
    Use this tool whenever the user asks about current events, stock prices, weather, documentation, or recent news.
    
    Args:
        query: Search query string.
        max_results: Maximum number of search results to return (default: 5).
    """
    try:
        logger.info(f"Searching web for: {query}")
        results = list(DDGS().text(query, max_results=max_results))
        if not results:
            return {"status": "success", "results": [], "message": "Tidak ada hasil pencarian ditemukan."}
        
        formatted_results = []
        for item in results:
            formatted_results.append({
                "title": item.get("title", ""),
                "snippet": item.get("body", ""),
                "link": item.get("href", "")
            })
            
        return {"status": "success", "results": formatted_results}
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return {"status": "error", "message": f"Gagal melakukan pencarian web: {str(e)}"}


def fetch_web_page_content(url: str, max_length: int = 4000) -> Dict[str, Any]:
    """
    Fetch and extract clean text and main content from a website/article URL.
    Use this tool when you need to read documentation, read a specific article, or analyze a web page.
    
    Args:
        url: Full web URL (e.g. 'https://en.wikipedia.org/wiki/Python').
        max_length: Maximum text length to extract (default: 4000 chars).
    """
    try:
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"status": "error", "message": f"Gagal mengambil URL, status code: {resp.status_code}"}
            
            html = resp.text
            # Remove scripts, styles, head, comments
            html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
            html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
            html = re.sub(r"<nav[\s\S]*?</nav>", " ", html, flags=re.IGNORECASE)
            html = re.sub(r"<footer[\s\S]*?</footer>", " ", html, flags=re.IGNORECASE)
            html = re.sub(r"<header[\s\S]*?</header>", " ", html, flags=re.IGNORECASE)
            html = re.sub(r"<!--[\s\S]*?-->", " ", html)
            
            # Extract plain text
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            
            if len(text) > max_length:
                text = text[:max_length] + "\n...[Konten web dipotong sesuai batas maksimal]"
                
            return {
                "status": "success",
                "url": url,
                "content": text or "Halaman web tidak memuat konten teks yang dapat dibaca."
            }
    except Exception as e:
        logger.error(f"Fetch web page error: {e}")
        return {"status": "error", "message": f"Gagal membaca URL: {str(e)}"}


def save_knowledge_memory(key_topic: str, content: str, category: str = "general") -> Dict[str, Any]:
    """
    Save or update an important fact, user preference, project detail, or note into persistent long-term memory.
    Use this tool whenever the user tells you to remember something, or when important facts about the user/project are shared.
    
    Args:
        key_topic: Short title or identifier for this memory (e.g. 'user_work_hours', 'project_stack', 'trading_rules').
        content: The detailed information to remember.
        category: Category tag (e.g. 'preference', 'project', 'server', 'general').
    """
    try:
        user_id = get_current_user_id()
        msg = database.save_memory_fact_sync(user_id=user_id, key_topic=key_topic, content=content, category=category)
        return {
            "status": "success",
            "message": msg
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def search_knowledge_memory(query: str) -> Dict[str, Any]:
    """
    Search the persistent long-term memory for previously saved facts, user preferences, or notes.
    Use this tool when answering questions about user preferences, stored projects, or past instructions.
    
    Args:
        query: Keyword or phrase to look up.
    """
    try:
        user_id = get_current_user_id()
        memories = database.search_memories_sync(user_id=user_id, query=query)
        return {"status": "success", "memories": memories}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def read_local_file(file_path: str, max_lines: int = 300, start_line: int = 1) -> Dict[str, Any]:
    """
    Read the text content of a local file on the system safely.
    
    Args:
        file_path: Absolute or relative path to the file.
        max_lines: Maximum number of lines to read (default: 300).
        start_line: Starting line number (1-indexed).
    """
    try:
        expanded_path = os.path.expanduser(file_path)
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.join(os.path.expanduser("~"), file_path)

        if not os.path.exists(expanded_path):
            return {"status": "error", "message": f"File tidak ditemukan: {file_path}"}
        
        if os.path.isdir(expanded_path):
            files = os.listdir(expanded_path)
            return {"status": "is_directory", "files": files[:50], "total": len(files)}

        with open(expanded_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        total_lines = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + max_lines)
        selected_lines = lines[start_idx:end_idx]
        
        numbered_content = "".join([f"{i+1}: {line}" for i, line in enumerate(selected_lines, start=start_idx)])
            
        return {
            "status": "success",
            "file_path": expanded_path,
            "total_lines": total_lines,
            "showing_lines": f"{start_idx+1} to {end_idx}",
            "content": numbered_content
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def write_local_file(file_path: str, content: str) -> Dict[str, Any]:
    """
    Write or create a text file on the local system.
    
    Args:
        file_path: Path to the target file.
        content: Text content to write.
    """
    try:
        expanded_path = os.path.expanduser(file_path)
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.join(os.path.expanduser("~"), file_path)

        os.makedirs(os.path.dirname(expanded_path), exist_ok=True)
        with open(expanded_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {"status": "success", "message": f"File berhasil disimpan di {expanded_path} ({len(content)} karakter)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def search_workspace_files(pattern: str, base_dir: str = "~", max_results: int = 30) -> Dict[str, Any]:
    """
    Search for files and directories matching a glob pattern (e.g. '*.py', '*.json', 'bot*').
    
    Args:
        pattern: Glob pattern to search.
        base_dir: Root search directory (default: user home).
        max_results: Maximum number of files to return.
    """
    try:
        root_dir = os.path.expanduser(base_dir)
        matches = []
        for root, dirs, files in os.walk(root_dir):
            # Ignore heavy/hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '__pycache__', 'dist', 'build')]
            for name in files:
                if glob.fnmatch.fnmatch(name, pattern) or pattern.lower() in name.lower():
                    rel = os.path.relpath(os.path.join(root, name), root_dir)
                    matches.append(rel)
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        return {
            "status": "success",
            "base_dir": root_dir,
            "matches_count": len(matches),
            "files": matches
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def grep_workspace(query: str, base_dir: str = "~", file_pattern: str = "") -> Dict[str, Any]:
    """
    Search for text or regex pattern inside files across workspace.
    
    Args:
        query: String or regex query to find.
        base_dir: Search directory.
        file_pattern: Optional glob filter for files (e.g. '*.py').
    """
    try:
        root_dir = os.path.expanduser(base_dir)
        cmd = ["grep", "-rnI", "--exclude-dir={.git,venv,node_modules,__pycache__}"]
        if file_pattern:
            cmd.append(f"--include={file_pattern}")
        cmd.extend([query, root_dir])

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        lines = res.stdout.strip().split("\n") if res.stdout.strip() else []
        
        return {
            "status": "success",
            "matches_count": len(lines),
            "results": lines[:30]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def schedule_reminder(reminder_time_iso: str, message: str) -> Dict[str, Any]:
    """
    Schedule a future proactive reminder or alert that the bot will send directly to Telegram.
    
    Args:
        reminder_time_iso: The target time in ISO format (YYYY-MM-DDTHH:MM:SS), e.g. '2026-08-19T08:00:00'.
        message: The reminder message content.
    """
    try:
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        rem_id = database.add_reminder_sync(user_id=user_id, chat_id=chat_id, reminder_time_iso=reminder_time_iso, message=message)
        return {
            "status": "success",
            "reminder_id": rem_id,
            "message": f"Pengingat #{rem_id} berhasil dijadwalkan pada {reminder_time_iso}: '{message}'"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def capture_desktop_screenshot() -> Dict[str, Any]:
    """
    Capture an ultra-fast, high-resolution screenshot of the active Linux desktop screen.
    Uses native Wayland XDG Desktop Portal capture (compatible with Ubuntu GNOME Wayland)
    with fallbacks to grim, import, and PIL ImageGrab.
    """
    try:
        screenshot_path = os.path.join(SANDBOX_DIR, "desktop_screen.png")
        if os.path.exists(screenshot_path):
            try:
                os.remove(screenshot_path)
            except OSError:
                pass

        # 1. Native Wayland XDG Desktop Portal (Official GNOME/KDE Wayland Screen Capture)
        portal_script = (
            "import os, sys, shutil, urllib.parse, random\n"
            "from gi.repository import Gio, GLib\n"
            "target_path = sys.argv[1]\n"
            "bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)\n"
            "loop = GLib.MainLoop()\n"
            "saved_uri = None\n"
            "def on_signal(connection, sender_name, object_path, interface_name, signal_name, parameters, user_data):\n"
            "    global saved_uri\n"
            "    res = parameters.unpack()\n"
            "    if len(res) >= 2 and isinstance(res[1], dict) and 'uri' in res[1]:\n"
            "        saved_uri = res[1]['uri']\n"
            "    loop.quit()\n"
            "token = f'shot_{random.randint(1000, 9999)}'\n"
            "options = {'interactive': GLib.Variant('b', False), 'handle_token': GLib.Variant('s', token)}\n"
            "ret = bus.call_sync(\n"
            "    'org.freedesktop.portal.Desktop',\n"
            "    '/org/freedesktop/portal/desktop',\n"
            "    'org.freedesktop.portal.Screenshot',\n"
            "    'Screenshot',\n"
            "    GLib.Variant('(sa{sv})', ('', options)),\n"
            "    GLib.VariantType('(o)'),\n"
            "    Gio.DBusCallFlags.NONE,\n"
            "    4000,\n"
            "    None\n"
            ")\n"
            "req_path = ret.unpack()[0]\n"
            "bus.signal_subscribe(\n"
            "    'org.freedesktop.portal.Desktop',\n"
            "    'org.freedesktop.portal.Request',\n"
            "    'Response',\n"
            "    req_path,\n"
            "    None,\n"
            "    Gio.DBusSignalFlags.NONE,\n"
            "    on_signal,\n"
            "    None\n"
            ")\n"
            "GLib.timeout_add_seconds(3, loop.quit)\n"
            "loop.run()\n"
            "if saved_uri and saved_uri.startswith('file://'):\n"
            "    parsed_path = urllib.parse.unquote(saved_uri[7:])\n"
            "    if os.path.exists(parsed_path) and os.path.getsize(parsed_path) > 1000:\n"
            "        os.makedirs(os.path.dirname(target_path), exist_ok=True)\n"
            "        shutil.move(parsed_path, target_path)\n"
            "        sys.exit(0)\n"
            "sys.exit(1)\n"
        )
        try:
            p_res = subprocess.run(
                ["/usr/bin/python3", "-c", portal_script, screenshot_path],
                capture_output=True,
                timeout=4
            )
            if p_res.returncode == 0 and os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                return {
                    "status": "success",
                    "message": "Screenshot desktop berhasil diambil via Wayland Portal.",
                    "file_path": screenshot_path
                }
        except Exception:
            pass

        # 2. Try grim (wlroots Wayland compositors like Sway/Hyprland)
        try:
            subprocess.run(f"grim '{screenshot_path}'", shell=True, capture_output=True, timeout=2)
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                return {
                    "status": "success",
                    "message": "Screenshot desktop berhasil diambil via grim.",
                    "file_path": screenshot_path
                }
        except Exception:
            pass

        # 3. Try import (ImageMagick)
        try:
            subprocess.run(f"import -window root '{screenshot_path}'", shell=True, capture_output=True, timeout=2)
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                return {
                    "status": "success",
                    "message": "Screenshot desktop berhasil diambil via ImageMagick.",
                    "file_path": screenshot_path
                }
        except Exception:
            pass

        # 4. Fallback PIL ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.save(screenshot_path)
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                return {
                    "status": "success",
                    "message": "Screenshot desktop berhasil diambil via ImageGrab.",
                    "file_path": screenshot_path
                }
        except Exception:
            pass

        return {"status": "error", "message": "Gagal mengambil screenshot desktop di lingkungan display saat ini."}
    except Exception as err:
        return {"status": "error", "message": str(err)}


def capture_webcam_frame() -> Dict[str, Any]:
    """
    Capture a live snapshot frame from the connected hardware webcam/camera (/dev/video0).
    Use this tool when the user asks for a desk check, room status, or webcam photo.
    """
    try:
        cam_path = os.path.join(SANDBOX_DIR, "webcam_frame.jpg")
        if os.path.exists(cam_path):
            try:
                os.remove(cam_path)
            except OSError:
                pass
                
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"status": "error", "message": "Perangkat webcam tidak dapat diakses atau tidak terdeteksi (/dev/video0)."}
        
        # Warmup camera frames
        for _ in range(5):
            ret, frame = cap.read()
        ret, frame = cap.read()
        cap.release()
        
        if ret and frame is not None:
            cv2.imwrite(cam_path, frame)
            return {
                "status": "success",
                "message": "Foto webcam berhasil diambil.",
                "file_path": cam_path
            }
    except Exception as err:
        return {"status": "error", "message": str(err)}


def scan_local_network() -> Dict[str, Any]:
    """
    Scan connected local LAN devices, IP neighbors, and active gateways.
    Use this tool when the user asks to check network devices, Wi-Fi neighbors, or connected hardware.
    """
    try:
        res = subprocess.run("ip neigh || arp -a", shell=True, capture_output=True, text=True, timeout=10)
        return {
            "status": "success",
            "devices": res.stdout.strip() or "Tidak ada perangkat terdeteksi di tabel ARP/Neighbor."
        }
    except Exception as err:
        return {"status": "error", "message": str(err)}


def _ensure_camofox_server() -> bool:
    """Ensure Camofox browser daemon is active and listening on port 9377."""
    try:
        import httpx
        try:
            r = httpx.get("http://127.0.0.1:9377/health", timeout=1.5)
            if r.status_code == 200 and r.json().get("running"):
                return True
        except Exception:
            pass

        # Attempt to start daemon
        env = os.environ.copy()
        env["CAMOFOX_API_KEY"] = "7edc51a9e8b2401f98bc43d105ef5f68"
        camofox_bin = "/home/fahmial/.nvm/versions/node/v24.19.0/bin/camofox"
        if os.path.exists(camofox_bin):
            subprocess.run([camofox_bin, "server", "start", "--background"], env=env, capture_output=True, timeout=10)
            import time
            time.sleep(1.5)
            return True
        return False
    except Exception as e:
        logger.error(f"Camofox ensure server error: {e}")
        return False


def _run_camofox_cli(args: List[str]) -> Dict[str, Any]:
    """Execute camofox CLI command with proper environment and output parsing."""
    _ensure_camofox_server()
    camofox_bin = "/home/fahmial/.nvm/versions/node/v24.19.0/bin/camofox"
    env = os.environ.copy()
    env["CAMOFOX_API_KEY"] = "7edc51a9e8b2401f98bc43d105ef5f68"
    
    cmd = [camofox_bin] + args
    try:
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        return {
            "success": res.returncode == 0,
            "stdout": stdout,
            "stderr": stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Camofox browser command timed out (30s)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_open_url(url: str) -> Dict[str, Any]:
    """
    Open a web page in the Camofox stealth browser engine and return its accessibility element tree snapshot.
    Use this tool when the user asks to open a website, browse a web page, fill forms, or interact with web elements.
    
    Args:
        url: Full web URL to open (e.g. 'https://github.com/trending', 'https://news.ycombinator.com').
    """
    try:
        res = _run_camofox_cli(["open", url])
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
        
        # Take snapshot immediately
        snap = _run_camofox_cli(["snapshot"])
        return {
            "status": "success",
            "message": f"Halaman web '{url}' berhasil dibuka.",
            "interactive_elements": snap.get("stdout") or res.get("stdout")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def browser_click_element(element_ref: str, tab_id: str = "") -> Dict[str, Any]:
    """
    Click an interactive button, link, checkbox, or element on the active Camofox browser page by its reference.
    
    Args:
        element_ref: Element ref identifier (e.g. 'e1', 'e2', 'e15') from the browser snapshot or CSS selector.
        tab_id: Optional specific tab ID.
    """
    try:
        args = ["click", element_ref]
        if tab_id:
            args.append(tab_id)
            
        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
            
        # Get updated snapshot after click
        snap_args = ["snapshot"]
        if tab_id:
            snap_args.append(tab_id)
        snap = _run_camofox_cli(snap_args)
        
        return {
            "status": "success",
            "message": f"Elemen '{element_ref}' berhasil diklik.",
            "updated_page_elements": snap.get("stdout", "")[:3000]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def browser_type_text(element_ref: str, text: str, tab_id: str = "") -> Dict[str, Any]:
    """
    Type text into an input field or search bar on the active Camofox browser page.
    
    Args:
        element_ref: Element ref identifier (e.g. 'e3') or selector of the input field.
        text: String text to type into the input field.
        tab_id: Optional tab ID.
    """
    try:
        args = ["type", element_ref, text]
        if tab_id:
            args.append(tab_id)
            
        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
            
        return {
            "status": "success",
            "message": f"Teks berhasil diketik ke elemen '{element_ref}'."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def browser_capture_screenshot(tab_id: str = "") -> Dict[str, Any]:
    """
    Take a screenshot of the current Camofox browser page and automatically send it to the Telegram chat.
    
    Args:
        tab_id: Optional tab ID.
    """
    try:
        args = ["screenshot"]
        if tab_id:
            args.append(tab_id)
            
        res = _run_camofox_cli(args)
        if not res.get("success"):
            return {"status": "error", "message": res.get("stderr") or res.get("error")}
            
        out = res.get("stdout", "")
        # Camofox returns "path: /home/fahmial/.camofox/screenshots/..."
        import shutil
        target_path = os.path.join(SANDBOX_DIR, "browser_screenshot.png")
        
        for line in out.splitlines():
            if line.startswith("path:"):
                src_path = line.replace("path:", "").strip()
                if os.path.exists(src_path):
                    shutil.copyfile(src_path, target_path)
                    return {
                        "status": "success",
                        "message": "Screenshot browser berhasil diambil dan akan dikirim ke Telegram.",
                        "file_path": target_path
                    }
                    
        return {"status": "success", "message": "Screenshot browser berhasil diproses.", "raw_output": out}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def browser_close_tab(tab_id: str = "") -> Dict[str, Any]:
    """
    Close the active or specified Camofox browser tab.
    
    Args:
        tab_id: Optional tab ID (defaults to active tab).
    """
    try:
        args = ["close"]
        if tab_id:
            args.append(tab_id)
        res = _run_camofox_cli(args)
        return {
            "status": "success" if res.get("success") else "error",
            "message": "Tab browser berhasil ditutup." if res.get("success") else res.get("stderr")
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def desktop_click_coordinate(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
    """
    Simulate a hardware mouse click on specific pixel coordinates (X, Y) on the Linux desktop screen.
    Use this tool for GUI desktop automation (e.g. clicking buttons, icons, or menus on active windows).
    
    Args:
        x: X coordinate pixel on screen (0 to 1920).
        y: Y coordinate pixel on screen (0 to 1080).
        button: Mouse button ('left', 'right', 'middle'). Default: 'left'.
        clicks: Number of clicks (1 for single click, 2 for double click).
    """
    try:
        # Try ydotool (Wayland compatible)
        btn_code = "0xC0" if button == "left" else "0xC1" if button == "right" else "0xC2"
        res = subprocess.run(f"ydotool mousemove -a {x} {y} && ydotool click {btn_code}", shell=True, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return {"status": "success", "message": f"Mouse berhasil diklik pada koordinat ({x}, {y}) [{button}]."}

        # Fallback to xdotool
        res = subprocess.run(f"xdotool mousemove {x} {y} click {'1' if button == 'left' else '3'}", shell=True, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return {"status": "success", "message": f"Mouse berhasil diklik via xdotool pada ({x}, {y})."}

        # Fallback to PyAutoGUI
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return {"status": "success", "message": f"Mouse berhasil diklik via PyAutoGUI pada ({x}, {y})."}
    except Exception as e:
        return {"status": "error", "message": f"Gagal melakukan klik mouse: {str(e)}"}


def desktop_type_keys(text: str = "", hotkey: str = "") -> Dict[str, Any]:
    """
    Type text or press keyboard shortcuts/hotkeys on the active Linux desktop window.
    
    Args:
        text: String of text to type.
        hotkey: Optional key combination (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'Return', 'Escape').
    """
    try:
        if hotkey:
            keys = [k.strip() for k in hotkey.split("+")]
            import pyautogui
            pyautogui.hotkey(*keys)
            return {"status": "success", "message": f"Shortcut '{hotkey}' berhasil ditekan."}
        
        if text:
            res = subprocess.run(["ydotool", "type", text], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {"status": "success", "message": f"Teks berhasil diketik ke desktop: '{text}'"}
            
            import pyautogui
            pyautogui.write(text)
            return {"status": "success", "message": "Teks berhasil diketik via PyAutoGUI."}
            
        return {"status": "error", "message": "Harus menyertakan text atau hotkey."}
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengetik tombol: {str(e)}"}


def desktop_launch_app(app_name_or_command: str) -> Dict[str, Any]:
    """
    Launch a Linux GUI software application in the background (e.g. 'code', 'brave-browser', 'spotify', 'nautilus').
    
    Args:
        app_name_or_command: Application executable name or command.
    """
    try:
        env = os.environ.copy()
        env["DISPLAY"] = env.get("DISPLAY", ":0")
        env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
        subprocess.Popen(app_name_or_command, shell=True, env=env, start_new_session=True)
        return {
            "status": "success",
            "message": f"Aplikasi '{app_name_or_command}' berhasil diluncurkan di background desktop."
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal meluncurkan aplikasi: {str(e)}"}


def spawn_background_subagent(task_description: str, agent_role: str = "Researcher & Coder") -> Dict[str, Any]:
    """
    Spawn an autonomous background subagent worker to solve a complex, long-running task
    (e.g. deep research, scraping multiple sources, data analysis, codebase audits)
    independently without blocking the user. When finished, the subagent sends a full report to Telegram.
    
    Args:
        task_description: Complete detailed instructions for the subagent.
        agent_role: Specialized title or job role (e.g. 'Deep Web Researcher', 'Python Coder', 'Security Auditor').
    """
    try:
        import subagents
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        return subagents.spawn_subagent(user_id=user_id, chat_id=chat_id, role=agent_role, task_description=task_description)
    except Exception as e:
        return {"status": "error", "message": str(e)}


def check_subagent_status(subagent_id: str) -> Dict[str, Any]:
    """
    Check the execution status and report of a spawned background subagent by its task ID.
    
    Args:
        subagent_id: The task ID (e.g. 'sub_1a2b3c4d').
    """
    try:
        task = database.get_subagent_task_sync(subagent_id)
        if not task:
            return {"status": "error", "message": f"Subagent dengan ID '{subagent_id}' tidak ditemukan."}
        return {"status": "success", "task": task}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def add_recurring_task(title: str, prompt_instruction: str, interval_minutes: int = 60) -> Dict[str, Any]:
    """
    Schedule an autonomous recurring task or proactive watchdog (e.g. monitor server stats every 30m, check crypto price every 15m, daily tech news briefing every 1440m).
    The AI will automatically run this instruction periodically and send the result to Telegram!
    
    Args:
        title: Short descriptive name for this task.
        prompt_instruction: The exact prompt/action for the AI agent to execute on each interval.
        interval_minutes: Repeat interval in minutes (default: 60 minutes).
    """
    try:
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        job_id = database.add_cron_job_sync(
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            prompt_instruction=prompt_instruction,
            interval_minutes=max(1, interval_minutes)
        )
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Tugas berulang #{job_id} '{title}' berhasil dijadwalkan setiap {interval_minutes} menit."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_recurring_tasks() -> Dict[str, Any]:
    """
    List all active recurring tasks and watchdogs scheduled for the user.
    """
    try:
        user_id = get_current_user_id()
        jobs = database.list_cron_jobs_sync(user_id)
        return {"status": "success", "total_jobs": len(jobs), "tasks": jobs}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def cancel_recurring_task(task_id: int) -> Dict[str, Any]:
    """
    Cancel and delete a scheduled recurring task or watchdog by its ID.
    
    Args:
        task_id: The ID of the recurring task.
    """
    try:
        user_id = get_current_user_id()
        success = database.delete_cron_job_sync(user_id, task_id)
        if success:
            return {"status": "success", "message": f"Tugas berulang #{task_id} berhasil dibatalkan dan dihapus."}
        return {"status": "error", "message": f"Tugas #{task_id} tidak ditemukan."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_pdf_report(title: str, summary: str, table_data: Optional[List[List[str]]] = None, filename: str = "laporan.pdf") -> Dict[str, Any]:
    """
    Generate a modern, beautifully styled PDF document report with ReportLab and automatically send it to Telegram.
    
    Args:
        title: Main document title (e.g. 'Laporan Analisis Kinerja Server', 'Rangkuman Riset Pasar').
        summary: Paragraphs of text explaining the findings, recommendations, or content.
        table_data: Optional 2D array of strings for tables [ ['Header1', 'Header2'], ['Val1', 'Val2'] ].
        filename: Output filename ending in .pdf.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        
        safe_name = filename if filename.endswith(".pdf") else f"{filename}.pdf"
        target_path = os.path.join(SANDBOX_DIR, safe_name)
        
        doc = SimpleDocTemplate(target_path, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#1E3A8A'),
            spaceAfter=15
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor('#334155'),
            spaceAfter=10
        )
        
        elements = [
            Paragraph(f"<b>{title}</b>", title_style),
            Spacer(1, 10),
        ]
        
        for paragraph in summary.split("\n\n"):
            if paragraph.strip():
                clean_p = paragraph.strip().replace("\n", "<br/>")
                elements.append(Paragraph(clean_p, body_style))
                elements.append(Spacer(1, 8))
                
        if table_data and len(table_data) > 0:
            elements.append(Spacer(1, 12))
            t = Table(table_data, style=[
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('TOPPADDING', (0,0), (-1,0), 8),
                ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#F8FAFC')),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('FONTSIZE', (0,1), (-1,-1), 9),
                ('TOPPADDING', (0,1), (-1,-1), 6),
                ('BOTTOMPADDING', (0,1), (-1,-1), 6),
            ])
            elements.append(t)
            
        doc.build(elements)
        return {
            "status": "success",
            "message": f"Dokumen PDF '{safe_name}' berhasil dibuat dan akan dikirim ke Telegram.",
            "file_path": target_path
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat PDF: {str(e)}"}


def generate_excel_spreadsheet(sheet_title: str, headers: List[str], rows: List[List[Any]], filename: str = "data.xlsx") -> Dict[str, Any]:
    """
    Generate an Excel (.xlsx) spreadsheet with styled headers, borders, and auto-adjusted columns, automatically sent to Telegram.
    
    Args:
        sheet_title: Name of the worksheet tab.
        headers: List of column header names (e.g. ['Nama', 'Kategori', 'Harga', 'Jumlah']).
        rows: 2D list of row values.
        filename: Output filename ending in .xlsx.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        
        safe_name = filename if filename.endswith(".xlsx") else f"{filename}.xlsx"
        target_path = os.path.join(SANDBOX_DIR, safe_name)
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_title[:30]
        
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )
        
        ws.append(headers)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border
            
        for row_data in rows:
            ws.append(row_data)
            row_idx = ws.max_row
            for col_num in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_idx, column=col_num)
                cell.border = thin_border
                
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
            
        wb.save(target_path)
        return {
            "status": "success",
            "message": f"Spreadsheet Excel '{safe_name}' berhasil dibuat dan akan dikirim ke Telegram.",
            "file_path": target_path
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat Excel: {str(e)}"}


def generate_presentation_pptx(title: str, subtitle: str, slides_content: List[Dict[str, Any]], filename: str = "presentasi.pptx") -> Dict[str, Any]:
    """
    Generate a clean PowerPoint presentation (.pptx) and send it directly to Telegram.
    
    Args:
        title: Main presentation title.
        subtitle: Subtitle / author note.
        slides_content: List of slide objects, each with 'title' (str) and 'points' (list of bullet points).
        filename: Output filename ending in .pptx.
    """
    try:
        from pptx import Presentation
        
        safe_name = filename if filename.endswith(".pptx") else f"{filename}.pptx"
        target_path = os.path.join(SANDBOX_DIR, safe_name)
        
        prs = Presentation()
        title_layout = prs.slide_layouts[0]
        slide = prs.slides.add_slide(title_layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = subtitle
        
        bullet_layout = prs.slide_layouts[1]
        for item in slides_content:
            s = prs.slides.add_slide(bullet_layout)
            s.shapes.title.text = item.get("title", "Slide")
            tf = s.placeholders[1].text_frame
            tf.word_wrap = True
            points = item.get("points", [])
            for i, pt in enumerate(points):
                if i == 0:
                    tf.text = str(pt)
                else:
                    p = tf.add_paragraph()
                    p.text = str(pt)
                    p.level = 0
                    
        prs.save(target_path)
        return {
            "status": "success",
            "message": f"Presentasi PowerPoint '{safe_name}' berhasil dibuat dan akan dikirim ke Telegram.",
            "file_path": target_path
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membuat PPTX: {str(e)}"}


def control_linux_hardware(action: str, value: str = "") -> Dict[str, Any]:
    """
    Control Linux laptop/server hardware, audio, screen lock, power, Wi-Fi, and media from Telegram.
    
    Args:
        action: Target hardware action. Options:
                - 'lock_screen': Lock the Linux desktop session immediately.
                - 'set_volume': Set audio output volume (value: '0' to '100', e.g. '50%').
                - 'mute_toggle': Toggle audio mute/unmute.
                - 'media_play_pause': Toggle media playback (Spotify, YouTube, VLC).
                - 'media_next': Next media track.
                - 'media_prev': Previous media track.
                - 'wifi_scan': Scan and list available Wi-Fi access points.
                - 'bluetooth_status': Check Bluetooth status and connected devices.
                - 'battery_status': Check battery health, percentage, and charging state.
        value: Optional parameter for the action (e.g. '50%' for set_volume).
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


# List of all tools available to the Gemini Model
AVAILABLE_TOOLS = [
    get_system_stats,
    execute_bash_command,
    execute_python_sandbox,
    web_search,
    fetch_web_page_content,
    browser_open_url,
    browser_click_element,
    browser_type_text,
    browser_capture_screenshot,
    browser_close_tab,
    desktop_click_coordinate,
    desktop_type_keys,
    desktop_launch_app,
    spawn_background_subagent,
    check_subagent_status,
    add_recurring_task,
    list_recurring_tasks,
    cancel_recurring_task,
    generate_pdf_report,
    generate_excel_spreadsheet,
    generate_presentation_pptx,
    control_linux_hardware,
    save_knowledge_memory,
    search_knowledge_memory,
    read_local_file,
    write_local_file,
    search_workspace_files,
    grep_workspace,
    schedule_reminder,
    capture_desktop_screenshot,
    capture_webcam_frame,
    scan_local_network
]

