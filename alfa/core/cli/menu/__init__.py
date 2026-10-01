"""Interactive TUI menu package: grouped menus plus dispatcher."""

from alfa.core.cli.menu.agents import (
    menu_configure_agent_models as menu_configure_agent_models,
)
from alfa.core.cli.menu.agents import menu_switch_persona as menu_switch_persona
from alfa.core.cli.menu.dispatcher import open_interactive_menu as open_interactive_menu
from alfa.core.cli.menu.files_ctx import get_workspace_files as get_workspace_files
from alfa.core.cli.menu.files_ctx import (
    menu_manage_context_files as menu_manage_context_files,
)
from alfa.core.cli.menu.models import menu_setup_api_keys as menu_setup_api_keys
from alfa.core.cli.menu.models import menu_switch_model as menu_switch_model
from alfa.core.cli.menu.models import menu_switch_preset as menu_switch_preset
from alfa.core.cli.menu.modes import (
    menu_switch_agent_execution_mode as menu_switch_agent_execution_mode,
)
from alfa.core.cli.menu.modes import menu_switch_mode as menu_switch_mode
from alfa.core.cli.menu.ops import menu_git_actions as menu_git_actions
from alfa.core.cli.menu.ops import menu_manage_servers as menu_manage_servers
from alfa.core.cli.menu.ops import menu_undo_patch as menu_undo_patch

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
