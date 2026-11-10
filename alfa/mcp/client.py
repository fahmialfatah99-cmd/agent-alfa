"""Klien MCP generik (Streamable HTTP + OAuth 2.1 PKCE) untuk server MCP remote.

Alur LottieFiles:
  1. mcp_connect('lottiefiles') -> URL otorisasi (buka di browser laptop).
  2. Login + approve -> redirect ke dashboard lokal -> token tersimpan.
  3. mcp_call('lottiefiles', tool, args) -> eksekusi tool remote.

Catatan keamanan (store kredensial):
  - File store berisi ``access_token``/``refresh_token``/``client_secret``.
    Disimpan dengan izin 0600 dan ditulis ATOMIK (tmp + ``os.replace``) supaya
    crash di tengah write tak pernah mengacorrupt seluruh koneksi.
  - Semua mutasi lewat :func:`_update` (di bawah satu kunci) supaya tidak ada
    lost-update saat beberapa proses menulis bersamaan.
"""

import asyncio
import base64
import contextlib
import hashlib
import inspect
import json
import logging
import os
import secrets
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("MCPClient")

STATE_DIR = os.path.join(os.path.expanduser("~"), ".alfa")
STORE_FILE = os.path.join(STATE_DIR, "mcp_connections.json")

SERVERS: dict[str, dict[str, Any]] = {
    "lottiefiles": {
        "url": "https://mcp.lottiefiles.com/mcp",
        "scopes": ["mcp:full"],
    },
}

# Kunci proses-lokal untuk read-modify-write pada store.
_STORE_LOCK = threading.RLock()


def _load() -> dict[str, Any]:
    """Baca store. Selalu UTF-8 (default platform bisa_cp1252 -> data rusak)."""
    try:
        with open(STORE_FILE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _save(store: dict[str, Any]) -> None:
    """Simpan store secara ATOMIK dengan izin ketat (0600).

    - Atomic (tmp file + ``os.replace``): crash/kejadian mati di tengah write
      tidak pernah meninggalkan store korup yang menghapus semua koneksi.
    - 0600: file berisi token — tidak boleh world-readable.
    - Error TIDAK ditelan: pemanggil wajib tahu kalau penyimpanan gagal,
      kalau tidak user dikasih "sukses" padahal sesinya tidak pernah tersimpan.
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    payload = json.dumps(store, indent=2, ensure_ascii=False)
    fd = -1
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=STATE_DIR, prefix=".mcp_store-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            with contextlib.suppress(OSError):
                os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, STORE_FILE)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


@contextlib.contextmanager
def _store_lock():
    """Kunci read-modify-write: threading (proses sama) + flock (antarses)."""
    _STORE_LOCK.acquire()
    handle = None
    try:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            handle = open(STORE_FILE + ".lock", "a+")  # noqa: SIM115
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):  # pragma: no cover - non-POSIX
                pass
        except OSError:  # pragma: no cover - store tak bisa ditulis
            handle = None
        yield
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                handle.close()
        _STORE_LOCK.release()


def _update(mutate) -> dict[str, Any]:
    """Baca -> ubah -> tulis dalam SATU kunci (mencegah lost-update)."""
    with _store_lock():
        store = _load()
        mutate(store)
        _save(store)
        return store


_BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _validate_http_url(url: str) -> None:
    """Pastikan skema URL hanya http/https untuk mencegah file:// atau skema lokal."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(url)


def _http(method: str, url: str, body=None, headers=None, timeout: int = 25) -> dict[str, Any]:
    _validate_http_url(url)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **_BROWSER_UA, **(headers or {})}, method=method)
    # Skema URL telah divalidasi hanya http/https via _validate_http_url
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
        raw = r.read().decode("utf-8", "replace")
        parsed = json.loads(raw) if raw.strip() else {}
        return parsed if isinstance(parsed, dict) else {}


def _post_form(url: str, fields: dict, headers: dict | None = None, timeout: int = 25) -> dict[str, Any]:
    """POST application/x-www-form-urlencoded (wajib untuk endpoint OAuth)."""
    _validate_http_url(url)
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          **_BROWSER_UA, **(headers or {})}, method="POST")
    # Skema URL telah divalidasi hanya http/https via _validate_http_url
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
        raw = r.read().decode("utf-8", "replace")
        parsed = json.loads(raw) if raw.strip() else {}
        return parsed if isinstance(parsed, dict) else {}



def _discover_oauth(base_url: str) -> dict[str, Any]:
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
        except (OSError, TypeError, ValueError) as e:
            last_err = e
    raise RuntimeError(f"Metadata OAuth tak ditemukan: {last_err}")


def _basic_auth_header(entry: dict[str, Any]) -> dict[str, str]:
    """Header Basic auth bila client_secret tersedia (RFC 6749 §2.3.1)."""
    secret = entry.get("client_secret")
    if not secret:
        return {}
    pair = f"{entry.get('client_id', '')}:{secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(pair).decode()}


def start_connect(server_id: str, redirect_uri: str) -> dict[str, Any]:
    """Mulai OAuth: registrasi klien dinamis + URL otorisasi. Return {auth_url, ...}."""
    sid = (server_id or "").lower()
    if sid not in SERVERS:
        return {"status": "error", "message": f"Server '{server_id}' tak dikenal. Pilihan: {sorted(SERVERS)}"}
    url = str(SERVERS[sid]["url"])
    scope = " ".join(SERVERS[sid].get("scopes", ["openid"]))
    try:
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
            "scope": scope,
        })
        client_id = reg.get("client_id")
        if not client_id:
            return {"status": "error", "message": f"Registrasi klien ditolak: {str(reg)[:150]}"}
    except (OSError, TypeError, ValueError, RuntimeError) as e:
        # Kontrak: fungsi ini SELALU mengembalikan dict status, tidak melempar.
        # Pemanggil (dashboard/agent) tidak siap dengan exception liar.
        logger.warning(f"[mcp] gagal mulai OAuth untuk '{sid}': {e}")
        return {"status": "error", "message": f"Gagal menghubungi server OAuth: {e}"}

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    def _mutate(store: dict[str, Any]) -> None:
        store[sid] = {
            "url": url, "client_id": client_id,
            "client_secret": reg.get("client_secret", ""),
            "redirect_uri": redirect_uri,
            "code_verifier": verifier, "state": state,
            "token_endpoint": meta.get("token_endpoint", ""),
            "connected": False,
        }

    try:
        _update(_mutate)
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"[mcp] gagal menyimpan sesi connect '{sid}': {e}")
        return {"status": "error", "message": f"Gagal menyimpan sesi connect: {e}. Silakan ulangi."}

    params = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": scope,
        "state": f"{sid}:{state}", "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return {"status": "success", "auth_url": f"{auth_ep}?{params}",
            "note": "Buka URL di browser, login + approve. Callback otomatis menyimpan token."}


def finish_connect(code: str, state: str) -> dict[str, Any]:
    """Tukar authorization code -> token. Dipanggil callback dashboard.

    ``state`` diterima dalam DUA bentuk: mentah (``lottiefiles:abc``) maupun
    URL-encoded (``lottiefiles%3Aabc``) — dashboard bisa mengambilnya dari
    query string tanpa atau dengan decode lebih dulu.
    """
    raw_state = state or ""
    sid = ""
    received_state = ""
    for candidate in (raw_state, urllib.parse.unquote(raw_state)):
        if ":" in candidate:
            sid, received_state = candidate.split(":", 1)
            break
    else:
        return {"status": "error", "message": "State tak valid."}
    store = _load()
    ent = store.get(sid)
    if not ent or not ent.get("token_endpoint"):
        return {"status": "error", "message": "Sesi connect tak ditemukan — ulangi dari awal."}
    # Validasi `state` (anti OAuth CSRF / session fixation). Tanpa ini siapa
    # pun bisa menyelesaikan flow dengan authorization code miliknya sendiri
    # dan mengikat tokennya ke entri server korban.
    expected_state = str(ent.get("state") or "")
    if not expected_state:
        return {"status": "error", "message": "Sesi connect tak punya state — ulangi dari awal."}
    if not secrets.compare_digest(expected_state, str(received_state or "")):
        logger.warning("[mcp] state OAuth tidak cocok — permintaan ditolak")
        return {"status": "error", "message": "State tidak cocok — permintaan ditolak."}
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": ent.get("redirect_uri", ""),
        "client_id": ent.get("client_id", ""),
        "code_verifier": ent.get("code_verifier", ""),
        "resource": ent.get("url", ""),
    }
    headers = _basic_auth_header(ent)
    try:
        tok = _post_form(ent["token_endpoint"], body, headers)
    except (OSError, TypeError, ValueError) as e:
        detail = ""
        try:
            import urllib.error as _ue

            if isinstance(e, _ue.HTTPError):
                detail = f" | body: {e.read().decode('utf-8', 'replace')[:300]}"
        except (AttributeError, OSError, ValueError):
            pass
        logger.warning(f"[mcp] tukar token gagal: {e}{detail}")
        return {"status": "error", "message": f"Tukar token gagal: {e}{detail}"}
    if not tok.get("access_token"):
        return {"status": "error", "message": f"Otorisasi ditolak: {str(tok)[:150]}"}

    def _mutate(store: dict[str, Any]) -> None:
        target = store.get(sid)
        if target is None:
            return
        target.update({
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token", ""),
            "expires_at": time.time() + int(tok.get("expires_in", 3600)),
            "connected": True,
        })
        # Sekali pakai: verifier & state dibuang setelah pertukaran sukses,
        # supaya authorization code tak bisa dipakai ulang untuk menimpa
        # sesi yang sudah terhubung.
        target.pop("code_verifier", None)
        target.pop("state", None)

    try:
        _update(_mutate)
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"[mcp] token diperoleh tapi gagal disimpan: {e}")
        return {"status": "error", "message": f"Token diperoleh tapi gagal disimpan: {e}. Jalankan connect ulang."}
    return {"status": "success", "server": sid}


def _mark_disconnected(sid: str) -> None:
    """Tandai entri sebagai terputus (dipanggil saat refresh ditolak)."""
    def _mutate(store: dict[str, Any]) -> None:
        target = store.get(sid)
        if target is not None:
            target["connected"] = False

    with contextlib.suppress(OSError, TypeError, ValueError):
        _update(_mutate)


def _fresh_token(sid: str) -> str:
    """Kembalikan access token yang valid (refresh bila perlu)."""
    store = _load()
    ent = store.get(sid, {})
    if not ent.get("access_token"):
        raise RuntimeError("belum terhubung — jalankan connect dulu")

    expires_at = float(ent.get("expires_at", 0) or 0)
    # Kompatibilitas store lama: entri tanpa `expires_at` (mis. token statis /
    # sesi yang dibuat versi sebelumnya) harus tetap dipakai, bukan dianggap
    # kedaluwarsa. Hanya refresh bila expiry benar-benar diketahui.
    if not expires_at or time.time() <= expires_at - 120:
        return str(ent.get("access_token", ""))

    # Sudah (hampir) kedaluwarsa.
    if not ent.get("refresh_token"):
        raise RuntimeError(
            "token akses kedaluwarsa dan tidak ada refresh token — jalankan connect ulang"
        )
    if not ent.get("token_endpoint"):
        raise RuntimeError("token_endpoint tak tersimpan — jalankan connect ulang")

    body = {"grant_type": "refresh_token", "refresh_token": ent["refresh_token"],
            "client_id": ent.get("client_id", ""), "resource": ent.get("url", "")}
    headers = _basic_auth_header(ent)
    try:
        tok = _post_form(ent["token_endpoint"], body, headers)
    except (OSError, TypeError, ValueError) as e:
        _mark_disconnected(sid)
        raise RuntimeError(f"refresh token ditolak: {e} — jalankan connect ulang") from e
    if not tok.get("access_token"):
        _mark_disconnected(sid)
        raise RuntimeError(
            f"refresh token ditolak: {str(tok)[:120]} — jalankan connect ulang"
        )

    new_token = str(tok["access_token"])
    new_expires = time.time() + int(tok.get("expires_in", 3600))

    def _mutate(store: dict[str, Any]) -> None:
        target = store.get(sid)
        if target is None:
            return
        target["access_token"] = new_token
        target["expires_at"] = new_expires
        if tok.get("refresh_token"):
            target["refresh_token"] = tok["refresh_token"]
        target["connected"] = True

    _update(_mutate)
    return new_token


def connection_status(server_id: str = "") -> dict:
    store = _load()
    if server_id:
        e = store.get(str(server_id).lower(), {})
        return {"server": server_id, "connected": bool(e.get("connected")),
                "url": e.get("url", "")}
    return {"servers": [
        {"server": k, "connected": bool(v.get("connected")), "url": v.get("url", "")}
        for k, v in store.items()
    ]}


def _import_streamable_client():
    """Ambil fungsi transport streamable HTTP (SDK v1 atau v2).

    v1: ``mcp.client.streamable_http.streamablehttp_client`` -> yield 3-tuple
    v2: ``mcp.client.streamable_http.streamable_http_client`` -> yield 2-tuple
    """
    try:
        from mcp.client.streamable_http import streamablehttp_client  # SDK v1

        return streamablehttp_client
    except ImportError:
        from mcp.client.streamable_http import streamable_http_client  # SDK v2

        return streamable_http_client


@contextlib.asynccontextmanager
async def _remote_session(url: str, token: str, timeout: float):
    """Buka sesi MCP streamable HTTP; tahan SDK v1 (3-tuple) & v2 (2-tuple)."""
    from mcp.client.session import ClientSession

    client = _import_streamable_client()
    params: Mapping[str, Any]
    try:
        params = inspect.signature(client).parameters
    except (TypeError, ValueError):  # pragma: no cover - signature tak terbaca
        params = {}

    kwargs: dict[str, Any] = {}
    http_client = None
    if "headers" in params:
        kwargs["headers"] = {"Authorization": f"Bearer {token}"}
        kwargs["timeout"] = timeout
    elif "http_client" in params:
        import httpx

        http_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            follow_redirects=True,
        )
        kwargs["http_client"] = http_client
    try:
        async with client(url, **kwargs) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    finally:
        if http_client is not None:
            with contextlib.suppress(Exception):
                await http_client.aclose()


async def _call_remote(url: str, token: str, tool: str, args: dict, timeout: float = 60.0) -> dict:
    async with _remote_session(url, token, timeout) as session:
        res: dict[str, Any] = (await session.call_tool(tool, args)).model_dump(mode="json")
        return res


async def _list_remote(url: str, token: str, timeout: float = 30.0) -> list:
    async with _remote_session(url, token, timeout) as session:
        tools = await session.list_tools()
        return [
            {
                "name": t.name,
                "description": (t.description or "")[:200],
                "input": getattr(t, "inputSchema", None) or {},
            }
            for t in tools.tools
        ]


def _run_sync(coro_factory, timeout: float) -> dict[str, Any]:
    """Jalankan coroutine sinkron tanpa pernah memblokir selamanya.

    Kalau dipanggil dari dalam event loop yang sedang berjalan, ``asyncio.run``
    tak boleh dipakai di thread yang sama. Thread *daemon* + ``join(timeout)``
    dipakai supaya:
      - timeout benar-benar dipatuhi dan tak menggantung proses selamanya, dan
      - thread yang masih jalan tidak menahan interpreter saat exit.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        res = asyncio.run(coro_factory())
        return dict(res) if isinstance(res, dict) else {"status": "success", "result": res}

    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["res"] = asyncio.run(coro_factory())
        except BaseException as e:  # noqa: BLE001 - dilaporkan ke pemanggil
            box["err"] = e

    t = threading.Thread(target=_worker, name="mcp-sync-call", daemon=True)
    t.start()
    t.join(max(float(timeout) + 30.0, 0.1))
    if t.is_alive():
        return {
            "status": "error",
            "message": f"Timeout {timeout:.0f}s — server MCP remote tak merespons.",
        }
    if "err" in box:
        e = box["err"]
        return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}
    res = box.get("res")
    return dict(res) if isinstance(res, dict) else {"status": "success", "result": res}


def call_tool_sync(server_id: str, tool: str, args: dict | None = None, timeout: float = 60.0) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        sid = str(server_id or "").lower()
        ent = _load().get(sid, {})
        if not ent.get("url"):
            return {"status": "error", "message": "server tak dikenal/belum connect"}
        try:
            token = await asyncio.to_thread(_fresh_token, sid)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
            return {"status": "error", "message": str(e)}
        try:
            out = await _call_remote(ent["url"], token, tool, args or {}, timeout)
            return {"status": "success", "result": out}
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}

    return _run_sync(_run, timeout)


def list_tools_sync(server_id: str, timeout: float = 30.0) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        sid = str(server_id or "").lower()
        ent = _load().get(sid, {})
        if not ent.get("url"):
            return {"status": "error", "message": "server tak dikenal/belum connect"}
        try:
            token = await asyncio.to_thread(_fresh_token, sid)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as e:
            return {"status": "error", "message": str(e)}
        try:
            return {"status": "success", "tools": await _list_remote(ent["url"], token, timeout)}
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}

    return _run_sync(_run, timeout)
