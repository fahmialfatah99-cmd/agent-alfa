"""CLI constants, terminal colors, and status helpers."""

import os
import platform
import sys
from pathlib import Path

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

try:
    import requests
except ImportError:
    print("❌ Error: Library 'requests' tidak ditemukan.")
    print("   Silakan install dengan: pip install requests")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.live import Live
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None

VERSION = "3.0.0"
DEFAULT_SERVER = "http://localhost:8080"
SESSION_FILE = Path.home() / ".alfa_cli_session.json"
CONFIG_FILE = Path.home() / ".alfa_cli_config.json"
HISTORY_FILE = Path.home() / ".alfa_cli_history"
TIMEOUT = 120
MAX_HISTORY_LENGTH = 1000

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GRAY = '\033[90m'
    WHITE = '\033[97m'

    @staticmethod
    def disable():
        if platform.system() == "Windows":
            pass 
        Colors.HEADER = ''
        Colors.BLUE = ''
        Colors.CYAN = ''
        Colors.GREEN = ''
        Colors.WARNING = ''
        Colors.FAIL = ''
        Colors.ENDC = ''
        Colors.BOLD = ''
        Colors.UNDERLINE = ''
        Colors.GRAY = ''
        Colors.WHITE = ''

# Cek apakah output ke terminal mendukung warna
if not sys.stdout.isatty():
    Colors.disable()

def print_banner():
    banner = f"""
{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗
║           ALFA Sovereign AI - CLI Client v{VERSION:<3}         ║
║                  Secure Terminal Interface                    ║
║     Type '/help' for commands or just start chatting!         ║
╚═══════════════════════════════════════════════════════════╝{Colors.ENDC}
    """
    print(banner)

def print_status(msg, status="info"):
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "error": "❌",
        "warning": "⚠️",
        "thinking": "🤔",
        "loading": "⏳"
    }
    colors = {
        "info": Colors.BLUE,
        "success": Colors.GREEN,
        "error": Colors.FAIL,
        "warning": Colors.WARNING,
        "thinking": Colors.CYAN,
        "loading": Colors.GRAY
    }
    
    icon = icons.get(status, "ℹ️")
    color = colors.get(status, Colors.BLUE)
    
    print(f"{color}{icon} {msg}{Colors.ENDC}")

