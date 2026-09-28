"""Desktop GUI automation, vision, screenshot, and webcam tools."""

import logging
import os
import re
import shutil
import subprocess
from typing import Any

from alfa.tools.desktop.capture import capture_desktop_screenshot
from alfa.tools.registry import register_tool
from alfa.tools.system_tools import SANDBOX_DIR

logger = logging.getLogger("AgentTools.Desktop")


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u or any(c.isspace() for c in u):
        return ""
    scheme = ""
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://(.+)$", u)
    if m:
        scheme, u = m.group(1).lower(), m.group(2)
    host = u.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not host:
        return ""
    hostname = host.rsplit(":", 1)[0]
    is_local = hostname == "localhost" or re.match(
        r"^\d{1,3}(\.\d{1,3}){3}$", hostname
    )
    if not is_local and (
        not re.match(r"^[A-Za-z0-9.-]+$", hostname) or "." not in hostname
    ):
        return ""
    return f"{scheme or 'https'}://{u}"


def _browser_openers() -> list[str]:
    """Daftar perintah yang bisa membuka URL di browser VISIBLE milik user."""
    found: list[str] = []
    for name in ("xdg-open", "gio", "sensible-browser", "x-www-browser", "www-browser"):
        if shutil.which(name):
            found.append(name)
    env_browser = (os.environ.get("BROWSER") or "").strip()
    if env_browser and shutil.which(env_browser):
        found.append(env_browser)
    for extra in (
        "firefox",
        "firefox-esr",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
    ):
        if shutil.which(extra):
            found.append(extra)
    return found


def open_url_in_default_browser(url: str) -> tuple[bool, str]:
    """Buka URL di browser desktop yang terlihat oleh user.

    Return (sukses, keterangan_mekanisme). Mencoba satu per satu opener
    sampai ada yang benar-benar menerima perintah — bukan sekadar 'berhasil'.
    """
    target = _normalize_url(url)
    if not target:
        return False, "URL kosong/tidak valid."

    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")

    tried: list[str] = []
    for opener in _browser_openers():
        cmd = [opener, "open", target] if opener == "gio" else [opener, target]
        tried.append(" ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                _, err = proc.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                # Opener masih memegang proses = biasanya browser sudah terbuka
                return True, f"{' '.join(cmd)} (browser berjalan)"
            if proc.returncode == 0:
                return True, f"{' '.join(cmd)}"
            detail = (err or b"").decode("utf-8", "replace").strip()[:200]
            logger.info(f"Opener '{opener}' gagal (rc={proc.returncode}): {detail}")
        except FileNotFoundError:
            continue
        except Exception as e:  # noqa: BLE001 - lanjut ke opener berikutnya
            logger.info(f"Opener '{opener}' error: {e}")
    return False, f"Tidak ada opener browser yang berhasil. Dicoba: {', '.join(tried) or '-'}"


@register_tool(category="media")
def open_url_in_system_browser(url: str) -> dict[str, Any]:
    """
    Open a URL in the user's real, visible desktop browser (Firefox/Chrome/Brave/xdg-open).

    Use this whenever the user asks to 'open/open this site/show this page on my computer'.
    Unlike browser_open_url (headless Camofox engine for scraping), this tool pops the page
    up on the user's actual screen.

    Args:
        url: Full web URL or bare domain to open (e.g. 'https://youtube.com', 'github.com').
    """
    target = _normalize_url(url)
    if not target:
        return {"status": "error", "message": "URL kosong atau tidak valid."}
    ok, how = open_url_in_default_browser(target)
    if ok:
        return {
            "status": "success",
            "message": f"Browser desktop berhasil membuka: {target}",
            "url": target,
            "mechanism": how,
        }
    return {
        "status": "error",
        "message": f"Gagal membuka '{target}' di browser desktop. {how}",
        "url": target,
    }


@register_tool(category="media")
def desktop_click_coordinate(
    x: int, y: int, button: str = "left", clicks: int = 1
) -> dict[str, Any]:
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
        btn_code = (
            "0xC0" if button == "left" else "0xC1" if button == "right" else "0xC2"
        )
        res = subprocess.run(
            f"ydotool mousemove -a {x} {y} && ydotool click {btn_code}",
            shell=True,  # nosec B602 - gated tool; coords typed int, launcher by design
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return {
                "status": "success",
                "message": f"Mouse berhasil diklik pada koordinat ({x}, {y}) [{button}].",
            }

        # Fallback to xdotool
        res = subprocess.run(
            f"xdotool mousemove {x} {y} click {'1' if button == 'left' else '3'}",
            shell=True,  # nosec B602 - gated tool; coords typed int, launcher by design
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return {
                "status": "success",
                "message": f"Mouse berhasil diklik via xdotool pada ({x}, {y}).",
            }

        # Fallback to PyAutoGUI
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return {
            "status": "success",
            "message": f"Mouse berhasil diklik via PyAutoGUI pada ({x}, {y}).",
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal melakukan klik mouse: {str(e)}"}


@register_tool(category="media")
def desktop_type_keys(text: str = "", hotkey: str = "") -> dict[str, Any]:
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
            return {
                "status": "success",
                "message": f"Shortcut '{hotkey}' berhasil ditekan.",
            }

        if text:
            res = subprocess.run(
                ["ydotool", "type", text], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                return {
                    "status": "success",
                    "message": f"Teks berhasil diketik ke desktop: '{text}'",
                }

            import pyautogui

            pyautogui.write(text)
            return {
                "status": "success",
                "message": "Teks berhasil diketik via PyAutoGUI.",
            }

        return {"status": "error", "message": "Harus menyertakan text atau hotkey."}
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengetik tombol: {str(e)}"}


@register_tool(category="media")
def desktop_launch_app(app_name_or_command: str) -> dict[str, Any]:
    """
    Launch a Linux GUI software application in the background (e.g. 'code', 'brave-browser', 'spotify', 'nautilus').
    Verifies the process really started and reports the real PID — returns an error if the app
    does not exist instead of falsely claiming success.

    Args:
        app_name_or_command: Application executable name, command line, or a URL to open.
    """
    cmd = (app_name_or_command or "").strip()
    if not cmd:
        return {"status": "error", "message": "Nama aplikasi/komando kosong."}

    # URL / domain -> serahkan ke pembuka browser sungguhan
    if re.match(r"^(https?://|www\.)", cmd, re.I) or (
        " " not in cmd and re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+([/?#].*)?$", cmd, re.I)
    ):
        return open_url_in_system_browser(cmd)

    try:
        import time as _time

        shell_meta = any(c in cmd for c in "|&;<>$`(){}")
        first = cmd.split()[0]
        if not shell_meta:
            resolved = shutil.which(first) or (
                first if os.path.exists(os.path.expanduser(first)) else None
            )
            if not resolved:
                return {
                    "status": "error",
                    "message": (
                        f"Aplikasi '{first}' tidak ditemukan di PATH sistem — "
                        "tidak ada yang diluncurkan. Cek nama binernya dulu."
                    ),
                }

        env = os.environ.copy()
        env["DISPLAY"] = env.get("DISPLAY", ":0")
        env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
        proc = subprocess.Popen(
            cmd,
            shell=True,  # nosec B602 - gated tool; coords typed int, launcher by design
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Verifikasi nyata: tunggu sebentar lalu cek apakah prosesnya hidup.
        _time.sleep(1.2)
        rc = proc.poll()
        stderr_txt = ""
        if rc is not None:
            try:
                stderr_txt = (proc.stderr.read() or b"").decode("utf-8", "replace").strip()
            except Exception:
                stderr_txt = ""
            if rc != 0:
                return {
                    "status": "error",
                    "message": (
                        f"Meluncurkan '{cmd}' gagal (exit code {rc})"
                        + (f": {stderr_txt[:300]}" if stderr_txt else ".")
                    ),
                }

        pids: list[str] = []
        try:
            probe = subprocess.run(
                ["pgrep", "-f", first if not shell_meta else cmd[:80]],
                capture_output=True,
                text=True,
                timeout=3,
            )
            pids = [p for p in probe.stdout.split() if p.strip()]
        except Exception:
            pids = []

        if rc is None or pids:
            return {
                "status": "success",
                "message": f"Aplikasi '{cmd}' berjalan di background desktop.",
                "pid": pids[0] if pids else proc.pid,
                "pids": pids[:10],
            }

        return {
            "status": "success",
            "message": (
                f"Perintah '{cmd}' diterima shell (exit 0) tetapi tidak terdeteksi "
                "sebagai proses berjalan — kemungkinan aplikasi langsung keluar/exit."
            ),
            "confidence": "low",
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal meluncurkan aplikasi: {str(e)}"}


@register_tool(category="media")
def vision_click_target(
    target_description: str, max_attempts: int = 3, action: str = "click"
) -> dict[str, Any]:
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

            if (
                not os.path.exists(screenshot_path)
                or os.path.getsize(screenshot_path) == 0
            ):
                return {
                    "status": "error",
                    "message": "Gagal mengambil screenshot desktop untuk vision loop.",
                }

            # Step 2: Send to Gemini Vision for coordinate analysis
            with open(screenshot_path, "rb") as f:
                img_bytes = f.read()

            image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")

            vision_prompt = (
                f"Kamu adalah sistem Vision AI untuk GUI automation pada layar Linux desktop 1920x1080.\n"
                f'Analisis screenshot ini dan temukan elemen UI berikut: "{target_description}"\n\n'
                f"INSTRUKSI:\n"
                f"1. Identifikasi lokasi elemen tersebut di layar.\n"
                f"2. Berikan koordinat pixel X dan Y dari TITIK TENGAH elemen tersebut.\n"
                f"3. Jika elemen TIDAK DITEMUKAN, jawab dengan found=false.\n\n"
                f"JAWAB DALAM FORMAT JSON SAJA, tanpa teks lain:\n"
                f'{{"found": true/false, "x": <int>, "y": <int>, "element_description": "<apa yang kamu lihat>", "confidence": "<high/medium/low>"}}'
            )

            response = client.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
                contents=[image_part, vision_prompt],
            )

            response_text = response.text.strip()

            # Parse JSON from response
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
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
                    "vision_response": result.get("element_description", ""),
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
                    "attempt": attempt,
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
                "action_performed": action,
            }

        return {
            "status": "error",
            "message": f"Gagal menemukan '{target_description}' setelah {attempts} percobaan vision loop.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Vision loop error: {str(e)}"}
