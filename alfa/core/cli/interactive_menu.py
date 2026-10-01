"""Backward-compatibility facade for the split interactive-menu modules.

All menu helpers live in `alfa.core.cli.menu`; every public name is
re-exported here so existing imports keep working unchanged.
"""

from alfa.core.cli.menu import get_workspace_files as get_workspace_files
from alfa.core.cli.menu import (
    menu_configure_agent_models as menu_configure_agent_models,
)
from alfa.core.cli.menu import menu_git_actions as menu_git_actions
from alfa.core.cli.menu import menu_manage_context_files as menu_manage_context_files
from alfa.core.cli.menu import menu_manage_servers as menu_manage_servers
from alfa.core.cli.menu import menu_setup_api_keys as menu_setup_api_keys
from alfa.core.cli.menu import (
    menu_switch_agent_execution_mode as menu_switch_agent_execution_mode,
)
from alfa.core.cli.menu import menu_switch_mode as menu_switch_mode
from alfa.core.cli.menu import menu_switch_model as menu_switch_model
from alfa.core.cli.menu import menu_switch_persona as menu_switch_persona
from alfa.core.cli.menu import menu_switch_preset as menu_switch_preset
from alfa.core.cli.menu import menu_undo_patch as menu_undo_patch
from alfa.core.cli.menu import open_interactive_menu as open_interactive_menu

__all__ = [
    "get_workspace_files",
    "menu_switch_model",
    "menu_manage_context_files",
    "menu_switch_preset",
    "menu_switch_mode",
    "menu_setup_api_keys",
    "menu_git_actions",
    "menu_undo_patch",
    "menu_switch_persona",
    "menu_manage_servers",
    "menu_switch_agent_execution_mode",
    "menu_configure_agent_models",
    "open_interactive_menu",
]
