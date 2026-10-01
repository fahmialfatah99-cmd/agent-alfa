"""Command handlers for ALFA CLI - Slash Commands Mixin (facade).

The 1170-line monolith was decomposed into domain mixins under
`alfa.core.cli.slash`; this facade recomposes them in one MRO so
`CliCommandsMixin` and all `do_slash_*` call sites keep working unchanged.
"""

from __future__ import annotations

from typing import Any

from alfa.core.cli.slash import (
    SlashDeveloperMixin,
    SlashNavigationMixin,
    SlashProvidersMixin,
    SlashServersMixin,
    SlashSwarmMixin,
    SlashVaultMixin,
)


class CliSlashCommandsMixin(
    SlashNavigationMixin,
    SlashProvidersMixin,
    SlashSwarmMixin,
    SlashServersMixin,
    SlashVaultMixin,
    SlashDeveloperMixin,
):
    """Implements slash commands for server orchestration, direct AI, and developer tools."""

    # Attributes provided by AlfaCLI composition (declared for type checkers).
    config: dict[str, Any]
    console: Any
    chat_history: list[dict[str, str]]
    streaming: bool
    server_url: str
    mode: str
    session_token: str | None
    username: str | None
    direct_ai: Any
    agent_runner: Any
    attached_files: list[str]
    patch_manager: Any
    repomap_gen: Any

    def _request(self, *args: Any, **kwargs: Any) -> Any: ...
    def _save_config(self) -> None: ...
    def _update_prompt(self) -> None: ...
    def _save_session(self) -> None: ...
    def _clear_session(self) -> None: ...
    def _save_history(self) -> None: ...
    def _run_swarm_execution(self, *args: Any, **kwargs: Any) -> Any: ...
