"""Shared runtime context across modules (circular-import free).

ContextVar for user/chat identity used across layers (tools, swarm,
gdrive_suite, bot). Placed in a neutral module so decomposed monoliths
can use it without importing tools.py (avoiding cycles).
"""

from contextvars import ContextVar

current_user_id_var: ContextVar[int] = ContextVar("current_user_id", default=0)
current_chat_id_var: ContextVar[int] = ContextVar("current_chat_id", default=0)
current_user_prompt_var: ContextVar[str] = ContextVar("current_user_prompt", default="")
current_executed_tools_var: ContextVar[list[str] | None] = ContextVar(
    "current_executed_tools", default=None
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


def get_current_user_prompt() -> str:
    """Get active prompt/instruction for the current agent turn."""
    return current_user_prompt_var.get() or ""


def record_executed_tool(name: str) -> None:
    """Record a tool execution during the current turn."""
    if not name:
        return
    tools = list(current_executed_tools_var.get() or [])
    tools.append(str(name))
    current_executed_tools_var.set(tools)


def get_current_executed_tools() -> list[str]:
    """Get the list of tools executed in the current turn."""
    return list(current_executed_tools_var.get() or [])


def record_turn_artifact(path: str) -> None:
    """Record an artifact file path explicitly generated for the user in this turn."""
    if not path:
        return
    arts = list(current_turn_artifacts_var.get() or [])
    if path not in arts:
        arts.append(str(path))
    current_turn_artifacts_var.set(arts)


def get_current_turn_artifacts() -> list[str]:
    """Get explicitly registered artifacts for this turn."""
    return list(current_turn_artifacts_var.get() or [])


def reset_turn_context() -> None:
    """Reset per-turn execution state (tools and artifacts)."""
    current_executed_tools_var.set([])
    current_turn_artifacts_var.set([])


__all__ = [
    "current_user_id_var",
    "current_chat_id_var",
    "current_user_prompt_var",
    "current_executed_tools_var",
    "current_turn_artifacts_var",
    "get_current_user_id",
    "get_current_chat_id",
    "get_current_user_prompt",
    "record_executed_tool",
    "get_current_executed_tools",
    "record_turn_artifact",
    "get_current_turn_artifacts",
    "reset_turn_context",
]

