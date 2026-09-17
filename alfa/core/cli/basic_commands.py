"""Command handlers for ALFA CLI."""

import getpass
import json
import os
import platform
import sys

from alfa.core.cli.constants import (
    RICH_AVAILABLE,
    Colors,
    Console,
    Panel,
    print_banner,
    print_status,
)


class CliBasicCommandsMixin:
    """Implements basic command handlers (register, login, stats, etc.)."""

    def do_register(self, arg):
        """Daftar akun baru. Usage: register <username>"""
        username = arg.strip()
        if not username:
            username = input("Masukkan username: ").strip()

        if not username:
            print_status("Username tidak boleh kosong.", "error")
            return

        password = getpass.getpass("Masukkan password: ")
        confirm = getpass.getpass("Konfirmasi password: ")

        if password != confirm:
            print_status("Password tidak cocok!", "error")
            return

        payload = {"username": username, "password": password}
        res = self._request("POST", "/api/auth/register", payload)

        if res:
            if res.status_code == 201:
                print_status(
                    f"Akun '{username}' berhasil dibuat! Silakan login.", "success"
                )
                # Auto login setelah register
                self.do_login(username)
            else:
                try:
                    msg = res.json().get("detail", "Registrasi gagal")
                except:
                    msg = res.text
                print_status(msg, "error")

    def do_login(self, arg):
        """Login ke akun. Usage: login <username>"""
        username = arg.strip()
        if not username:
            username = input("Username: ").strip()

        if not username:
            print_status("Username diperlukan.", "error")
            return

        password = getpass.getpass("Password: ")
        payload = {"username": username, "password": password}

        print_status("Sedang login...", "info")
        res = self._request("POST", "/api/auth/login", payload)

        if res:
            if res.status_code == 200:
                data = res.json()
                self.session_token = data.get("access_token") or data.get("token")
                self.username = username
                # Cek admin status
                me_res = self._request("GET", "/api/auth/me")
                if me_res and me_res.status_code == 200:
                    me_data = me_res.json()
                    self.is_admin = me_data.get("user", {}).get(
                        "is_admin", False
                    ) or me_data.get("is_admin", False)

                self._save_session()
                self._update_prompt()
                print_status(f"Login berhasil sebagai {self.username}!", "success")
            else:
                try:
                    msg = res.json().get("detail", "Login gagal")
                except:
                    msg = "Username atau password salah."
                print_status(msg, "error")

    def do_logout(self, arg):
        """Logout dari akun saat ini."""
        if self.session_token:
            self._request("POST", "/api/auth/logout")  # Optional invalidate di server
        self._clear_session()
        print_status("Berhasil logout.", "success")

    def do_stats(self, arg):
        """Melihat statistik sistem ALFA."""
        if not self.session_token:
            print_status("Anda harus login terlebih dahulu.", "warning")
            return

        res = self._request("GET", "/api/stats")
        if res and res.status_code == 200:
            data = res.json()
            print("\n" + "=" * 30)
            print(f"{Colors.BOLD}📊 Statistik Sistem{Colors.ENDC}")
            print("=" * 30)
            for key, value in data.items():
                print(f"{Colors.CYAN}{key}:{Colors.ENDC} {value}")
            print("=" * 30 + "\n")
        else:
            print_status("Gagal mengambil statistik.", "error")

    def do_tools(self, arg):
        """Melihat daftar tools yang tersedia."""
        if not self.session_token:
            print_status("Anda harus login terlebih dahulu.", "warning")
            return

        # Asumsi endpoint /api/tools ada, jika tidak fallback
        res = self._request("GET", "/api/tools")
        if res and res.status_code == 200:
            data = res.json()
            tools = data if isinstance(data, list) else data.get("tools", [])
            print(f"\n{Colors.BOLD}🛠️ Daftar Tools ({len(tools)}):{Colors.ENDC}\n")
            for i, tool in enumerate(tools[:20], 1):  # Tampilkan 20 pertama
                name = (
                    tool.get("name", "Unknown") if isinstance(tool, dict) else str(tool)
                )
                desc = tool.get("description", "") if isinstance(tool, dict) else ""
                print(f"{i}. {Colors.GREEN}{name}{Colors.ENDC}")
                if desc:
                    print(f"   {Colors.WARNING}{desc}{Colors.ENDC}")
            if len(tools) > 20:
                print(f"... dan {len(tools)-20} tools lainnya.")
            print()
        else:
            print_status(
                "Gagal mengambil daftar tools atau endpoint belum tersedia.", "error"
            )

    def do_clear(self, arg):
        """Membersihkan layar terminal."""
        os.system("cls" if platform.system() == "Windows" else "clear")
        print_banner()

    def do_exit(self, arg):
        """Keluar dari aplikasi."""
        print_status(
            "Terima kasih telah menggunakan ALFA CLI. Sampai jumpa!", "success"
        )
        return True

    def do_q(self, arg):
        """Alias untuk exit."""
        return self.do_exit(arg)

    # --- Slash Commands (Modern CLI Style) ---

    def do_slash_help(self, arg):
        """Tampilkan bantuan lengkap. Usage: /help"""
        help_text = f"""
{Colors.BOLD}📚 ALFA CLI - Daftar Perintah Lengkap{Colors.ENDC}
{'='*50}

{Colors.CYAN}🔐 Authentication:{Colors.ENDC}
  /login     - Login ke akun Anda
  /logout    - Logout dari sesi saat ini
  /register  - Daftar akun baru

{Colors.CYAN}💬 Chat & Interaction:{Colors.ENDC}
  [pesan]    - Langsung ketik pesan untuk chatting
  /clear     - Bersihkan layar terminal
  /history   - Lihat riwayat chat
  /stream on|off - Toggle streaming mode

{Colors.CYAN}🛠️ System & Tools:{Colors.ENDC}
  /tools     - Lihat daftar tools AI yang tersedia
  /stats     - Tampilkan statistik sistem
  /models    - Lihat model AI yang aktif
  /agents    - Lihat status swarm agents

{Colors.CYAN}⚙️ Configuration:{Colors.ENDC}
  /config    - Lihat/ubah konfigurasi CLI
  /theme     - Ubah tema warna
  /upload    - Upload file ke server
  /download  - Download file dari server

{Colors.CYAN}🤖 AI Provider Settings:{Colors.ENDC}
  /provider  - Set provider AI (openai/anthropic/google/ollama/etc)
  /settings  - Advanced AI settings (temperature, max_tokens, etc)
  /switch    - Quick switch presets (fast/smart/creative/precise/coding)

{Colors.CYAN}❌ Exit:{Colors.ENDC}
  /exit      - Keluar dari aplikasi
  /quit      - Alias untuk exit

{Colors.GRAY}Tips: Tekan TAB untuk auto-complete perintah!{Colors.ENDC}
"""
        print(help_text)

    def do_slash_clear(self, arg):
        """Bersihkan layar. Usage: /clear"""
        os.system("cls" if platform.system() == "Windows" else "clear")
        print_banner()

    def do_slash_exit(self, arg):
        """Keluar dari aplikasi. Usage: /exit"""
        self._save_history()
        print_status(
            "Terima kasih telah menggunakan ALFA CLI. Sampai jumpa!", "success"
        )
        return True

    def do_slash_quit(self, arg):
        """Alias untuk exit. Usage: /quit"""
        return self.do_slash_exit(arg)

    def do_slash_history(self, arg):
        """Lihat riwayat chat. Usage: /history [jumlah]"""
        if not self.chat_history:
            print_status("Belum ada riwayat chat.", "info")
            return

        limit = int(arg.strip()) if arg.strip().isdigit() else 10
        recent = self.chat_history[-limit * 2 :]  # User + assistant pairs

        print(
            f"\n{Colors.BOLD}📜 Riwayat Chat ({len(recent)//2} percakapan):{Colors.ENDC}\n"
        )
        for i in range(0, len(recent), 2):
            user_msg = recent[i].get("content", "")[:100]
            print(f"{Colors.CYAN}You:{Colors.ENDC} {user_msg}...")
            if i + 1 < len(recent):
                assistant_msg = recent[i + 1].get("content", "")[:100]
                print(f"{Colors.GREEN}ALFA:{Colors.ENDC} {assistant_msg}...\n")

    def do_slash_config(self, arg):
        """Lihat/ubah konfigurasi. Usage: /config [key=value]"""
        if not arg:
            print(f"\n{Colors.BOLD}⚙️ Konfigurasi Saat Ini:{Colors.ENDC}")
            for key, value in self.config.items():
                print(f"  {Colors.CYAN}{key}:{Colors.ENDC} {value}")
            print()
            return

        # Update config
        if "=" in arg:
            key, value = arg.split("=", 1)
            key = key.strip()
            value = value.strip().lower()

            if value in ["true", "yes", "1"]:
                value = True
            elif value in ["false", "no", "0"]:
                value = False

            self.config[key] = value
            self._save_config()
            print_status(f"Konfigurasi '{key}' diperbarui menjadi {value}", "success")

            # Apply config changes
            if key == "streaming":
                self.streaming = value

    def do_slash_theme(self, arg):
        """Ubah tema. Usage: /theme [default|minimal|colorful]"""
        themes = ["default", "minimal", "colorful"]
        if not arg or arg not in themes:
            print(f"Tema tersedia: {', '.join(themes)}")
            return

        self.config["theme"] = arg
        self._save_config()
        print_status(
            f"Tema diubah ke '{arg}'. Restart CLI untuk melihat perubahan.", "success"
        )

    def do_slash_stream(self, arg):
        """Toggle streaming mode. Usage: /stream on|off"""
        if arg.lower() == "on":
            self.streaming = True
            self.config["streaming"] = True
            print_status("Streaming mode: ON", "success")
        elif arg.lower() == "off":
            self.streaming = False
            self.config["streaming"] = False
            print_status("Streaming mode: OFF", "success")
        else:
            current = "ON" if self.streaming else "OFF"
            print_status(
                f"Streaming mode saat ini: {current}. Gunakan '/stream on' atau '/stream off'",
                "info",
            )

        self._save_config()

    def do_slash_tools(self, arg):
        """Lihat tools. Usage: /tools"""
        self.do_tools(arg)

    def do_slash_stats(self, arg):
        """Lihat statistik. Usage: /stats"""
        self.do_stats(arg)

    def do_slash_login(self, arg):
        """Login. Usage: /login"""
        self.do_login(arg)

    def do_slash_logout(self, arg):
        """Logout. Usage: /logout"""
        self.do_logout(arg)

    def do_slash_register(self, arg):
        """Register. Usage: /register"""
        self.do_register(arg)
