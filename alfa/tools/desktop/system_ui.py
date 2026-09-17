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

