"""Akses dinamis ke simbol paket `alfa.bot.advanced_commands`.

Supaya patch/mock pada `alfa.bot.advanced_commands.<nama>` (dipakai test &
pemanggil internal) tetap memengaruhi sub-modul.
"""

from __future__ import annotations

from typing import Any


def _pkg() -> Any:
    from alfa.bot import advanced_commands

    return advanced_commands


def is_authorized(user_id: int) -> bool:
    return bool(_pkg()._is_authorized(user_id))


def safe_send_message(*args: Any, **kwargs: Any) -> Any:
    return _pkg().safe_send_message(*args, **kwargs)
