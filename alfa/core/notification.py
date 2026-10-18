"""Penyambatan notifikasi lintas-lapis (port & adapter) — memutus siklus impor
``alfa.tools`` ← ``alfa.bot``.

Dulu tool menulis ``from alfa.bot import telegram_bot`` di dalam fungsi
(313 lazy import hidup dari siklus modul). Sekarang:

- Bot mendaftarkan dirinya ke port ini saat modul dimuat (adapter sisi-lokap).
- Tools memanggil :func:`send_message` / :func:`get_swarm_templates` tanpa
  pernah mengimpor paket bot; fallback lazy tetap ada demi kompatibilitas
  bila contoh berjalan tanpa bot (CLI/test).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("Core.Notification")

# ── Registry (dipasang oleh sisi bot) ────────────────────────────────────────
_send_message: Callable[..., Awaitable[dict[str, Any]]] | None = None
_templates_provider: Callable[[], dict[str, Any]] | None = None
_app_provider: Callable[[], Any] | None = None
_loop_provider: Callable[[], Any] | None = None


def register_send_message(fn) -> None:
    """Adapter bot: taruh fungsi terkirim pesan (dipanggil saat bot dimuat)."""
    global _send_message
    import inspect

    if fn is not None and inspect.iscoroutinefunction(fn):
        _send_message = fn
    else:
        logger.warning("register_send_message: fungsi bukan coroutine — diabaikan")


def register_swarm_templates(fn) -> None:
    global _templates_provider
    _templates_provider = fn


def register_telegram_runtime(app_provider, loop_provider) -> None:
    """Adapter bot: penyedia application+loop Telegram aktif."""
    global _app_provider, _loop_provider
    _app_provider = app_provider
    _loop_provider = loop_provider


def is_registered() -> bool:
    return _send_message is not None


def get_swarm_templates() -> dict[str, Any]:
    """Ambil SWARM_TEMPLATES tanpa impor alfa.bot dari lapisan tools."""
    if _templates_provider is not None:
        try:
            return _templates_provider() or {}
        except Exception as e:
            logger.debug(f"templates provider gagal: {e}")
    # Fallback lazy (satu-satunya subsys yang tetap boleh lazy)
    try:
        from alfa.bot.mode_commands import SWARM_TEMPLATES

        return SWARM_TEMPLATES
    except Exception:
        return {}


def get_telegram_runtime() -> tuple[Any, Any]:
    """Return (application, loop) Telegram yang aktif, tanpa siklus impor.

    Fallback: alfa.swarm.subagents (bukan bot, bukan siklus).
    """
    if _app_provider is not None:
        try:
            return _app_provider(), _loop_provider() if _loop_provider else None
        except Exception as e:
            logger.debug(f"runtime provider gagal: {e}")
    try:
        from alfa.swarm import subagents

        return subagents.get_telegram_app(), subagents.get_telegram_loop()
    except Exception:
        return None, None


async def safe_send_message(
    application: Any,
    chat_id: int,
    text: str,
    reply_markup: Any = None,
) -> dict[str, Any]:
    """Kirim pesan Telegram melalui adapter yang teregistrasi (anti-siklus).

    Prioritas: adapter bot aktif → ``alfa.bot.helpers.safe_send_message``
    (fallback lazy demi CLI/proses dashboard tanpa konteks bot).
    """
    if _send_message is not None:
        try:
            return await _send_message(application, chat_id, text, reply_markup)
        except Exception as e:
            logger.debug(f"adapter send_message gagal: {e}")
            # adiabatik: coba jalur sub-loop bot bila ada runtime aktif
    try:
        from alfa.bot.helpers import safe_send_message as _helpers_send

        return await _helpers_send(application, chat_id, text, reply_markup)
    except Exception as e:
        logger.warning(f"send_message gagal total: {e}")
        return {"status": "error", "message": str(e)}


def safe_send_message_sync(
    application: Any, chat_id: int, text: str, reply_markup: Any = None
) -> dict[str, Any]:
    """Varian sync untuk konteks non-async (dashboard thread/loop asing)."""
    coro = safe_send_message(application, chat_id, text, reply_markup)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_coro_blocking, coro).result(timeout=30)
    return _run_coro_blocking(coro)


def _run_coro_blocking(coro) -> dict[str, Any]:
    return asyncio.run(coro)
