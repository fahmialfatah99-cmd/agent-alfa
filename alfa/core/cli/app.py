"""ALFA Sovereign AI - CLI application class and main entrypoint."""

import argparse
import cmd
import os
import sys

import requests

from alfa.core.cli.chat import CliChatMixin
from alfa.core.cli.commands import CliCommandsMixin
from alfa.core.cli.constants import (
    DEFAULT_SERVER,
    RICH_AVAILABLE,
    Colors,
    Console,
    print_banner,
    print_status,
)
from alfa.core.cli.session import CliSessionMixin


class AlfaCLI(CliSessionMixin, CliCommandsMixin, CliChatMixin, cmd.Cmd):
    intro = f"{Colors.GREEN}Selamat datang di ALFA CLI. Ketik '/help' untuk daftar perintah atau langsung chatting!{Colors.ENDC}"
    prompt = f"{Colors.BOLD}alfa>{Colors.ENDC} "

    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url.rstrip("/")
        self.session_token = None
        self.username = None
        self.is_admin = False
        self.chat_history = []
        self.config = self._load_config()
        self.streaming = self.config.get("streaming", False)
        self.console = Console() if RICH_AVAILABLE else None

        self._setup_readline()
        self._load_session()


def main():
    parser = argparse.ArgumentParser(
        description="ALFA Sovereign AI - Advanced CLI Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py                          # Start dengan server default
  python cli.py --server http://IP:8080  # Connect ke remote server
  python cli.py --stream --no-color      # Enable streaming, disable colors
  python cli.py --help                   # Show help message

Features:
  - Slash commands (/help, /clear, /config, etc.)
  - Auto-completion with TAB
  - Command history persistence
  - Rich markdown rendering (install 'rich' package)
  - Streaming responses
  - Session management
  - Configurable themes
        """,
    )
    parser.add_argument(
        "--server",
        type=str,
        default=os.getenv("ALFA_SERVER", DEFAULT_SERVER),
        help=f"URL Server ALFA (default: {DEFAULT_SERVER})",
    )
    parser.add_argument("--no-color", action="store_true", help="Matikan warna output")
    parser.add_argument("--stream", action="store_true", help="Enable streaming mode")

    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    print_banner()

    # Cek koneksi awal
    try:
        r = requests.get(f"{args.server}/health", timeout=5)
        if r.status_code == 200:
            print_status(f"Terhubung ke server: {args.server}", "success")
        else:
            print_status(
                f"Server merespons tapi status code: {r.status_code}", "warning"
            )
    except Exception:
        print_status(
            f"Tidak dapat menghubungi server di {args.server}. Pastikan server berjalan.",
            "error",
        )
        print("Tips: Gunakan flag --server http://ip-address:port jika server remote.")
        # Jangan exit, biarkan user tetap bisa coba login nanti atau exit manual

    try:
        cli = AlfaCLI(args.server)

        # Override streaming from args
        if args.stream:
            cli.streaming = True
            cli.config["streaming"] = True

        cli.cmdloop()
    except KeyboardInterrupt:
        print("\n")
        print_status("Interupsi diterima. Keluar...", "warning")
        sys.exit(0)


if __name__ == "__main__":
    main()
