#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALFA Sovereign AI - Command Line Interface (CLI)
Cross-platform (Windows/Linux/Mac) terminal client for ALFA Agent.

Usage:
    python cli.py
    python cli.py --server http://localhost:8080
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

# Try to import requests, if not installed, show helpful error
try:
    import requests
except ImportError:
    print("❌ Error: Library 'requests' tidak ditemukan.")
    print("   Silakan install dengan: pip install requests")
    sys.exit(1)

# --- Konfigurasi & Constants ---
VERSION = "1.0.0"
DEFAULT_SERVER = "http://localhost:8080"
SESSION_FILE = Path.home() / ".alfa_cli_session.json"
TIMEOUT = 120  # Timeout request ke server (detik)

# Warna ANSI (Support Windows 10+ dan Linux/Mac)
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

    @staticmethod
    def disable():
        # Disable colors jika bukan terminal atau Windows lama
        if platform.system() == "Windows":
            # Windows 10+ support ANSI, versi lama butuh win_unicode_console
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

# Cek apakah output ke terminal mendukung warna
if not sys.stdout.isatty():
    Colors.disable()

def print_banner():
    banner = f"""
{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗
║           ALFA Sovereign AI - CLI Client v{VERSION}           ║
║                  Secure Terminal Interface                    ║
╚═══════════════════════════════════════════════════════════╝{Colors.ENDC}
    """
    print(banner)

def print_status(msg, status="info"):
    icon = "ℹ️"
    color = Colors.BLUE
    if status == "success":
        icon = "✅"
        color = Colors.GREEN
    elif status == "error":
        icon = "❌"
        color = Colors.FAIL
    elif status == "warning":
        icon = "⚠️"
        color = Colors.WARNING
    
    print(f"{color}{icon} {msg}{Colors.ENDC}")

class AlfaCLI(cmd.Cmd):
    intro = f"{Colors.GREEN}Selamat datang di ALFA CLI. Ketik 'help' atau '?' untuk daftar perintah.{Colors.ENDC}"
    prompt = f"{Colors.BOLD}alfa>{Colors.ENDC} "

    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url.rstrip('/')
        self.session_token = None
        self.username = None
        self.is_admin = False
        self.chat_history = []
        
        # Load session jika ada
        self._load_session()

    def _load_session(self):
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, 'r') as f:
                    data = json.load(f)
                    self.session_token = data.get('token')
                    self.username = data.get('username')
                    self.is_admin = data.get('is_admin', False)
                    
                    # Validasi session
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
                # Set permission aman (hanya user yang bisa baca)
                if platform.system() != "Windows":
                    os.chmod(SESSION_FILE, 0o600)
            except Exception as e:
                print_status(f"Gagal menyimpan session: {e}", "error")

    def _clear_session(self):
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
        if self.username:
            role = "👑" if self.is_admin else "👤"
            self.prompt = f"{Colors.BOLD}{role} {self.username} >{Colors.ENDC} "
        else:
            self.prompt = f"{Colors.BOLD}alfa (guest)>{Colors.ENDC} "

    def _request(self, method, endpoint, data=None, headers=None):
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

    def _check_auth(self):
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
                print_status(f"Akun '{username}' berhasil dibuat! Silakan login.", "success")
                # Auto login setelah register
                self.do_login(username)
            else:
                try:
                    msg = res.json().get('detail', 'Registrasi gagal')
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
                self.session_token = data.get('access_token') or data.get('token')
                self.username = username
                # Cek admin status
                me_res = self._request("GET", "/api/auth/me")
                if me_res and me_res.status_code == 200:
                    self.is_admin = me_res.json().get('is_admin', False)
                
                self._save_session()
                self._update_prompt()
                print_status(f"Login berhasil sebagai {self.username}!", "success")
            else:
                try:
                    msg = res.json().get('detail', 'Login gagal')
                except:
                    msg = "Username atau password salah."
                print_status(msg, "error")

    def do_logout(self, arg):
        """Logout dari akun saat ini."""
        if self.session_token:
            self._request("POST", "/api/auth/logout") # Optional invalidate di server
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
            print("\n" + "="*30)
            print(f"{Colors.BOLD}📊 Statistik Sistem{Colors.ENDC}")
            print("="*30)
            for key, value in data.items():
                print(f"{Colors.CYAN}{key}:{Colors.ENDC} {value}")
            print("="*30 + "\n")
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
            tools = data if isinstance(data, list) else data.get('tools', [])
            print(f"\n{Colors.BOLD}🛠️ Daftar Tools ({len(tools)}):{Colors.ENDC}\n")
            for i, tool in enumerate(tools[:20], 1): # Tampilkan 20 pertama
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

    def do_clear(self, arg):
        """Membersihkan layar terminal."""
        os.system('cls' if platform.system() == 'Windows' else 'clear')
        print_banner()

    def do_exit(self, arg):
        """Keluar dari aplikasi."""
        print_status("Terima kasih telah menggunakan ALFA CLI. Sampai jumpa!", "success")
        return True

    def do_q(self, arg):
        """Alias untuk exit."""
        return self.do_exit(arg)

    def default(self, line):
        """Menangani input chat biasa (bukan command)."""
        if not self.session_token:
            print_status("Anda harus login dulu untuk chatting. Ketik 'login' atau 'register'.", "warning")
            return

        message = line.strip()
        if not message:
            return

        # Kirim pesan ke endpoint chat agent
        # Asumsi endpoint: POST /api/chat { "message": "..." }
        payload = {"message": message}
        
        print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC} Sedang berpikir...", end="\r")
        
        res = self._request("POST", "/api/chat", payload)
        
        # Hapus baris "Sedang berpikir..."
        sys.stdout.write("\033[K") 

        if res and res.status_code == 200:
            data = res.json()
            response_text = data.get('response') or data.get('message') or str(data)
            
            # Format output respons
            print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
            print(f"{Colors.WHITE}{response_text}{Colors.ENDC}\n")
            
            # Simpan ke history lokal (opsional)
            self.chat_history.append({"role": "user", "content": message})
            self.chat_history.append({"role": "assistant", "content": response_text})
        else:
            print(f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons dari agen.")
            if res:
                try:
                    err = res.json()
                    print(f"Detail: {err}")
                except:
                    print(f"Status: {res.status_code}")

    def emptyline(self):
        pass

def main():
    parser = argparse.ArgumentParser(description="ALFA Sovereign AI CLI Client")
    parser.add_argument("--server", type=str, default=os.getenv("ALFA_SERVER", DEFAULT_SERVER),
                        help=f"URL Server ALFA (default: {DEFAULT_SERVER})")
    parser.add_argument("--no-color", action="store_true", help="Matikan warna output")
    
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
            print_status(f"Server merespons tapi status code: {r.status_code}", "warning")
    except:
        print_status(f"Tidak dapat menghubungi server di {args.server}. Pastikan server berjalan.", "error")
        print("Tips: Gunakan flag --server http://ip-address:port jika server remote.")
        # Jangan exit, biarkan user tetap bisa coba login nanti atau exit manual

    try:
        cli = AlfaCLI(args.server)
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\n")
        print_status("Interupsi diterima. Keluar...", "warning")
        sys.exit(0)

if __name__ == "__main__":
    main()
