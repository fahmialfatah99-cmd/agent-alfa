"""Akses dinamis ke simbol paket `alfa.bot.handlers`.

Sub-modul memanggil helper ini (bukan impor langsung) supaya patch/mock pada
`alfa.bot.handlers.<nama>` — misalnya di test — tetap berlaku untuk pemanggil
internal. Ini menjaga kompatibilitas setelah modul monolitik dipecah.
"""

from __future__ import annotations

from typing import Any


def _pkg() -> Any:
    from alfa.bot import handlers

    return handlers


def safe_send_message(*args: Any, **kwargs: Any) -> Any:
    return _pkg().safe_send_message(*args, **kwargs)


def send_typing_loop(*args: Any, **kwargs: Any) -> Any:
    return _pkg().send_typing_loop(*args, **kwargs)


def run_agent_turn(*args: Any, **kwargs: Any) -> Any:
    return _pkg()._run_agent_turn(*args, **kwargs)


def agent_turn_impl(*args: Any, **kwargs: Any) -> Any:
    """Implementasi agent turn mentah (tanpa audit learning-loop)."""
    return _pkg().run_agent_turn(*args, **kwargs)


def bot_module() -> Any:
    """Modul bot Telegram (atau None saat belum termuat)."""
    return _pkg()._get_bot_module()


def doc_action_callback(*args: Any, **kwargs: Any) -> Any:
    return _pkg().handle_doc_action_callback(*args, **kwargs)


def forward_action_callback(*args: Any, **kwargs: Any) -> Any:
    return _pkg().handle_forward_action_callback(*args, **kwargs)


def check_artifacts_turn(*args: Any, **kwargs: Any) -> Any:
    """Pemeriksa artefak per-turn (nama privat yang di-patch test)."""
    return _pkg()._check_and_send_media_artifacts(*args, **kwargs)


def system_stats(*args: Any, **kwargs: Any) -> Any:
    return _pkg().get_system_stats(*args, **kwargs)


def is_authorized(*args: Any, **kwargs: Any) -> Any:
    return _pkg()._is_authorized(*args, **kwargs)


def check_and_send_media_artifacts(*args: Any, **kwargs: Any) -> Any:
    return _pkg().check_and_send_media_artifacts(*args, **kwargs)


def telegram_streamer(*args: Any, **kwargs: Any) -> Any:
    return _pkg().TelegramStreamer(*args, **kwargs)


def sandbox_dir() -> str:
    return str(_pkg().SANDBOX_DIR)
