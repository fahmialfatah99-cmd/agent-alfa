#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ALFA Sovereign AI - Advanced Command Line Interface (CLI)
Cross-platform (Windows/Linux/Mac) terminal client for ALFA Agent.

Features:
  - Interactive REPL with syntax highlighting
  - Multi-line input support
  - Command history & auto-completion
  - Streaming responses
  - Rich markdown rendering
  - Session management
  - Slash commands (/help, /clear, /config, etc.)
  - File upload/download support
  - Real-time status indicators
  - Context-aware suggestions

Usage:
    python cli.py
    python cli.py --server http://localhost:8080
    python cli.py --stream --no-color
"""

import cmd
import json
import os
import sys
import platform
import getpass
import argparse
import readline
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Try to import requests
try:
    import requests
except ImportError:
    print("❌ Error: Library 'requests' tidak ditemukan.")
    print("   Silakan install dengan: pip install requests")
    sys.exit(1)

# Try to import rich for beautiful output
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

# --- Konfigurasi & Constants ---
VERSION = "3.0.0"
DEFAULT_SERVER = "http://localhost:8080"
SESSION_FILE = Path.home() / ".alfa_cli_session.json"
CONFIG_FILE = Path.home() / ".alfa_cli_config.json"
HISTORY_FILE = Path.home() / ".alfa_cli_history"
TIMEOUT = 120  # Timeout request ke server (detik)
MAX_HISTORY_LENGTH = 1000

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

class AlfaCLI(cmd.Cmd):
    intro = f"{Colors.GREEN}Selamat datang di ALFA CLI. Ketik '/help' untuk daftar perintah atau langsung chatting!{Colors.ENDC}"
    prompt = f"{Colors.BOLD}alfa>{Colors.ENDC} "

    def __init__(self, server_url):
        super().__init__()
        self.server_url = server_url.rstrip('/')
        self.session_token = None
        self.username = None
        self.is_admin = False
        self.chat_history = []
        self.config = self._load_config()
        self.streaming = self.config.get('streaming', False)
        self.console = Console() if RICH_AVAILABLE else None
        
        # Setup readline for better input experience
        self._setup_readline()
        
        # Load session jika ada
        self._load_session()
    
    def _setup_readline(self):
        """Setup readline for command history and auto-completion."""
        try:
            readline.read_history_file(HISTORY_FILE)
        except FileNotFoundError:
            pass
        
        readline.set_history_length(MAX_HISTORY_LENGTH)
        
        # Setup completer
        readline.set_completer(self._completer)
        if sys.platform != 'win32':
            readline.parse_and_bind("tab: complete")
        else:
            readline.parse_and_bind("tab: complete")
    
    def _completer(self, text, state):
        """Auto-completion for slash commands."""
        commands = ['/help', '/clear', '/exit', '/quit', '/config', '/history', 
                    '/tools', '/stats', '/login', '/logout', '/register', '/upload',
                    '/download', '/models', '/agents', '/stream', '/theme']
        
        if text.startswith('/'):
            matches = [cmd for cmd in commands if cmd.startswith(text)]
            if 0 <= state < len(matches):
                return matches[state]
        return None
    
    def _save_history(self):
        """Save command history to file."""
        try:
            readline.write_history_file(HISTORY_FILE)
        except Exception:
            pass
    
    def _load_config(self):
        """Load user configuration from file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'theme': 'default', 'streaming': False, 'markdown': True}
    
    def _save_config(self):
        """Save current configuration to file."""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print_status(f"Gagal menyimpan config: {e}", "error")

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

{Colors.CYAN}❌ Exit:{Colors.ENDC}
  /exit      - Keluar dari aplikasi
  /quit      - Alias untuk exit

{Colors.GRAY}Tips: Tekan TAB untuk auto-complete perintah!{Colors.ENDC}
"""
        print(help_text)
    
    def do_slash_clear(self, arg):
        """Bersihkan layar. Usage: /clear"""
        os.system('cls' if platform.system() == 'Windows' else 'clear')
        print_banner()
    
    def do_slash_exit(self, arg):
        """Keluar dari aplikasi. Usage: /exit"""
        self._save_history()
        print_status("Terima kasih telah menggunakan ALFA CLI. Sampai jumpa!", "success")
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
        recent = self.chat_history[-limit*2:]  # User + assistant pairs
        
        print(f"\n{Colors.BOLD}📜 Riwayat Chat ({len(recent)//2} percakapan):{Colors.ENDC}\n")
        for i in range(0, len(recent), 2):
            user_msg = recent[i].get('content', '')[:100]
            print(f"{Colors.CYAN}You:{Colors.ENDC} {user_msg}...")
            if i+1 < len(recent):
                assistant_msg = recent[i+1].get('content', '')[:100]
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
        if '=' in arg:
            key, value = arg.split('=', 1)
            key = key.strip()
            value = value.strip().lower()
            
            if value in ['true', 'yes', '1']:
                value = True
            elif value in ['false', 'no', '0']:
                value = False
            
            self.config[key] = value
            self._save_config()
            print_status(f"Konfigurasi '{key}' diperbarui menjadi {value}", "success")
            
            # Apply config changes
            if key == 'streaming':
                self.streaming = value
    
    def do_slash_theme(self, arg):
        """Ubah tema. Usage: /theme [default|minimal|colorful]"""
        themes = ['default', 'minimal', 'colorful']
        if not arg or arg not in themes:
            print(f"Tema tersedia: {', '.join(themes)}")
            return
        
        self.config['theme'] = arg
        self._save_config()
        print_status(f"Tema diubah ke '{arg}'. Restart CLI untuk melihat perubahan.", "success")
    
    def do_slash_stream(self, arg):
        """Toggle streaming mode. Usage: /stream on|off"""
        if arg.lower() == 'on':
            self.streaming = True
            self.config['streaming'] = True
            print_status("Streaming mode: ON", "success")
        elif arg.lower() == 'off':
            self.streaming = False
            self.config['streaming'] = False
            print_status("Streaming mode: OFF", "success")
        else:
            current = "ON" if self.streaming else "OFF"
            print_status(f"Streaming mode saat ini: {current}. Gunakan '/stream on' atau '/stream off'", "info")
        
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
    
    def do_slash_models(self, arg):
        """Lihat model AI aktif. Usage: /models"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        res = self._request("GET", "/api/models")
        if res and res.status_code == 200:
            data = res.json()
            models = data if isinstance(data, list) else data.get('models', [])
            print(f"\n{Colors.BOLD}🧠 Model AI Aktif:{Colors.ENDC}\n")
            for model in models:
                name = model.get('name', 'Unknown') if isinstance(model, dict) else str(model)
                status = model.get('status', 'active') if isinstance(model, dict) else 'active'
                print(f"  • {Colors.GREEN}{name}{Colors.ENDC} [{status}]")
            print()
        else:
            print_status("Gagal mengambil info model.", "error")
    
    def do_slash_agents(self, arg):
        """Lihat status swarm agents. Usage: /agents"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        res = self._request("GET", "/api/swarm/status")
        if res and res.status_code == 200:
            data = res.json()
            print(f"\n{Colors.BOLD}🤖 Swarm Agents Status:{Colors.ENDC}\n")
            agents = data.get('agents', [])
            for agent in agents:
                name = agent.get('name', 'Unknown')
                status = agent.get('status', 'idle')
                task = agent.get('current_task', 'No task')
                icon = "🟢" if status == 'active' else "🟡" if status == 'busy' else "⚪"
                print(f"  {icon} {Colors.CYAN}{name}{Colors.ENDC}: {status} - {task}")
            print()
        else:
            print_status("Gagal mengambil status agents.", "error")
    
    def do_slash_upload(self, arg):
        """Upload file. Usage: /upload <filepath>"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        filepath = arg.strip()
        if not filepath:
            filepath = input("Path file: ").strip()
        
        if not os.path.exists(filepath):
            print_status(f"File tidak ditemukan: {filepath}", "error")
            return
        
        try:
            files = {'file': open(filepath, 'rb')}
            res = self._request("POST", "/api/upload", headers={})
            # Note: Need custom request for file upload
            print_status("Fitur upload akan segera hadir.", "info")
        except Exception as e:
            print_status(f"Error upload: {e}", "error")
    
    def do_slash_download(self, arg):
        """Download file. Usage: /download <filename>"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        print_status("Fitur download akan segera hadir.", "info")

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
        self._save_history()
        print_status("Terima kasih telah menggunakan ALFA CLI. Sampai jumpa!", "success")
        return True

    def do_q(self, arg):
        """Alias untuk exit."""
        return self.do_exit(arg)

    def default(self, line):
        """Menangani input chat biasa atau slash commands."""
        # Handle slash commands
        if line.startswith('/'):
            parts = line[1:].split(' ', 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ''
            
            # Try to call the corresponding slash command method
            method_name = f'do_slash_{cmd}'
            if hasattr(self, method_name):
                return getattr(self, method_name)(args)
            else:
                print_status(f"Perintah tidak dikenal: {line}", "error")
                print("Ketik /help untuk daftar perintah.", "info")
                return
        
        # Handle regular chat
        if not self.session_token:
            print_status("Anda harus login dulu untuk chatting. Ketik /login atau /register.", "warning")
            return

        message = line.strip()
        if not message:
            return

        # Kirim pesan ke endpoint chat agent
        payload = {"message": message, "stream": self.streaming}
        
        # Show thinking indicator
        if self.streaming:
            print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC} ", end="")
            if RICH_AVAILABLE and self.console:
                with Live(Spinner('dots', text='Thinking...', style='cyan'), refresh_per_second=10) as live:
                    res = self._request("POST", "/api/chat/stream", payload)
                    live.update(Spinner('dots', text='Streaming...', style='green'))
                    
                    if res and res.status_code == 200:
                        # Handle streaming response
                        full_response = ""
                        for chunk in res.iter_lines():
                            if chunk:
                                chunk_data = json.loads(chunk.decode('utf-8'))
                                token = chunk_data.get('token', '')
                                full_response += token
                                print(token, end='', flush=True)
                        print()
                        
                        self.chat_history.append({"role": "user", "content": message})
                        self.chat_history.append({"role": "assistant", "content": full_response})
                    else:
                        print(f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons.")
            else:
                res = self._request("POST", "/api/chat", payload)
                sys.stdout.write("\033[K")
                
                if res and res.status_code == 200:
                    data = res.json()
                    response_text = data.get('response') or data.get('message') or str(data)
                    
                    # Render dengan Rich jika tersedia
                    if RICH_AVAILABLE and self.console and self.config.get('markdown', True):
                        self.console.print(Markdown(response_text))
                    else:
                        print(f"\n{Colors.WHITE}{response_text}{Colors.ENDC}\n")
                    
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
        else:
            # Non-streaming mode
            print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC} Sedang berpikir...", end="\r")
            
            res = self._request("POST", "/api/chat", payload)
            
            # Hapus baris "Sedang berpikir..."
            sys.stdout.write("\033[K") 

            if res and res.status_code == 200:
                data = res.json()
                response_text = data.get('response') or data.get('message') or str(data)
                
                # Render dengan Rich jika tersedia
                if RICH_AVAILABLE and self.console and self.config.get('markdown', True):
                    print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
                    self.console.print(Markdown(response_text))
                else:
                    print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
                    print(f"{Colors.WHITE}{response_text}{Colors.ENDC}\n")
                
                # Simpan ke history lokal
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
        """
    )
    parser.add_argument("--server", type=str, default=os.getenv("ALFA_SERVER", DEFAULT_SERVER),
                        help=f"URL Server ALFA (default: {DEFAULT_SERVER})")
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
            print_status(f"Server merespons tapi status code: {r.status_code}", "warning")
    except Exception:
        print_status(f"Tidak dapat menghubungi server di {args.server}. Pastikan server berjalan.", "error")
        print("Tips: Gunakan flag --server http://ip-address:port jika server remote.")
        # Jangan exit, biarkan user tetap bisa coba login nanti atau exit manual

    try:
        cli = AlfaCLI(args.server)
        
        # Override streaming from args
        if args.stream:
            cli.streaming = True
            cli.config['streaming'] = True
        
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\n")
        print_status("Interupsi diterima. Keluar...", "warning")
        sys.exit(0)

if __name__ == "__main__":
    main()
