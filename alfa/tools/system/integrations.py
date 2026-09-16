# -*- coding: utf-8 -*-
"""
Ecosystem and productivity integration tools for ALFA.
Includes reminders, focus sessions, password generation, WhatsApp bot, Android (ADB/scrcpy), and database queries.
"""

import os
import sys
import time
import math
import secrets
import string
import shutil
import sqlite3
import subprocess
import json
from typing import Dict, Any, Optional, List

from alfa.tools.registry import register_tool
from alfa.core.runtime_ctx import get_current_user_id, get_current_chat_id
from alfa.core import database


@register_tool(category="system")
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


@register_tool(category="system")
def generate_secure_password(length: int = 20, include_uppercase: bool = True, include_digits: bool = True, include_special: bool = True, count: int = 1) -> Dict[str, Any]:
    """
    Generate one or more cryptographically secure random passwords.
    
    Args:
        length: Password length (8-128 characters, default: 20).
        include_uppercase: Include uppercase letters (default: True).
        include_digits: Include digits (default: True).
        include_special: Include special characters !@#$%^&* (default: True).
        count: Number of passwords to generate (1-10, default: 1).
    """
    try:
        length = max(8, min(128, length))
        count = max(1, min(10, count))
        
        chars = string.ascii_lowercase
        if include_uppercase:
            chars += string.ascii_uppercase
        if include_digits:
            chars += string.digits
        if include_special:
            chars += "!@#$%^&*_+-=?."
        
        passwords = []
        for _ in range(count):
            pw = ''.join(secrets.choice(chars) for _ in range(length))
            passwords.append(pw)
        
        # Calculate entropy
        entropy = round(math.log2(len(chars)) * length, 1)
        strength = "Sangat Kuat 🟢" if entropy > 80 else "Kuat 🔵" if entropy > 60 else "Cukup 🟡" if entropy > 40 else "Lemah 🔴"
        
        return {
            "status": "success",
            "passwords": passwords,
            "length": length,
            "entropy_bits": entropy,
            "strength": strength,
            "charset_size": len(chars)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def start_focus_session(title: str, duration_minutes: int = 25, notes: str = "") -> Dict[str, Any]:
    """
    GOD MODE: Focus & Pomodoro Productivity Session.
    Starts a deep work focus session with automatic timer, records target end time,
    and schedules an automatic Telegram completion alert.
    
    Args:
        title: Title/objective of the focus session (e.g. 'Code Review Backend', 'Menulis Laporan').
        duration_minutes: Duration in minutes (default: 25).
        notes: Optional extra notes for the session.
    """
    uid = get_current_user_id()
    cid = get_current_chat_id()
    if not uid:
        return {"status": "error", "message": "User context tidak ditemukan."}
    res = database.start_focus_session_sync(uid, cid, title, duration_minutes, notes)
    return {
        "status": "success",
        "message": f"🎯 Sesi fokus '{title}' ({duration_minutes} menit) dimulai! Berakhir pada: {res['end_time']}. Bot akan mengirim notifikasi saat waktu habis.",
        "session_details": res
    }


@register_tool(category="system")
def manage_wa_sheets_bot(action: str = "status") -> Dict[str, Any]:
    """
    ECOSYSTEM INTEGRATION: WhatsApp Google Sheets Bot Controller.
    Controls and monitors the wa-sheets-bot systemd user service.
    Can check status, start, stop, restart, enable auto-start, or view live logs.
    
    Args:
        action: 'status' (check running state & memory), 'start', 'stop', 'restart', 'logs' (recent 20 lines), 'enable' (enable autostart on boot).
    """
    try:
        act = action.lower().strip()
        svc_name = "wa-sheets-bot.service"
        
        if act == "status":
            res_active = subprocess.run(["systemctl", "--user", "is-active", svc_name], capture_output=True, text=True)
            res_enabled = subprocess.run(["systemctl", "--user", "is-enabled", svc_name], capture_output=True, text=True)
            res_status = subprocess.run(["systemctl", "--user", "status", svc_name, "--no-pager", "-n", "5"], capture_output=True, text=True)
            
            is_act = res_active.stdout.strip() == "active"
            return {
                "status": "success",
                "service": svc_name,
                "is_running": is_act,
                "state": res_active.stdout.strip(),
                "enabled_on_boot": res_enabled.stdout.strip() == "enabled",
                "details": res_status.stdout.strip()
            }
            
        elif act in ["start", "stop", "restart", "enable", "disable"]:
            res = subprocess.run(["systemctl", "--user", act, svc_name], capture_output=True, text=True)
            if res.returncode == 0:
                time.sleep(1)
                res_active = subprocess.run(["systemctl", "--user", "is-active", svc_name], capture_output=True, text=True)
                return {
                    "status": "success",
                    "message": f"Service '{svc_name}' berhasil di-{act}! Status saat ini: {res_active.stdout.strip()}.",
                    "current_state": res_active.stdout.strip()
                }
            return {"status": "error", "message": f"Gagal mengeksekusi {act}: {res.stderr}"}
            
        elif act == "logs":
            res_logs = subprocess.run(["journalctl", "--user", "-u", svc_name, "-n", "25", "--no-pager"], capture_output=True, text=True)
            return {
                "status": "success",
                "service": svc_name,
                "logs": res_logs.stdout.strip()
            }
            
        return {"status": "error", "message": f"Aksi '{action}' tidak dikenal. Gunakan: status, start, stop, restart, logs, enable."}
    except Exception as e:
        return {"status": "error", "message": f"Manage wa-sheets-bot error: {str(e)}"}


@register_tool(category="system")
def list_wa_drive_uploads(limit: int = 20) -> Dict[str, Any]:
    """
    Daftar berkas (foto/PDF/dokumen) yang otomatis diunggah dari WhatsApp ke Google Drive.
    
    Args:
        limit: Jumlah maksimal entri terbaru (default 20).
    """
    try:
        path = os.path.expanduser("~/wa-sheets-bot/drive_uploads.json")
        if not os.path.exists(path):
            return {"status": "success", "total": 0,
                    "message": "Belum ada berkas WA yang terunggah ke Drive.",
                    "uploads": []}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        uploads = (data.get("uploads") or [])[: max(1, min(int(limit), 100))]
        compact = [{
            'waktu': u.get('ts'), 'nama_file': u.get('file_name'),
            'folder': u.get('folder'), 'pengirim': u.get('sender'),
            'grup': u.get('group'), 'link': u.get('web_link'),
        } for u in uploads]
        return {"status": "success", "total": len(uploads),
                "message": f"{len(uploads)} berkas WA terakhir di Drive.",
                "uploads": compact}
    except Exception as e:
        return {"status": "error", "message": f"Gagal membaca log unggahan: {str(e)}"}


@register_tool(category="system")
def scrcpy_android_control(action: str = "status", device_id: str = "", command_or_key: str = "", capture_screenshot: bool = True) -> Dict[str, Any]:
    """
    SCRCPY & ADB ANDROID ENGINE: Control Android smartphones/tablets via USB or Wi-Fi.
    Allows screen capture, sending keyevents, touch taps, app launches, and desktop screen mirroring.
    
    Args:
        action: 'status' (list devices), 'screenshot' (save screen PNG), 'key' (send HOME/BACK/ENTER), 
                'tap' (tap X Y coordinates), 'swipe' (swipe X1 Y1 X2 Y2), 'launch_app' (open app package), 'mirror' (open scrcpy window).
        device_id: Optional specific Android device serial (from adb devices).
        command_or_key: Key name or coordinates (e.g. 'BACK', 'HOME', '500 800' for tap, 'com.whatsapp' for launch_app).
        capture_screenshot: If True, takes a fresh screenshot after performing the action.
    """
    adb_bin = shutil.which("adb")
    scrcpy_bin = shutil.which("scrcpy")
    
    if not adb_bin and not scrcpy_bin:
        return {
            "status": "error",
            "message": "ADB / Scrcpy belum terpasang di sistem. Untuk mengaktifkan kontrol Android, jalankan: 'sudo apt install -y scrcpy adb' (Linux), 'brew install scrcpy' (macOS), atau 'winget install scrcpy' (Windows)."
        }
        
    dev_flag = ["-s", device_id] if device_id else []
    
    try:
        if action == "status":
            res = subprocess.run([adb_bin, "devices", "-l"], capture_output=True, text=True, timeout=5)
            return {
                "status": "success",
                "raw_devices_output": res.stdout.strip(),
                "adb_path": adb_bin,
                "scrcpy_path": scrcpy_bin
            }
            
        elif action == "screenshot":
            out_dir = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
            os.makedirs(out_dir, exist_ok=True)
            shot_file = os.path.join(out_dir, f"android_screen_{int(time.time())}.png")
            with open(shot_file, "wb") as f:
                subprocess.run([adb_bin] + dev_flag + ["exec-out", "screencap", "-p"], stdout=f, timeout=10)
            return {
                "status": "success",
                "screenshot_file": shot_file,
                "file_size": os.path.getsize(shot_file) if os.path.exists(shot_file) else 0
            }
            
        elif action == "key":
            key_map = {
                "HOME": "3", "BACK": "4", "CALL": "5", "ENDCALL": "6",
                "ENTER": "66", "DELETE": "67", "TAB": "61", "SPACE": "62",
                "VOLUME_UP": "24", "VOLUME_DOWN": "25", "POWER": "26", "CAMERA": "27"
            }
            keycode = key_map.get(command_or_key.upper(), command_or_key)
            subprocess.run([adb_bin] + dev_flag + ["shell", "input", "keyevent", keycode], capture_output=True, timeout=5)
            return {"status": "success", "action": "key", "sent_key": command_or_key}
            
        elif action == "tap":
            coords = command_or_key.split()
            if len(coords) < 2:
                return {"status": "error", "message": "Koordinat tap harus berupa 'X Y' (contoh: '500 800')"}
            subprocess.run([adb_bin] + dev_flag + ["shell", "input", "tap", coords[0], coords[1]], capture_output=True, timeout=5)
            return {"status": "success", "action": "tap", "coords": coords[:2]}
            
        elif action == "launch_app":
            subprocess.run([adb_bin] + dev_flag + ["shell", "monkey", "-p", command_or_key, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True, timeout=5)
            return {"status": "success", "action": "launch_app", "package": command_or_key}
            
        elif action == "mirror":
            if not scrcpy_bin:
                return {"status": "error", "message": "Binary scrcpy tidak ditemukan. Install dengan 'sudo apt install -y scrcpy'"}
            subprocess.Popen([scrcpy_bin] + (["-s", device_id] if device_id else []))
            return {"status": "success", "message": "Window screen mirroring Scrcpy berhasil dibuka di desktop."}
            
        else:
            return {"status": "error", "message": f"Action '{action}' tidak dikenal."}
    except Exception as e:
        return {"status": "error", "message": f"Android control error: {str(e)}"}


@register_tool(category="system")
def query_database(db_path: str, sql_query: str) -> Dict[str, Any]:
    """
    Execute a SQL query on a local SQLite database file and return the results as a table.
    
    Args:
        db_path: Path to the SQLite database file (e.g. '~/data/app.db', 'bot_database.db').
        sql_query: SQL query to execute (SELECT, INSERT, UPDATE, DELETE, etc.).
    
    Security Note: This function accepts raw SQL queries. Ensure input is validated
    before calling this function to prevent SQL injection attacks.
    """
    try:
        expanded = os.path.expanduser(db_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"Database file tidak ditemukan: {db_path}"}
        
        # Security validation: Block dangerous statements
        query_upper = sql_query.strip().upper()
        dangerous_keywords = ["DROP ", "DELETE FROM ", "TRUNCATE", "ALTER ", "CREATE INDEX", 
                             "DETACH DATABASE", "ATTACH DATABASE"]
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return {"status": "error", "message": f"Potensi SQL injection terdeteksi: '{keyword}' tidak diizinkan."}
        
        conn = sqlite3.connect(expanded)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(sql_query)
        
        query_upper = sql_query.strip().upper()
        if query_upper.startswith("SELECT") or query_upper.startswith("PRAGMA") or query_upper.startswith("WITH"):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows[:100]]
            conn.close()
            return {
                "status": "success",
                "columns": columns,
                "row_count": len(data),
                "total_available": len(rows) if len(rows) <= 100 else f"{len(rows)}+ (showing first 100)",
                "data": data
            }
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return {"status": "success", "message": f"Query berhasil dieksekusi. {affected} baris terpengaruh."}
    except Exception as e:
        return {"status": "error", "message": f"SQL error: {str(e)}"}
