"""Konteks runtime bersama antar-modul (bebas impor melingkar).

ContextVar identitas user/chat dipakai lintas lapisan (tools, swarm,
gdrive_suite, bot). Diletakkan di modul netral supaya modul hasil pemecahan
monolit bisa memakainya tanpa mengimpor tools.py (menghindari siklus).
"""

from contextvars import ContextVar

current_user_id_var: ContextVar[int] = ContextVar("current_user_id", default=0)
current_chat_id_var: ContextVar[int] = ContextVar("current_chat_id", default=0)


def get_current_user_id() -> int:
    """Get active Telegram User ID for the current agent turn."""
    uid = current_user_id_var.get()
    return uid if uid else 0


def get_current_chat_id() -> int:
    """Get active Telegram Chat ID for the current agent turn."""
    cid = current_chat_id_var.get()
    return cid if cid else get_current_user_id()
