"""Klien MCP generik (Streamable HTTP + OAuth 2.1 PKCE) untuk server MCP remote.

Alur LottieFiles:
  1. mcp_connect('lottiefiles') -> URL otorisasi (buka di browser laptop).
  2. Login + approve -> redirect ke dashboard lokal -> token tersimpan.
  3. mcp_call('lottiefiles', tool, args) -> eksekusi tool remote.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
import urllib.request

logger = logging.getLogger("MCPClient")

STATE_DIR = os.path.join(os.path.expanduser("~"), ".alfa")
STORE_FILE = os.path.join(STATE_DIR, "mcp_connections.json")

SERVERS = {
    "lottiefiles": {
        "url": "https://mcp.lottiefiles.com/mcp",
        "scopes": ["mcp:full"],
    },
}


def _load() -> dict:
    try:
        with open(STORE_FILE) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(store: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STORE_FILE, "w") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        logger.debug(f"[mcp] simpan gagal: {e}")


_BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _http(method: str, url: str, body=None, headers=None, timeout: int = 25):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **_BROWSER_UA, **(headers or {})}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}


def _post_form(url: str, fields: dict, headers: dict | None = None, timeout: int = 25) -> dict:
    """POST application/x-www-form-urlencoded (wajib untuk endpoint OAuth)."""
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          **_BROWSER_UA, **(headers or {})}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}



def _discover_oauth(base_url: str) -> dict:
    """RFC8414 + RFC9728: metadata otorisasi server MCP."""
    parsed = urllib.parse.urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    last_err: Exception | None = None
    for meta_url in (
        f"{origin}/.well-known/oauth-authorization-server",
        f"{origin}/.well-known/oauth-authorization-server{parsed.path}",
    ):
        try:
            return _http("GET", meta_url)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Metadata OAuth tak ditemukan: {last_err}")


def start_connect(server_id: str, redirect_uri: str) -> dict:
    """Mulai OAuth: registrasi klien dinamis + URL otorisasi. Return {auth_url, ...}."""
    sid = (server_id or "").lower()
    if sid not in SERVERS:
        return {"status": "error", "message": f"Server '{server_id}' tak dikenal. Pilihan: {sorted(SERVERS)}"}
    url = SERVERS[sid]["url"]
    meta = _discover_oauth(url)
    reg_ep = meta.get("registration_endpoint")
    auth_ep = meta.get("authorization_endpoint")
    if not reg_ep or not auth_ep:
        return {"status": "error", "message": "Server tak publikasikan endpoint registrasi/otorisasi."}
    reg = _http("POST", reg_ep, {
        "client_name": "ALFA Sovereign Agent",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": " ".join(SERVERS[sid].get("scopes", ["openid"])),
    })
    client_id = reg.get("client_id")
    if not client_id:
        return {"status": "error", "message": f"Registrasi klien ditolak: {str(reg)[:150]}"}
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    store = _load()
    store[sid] = {
        "url": url, "client_id": client_id,
        "client_secret": reg.get("client_secret", ""),
        "redirect_uri": redirect_uri,
        "code_verifier": verifier, "state": state,
        "token_endpoint": meta.get("token_endpoint", ""),
        "connected": False,
    }
    _save(store)
    params = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": " ".join(SERVERS[sid].get("scopes", ["openid"])),
        "state": f"{sid}:{state}", "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return {"status": "success", "auth_url": f"{auth_ep}?{params}",
            "note": "Buka URL di browser, login + approve. Callback otomatis menyimpan token."}


def finish_connect(code: str, state: str) -> dict:
    """Tukar authorization code -> token. Dipanggil callback dashboard."""
    try:
        sid, _ = (state or "").split(":", 1)
    except ValueError:
        return {"status": "error", "message": "State tak valid."}
    store = _load()
    ent = store.get(sid)
    if not ent or not ent.get("token_endpoint"):
        return {"status": "error", "message": "Sesi connect tak ditemukan — ulangi dari awal."}
    body = {"grant_type": "authorization_code", "code": code,
            "redirect_uri": ent["redirect_uri"], "client_id": ent["client_id"],
            "code_verifier": ent.get("code_verifier", ""),
            "resource": ent.get("url", "")}
    headers = {}
    if ent.get("client_secret"):
        pair = f"{ent['client_id']}:{ent['client_secret']}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
    try:
        tok = _post_form(ent["token_endpoint"], body, headers)
    except Exception as e:
        detail = ""
        try:
            import urllib.error as _ue

            if isinstance(e, _ue.HTTPError):
                detail = f" | body: {e.read().decode('utf-8', 'replace')[:300]}"
        except Exception:
            pass
        logger.warning(f"[mcp] tukar token gagal: {e}{detail}")
        return {"status": "error", "message": f"Tukar token gagal: {e}{detail}"}
    if not tok.get("access_token"):
        return {"status": "error", "message": f"Otorisasi ditolak: {str(tok)[:150]}"}
    ent.update({
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": time.time() + int(tok.get("expires_in", 3600)),
        "connected": True,
    })
    ent.pop("code_verifier", None)
    _save(store)
    return {"status": "success", "server": sid}


def _fresh_token(sid: str) -> str:
    store = _load()
    ent = store.get(sid, {})
    if not ent.get("access_token"):
        raise RuntimeError("belum terhubung — jalankan connect dulu")
    if ent.get("refresh_token") and time.time() > float(ent.get("expires_at", 0)) - 120:
        body = {"grant_type": "refresh_token", "refresh_token": ent["refresh_token"],
                "client_id": ent["client_id"], "resource": ent.get("url", "")}
        headers = {}
        if ent.get("client_secret"):
            pair = f"{ent['client_id']}:{ent['client_secret']}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
        tok = _post_form(ent["token_endpoint"], body, headers)
        if tok.get("access_token"):
            ent["access_token"] = tok["access_token"]
            ent["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
            if tok.get("refresh_token"):
                ent["refresh_token"] = tok["refresh_token"]
            _save(store)
    return _load().get(sid, {}).get("access_token", "")


def connection_status(server_id: str = "") -> dict:
    store = _load()
    if server_id:
        e = store.get(server_id.lower(), {})
        return {"server": server_id, "connected": bool(e.get("connected")),
                "url": e.get("url", "")}
    return {"servers": [
        {"server": k, "connected": bool(v.get("connected")), "url": v.get("url", "")}
        for k, v in store.items()
    ]}


async def _call_remote(url: str, token: str, tool: str, args: dict, timeout: float = 60.0) -> dict:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return (await session.call_tool(tool, args)).model_dump(mode="json")


async def _list_remote(url: str, token: str, timeout: float = 30.0) -> list:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [{"name": t.name, "description": (t.description or "")[:200],
                     "input": t.inputSchema} for t in tools.tools]


def call_tool_sync(server_id: str, tool: str, args: dict | None = None, timeout: float = 60.0) -> dict:
    import asyncio as _a

    async def _run():
        sid = server_id.lower()
        ent = _load().get(sid, {})
        if not ent.get("url"):
            return {"status": "error", "message": "server tak dikenal/belum connect"}
        try:
            token = await _a.to_thread(_fresh_token, sid)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        try:
            out = await _call_remote(ent["url"], token, tool, args or {}, timeout)
            return {"status": "success", "result": out}
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures as _cf

        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(_run(), debug=False)).result(timeout=timeout + 30)
    return asyncio.run(_run())


def list_tools_sync(server_id: str, timeout: float = 30.0) -> dict:
    import asyncio as _a

    async def _run():
        sid = server_id.lower()
        ent = _load().get(sid, {})
        if not ent.get("url"):
            return {"status": "error", "message": "server tak dikenal/belum connect"}
        try:
            token = await _a.to_thread(_fresh_token, sid)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        try:
            return {"status": "success", "tools": await _list_remote(ent["url"], token, timeout)}
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures as _cf

        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(_run(), debug=False)).result(timeout=timeout + 30)
    return asyncio.run(_run())
