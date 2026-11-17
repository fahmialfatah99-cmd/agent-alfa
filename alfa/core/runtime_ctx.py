"""Shared runtime context across modules (circular-import free).

ContextVar for user/chat identity used across layers (tools, swarm,
gdrive_suite, bot). Placed in a neutral module so decomposed monoliths
can use it without importing tools.py (avoiding cycles).
"""

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("RuntimeCtx")

current_user_id_var: ContextVar[int] = ContextVar("current_user_id", default=0)
current_turn_id_var: ContextVar[str] = ContextVar("current_turn_id", default="")
current_chat_id_var: ContextVar[int] = ContextVar("current_chat_id", default=0)
current_conversation_id_var: ContextVar[str] = ContextVar(
    "current_conversation_id", default=""
)
current_user_prompt_var: ContextVar[str] = ContextVar("current_user_prompt", default="")
current_tool_event_cb_var: ContextVar[Any] = ContextVar(
    "current_tool_event_cb", default=None
)
current_executed_tools_var: ContextVar[list[str] | None] = ContextVar(
    "current_executed_tools", default=None
)
current_executed_tool_calls_var: ContextVar[list[dict[str, str]] | None] = ContextVar(
    "current_executed_tool_calls", default=None
)
current_turn_artifacts_var: ContextVar[list[str] | None] = ContextVar(
    "current_turn_artifacts", default=None
)


def get_current_user_id() -> int:
    """Get active Telegram User ID for the current agent turn."""
    uid = current_user_id_var.get()
    return uid if uid else 0


def get_current_chat_id() -> int:
    """Get active Telegram Chat ID for the current agent turn."""
    cid = current_chat_id_var.get()
    return cid if cid else get_current_user_id()


def get_current_conversation_id() -> str:
    """Get active dashboard conversation/thread id ('' untuk kanal non-dashboard)."""
    return current_conversation_id_var.get() or ""


def set_tool_event_callback(callback: Any) -> Any:
    """Pasang callback sinkron (nama_tool, args_teredaksi) untuk event UI.

    Callback dipanggil dari event loop yang sama; implementasi harus tidak
    memblokir (mis. ``queue.put_nowait``). ``None`` mematikan callback.
    Return token ContextVar yang bisa dipakai untuk ``reset``.
    """
    return current_tool_event_cb_var.set(callback)


def get_current_user_prompt() -> str:
    """Get active prompt/instruction for the current agent turn."""
    return current_user_prompt_var.get() or ""


def begin_turn() -> str:
    """Mulai giliran baru dan kembalikan ``turn_id`` unik.

    ``turn_id`` dipakai evidence ledger untuk mengikat bukti tool ke satu
    giliran chat. Nilainya sengaja TIDAK direset oleh ``reset_turn_context``
    agar wrapper turn dan tool yang dieksekusi tetap melihat id yang sama.
    """
    turn_id = uuid.uuid4().hex
    current_turn_id_var.set(turn_id)
    return turn_id


def ensure_turn_id() -> str:
    """Pastikan ada ``turn_id`` aktif (dibuat bila belum ada)."""
    current = current_turn_id_var.get()
    return current if current else begin_turn()


def get_current_turn_id() -> str:
    """Get active turn id for evidence/audit correlation."""
    return current_turn_id_var.get() or ""


def summarize_tool_args(args: str | None, limit: int = 400) -> str:
    """Ringkas argumen tool + redaksi rahasia (publik, dipakai audit)."""
    return _summarize_tool_args(args, limit=limit)


_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|password|secret|authorization)"
    r"([\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)"
)


def redact_sensitive(text: str | None, limit: int = 400) -> str:
    """Redaksi nilai rahasia dan potong teks (audit/evidence safe)."""
    if not text:
        return ""
    redacted = _SECRET_RE.sub(r"\1\2***", str(text))
    return redacted[: max(0, int(limit))]


def _summarize_tool_args(args: str | None, limit: int = 400) -> str:
    """Ringkas argumen tool dan redaksi nilai rahasia."""
    return redact_sensitive(args, limit=limit)


def record_executed_tool(name: str, args: str | None = None) -> None:
    """Record a tool execution during the current turn (thread-safe in-place append).

    ``args`` bersifat opsional agar pemanggil lama tetap kompatibel; bila
    diberikan, argumen (setelah redaksi rahasia) disimpan untuk audit trail.
    """
    if not name:
        return
    tool_name = str(name)
    cur = current_executed_tools_var.get()
    if isinstance(cur, list):
        cur.append(tool_name)
    else:
        current_executed_tools_var.set([tool_name])

    calls = current_executed_tool_calls_var.get()
    if not isinstance(calls, list):
        calls = []
        current_executed_tool_calls_var.set(calls)
    entry: dict[str, str] = {"tool": tool_name}
    summary = _summarize_tool_args(args)
    if summary:
        entry["args"] = summary
    calls.append(entry)

    cb = current_tool_event_cb_var.get()
    if cb is not None:
        try:
            cb(tool_name, summary)
        except Exception as cb_err:  # noqa: BLE001 - UI callback tidak boleh mematikan tool
            logger.debug("tool event callback gagal: %s", cb_err)


def get_current_executed_tools() -> list[str]:
    """Get the list of tools executed in the current turn."""
    return list(current_executed_tools_var.get() or [])


def get_current_executed_tool_calls() -> list[dict[str, str]]:
    """Get tool calls (nama + argumen teredaksi) untuk audit trail."""
    return [dict(item) for item in (current_executed_tool_calls_var.get() or [])]


def record_turn_artifact(path: str) -> None:
    """Record an artifact file path explicitly generated for the user in this turn."""
    if not path:
        return
    cur = current_turn_artifacts_var.get()
    if isinstance(cur, list):
        if path not in cur:
            cur.append(str(path))
    else:
        current_turn_artifacts_var.set([str(path)])


def get_current_turn_artifacts() -> list[str]:
    """Get explicitly registered artifacts for this turn."""
    return list(current_turn_artifacts_var.get() or [])


def reset_turn_context() -> None:
    """Reset per-turn execution state (tools and artifacts)."""
    current_executed_tools_var.set([])
    current_executed_tool_calls_var.set([])
    current_turn_artifacts_var.set([])


__all__ = [
    "current_user_id_var",
    "current_chat_id_var",
    "current_conversation_id_var",
    "current_user_prompt_var",
    "current_turn_id_var",
    "current_executed_tools_var",
    "current_executed_tool_calls_var",
    "current_turn_artifacts_var",
    "current_tool_event_cb_var",
    "get_current_user_id",
    "get_current_chat_id",
    "get_current_conversation_id",
    "set_tool_event_callback",
    "get_current_user_prompt",
    "begin_turn",
    "ensure_turn_id",
    "get_current_turn_id",
    "summarize_tool_args",
    "redact_sensitive",
    "record_executed_tool",
    "get_current_executed_tools",
    "get_current_executed_tool_calls",
    "record_turn_artifact",
    "get_current_turn_artifacts",
    "reset_turn_context",
]

