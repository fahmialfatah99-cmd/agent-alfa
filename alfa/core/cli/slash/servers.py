"""Slash-command mixin: Background server orchestration and file transfer commands."""

import os

from alfa.core.cli.constants import Colors, print_status


class SlashServersMixin:
    """Background server orchestration and file transfer commands."""

    def do_slash_servers(self, arg: str) -> None:
        """Kelola & pantau server latar belakang ALFA (Dashboard, 9Router, Bot). Usage: /servers [status|start|stop|restart]"""
        from alfa.core.cli.server_manager import (
            auto_start_all_servers,
            get_servers_status,
            stop_all_servers,
        )

        sub = arg.strip().lower() or "status"

        if sub == "status":
            statuses = get_servers_status()
            print(f"\n{Colors.BOLD}🌐 Status Server Ekosistem ALFA:{Colors.ENDC}")
            dash = statuses["dashboard"]
            r9 = statuses["9router"]
            bot = statuses["bot"]

            print(
                f"  {'🟢' if dash['ok'] else '🔴'} Web Command Center : {Colors.CYAN}{dash['status']}{Colors.ENDC}"
            )
            print(
                f"  {'🔀' if r9['ok'] else '⚪'} 9Router AI Gateway : {Colors.CYAN}{r9['status']}{Colors.ENDC}"
            )
            print(
                f"  {'🤖' if bot['ok'] else '⚪'} Telegram AI Bot    : {Colors.CYAN}{bot['status']}{Colors.ENDC}\n"
            )
            print(
                f"Perintah: {Colors.CYAN}/servers start{Colors.ENDC} | {Colors.CYAN}/servers restart{Colors.ENDC} | {Colors.CYAN}/servers stop{Colors.ENDC}\n"
            )

        elif sub == "start":
            print_status("Memulai semua server ekosistem ALFA...", "info")
            auto_start_all_servers(verbose=True)
            self.server_reachable = True

        elif sub == "stop":
            print_status("Menghentikan server latar belakang...", "warning")
            stop_all_servers()
            self.server_reachable = False
            print_status("Server berhasil dihentikan.", "success")

        elif sub == "restart":
            print_status("Me-restart semua server ekosistem ALFA...", "info")
            stop_all_servers()
            import time

            time.sleep(1)
            auto_start_all_servers(verbose=True)
            self.server_reachable = True

        else:
            print_status(
                "Subcommand tidak dikenal. Pilihan: status, start, stop, restart",
                "error",
            )

    def do_slash_upload(self, arg: str) -> None:
        """Upload file ke server ALFA. Usage: /upload <filepath>"""
        if not getattr(self, "session_token", None):
            print_status("Login terlebih dahulu.", "warning")
            return
        filepath = arg.strip()
        if not filepath:
            filepath = input("Path file: ").strip()
        if not os.path.exists(filepath):
            print_status(f"File tidak ditemukan: {filepath}", "error")
            return
        print_status("Endpoint upload sedang disiapkan di backend server.", "info")

    def do_slash_download(self, arg: str) -> None:
        """Download file dari server ALFA. Usage: /download <filename>"""
        if not getattr(self, "session_token", None):
            print_status("Login terlebih dahulu.", "warning")
            return
        print_status("Endpoint download sedang disiapkan di backend server.", "info")
