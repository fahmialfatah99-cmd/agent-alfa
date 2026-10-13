"""ALFA Core Subsystems: Database, Brain, Permissions, Runtime Context, and CLI."""

import importlib
from typing import Any

from alfa.core import cli, permissions, runtime_ctx

__all__ = [
    "brain",
    "cli",
    "database",
    "permissions",
    "runtime_ctx",
    "get_brain",
    "get_main_brain",
]


def __getattr__(name: str) -> Any:
    if name in ("brain", "get_brain", "get_main_brain"):
        mod = importlib.import_module("alfa.core.brain")
        return getattr(mod, name) if name != "brain" else mod
    if name == "database":
        return importlib.import_module("alfa.core.database")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

