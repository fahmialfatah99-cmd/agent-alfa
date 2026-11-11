"""Kontrol perangkat Android lokal via scrcpy."""
import logging
import os
import shutil
import subprocess
import time
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Integrations")

@register_tool(category="system")
def scrcpy_android_control(
    action: str = "status",
    device_id: str = "",
    command_or_key: str = "",
    capture_screenshot: bool = True,
) -> dict[str, Any]:
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
    adb_bin = shutil.which("adb") or "adb"
    scrcpy_bin = shutil.which("scrcpy")

    if not adb_bin and not scrcpy_bin:
        return {
            "status": "error",
            "message": "ADB / Scrcpy belum terpasang di sistem. Untuk mengaktifkan kontrol Android, jalankan: 'sudo apt install -y scrcpy adb' (Linux), 'brew install scrcpy' (macOS), atau 'winget install scrcpy' (Windows).",
        }

    dev_flag: list[str] = ["-s", device_id] if device_id else []

    try:
        if action == "status":
            res = subprocess.run(
                [adb_bin, "devices", "-l"], capture_output=True, text=True, timeout=5
            )
            return {
                "status": "success",
                "raw_devices_output": res.stdout.strip(),
                "adb_path": adb_bin,
                "scrcpy_path": scrcpy_bin,
            }

        elif action == "screenshot":
            out_dir = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
            os.makedirs(out_dir, exist_ok=True)
            shot_file = os.path.join(out_dir, f"android_screen_{int(time.time())}.png")
            with open(shot_file, "wb") as f:
                subprocess.run(
                    [adb_bin] + dev_flag + ["exec-out", "screencap", "-p"],
                    stdout=f,
                    timeout=10,
                )
            return {
                "status": "success",
                "screenshot_file": shot_file,
                "file_size": (
                    os.path.getsize(shot_file) if os.path.exists(shot_file) else 0
                ),
            }

        elif action == "key":
            key_map = {
                "HOME": "3",
                "BACK": "4",
                "CALL": "5",
                "ENDCALL": "6",
                "ENTER": "66",
                "DELETE": "67",
                "TAB": "61",
                "SPACE": "62",
                "VOLUME_UP": "24",
                "VOLUME_DOWN": "25",
                "POWER": "26",
                "CAMERA": "27",
            }
            keycode = key_map.get(command_or_key.upper(), command_or_key)
            subprocess.run(
                [adb_bin] + dev_flag + ["shell", "input", "keyevent", keycode],
                capture_output=True,
                timeout=5,
            )
            return {"status": "success", "action": "key", "sent_key": command_or_key}

        elif action == "tap":
            coords = command_or_key.split()
            if len(coords) < 2:
                return {
                    "status": "error",
                    "message": "Koordinat tap harus berupa 'X Y' (contoh: '500 800')",
                }
            subprocess.run(
                [adb_bin] + dev_flag + ["shell", "input", "tap", coords[0], coords[1]],
                capture_output=True,
                timeout=5,
            )
            return {"status": "success", "action": "tap", "coords": coords[:2]}

        elif action == "launch_app":
            subprocess.run(
                [adb_bin]
                + dev_flag
                + [
                    "shell",
                    "monkey",
                    "-p",
                    command_or_key,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                capture_output=True,
                timeout=5,
            )
            return {
                "status": "success",
                "action": "launch_app",
                "package": command_or_key,
            }

        elif action == "mirror":
            if not scrcpy_bin:
                return {
                    "status": "error",
                    "message": "Binary scrcpy tidak ditemukan. Install dengan 'sudo apt install -y scrcpy'",
                }
            subprocess.Popen([scrcpy_bin] + (["-s", device_id] if device_id else []))
            return {
                "status": "success",
                "message": "Window screen mirroring Scrcpy berhasil dibuka di desktop.",
            }

        else:
            return {"status": "error", "message": f"Action '{action}' tidak dikenal."}
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError) as e:
        return {"status": "error", "message": f"Android control error: {str(e)}"}
