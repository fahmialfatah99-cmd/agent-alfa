"""ALFA Core Subsystems: Database, Brain, Permissions, Runtime Context, and CLI."""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
root_dir = str(Path(__file__).resolve().parents[2])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from alfa.core import brain, cli, database, permissions, runtime_ctx
from alfa.core.brain import get_brain, get_main_brain

__all__ = [
    "brain",
    "cli",
    "database",
    "permissions",
    "runtime_ctx",
    "get_brain",
    "get_main_brain",
]
