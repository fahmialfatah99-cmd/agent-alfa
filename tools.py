"""
Agent Tools Module for Telegram AI Bot.
Provides system monitoring, bash command execution, live web search,
persistent long-term memory, file I/O, and proactive reminders.
"""

import os
import subprocess
import psutil
import datetime
import logging
from typing import Dict, Any, List, Optional
from ddgs import DDGS
import database

logger = logging.getLogger("AgentTools")


def get_system_stats() -> Dict[str, Any]:
    """
    Get real-time Linux system health metrics including CPU, RAM, Disk, Uptime, and Top Processes.
    Use this tool when the user asks about server/laptop performance, system specs, memory, or disk usage.
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        
        mem = psutil.virtual_memory()
        ram_total_gb = round(mem.total / (1024 ** 3), 2)
        ram_used_gb = round(mem.used / (1024 ** 3), 2)
        ram_percent = mem.percent
        
        disk = psutil.disk_usage('/')
        disk_total_gb = round(disk.total / (1024 ** 3), 2)
        disk_used_gb = round(disk.used / (1024 ** 3), 2)
        disk_percent = disk.percent
        
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = str(datetime.datetime.now() - boot_time).split('.')[0]
        
        # Get top 5 memory consuming processes
        processes = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(p.info)
            except Exception:
                pass
        top_procs = sorted(processes, key=lambda p: p.get('memory_percent') or 0, reverse=True)[:5]
        
        return {
            "status": "success",
            "cpu": f"{cpu_percent}% ({cpu_count} cores)",
            "ram": f"{ram_used_gb} GB / {ram_total_gb} GB ({ram_percent}%)",
            "disk": f"{disk_used_gb} GB / {disk_total_gb} GB ({disk_percent}%)",
            "uptime": uptime,
            "top_processes": [
                f"{p['name']} (PID: {p['pid']}, RAM: {round(p['memory_percent'] or 0, 1)}%)"
                for p in top_procs
            ]
        }
    except Exception as e:
        logger.error(f"Error in get_system_stats: {e}")
        return {"status": "error", "message": str(e)}


def execute_bash_command(command: str) -> Dict[str, Any]:
    """
    Execute a Linux shell command safely on the host system and return its output.
    Use this tool when the user asks to run commands, check files, test code, or manage the system.
    
    Args:
        command: The bash command string to execute (e.g. 'ls -la', 'uptime', 'docker ps').
    """
    # Block dangerous destructive commands
    dangerous_keywords = ["rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:"]
    for kw in dangerous_keywords:
        if kw in command:
            return {"status": "error", "message": f"Perintah diblokir demi keamanan sistem: '{kw}'"}

    try:
        logger.info(f"Executing bash command: {command}")
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=45,
            cwd="/home/fahmial"
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        # Truncate if output is extremely long
        if len(stdout) > 3000:
            stdout = stdout[:3000] + "\n...[Output terpotong karena terlalu panjang]"
        if len(stderr) > 1000:
            stderr = stderr[:1000] + "\n...[Stderr terpotong]"

        return {
            "status": "success" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "stdout": stdout or "(tidak ada output)",
            "stderr": stderr or None
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Command execution timed out (45s)."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
        # Synchronous wrapper calling async db in caller or standard async loop
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(database.save_memory_fact(8821693251, key_topic, content, category))
        else:
            asyncio.run(database.save_memory_fact(8821693251, key_topic, content, category))
            
        return {
            "status": "success",
            "message": f"Memori '{key_topic}' berhasil disimpan dalam kategori '{category}'."
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
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create task or run with sqlite sync
            import sqlite3
            conn = sqlite3.connect(database.DB_PATH)
            cursor = conn.cursor()
            pattern = f"%{query.strip().lower()}%"
            cursor.execute(
                "SELECT category, key_topic, content FROM knowledge_memory WHERE LOWER(key_topic) LIKE ? OR LOWER(content) LIKE ?",
                (pattern, pattern)
            )
            rows = cursor.fetchall()
            conn.close()
            results = [{"category": r[0], "topic": r[1], "content": r[2]} for r in rows]
            return {"status": "success", "memories": results}
        else:
            memories = asyncio.run(database.search_memories(8821693251, query))
            return {"status": "success", "memories": memories}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def read_local_file(file_path: str) -> Dict[str, Any]:
    """
    Read the text content of a local file on the system.
    
    Args:
        file_path: Absolute or relative path to the file.
    """
    try:
        expanded_path = os.path.expanduser(file_path)
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.join("/home/fahmial", file_path)

        if not os.path.exists(expanded_path):
            return {"status": "error", "message": f"File tidak ditemukan: {file_path}"}
        
        with open(expanded_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(10000)  # Read up to 10k chars
            
        return {
            "status": "success",
            "file_path": expanded_path,
            "content": content
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
            expanded_path = os.path.join("/home/fahmial", file_path)

        os.makedirs(os.path.dirname(expanded_path), exist_ok=True)
        with open(expanded_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {"status": "success", "message": f"File berhasil disimpan di {expanded_path}"}
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
        import sqlite3
        conn = sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (user_id, chat_id, reminder_time, message) VALUES (?, ?, ?, ?)",
            (8821693251, 8821693251, reminder_time_iso, message)
        )
        conn.commit()
        conn.close()
        return {
            "status": "success",
            "message": f"Pengingat dijadwalkan pada {reminder_time_iso}: '{message}'"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def capture_desktop_screenshot() -> Dict[str, Any]:
    """
    Capture a high-resolution screenshot of the active Linux desktop screen.
    Automatically detects Wayland / X11 display environment and saves to RAM sandbox.
    """
    try:
        sandbox_dir = "/dev/shm/alfa_sandbox"
        os.makedirs(sandbox_dir, exist_ok=True)
        screenshot_path = os.path.join(sandbox_dir, "desktop_screen.png")
        if os.path.exists(screenshot_path):
            try:
                os.remove(screenshot_path)
            except OSError:
                pass

        # Robust display sourcing for Wayland and X11
        cmd = (
            f"export XDG_RUNTIME_DIR=/run/user/$(id -u); "
            f"export WAYLAND_DISPLAY=wayland-0; "
            f"grim '{screenshot_path}' 2>/dev/null || "
            f"(export DISPLAY=:0; export XAUTHORITY=$(find /home -name .Xauthority 2>/dev/null | head -n 1); scrot '{screenshot_path}' 2>/dev/null || import -window root '{screenshot_path}' 2>/dev/null)"
        )
        subprocess.run(cmd, shell=True, timeout=5)

        if not os.path.exists(screenshot_path) or os.path.getsize(screenshot_path) == 0:
            try:
                import pyautogui
                img = pyautogui.screenshot()
                img.save(screenshot_path)
            except Exception as e:
                return {"status": "error", "message": f"Gagal mengambil screenshot: {str(e)}"}

        if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
            return {
                "status": "success",
                "message": "Screenshot desktop berhasil diambil.",
                "file_path": screenshot_path
            }
        return {"status": "error", "message": "Screenshot file tidak terbentuk."}
    except Exception as err:
        return {"status": "error", "message": str(err)}


def capture_webcam_frame() -> Dict[str, Any]:
    """
    Capture a live snapshot frame from the connected hardware webcam/camera.
    Use this tool when the user asks for a desk check, room status, or webcam photo.
    """
    try:
        sandbox_dir = "/dev/shm/alfa_sandbox"
        os.makedirs(sandbox_dir, exist_ok=True)
        cam_path = os.path.join(sandbox_dir, "webcam_frame.jpg")
        
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
        return {"status": "error", "message": "Gagal membaca frame dari webcam."}
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


# List of all tools available to the Gemini Model
AVAILABLE_TOOLS = [
    get_system_stats,
    execute_bash_command,
    web_search,
    save_knowledge_memory,
    search_knowledge_memory,
    read_local_file,
    write_local_file,
    schedule_reminder,
    capture_desktop_screenshot,
    capture_webcam_frame,
    scan_local_network
]
