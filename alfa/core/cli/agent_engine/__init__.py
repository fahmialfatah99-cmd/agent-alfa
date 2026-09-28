"""Autonomous agent engine (split from monolithic agent_engine.py).

Re-exports the full public surface for backward compatibility.
"""

from alfa.core.cli.agent_engine.patch_history import PatchHistoryManager, PatchRecord
from alfa.core.cli.agent_engine.prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
from alfa.core.cli.agent_engine.repomap import RepomapGenerator
from alfa.core.cli.agent_engine.runner import AutonomousAgentRunner
from alfa.core.cli.agent_engine.tool_registry import LocalToolRegistry

__all__ = [
    "AGENT_SYSTEM_PROMPT_TEMPLATE",
    "AutonomousAgentRunner",
    "LocalToolRegistry",
    "PatchHistoryManager",
    "PatchRecord",
    "RepomapGenerator",
]
