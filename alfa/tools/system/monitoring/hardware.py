"""Linux hardware control tool."""

import logging
import subprocess
from typing import Any

import psutil

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.System")

@register_tool(category="system")
def control_linux_hardware(action: str, value: str = "") -> dict[str, Any]:
    """
    Control Linux laptop/server hardware, audio, screen lock, power, Wi-Fi, and media from Telegram.
    """
    try:
        act = action.strip().lower()
        if act == "lock_screen":
            subprocess.run(
                "loginctl lock-session 2>/dev/null || gnome-screensaver-command -l",
                shell=True,  # nosec B602 - fixed string
                capture_output=True,
                text=True,
            )
            return {
                "status": "success",
                "message": "🔒 Layar desktop Linux telah berhasil dikunci.",
            }

        elif act == "set_volume":
            vol_val = value.replace("%", "").strip() or "50"
            try:
                vol_int = max(0, min(100, int(float(vol_val))))
            except (TypeError, ValueError):
                return {
                    "status": "error",
                    "message": f"Volume '{value}' tidak valid (0-100).",
                }
            try:
                frac = vol_int / 100.0
                subprocess.run(
                    f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {frac}",
                    shell=True,  # nosec B602 - vol_int validated 0-100 int above
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                subprocess.run(
                    f"amixer set Master {vol_int}%",
                    shell=True,  # nosec B602 - vol_int validated 0-100 int above
                    capture_output=True,
                    timeout=3,
                )
            return {
                "status": "success",
                "message": f"🔊 Volume speaker berhasil diubah ke {vol_val}%.",
            }

        elif act == "mute_toggle":
            subprocess.run(
                "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle || amixer set Master toggle",
                shell=True,  # nosec B602 - fixed string
                capture_output=True,
                timeout=3,
            )
            return {
                "status": "success",
                "message": "🔇 Status mute audio berhasil dialihkan (toggle).",
            }

        elif act in ["media_play_pause", "media_next", "media_prev"]:
            cmd = (
                "playerctl play-pause"
                if act == "media_play_pause"
                else "playerctl next"
                if act == "media_next"
                else "playerctl previous"
            )
            subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)  # nosec B602 - cmd from fixed allowlist map above
            return {
                "status": "success",
                "message": f"🎵 Perintah media '{act}' berhasil dieksekusi.",
            }

        elif act == "wifi_scan":
            res = subprocess.run(
                "nmcli -f SSID,SIGNAL,SECURITY dev wifi list | head -n 12",
                shell=True,
                capture_output=True,
                text=True,
                timeout=8,
            )
            return {
                "status": "success",
                "wifi_networks": res.stdout.strip()
                or "Tidak ada jaringan Wi-Fi ditemukan.",
            }

        elif act == "bluetooth_status":
            res = subprocess.run(
                "bluetoothctl show 2>/dev/null | grep -E 'Name|Powered|Discoverable'; bluetoothctl devices 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return {
                "status": "success",
                "bluetooth": res.stdout.strip() or "Bluetooth tidak aktif.",
            }

        elif act == "battery_status":
            bat = psutil.sensors_battery()
            if not bat:
                return {
                    "status": "success",
                    "battery": "Perangkat tidak menggunakan baterai (Desktop PC / Server).",
                }
            plugged = (
                "🔌 Sedang Mengisi Daya (Charging)"
                if bat.power_plugged
                else "🔋 Berjalan dengan Baterai (Discharging)"
            )
            time_left = (
                f"{round(bat.secsleft / 60)} menit" if bat.secsleft > 0 else "N/A"
            )
            return {
                "status": "success",
                "percentage": f"{bat.percent}%",
                "power_state": plugged,
                "estimated_time_remaining": time_left,
            }

        return {
            "status": "error",
            "message": f"Aksi hardware '{action}' tidak dikenal.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
