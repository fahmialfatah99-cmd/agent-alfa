"""Desktop GUI automation, vision, screenshot, and webcam tools."""

import datetime
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Desktop")



@register_tool(category="media")
def capture_desktop_screenshot(*args, **kwargs) -> Dict[str, Any]:
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
        if os.name == 'nt' or sys.platform == 'win32':
            try:
                import ctypes, struct
                from PIL import Image

                user32 = ctypes.windll.user32
                gdi32 = ctypes.windll.gdi32
                user32.SetProcessDPIAware()

                left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
                top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
                width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
                height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN

                if width <= 0 or height <= 0:
                    left, top = 0, 0
                    width = user32.GetSystemMetrics(0)
                    height = user32.GetSystemMetrics(1)

                hdesktop = user32.GetDesktopWindow()
                desktop_dc = user32.GetWindowDC(hdesktop)
                img_dc = gdi32.CreateCompatibleDC(desktop_dc)
                mem_bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
                gdi32.SelectObject(img_dc, mem_bitmap)
                gdi32.BitBlt(img_dc, 0, 0, width, height, desktop_dc, left, top, 0x00CC0020)

                struct_fmt = '<IiiHHIIIIII'
                bmi_bytes = struct.pack(struct_fmt, 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
                buf = (ctypes.c_char * (width * height * 4))()
                gdi32.GetDIBits(img_dc, mem_bitmap, 0, height, ctypes.byref(buf), ctypes.c_char_p(bmi_bytes), 0)

                img = Image.frombuffer('RGBA', (width, height), buf, 'raw', 'BGRA', 0, 1)
                img = img.convert('RGB')
                img.save(screenshot_path, quality=95)

                gdi32.DeleteObject(mem_bitmap)
                gdi32.DeleteDC(img_dc)
                user32.ReleaseDC(hdesktop, desktop_dc)

                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                    return {
                        "status": "success",
                        "message": "Screenshot desktop Windows berhasil diambil dengan resolusi penuh.",
                        "file_path": screenshot_path
                    }
            except Exception as win_err:
                logger.warning(f"Win32 GDI screen capture failed ({win_err}), trying fallbacks...")

        # 2. Native Wayland XDG Desktop Portal (Official GNOME/KDE Wayland Screen Capture)
        if sys.platform.startswith('linux'):
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

            # 3. Try grim (wlroots Wayland compositors like Sway/Hyprland)
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

            # 4. Try import (ImageMagick)
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

            # 5. Try scrot (Standard Linux X11 screen capture tool)
            try:
                subprocess.run(f"scrot '{screenshot_path}'", shell=True, capture_output=True, timeout=2)
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                    return {
                        "status": "success",
                        "message": "Screenshot desktop berhasil diambil via scrot.",
                        "file_path": screenshot_path
                    }
            except Exception:
                pass

        # 6. Fallback PIL ImageGrab (Universal / macOS / Linux / Windows)
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


@register_tool(category="media")
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


@register_tool(category="media")
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


@register_tool(category="media")
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


@register_tool(category="media")
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


@register_tool(category="media")
def vision_click_target(target_description: str, max_attempts: int = 3, action: str = "click") -> Dict[str, Any]:
    """
    GOD MODE: Vision-guided autonomous computer use loop.
    Takes a screenshot of the desktop, sends it to Gemini Vision AI to locate a target
    UI element (button, icon, text, link, menu), clicks on it, then takes another
    screenshot to verify the action succeeded. Repeats if needed.
    
    This allows the bot to operate ANY desktop application (browsers, editors, file managers,
    settings, terminals) purely through visual understanding — like a human looking at a screen.
    
    Args:
        target_description: Natural language description of what to find and click 
                           (e.g. 'the red Close button', 'Firefox icon on taskbar', 
                            'File menu in top left', 'Play button on Spotify',
                            'the search bar', 'Settings gear icon').
        max_attempts: Maximum number of screenshot-analyze-click attempts (1-5, default: 3).
        action: What to do with the found element: 'click' (default), 'double_click', 'right_click', 'identify_only'.
    """
    try:
        import json as _json

        from google import genai
        from google.genai import types
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("GEMINI_API_KEY")
            
        client = genai.Client(api_key=api_key)
        attempts = min(max(1, max_attempts), 5)
        
        for attempt in range(1, attempts + 1):
            # Step 1: Capture desktop screenshot
            capture_desktop_screenshot()
            screenshot_path = os.path.join(SANDBOX_DIR, "desktop_screen.png")
            
            if not os.path.exists(screenshot_path) or os.path.getsize(screenshot_path) == 0:
                return {"status": "error", "message": "Gagal mengambil screenshot desktop untuk vision loop."}
            
            # Step 2: Send to Gemini Vision for coordinate analysis
            with open(screenshot_path, "rb") as f:
                img_bytes = f.read()
            
            image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
            
            vision_prompt = (
                f"Kamu adalah sistem Vision AI untuk GUI automation pada layar Linux desktop 1920x1080.\n"
                f"Analisis screenshot ini dan temukan elemen UI berikut: \"{target_description}\"\n\n"
                f"INSTRUKSI:\n"
                f"1. Identifikasi lokasi elemen tersebut di layar.\n"
                f"2. Berikan koordinat pixel X dan Y dari TITIK TENGAH elemen tersebut.\n"
                f"3. Jika elemen TIDAK DITEMUKAN, jawab dengan found=false.\n\n"
                f"JAWAB DALAM FORMAT JSON SAJA, tanpa teks lain:\n"
                f'{{"found": true/false, "x": <int>, "y": <int>, "element_description": "<apa yang kamu lihat>", "confidence": "<high/medium/low>"}}'
            )
            
            response = client.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
                contents=[image_part, vision_prompt]
            )
            
            response_text = response.text.strip()
            
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                continue
            
            result = _json.loads(json_match.group())
            
            if not result.get("found", False):
                if attempt < attempts:
                    import time
                    time.sleep(1)
                    continue
                return {
                    "status": "error",
                    "message": f"Elemen '{target_description}' tidak ditemukan di layar setelah {attempts} percobaan.",
                    "vision_response": result.get("element_description", "")
                }
            
            x = int(result["x"])
            y = int(result["y"])
            confidence = result.get("confidence", "unknown")
            desc = result.get("element_description", "")
            
            if action == "identify_only":
                # Remove the screenshot from sandbox so it doesn't get auto-sent
                try:
                    os.remove(screenshot_path)
                except OSError:
                    pass
                return {
                    "status": "success",
                    "message": f"Elemen ditemukan di koordinat ({x}, {y}).",
                    "coordinates": {"x": x, "y": y},
                    "element_description": desc,
                    "confidence": confidence,
                    "attempt": attempt
                }
            
            # Remove pre-click screenshot
            try:
                os.remove(screenshot_path)
            except OSError:
                pass
            
            # Step 3: Click the target
            clicks = 2 if action == "double_click" else 1
            button = "right" if action == "right_click" else "left"
            desktop_click_coordinate(x=x, y=y, button=button, clicks=clicks)
            
            # Step 4: Wait briefly then take verification screenshot
            import time
            time.sleep(0.8)
            capture_desktop_screenshot()
            
            return {
                "status": "success",
                "message": f"Vision Loop berhasil! Elemen '{target_description}' ditemukan dan di-{action} pada koordinat ({x}, {y}). Screenshot verifikasi akan dikirim ke Telegram.",
                "coordinates": {"x": x, "y": y},
                "element_description": desc,
                "confidence": confidence,
                "attempt": attempt,
                "action_performed": action
            }
        
        return {"status": "error", "message": f"Gagal menemukan '{target_description}' setelah {attempts} percobaan vision loop."}
    except Exception as e:
        return {"status": "error", "message": f"Vision loop error: {str(e)}"}


@register_tool(category="media")
def record_desktop_screen(duration_seconds: int = 10) -> Dict[str, Any]:
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
                f'ffmpeg -y -f gdigrab -framerate 15 -i desktop -t {duration} '
                f'-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p "{output_path}"',
                shell=True, capture_output=True, text=True, timeout=duration + 30
            )
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                return {"status": "success", "message": f"Rekaman layar {duration}s berhasil ({round(size_mb, 2)} MB) dan akan dikirim ke Telegram."}
            err = (res.stderr or "")[-300:]
            return {"status": "error", "message": f"Gagal merekam layar via ffmpeg/gdigrab: {err}"}
        
        # Try Wayland wf-recorder first
        res = subprocess.run(
            f"timeout {duration + 2} wf-recorder -d /dev/dri/renderD128 -f {output_path} --duration {duration} 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=duration + 10
        )
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return {"status": "success", "message": f"Rekaman layar {duration}s berhasil ({round(size_mb, 2)} MB) dan akan dikirim ke Telegram."}
        
        # Fallback to ffmpeg with PipeWire
        res = subprocess.run(
            f"timeout {duration + 5} ffmpeg -y -video_size 1920x1080 -framerate 15 -f x11grab -i :0 -t {duration} -c:v libx264 -preset ultrafast -crf 28 {output_path} 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=duration + 15
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            return {"status": "success", "message": f"Rekaman layar {duration}s berhasil via ffmpeg ({round(size_mb, 2)} MB)."}
        
        return {"status": "error", "message": "Gagal merekam layar. Pastikan wf-recorder atau ffmpeg terinstall."}
    except subprocess.TimeoutExpired:
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return {"status": "success", "message": "Rekaman layar berhasil (timeout graceful)."}
        return {"status": "error", "message": "Timeout saat merekam layar."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="media")
def read_clipboard() -> Dict[str, Any]:
    """
    Read the current desktop clipboard content (Windows: PowerShell, Linux: wl-paste/xclip/xsel).
    """
    try:
        if os.name == "nt":
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5)
            content = (res.stdout or "").strip()
        else:
            # Try Wayland wl-paste
            res = subprocess.run("wl-paste 2>/dev/null || xclip -selection clipboard -o 2>/dev/null || xsel --clipboard --output 2>/dev/null",
                                 shell=True, capture_output=True, text=True, timeout=3)
            content = res.stdout.strip()
        if content:
            return {"status": "success", "clipboard_content": content[:5000]}
        return {"status": "success", "clipboard_content": "(Clipboard kosong)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="media")
def write_to_clipboard(text: str) -> Dict[str, Any]:
    """
    Write/copy text to the desktop clipboard so it can be pasted (Ctrl+V) anywhere.
    
    Args:
        text: The text string to copy to clipboard.
    """
    try:
        if os.name == "nt":
            import base64 as _b64
            encoded = _b64.b64encode(text.encode("utf-16-le")).decode("ascii")
            cmd = ("$t=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + encoded + "')); "
                   "Set-Clipboard -Value $t")
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                                 capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return {"status": "success", "message": f"Teks berhasil disalin ke clipboard ({len(text)} karakter). Siap di-paste (Ctrl+V)."}
            return {"status": "error", "message": f"Set-Clipboard gagal: {(res.stderr or '')[:200]}"}
        proc = subprocess.Popen("wl-copy 2>/dev/null || xclip -selection clipboard 2>/dev/null",
                                shell=True, stdin=subprocess.PIPE, text=True)
        proc.communicate(input=text, timeout=3)
        return {"status": "success", "message": f"Teks berhasil disalin ke clipboard ({len(text)} karakter). Siap di-paste (Ctrl+V)."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="media")
def show_desktop_notification(title: str, message: str, urgency: str = "normal") -> Dict[str, Any]:
    """
    Show a native desktop popup notification across Linux, macOS, and Windows.
    
    Args:
        title: Notification title.
        message: Notification body text.
        urgency: 'low', 'normal', or 'critical'.
    """
    import sys
    try:
        if sys.platform == "darwin":  # macOS
            apple_script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", apple_script], capture_output=True, text=True, timeout=3)
        elif sys.platform == "win32":  # Windows
            ps_cmd = (
                f"[reflection.assembly]::loadwithpartialname('System.Windows.Forms');"
                f"$notify = new-object system.windows.forms.notifyicon;"
                f"$notify.icon = [system.drawing.systemicons]::information;"
                f"$notify.visible = $true;"
                f"$notify.showballoontip(10, '{title}', '{message}', [system.windows.forms.tooltipicon]::None)"
            )
            subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=3)
        else:  # Linux / Unix
            subprocess.run(
                ["notify-send", f"--urgency={urgency}", "--app-name=AgentALFA", title, message],
                capture_output=True, text=True, timeout=3
            )
        return {"status": "success", "message": f"Notifikasi desktop '{title}' berhasil ditampilkan di layar."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

