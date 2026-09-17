"""Session management, readline auto-completion, and HTTP client transport for CLI."""

import json
import os
import platform
import sys
from datetime import datetime

import requests

from alfa.core.cli.constants import (
    CONFIG_FILE,
    HISTORY_FILE,
    MAX_HISTORY_LENGTH,
    READLINE_AVAILABLE,
    SESSION_FILE,
    TIMEOUT,
    VERSION,
    Colors,
    print_status,
)

if READLINE_AVAILABLE:
    import readline


class CliSessionMixin:
    """Handles session persistence, readline integration, and API requests."""

    def _setup_readline(self):
        """Setup readline for command history and auto-completion."""
        if not READLINE_AVAILABLE:
            return
        try:
            readline.read_history_file(HISTORY_FILE)
        except FileNotFoundError:
            pass

        readline.set_history_length(MAX_HISTORY_LENGTH)

        # Setup completer
        readline.set_completer(self._completer)
        if sys.platform != "win32":
            readline.parse_and_bind("tab: complete")
        else:
            readline.parse_and_bind("tab: complete")

    def _completer(self, text, state):
        """Auto-completion for slash commands."""
        commands = [
            "/help",
            "/clear",
            "/exit",
            "/quit",
            "/config",
            "/history",
            "/tools",
            "/stats",
            "/login",
            "/logout",
            "/register",
            "/upload",
            "/download",
            "/models",
            "/agents",
            "/stream",
            "/theme",
            "/provider",
            "/settings",
            "/switch",
        ]

        if text.startswith("/"):
            matches = [cmd for cmd in commands if cmd.startswith(text)]
            if 0 <= state < len(matches):
                return matches[state]
        return None

    def _save_history(self):
        """Save command history to file."""
        if not READLINE_AVAILABLE:
            return
        try:
            readline.write_history_file(HISTORY_FILE)
        except Exception:
            pass

    def _load_config(self):
        """Load user configuration from file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"theme": "default", "streaming": False, "markdown": True}

    def _save_config(self):
        """Save current configuration to file."""
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print_status(f"Gagal menyimpan config: {e}", "error")

    def _load_session(self):
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE) as f:
                    data = json.load(f)
                    self.session_token = data.get("token")
                    self.username = data.get("username")
                    self.is_admin = data.get("is_admin", False)

                    # Validasi session
                    if self._check_auth():
                        print_status(
                            f"Session ditemukan. Selamat datang kembali, {self.username}!",
                            "success",
                        )
                        self._update_prompt()
                        return
                    else:
                        print_status(
                            "Session kadaluarsa atau tidak valid. Silakan login.",
                            "warning",
                        )
                        self._clear_session()
            except Exception:
                self._clear_session()

    def _save_session(self):
        if self.session_token and self.username:
            data = {
                "token": self.session_token,
                "username": self.username,
                "is_admin": self.is_admin,
                "saved_at": datetime.now().isoformat(),
            }
            try:
                with open(SESSION_FILE, "w") as f:
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
            "User-Agent": f"ALFA-CLI/{VERSION}",
        }

        if self.session_token:
            req_headers["Authorization"] = f"Bearer {self.session_token}"

        if headers:
            req_headers.update(headers)

        try:
            if method == "GET":
                res = requests.get(url, headers=req_headers, timeout=TIMEOUT)
            elif method == "POST":
                res = requests.post(
                    url, json=data, headers=req_headers, timeout=TIMEOUT
                )
            elif method == "DELETE":
                res = requests.delete(url, headers=req_headers, timeout=TIMEOUT)
            else:
                raise ValueError(f"Method {method} tidak didukung")

            return res
        except requests.exceptions.ConnectionError:
            print_status(
                f"Tidak dapat terhubung ke server di {url}. Pastikan server berjalan.",
                "error",
            )
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
            user_data = data.get("user", {})
            self.username = user_data.get("username") or data.get("username")
            self.is_admin = user_data.get("is_admin", False) or data.get(
                "is_admin", False
            )
            return True
        return False
