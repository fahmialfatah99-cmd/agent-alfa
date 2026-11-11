"""Utilitas bersama: akses modul bot & otorisasi user."""

from __future__ import annotations

import sys

from telegram.error import TelegramError

from alfa.bot.config import is_authorized as _config_is_authorized

logger = __import__("logging").getLogger("TelegramAIAgent")

#: Error yang realistis pada alur perintah bot.
_ADV_ERR = (
    TelegramError,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)


def _get_bot_module():
    """Modul bot Telegram yang sedang berjalan (atau None)."""
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return _config_is_authorized(user_id)
