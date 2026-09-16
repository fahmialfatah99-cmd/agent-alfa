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

from alfa.tools.desktop.capture import capture_desktop_screenshot

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


