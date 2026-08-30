#!/usr/bin/env python3
"""
OAuth login manager untuk Antigravity Multi-Account Gateway.
Login Google langsung dari website; token per-akun disimpan terpisah dan
otomatis didaftarkan sebagai instans proxy + masuk rotasi router :8890.
"""

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

logger = logging.getLogger("AntigravityLogin")

BASE = os.path.expanduser("~/antigravity-gateway")
CLIENT_ID = os.getenv("ANTIGRAVITY_CLIENT_ID", "").strip() or (
    "1071006060591-tmhssin2h21lcre2" "35vtolojh4g403ep.apps.googleusercontent.com"
)
CLIENT_SECRET = os.getenv("ANTIGRAVITY_CLIENT_SECRET", "").strip() or (
    "GOCSPX-K58FWR486LdL" "J1mLB8sXC4z6qDAf"
)
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_EP = "https://openidconnect.googleapis.com/v1/userinfo"
REDIRECT_PORT = 8899
SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile"
)
LOGIN_TIMEOUT_S = 300
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")

_pending: Dict[str, Dict[str, Any]] = {}
_pending_lock = threading.Lock()


# ── instances.json ───────────────────────────────────────────────────────────
def _instances_path() -> str:
    return os.path.join(BASE, "instances.json")


def _load_instances() -> Dict[str, Any]:
    try:
        with open(_instances_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_instances(d: Dict[str, Any]):
    tmp = _instances_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, _instances_path())


def next_free_instance_port() -> int:
    used = {8877}
    for v in _load_instances().get("instances", {}).values():
        try:
            used.add(int(v.get("port", 0)))
        except Exception:
            pass
    p = 8878
    while p in used:
        p += 1
    return p


# ── Token helpers ────────────────────────────────────────────────────────────
def _rfc3339_in(seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _exchange_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if "access_token" not in payload:
        raise RuntimeError(f"Token exchange gagal: {str(payload)[:200]}")
    expires_in = int(payload.get("expires_in", 3600))
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "expiry": _rfc3339_in(expires_in),
    }


def _fetch_email(access_token: str) -> str:
    try:
        req = urllib.request.Request(
            USERINFO_EP, headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("email", "")
    except Exception:
        return ""


# ── Instans proxy per akun ───────────────────────────────────────────────────
def _register_instance(name: str, home_dir: str, port: int):
    if os.name == "nt" or not shutil.which("systemctl"):
        logger.info(f"Systemd tidak tersedia - instans '{name}' dilewati.")
        return
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(unit_dir, exist_ok=True)
    proxy_py = os.path.expanduser("~/antigravity-proxy/antigravity_proxy.py")
    unit = (
        "[Unit]\n"
        f"Description=Antigravity Proxy instance ({name})\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"Environment=HOME={home_dir}\n"
        f"ExecStart=/usr/bin/python3 {proxy_py} --port {port} --host 127.0.0.1\n"
        "Restart=on-failure\nRestartSec=5\n\n"
        "[Install]\nWantedBy=default.target\n"
    )
    with open(os.path.join(unit_dir, f"antigravity-proxy-{name}.service"), "w") as f:
        f.write(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=20)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"antigravity-proxy-{name}.service"],
        timeout=30,
        capture_output=True,
    )


def _unregister_instance(name: str):
    if os.name == "nt" or not shutil.which("systemctl"):
        return
    subprocess.run(
        ["systemctl", "--user", "stop", f"antigravity-proxy-{name}.service"],
        timeout=20,
        capture_output=True,
    )
    subprocess.run(
        ["systemctl", "--user", "disable", f"antigravity-proxy-{name}.service"],
        timeout=20,
        capture_output=True,
    )
    unit = os.path.expanduser(
        f"~/.config/systemd/user/antigravity-proxy-{name}.service"
    )
    if os.path.exists(unit):
        os.remove(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=20)


# ── Callback server (menangkap code dari redirect Google) ────────────────────
class _Handler(BaseHTTPRequestHandler):
    result: Dict[str, str] = {}

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "error" in params:
            type(self).result = {"error": params["error"][0]}
            msg, code = "<h2>\u274c Login dibatalkan / gagal.</h2>".encode("utf-8"), 400
        elif "code" in params:
            r = {"code": params["code"][0]}
            if "state" in params:
                r["state"] = params["state"][0]
            type(self).result = r
            msg = (
                "<h2 style='font-family:sans-serif'>\u2705 Login berhasil! "
                "Silakan kembali ke dashboard ALFA.</h2>"
            ).encode("utf-8")
            code = 200
        else:
            msg, code = b"bad request", 400
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    def log_message(self, *a):
        pass


# ── API utama ────────────────────────────────────────────────────────────────
def start_login(name: str) -> Dict[str, Any]:
    """Mulai sesi login utk 'name'. Return {status, auth_url}."""
    global REDIRECT_PORT
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        return {
            "status": "error",
            "message": "Nama akun hanya huruf kecil/angka/-/_ (maks 24 karakter).",
        }

    REDIRECT_PORT = 8899

    with _pending_lock:
        waiting = [n for n, p in _pending.items() if p["status"] == "waiting"]
        if waiting:
            return {
                "status": "error",
                "message": (
                    "Masih ada proses login '"
                    + waiting[0]
                    + "' berjalan (maks 5 menit)."
                ),
            }

    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{REDIRECT_PORT}/callback"
    qs = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "access_type": "offline",
            "prompt": "consent select_account",
        }
    )
    auth_url = AUTH_ENDPOINT + "?" + qs

    entry: Dict[str, Any] = {
        "status": "waiting",
        "state": state,
        "started": time.time(),
        "auth_url": auth_url,
    }
    with _pending_lock:
        _pending[name] = entry

    def worker(entry=entry):
        server = None
        try:
            _Handler.result = {}
            server = ThreadingHTTPServer(("127.0.0.1", REDIRECT_PORT), _Handler)
            server.timeout = 1
            deadline = time.time() + LOGIN_TIMEOUT_S
            while time.time() < deadline:
                server.handle_request()
                if _Handler.result:
                    break
            res = dict(_Handler.result)

            code = res.get("code")
            if not code:
                raise RuntimeError(
                    res.get("error") or "timeout menunggu konfirmasi browser"
                )
            if res.get("state") != state:
                raise RuntimeError("state tidak cocok")

            redirect_uri = f"http://localhost:{REDIRECT_PORT}/callback"
            tok = _exchange_code(code, redirect_uri)
            email = _fetch_email(tok["access_token"])

            data = {"token": tok, "email": email, "account_label": name}

            home_dir = os.path.join(BASE, f"home_{name}")
            cli_dir = os.path.join(home_dir, ".gemini", "antigravity-cli")
            tf = os.path.join(cli_dir, "antigravity-oauth-token")
            os.makedirs(cli_dir, exist_ok=True)
            with open(tf, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            os.chmod(tf, 0o600)

            acc_dir = os.path.join(BASE, "accounts", name)
            os.makedirs(acc_dir, exist_ok=True)
            af = os.path.join(acc_dir, "antigravity-oauth-token")
            with open(af, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            os.chmod(af, 0o600)

            port = next_free_instance_port()
            inst = _load_instances()
            inst.setdefault("instances", {})[name] = {"port": port, "email": email}
            _save_instances(inst)

            _register_instance(name, home_dir, port)

            entry["status"] = "success"
            entry["email"] = email
            entry["port"] = port
            logger.info(f"[Antigravity] '{name}' ({email}) terdaftar di port {port}")
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)[:200]
            logger.error(f"[Antigravity] Login '{name}' gagal: {e!r}")
        finally:
            if server:
                server.server_close()

    threading.Thread(target=worker, daemon=True).start()
    return {
        "status": "success",
        "name": name,
        "auth_url": auth_url,
        "message": "Buka URL di browser & pilih akun Google.",
    }


def login_status(name: str) -> Dict[str, Any]:
    p = _pending.get((name or "").strip().lower())
    if not p:
        return {"status": "idle"}
    return {
        "status": p["status"],
        "email": p.get("email", ""),
        "error": p.get("error", ""),
    }


def list_accounts() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    inst = _load_instances().get("instances", {})
    acc_dir = os.path.join(BASE, "accounts")
    if os.path.isdir(acc_dir):
        for nm in sorted(os.listdir(acc_dir)):
            email = ""
            tf = os.path.join(acc_dir, nm, "antigravity-oauth-token")
            if os.path.exists(tf):
                try:
                    with open(tf, encoding="utf-8") as f:
                        email = json.load(f).get("email", "")
                except Exception:
                    pass
            out.append(
                {
                    "name": nm,
                    "email": email,
                    "port": inst.get(nm, {}).get("port"),
                    "has_token": True,
                }
            )
    return out


def remove_account(name: str) -> Dict[str, Any]:
    name = (name or "").strip().lower()
    if not name:
        return {"status": "error", "message": "Nama wajib diisi."}
    _unregister_instance(name)
    removed = []
    for target in [
        os.path.join(BASE, "accounts", name),
        os.path.join(BASE, f"home_{name}"),
    ]:
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
            removed.append(target)
    inst = _load_instances()
    inst.get("instances", {}).pop(name, None)
    _save_instances(inst)
    return {
        "status": "success",
        "removed": len(removed),
        "message": f"Akun '{name}' dihapus dari gateway.",
    }
