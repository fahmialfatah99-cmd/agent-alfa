"""Browser process lifecycle and single-threaded page access."""

from __future__ import annotations

import atexit
import concurrent.futures
import functools
import logging
import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from alfa.tools.web.browser.state import _AT_EXIT_DONE, _LOCK, _STATE

logger = logging.getLogger("AgentTools.Web.Browser")

# ── engine ──────────────────────────────────────────────────────────────────
def _headless() -> bool:
    return (
        os.getenv("ALFA_BROWSER_HEADLESS", "true").strip().lower()
        not in ("0", "false", "off", "no")
    )


_T = TypeVar("_T")
_UI_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_UI_POOL_LOCK = threading.Lock()


def _ui(fn: Callable[..., _T], *args: Any, timeout: float = 240.0, **kwargs: Any) -> _T:
    """Jalankan operasi browser di SATU thread khusus.

    Playwright/Camoufox sync API hanya aman dipakai dari thread yang sama dengan
    thread pembuatnya, dan engine-nya meninggalkan 'running loop' di thread
    pemanggil. Tanpa thread khusus ini, satu tool call merusak event loop milik
    pemanggil (asyncio.run() di test/bot jadi 'cannot be called from a running
    event loop').
    """
    global _UI_POOL
    with _UI_POOL_LOCK:
        if _UI_POOL is None:
            _UI_POOL = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="alfa-browser"
            )
    fut = _UI_POOL.submit(fn, *args, **kwargs)
    return fut.result(timeout=timeout)


def _on_browser_thread(fn: Callable) -> Callable:
    """Decorator: seluruh tubuh tool dijalankan di thread browser tunggal."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _ui(fn, *args, **kwargs)

    return wrapper


def _shutdown_browser() -> None:
    """Tutup browser + thread worker saat interpreter berhenti."""
    global _UI_POOL
    pool = _UI_POOL
    if pool is None:
        _close_browser()
        return
    try:
        pool.submit(_close_browser).result(timeout=15)
    except Exception:  # noqa: BLE001
        pass
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass
    _UI_POOL = None


def _close_browser() -> None:
    global _AT_EXIT_DONE
    with _LOCK:
        ctx = _STATE.get("ctx")
        _STATE["ctx"] = None
        _STATE["page"] = None
        _STATE["elements"] = []
    if ctx is not None:
        try:
            ctx.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    if not _AT_EXIT_DONE:
        _AT_EXIT_DONE = True


def _ensure_page():
    """Kembalikan page Camoufox aktif, launch bila belum ada. None bila gagal."""
    global _AT_EXIT_DONE
    with _LOCK:
        page = _STATE.get("page")
        if page is not None:
            try:
                if not page.is_closed():
                    return page
            except Exception:  # noqa: BLE001
                pass
            _STATE["page"] = None

        try:
            from camoufox.sync_api import Camoufox

            ctx = Camoufox(headless=_headless(), humanize=False, enable_cache=True)
            browser = ctx.__enter__()
            page = browser.new_page()
            page.set_default_timeout(20000)
            _STATE["ctx"] = ctx
            _STATE["page"] = page
            _STATE["elements"] = []
            if not _AT_EXIT_DONE:
                atexit.register(_shutdown_browser)
                _AT_EXIT_DONE = True
            logger.info("Camoufox engine diluncurkan (headless=%s)", _headless())
            return page
        except Exception as e:  # noqa: BLE001
            logger.error("Gagal meluncurkan Camoufox: %s", e)
            _STATE["ctx"] = None
            _STATE["page"] = None
            return None


