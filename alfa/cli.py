#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALFA Sovereign AI - Command Line Interface (CLI)
Cross-platform terminal client for ALFA Agent.

Usage:
    python -m alfa.cli
    python -m alfa.cli --server http://localhost:8080
    alfa-cli --server http://localhost:8080
"""

import cmd
import json
import os
import sys
import platform
import getpass
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Try to import requests
try:
    import requests
except ImportError:
    print("❌ Error: Library 'requests' tidak ditemukan.")
    print("   Silakan install dengan: pip install requests")
    sys.exit(1)

# --- Constants & Configuration ---
VERSION = "2.5.0"
DEFAULT_SERVER = "http://localhost:8080"
SESSION_FILE = Path.home() / ".alfa_cli_session.json"
TIMEOUT = 120  # Request timeout in seconds


class Colors:
    """ANSI color codes for terminal output."""
    
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    @staticmethod
    def disable():
        """Disable all colors."""
        Colors.HEADER = ''
        Colors.BLUE = ''
        Colors.CYAN = ''
        Colors.GREEN = ''
        Colors.WARNING = ''
        Colors.FAIL = ''
        Colors.ENDC = ''
        Colors.BOLD = ''
        Colors.UNDERLINE = ''


# Disable colors if not outputting to terminal
if not sys.stdout.isatty():
    Colors.disable()


def print_banner():
    """Print the ALFA CLI banner."""
    banner = f"""
{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗
║           ALFA Sovereign AI - CLI Client v{VERSION:<3}         ║
║                  Secure Terminal Interface                    ║
╚═══════════════════════════════════════════════════════════╝{Colors.ENDC}
    """
    print(banner)


def print_status(msg: str, status: str = "info"):
    """Print a status message with icon and color."""
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "error": "❌",
        "warning": "⚠️"
    }
    colors = {
        "info": Colors.BLUE,
        "success": Colors.GREEN,
        "error": Colors.FAIL,
        "warning": Colors.WARNING
    }
    
    icon = icons.get(status, "ℹ️")
    color = colors.get(status, Colors.BLUE)
    
    print(f"{color}{icon} {msg}{Colors.ENDC}")


class AlfaCLI(cmd.Cmd):
    """ALFA Command Line Interface."""
    
    intro = f"{Colors.GREEN}Selamat datang di ALFA CLI. Ketik 'help' atau '?' untuk daftar perintah.{Colors.ENDC}"
    prompt = f"{Colors.BOLD}alfa>{Colors.ENDC} "
    
    def __init__(self, server_url: str):
        super().__init__()
        self.server_url = server_url.rstrip('/')
        self.session_token: Optional[str] = None
        self.username: Optional[str] = None
        self.is_admin: bool = False
        self.chat_history: List[Dict[str, str]] = []
        
        # Load existing session if available
        self._load_session()
    
    def _load_session(self):
        """Load session from file if exists."""
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, 'r') as f:
                    data = json.load(f)
                    self.session_token = data.get('token')
                    self.username = data.get('username')
                    self.is_admin = data.get('is_admin', False)
                    
                    # Validate session
                    if self._check_auth():
                        print_status(f"Session ditemukan. Selamat datang kembali, {self.username}!", "success")
                        self._update_prompt()
                        return
                    else:
                        print_status("Session kadaluarsa atau tidak valid. Silakan login.", "warning")
                        self._clear_session()
            except Exception:
                self._clear_session()
    
    def _save_session(self):
        """Save current session to file."""
        if self.session_token and self.username:
            data = {
                'token': self.session_token,
                'username': self.username,
                'is_admin': self.is_admin,
                'saved_at': datetime.now().isoformat()
            }
            try:
                with open(SESSION_FILE, 'w') as f:
                    json.dump(data, f)
                # Set secure permissions (user only)
                if platform.system() != "Windows":
                    os.chmod(SESSION_FILE, 0o600)
            except Exception as e:
                print_status(f"Gagal menyimpan session: {e}", "error")
    
    def _clear_session(self):
        """Clear current session."""
        self.session_token = None
        self.username = None
        self.is_admin = False
        self._update_prompt()
        if SESSION_FILE.exists():
            try:
                SESSION_FILE.unlink()
            except Exception:
                pass
    
    def _update_prompt(self):
        """Update command prompt based on authentication status."""
        if self.username:
            role = "👑" if self.is_admin else "👤"
            self.prompt = f"{Colors.BOLD}{role} {self.username} >{Colors.ENDC} "
        else:
            self.prompt = f"{Colors.BOLD}alfa (guest)>{Colors.ENDC} "
    
    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                 headers: Optional[Dict] = None) -> Optional[requests.Response]:
        """Make HTTP request to ALFA server."""
        url = f"{self.server_url}{endpoint}"
        req_headers = {
            "Content-Type": "application/json",
            "User-Agent": f"ALFA-CLI/{VERSION}"
        }
        
        if self.session_token:
            req_headers["Authorization"] = f"Bearer {self.session_token}"
        
        if headers:
            req_headers.update(headers)
        
        try:
            if method == "GET":
                res = requests.get(url, headers=req_headers, timeout=TIMEOUT)
            elif method == "POST":
                res = requests.post(url, json=data, headers=req_headers, timeout=TIMEOUT)
            elif method == "DELETE":
                res = requests.delete(url, headers=req_headers, timeout=TIMEOUT)
            else:
                raise ValueError(f"Method {method} tidak didukung")
            
            return res
        except requests.exceptions.ConnectionError:
            print_status(f"Tidak dapat terhubung ke server di {url}. Pastikan server berjalan.", "error")
            return None
        except requests.exceptions.Timeout:
            print_status("Request timeout. Server mungkin sedang sibuk.", "error")
            return None
        except Exception as e:
            print_status(f"Error request: {e}", "error")
            return None
    
    def _check_auth(self) -> bool:
        """Check if current session token is valid."""
        if not self.session_token:
            return False
        res = self._request("GET", "/api/auth/me")
        if res and res.status_code == 200:
            data = res.json()
            self.username = data.get('username')
            self.is_admin = data.get('is_admin', False)
            return True
        return False
    
    # --- Commands ---
    
    def do_register(self, arg: str):
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
                print_status(f"Akun '{username}' berhasil dibuat! Silakan login.", "success")
                # Auto login after registration
                self.do_login(username)
            else:
                try:
                    msg = res.json().get('detail', 'Registrasi gagal')
                except Exception:
                    msg = res.text
                print_status(msg, "error")
    
    def do_login(self, arg: str):
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
                self.session_token = data.get('access_token') or data.get('token')
                self.username = username
                
                # Check admin status
                me_res = self._request("GET", "/api/auth/me")
                if me_res and me_res.status_code == 200:
                    self.is_admin = me_res.json().get('is_admin', False)
                
                self._save_session()
                self._update_prompt()
                print_status(f"Login berhasil sebagai {self.username}!", "success")
            else:
                try:
                    msg = res.json().get('detail', 'Login gagal')
                except Exception:
                    msg = "Username atau password salah."
                print_status(msg, "error")
    
    def do_logout(self, arg: str):
        """Logout dari akun saat ini."""
        if self.session_token:
            self._request("POST", "/api/auth/logout")
        self._clear_session()
        print_status("Berhasil logout.", "success")
    
    def do_stats(self, arg: str):
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
    
    def do_tools(self, arg: str):
        """Melihat daftar tools yang tersedia."""
        if not self.session_token:
            print_status("Anda harus login terlebih dahulu.", "warning")
            return
        
        res = self._request("GET", "/api/tools")
        if res and res.status_code == 200:
            data = res.json()
            tools = data if isinstance(data, list) else data.get('tools', [])
            print(f"\n{Colors.BOLD}🛠️ Daftar Tools ({len(tools)}):{Colors.ENDC}\n")
            for i, tool in enumerate(tools[:20], 1):
                name = tool.get('name', 'Unknown') if isinstance(tool, dict) else str(tool)
                desc = tool.get('description', '') if isinstance(tool, dict) else ''
                print(f"{i}. {Colors.GREEN}{name}{Colors.ENDC}")
                if desc:
                    print(f"   {Colors.WARNING}{desc}{Colors.ENDC}")
            if len(tools) > 20:
                print(f"... dan {len(tools)-20} tools lainnya.")
            print()
        else:
            print_status("Gagal mengambil daftar tools atau endpoint belum tersedia.", "error")
    
    def do_clear(self, arg: str):
        """Membersihkan layar terminal."""
        os.system('cls' if platform.system() == 'Windows' else 'clear')
        print_banner()
    
    def do_exit(self, arg: str):
        """Keluar dari aplikasi."""
        print_status("Terima kasih telah menggunakan ALFA CLI. Sampai jumpa!", "success")
        return True
    
    def do_q(self, arg: str):
        """Alias untuk exit."""
        return self.do_exit(arg)
    
    def default(self, line: str):
        """Handle regular chat input (not a command)."""
        if not self.session_token:
            print_status("Anda harus login dulu untuk chatting. Ketik 'login' atau 'register'.", "warning")
            return
        
        message = line.strip()
        if not message:
            return
        
        # Send message to agent chat endpoint
        payload = {"message": message}
        
        print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC} Sedang berpikir...", end="\r")
        
        res = self._request("POST", "/api/chat", payload)
        
        # Clear "Sedang berpikir..." line
        sys.stdout.write("\033[K")
        
        if res and res.status_code == 200:
            data = res.json()
            response_text = data.get('response') or data.get('message') or str(data)
            
            print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
            print(f"{Colors.WHITE}{response_text}{Colors.ENDC}\n")
            
            # Save to local history (optional)
            self.chat_history.append({"role": "user", "content": message})
            self.chat_history.append({"role": "assistant", "content": response_text})
        else:
            print(f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons dari agen.")
            if res:
                try:
                    err = res.json()
                    print(f"Detail: {err}")
                except Exception:
                    print(f"Status: {res.status_code}")
    
    def emptyline(self):
        """Handle empty line input."""
        pass


def main():
    """Main entry point for ALFA CLI."""
    parser = argparse.ArgumentParser(
        description="ALFA Sovereign AI CLI Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m alfa.cli
  python -m alfa.cli --server http://192.168.1.100:8080
  alfa-cli --no-color
        """
    )
    parser.add_argument(
        "--server", 
        type=str, 
        default=os.getenv("ALFA_SERVER", DEFAULT_SERVER),
        help=f"URL Server ALFA (default: {DEFAULT_SERVER})"
    )
    parser.add_argument(
        "--no-color", 
        action="store_true", 
        help="Matikan warna output"
    )
    
    args = parser.parse_args()
    
    if args.no_color:
        Colors.disable()
    
    print_banner()
    
    # Check initial connection
    try:
        r = requests.get(f"{args.server}/health", timeout=5)
        if r.status_code == 200:
            print_status(f"Terhubung ke server: {args.server}", "success")
        else:
            print_status(f"Server merespons tapi status code: {r.status_code}", "warning")
    except Exception:
        print_status(f"Tidak dapat menghubungi server di {args.server}. Pastikan server berjalan.", "error")
        print("Tips: Gunakan flag --server http://ip-address:port jika server remote.")
    
    try:
        cli = AlfaCLI(args.server)
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\n")
        print_status("Interupsi diterima. Keluar...", "warning")
        sys.exit(0)


if __name__ == "__main__":
    main()
