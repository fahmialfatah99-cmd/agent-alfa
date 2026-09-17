"""Desktop GUI automation, vision, screenshot, and webcam tools."""

import logging
import os
import subprocess
import sys
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Desktop")


@register_tool(category="media")
def capture_desktop_screenshot(*args, **kwargs) -> dict[str, Any]:
    """
    Capture an ultra-fast, high-resolution screenshot of the active desktop screen (Windows, Linux & Mac).
    On Windows: Uses native Win32 GDI screen capture for instant full-resolution multi-monitor screenshot.
    On Linux: Uses Wayland XDG Desktop Portal, grim, ImageMagick, or PIL ImageGrab.
    """
    try:
        screenshot_path = os.path.join(SANDBOX_DIR, "desktop_screen.png")
        if os.path.exists(screenshot_path):
            try:
                os.remove(screenshot_path)
            except OSError:
                pass
        os.makedirs(os.path.dirname(os.path.abspath(screenshot_path)), exist_ok=True)

        # 1. Native Windows GDI Screen Capture (Windows 10 / 11 Native Multi-Monitor)
        if os.name == "nt" or sys.platform == "win32":
            try:
                import ctypes
                import struct

                from PIL import Image

                user32 = ctypes.windll.user32
                gdi32 = ctypes.windll.gdi32
                user32.SetProcessDPIAware()

                left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
                top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
                width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
                height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

                if width <= 0 or height <= 0:
                    left, top = 0, 0
                    width = user32.GetSystemMetrics(0)
                    height = user32.GetSystemMetrics(1)

                hdesktop = user32.GetDesktopWindow()
                desktop_dc = user32.GetWindowDC(hdesktop)
                img_dc = gdi32.CreateCompatibleDC(desktop_dc)
                mem_bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
                gdi32.SelectObject(img_dc, mem_bitmap)
                gdi32.BitBlt(
                    img_dc, 0, 0, width, height, desktop_dc, left, top, 0x00CC0020
                )

                struct_fmt = "<IiiHHIIIIII"
                bmi_bytes = struct.pack(
                    struct_fmt,
                    40,
                    width,
                    -height,
                    1,
                    32,
                    0,
                    width * height * 4,
                    0,
                    0,
                    0,
                    0,
                )
                buf = (ctypes.c_char * (width * height * 4))()
                gdi32.GetDIBits(
                    img_dc,
                    mem_bitmap,
                    0,
                    height,
                    ctypes.byref(buf),
                    ctypes.c_char_p(bmi_bytes),
                    0,
                )

                img = Image.frombuffer(
                    "RGBA", (width, height), buf, "raw", "BGRA", 0, 1
                )
                img = img.convert("RGB")
                img.save(screenshot_path, quality=95)

                gdi32.DeleteObject(mem_bitmap)
                gdi32.DeleteDC(img_dc)
                user32.ReleaseDC(hdesktop, desktop_dc)

                if (
                    os.path.exists(screenshot_path)
                    and os.path.getsize(screenshot_path) > 1000
                ):
                    return {
                        "status": "success",
                        "message": "Screenshot desktop Windows berhasil diambil dengan resolusi penuh.",
                        "file_path": screenshot_path,
                    }
            except Exception as win_err:
                logger.warning(
                    f"Win32 GDI screen capture failed ({win_err}), trying fallbacks..."
                )

        # 2. Native Wayland XDG Desktop Portal (Official GNOME/KDE Wayland Screen Capture)
        if sys.platform.startswith("linux"):
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
                    timeout=4,
                )
                if (
                    p_res.returncode == 0
                    and os.path.exists(screenshot_path)
                    and os.path.getsize(screenshot_path) > 1000
                ):
                    return {
                        "status": "success",
                        "message": "Screenshot desktop berhasil diambil via Wayland Portal.",
                        "file_path": screenshot_path,
                    }
            except Exception:
                pass

            # 3. Try grim (wlroots Wayland compositors like Sway/Hyprland)
            try:
                subprocess.run(
                    f"grim '{screenshot_path}'",
                    shell=True,
                    capture_output=True,
                    timeout=2,
                )
                if (
                    os.path.exists(screenshot_path)
                    and os.path.getsize(screenshot_path) > 1000
                ):
                    return {
                        "status": "success",
                        "message": "Screenshot desktop berhasil diambil via grim.",
                        "file_path": screenshot_path,
                    }
            except Exception:
                pass

            # 4. Try import (ImageMagick)
            try:
                subprocess.run(
                    f"import -window root '{screenshot_path}'",
                    shell=True,
                    capture_output=True,
                    timeout=2,
                )
                if (
                    os.path.exists(screenshot_path)
                    and os.path.getsize(screenshot_path) > 1000
                ):
                    return {
                        "status": "success",
                        "message": "Screenshot desktop berhasil diambil via ImageMagick.",
                        "file_path": screenshot_path,
                    }
            except Exception:
                pass

            # 5. Try scrot (Standard Linux X11 screen capture tool)
            try:
                subprocess.run(
                    f"scrot '{screenshot_path}'",
                    shell=True,
                    capture_output=True,
                    timeout=2,
                )
                if (
                    os.path.exists(screenshot_path)
                    and os.path.getsize(screenshot_path) > 1000
                ):
                    return {
                        "status": "success",
                        "message": "Screenshot desktop berhasil diambil via scrot.",
                        "file_path": screenshot_path,
                    }
            except Exception:
                pass

        # 6. Fallback PIL ImageGrab (Universal / macOS / Linux / Windows)
        try:
            from PIL import ImageGrab

            img = ImageGrab.grab()
            img.save(screenshot_path)
            if (
                os.path.exists(screenshot_path)
                and os.path.getsize(screenshot_path) > 1000
            ):
                return {
                    "status": "success",
                    "message": "Screenshot desktop berhasil diambil via ImageGrab.",
                    "file_path": screenshot_path,
                }
        except Exception:
            pass

        return {
            "status": "error",
            "message": "Gagal mengambil screenshot desktop di lingkungan display saat ini.",
        }
    except Exception as err:
        return {"status": "error", "message": str(err)}


@register_tool(category="media")
def capture_webcam_frame() -> dict[str, Any]:
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
            return {
                "status": "error",
                "message": "Perangkat webcam tidak dapat diakses atau tidak terdeteksi (/dev/video0).",
            }

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
                "file_path": cam_path,
            }
    except Exception as err:
        return {"status": "error", "message": str(err)}


def record_desktop_screen(duration_seconds: int = 10) -> dict[str, Any]:
    """
    Record the desktop screen as an MP4 video for a specified duration and send to Telegram.
    Cross-platform: Windows (ffmpeg gdigrab), Linux (wf-recorder / x11grab).

    Args:
        duration_seconds: Recording duration in seconds (1-60, default: 10).
    """
    try:
        duration = max(1, min(60, duration_seconds))
        output_path = os.path.join(SANDBOX_DIR, "screen_recording.mp4")

        # Windows: ffmpeg dengan capture driver gdigrab
        if os.name == "nt":
            res = subprocess.run(
                f"ffmpeg -y -f gdigrab -framerate 15 -i desktop -t {duration} "
                f'-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p "{output_path}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=duration + 30,
            )
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                return {
                    "status": "success",
                    "message": f"Rekaman layar {duration}s berhasil ({round(size_mb, 2)} MB) dan akan dikirim ke Telegram.",
                }
            err = (res.stderr or "")[-300:]
            return {
                "status": "error",
                "message": f"Gagal merekam layar via ffmpeg/gdigrab: {err}",
            }

        # Try Wayland wf-recorder first
        res = subprocess.run(
            f"timeout {duration + 2} wf-recorder -d /dev/dri/renderD128 -f {output_path} --duration {duration} 2>/dev/null",
            shell=True,
            capture_output=True,
            text=True,
            timeout=duration + 10,
        )
        if (
            res.returncode == 0
            and os.path.exists(output_path)
            and os.path.getsize(output_path) > 0
        ):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return {
                "status": "success",
                "message": f"Rekaman layar {duration}s berhasil ({round(size_mb, 2)} MB) dan akan dikirim ke Telegram.",
            }

        # Fallback to ffmpeg with PipeWire
        res = subprocess.run(
            f"timeout {duration + 5} ffmpeg -y -video_size 1920x1080 -framerate 15 -f x11grab -i :0 -t {duration} -c:v libx264 -preset ultrafast -crf 28 {output_path} 2>/dev/null",
            shell=True,
            capture_output=True,
            text=True,
            timeout=duration + 15,
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return {
                "status": "success",
                "message": f"Rekaman layar {duration}s berhasil via ffmpeg ({round(size_mb, 2)} MB).",
            }

        return {
            "status": "error",
            "message": "Gagal merekam layar. Pastikan wf-recorder atau ffmpeg terinstall.",
        }
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return {
                "status": "success",
                "message": "Rekaman layar berhasil (timeout graceful).",
            }
        return {"status": "error", "message": "Timeout saat merekam layar."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
