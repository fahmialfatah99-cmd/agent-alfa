"""Client for the external camofox-browser REST server (~/camofox-browser).

Optional engine for session-persistent browsing: the Node server keeps tabs,
cookies and storage partitioned per userId/sessionKey (persistence plugin),
so logins and context survive across agent runs — unlike the embedded
engine which starts fresh each process.

Select with ``ALFA_BROWSER_ENGINE=rest`` (default: ``embedded``).
Server URL via ``CAMOFOX_BASE_URL`` (default ``http://localhost:9377``),
optional ``CAMOFOX_ACCESS_KEY``, identity via ``CAMOFOX_USER_ID`` /
``CAMOFOX_SESSION_KEY``.

Start the server with: ``cd ~/camofox-browser && ./run.sh``
(or ``CAMOFOX_PORT=9377 node server.js``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("AgentTools.Web.Browser.Rest")


def base_url() -> str:
    return (
        os.getenv("CAMOFOX_BASE_URL", "http://localhost:9377").strip().rstrip("/")
        or "http://localhost:9377"
    )


def _user_id() -> str:
    return os.getenv("CAMOFOX_USER_ID", "alfa-default").strip() or "alfa-default"


def _session_key() -> str:
    return os.getenv("CAMOFOX_SESSION_KEY", "alfa").strip() or "alfa"


def _headers() -> dict[str, str]:
    key = os.getenv("CAMOFOX_ACCESS_KEY", "").strip()
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def prefer_rest() -> bool:
    """True bila user memilih engine REST via ALFA_BROWSER_ENGINE=rest."""
    return os.getenv("ALFA_BROWSER_ENGINE", "embedded").strip().lower() == "rest"


def server_available(timeout: float = 3.0) -> bool:
    """Cek cepat apakah server REST camofox sedang jalan."""
    try:
        import httpx

        r = httpx.get(
            f"{base_url()}/tabs",
            params={"userId": _user_id()},
            headers=_headers(),
            timeout=timeout,
        )
        return bool(r.status_code < 500)
    except Exception:  # noqa: BLE001
        return False


_REST_TAB: str | None = None


def _get_or_create_tab(url: str, timeout: float = 30.0) -> str:
    """Kembalikan tabId persisten (buat baru bila belum ada)."""
    global _REST_TAB
    import httpx

    base = base_url()
    if _REST_TAB:
        return _REST_TAB
    # Reuse tab pertama milik user bila ada (sesi persisten).
    try:
        r = httpx.get(
            f"{base}/tabs",
            params={"userId": _user_id()},
            headers=_headers(),
            timeout=10.0,
        )
        if r.status_code == 200:
            data = r.json()
            tabs = data if isinstance(data, list) else data.get("tabs", [])
            if tabs and isinstance(tabs[0], dict) and tabs[0].get("tabId"):
                _REST_TAB = str(tabs[0]["tabId"])
                return _REST_TAB
    except Exception:  # noqa: BLE001
        pass
    r = httpx.post(
        f"{base}/tabs",
        json={"url": url, "userId": _user_id(), "sessionKey": _session_key()},
        headers=_headers(),
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    tab_id = (
        data.get("tabId") or data.get("id") or (data.get("tab") or {}).get("tabId")
    )
    if not tab_id:
        raise RuntimeError(f"REST server tidak mengembalikan tabId: {data}")
    _REST_TAB = str(tab_id)
    return _REST_TAB


def rest_open_url(url: str, timeout: float = 45.0) -> dict[str, Any]:
    """Buka URL via server REST camofox (sesi persisten)."""
    global _REST_TAB
    import httpx

    base = base_url()
    try:
        tab_id = _get_or_create_tab(url, timeout=timeout)
        # Navigasi tab persisten ke URL tujuan.
        try:
            httpx.post(
                f"{base}/tabs/{tab_id}/navigate",
                json={"url": url, "userId": _user_id()},
                headers=_headers(),
                timeout=timeout,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("REST navigate gagal, coba buat tab baru: %s", e)
            _REST_TAB = None
            tab_id = _get_or_create_tab(url, timeout=timeout)
        snap = httpx.get(
            f"{base}/tabs/{tab_id}/snapshot",
            params={"userId": _user_id()},
            headers=_headers(),
            timeout=timeout,
        )
        snap.raise_for_status()
        payload = snap.json()
        text = str(payload)[:6000]
        return {
            "status": "success",
            "engine": "camofox_rest",
            "message": f"Halaman '{url}' terbuka via server persisten (tab {tab_id}).",
            "url": url,
            "tabId": tab_id,
            "interactive_elements": text,
        }
    except Exception as e:  # noqa: BLE001
        _REST_TAB = None
        return {"status": "error", "message": f"Camofox REST error: {e}"}


def rest_close_tab() -> dict[str, Any]:
    """Tutup tab persisten dan reset cache lokal."""
    global _REST_TAB
    import httpx

    if not _REST_TAB:
        return {"status": "success", "message": "Tidak ada tab REST aktif."}
    try:
        httpx.delete(
            f"{base_url()}/tabs/{_REST_TAB}",
            params={"userId": _user_id()},
            headers=_headers(),
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001
        pass
    _REST_TAB = None
    return {"status": "success", "message": "Tab REST ditutup."}
