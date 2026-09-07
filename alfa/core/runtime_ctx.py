"""Shared runtime context across modules (circular-import free).

ContextVar for user/chat identity used across layers (tools, swarm,
gdrive_suite, bot). Placed in a neutral module so decomposed monoliths
can use it without importing tools.py (avoiding cycles).
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


__all__ = [
    "current_user_id_var",
    "current_chat_id_var",
    "get_current_user_id",
    "get_current_chat_id",
]
