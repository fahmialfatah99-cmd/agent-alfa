"""Slash-command package: domain mixins composed into CliSlashCommandsMixin."""

from alfa.core.cli.slash.agents_swarm import SlashSwarmMixin
from alfa.core.cli.slash.developer import SlashDeveloperMixin
from alfa.core.cli.slash.extras import SlashExtrasMixin
from alfa.core.cli.slash.navigation import SlashNavigationMixin
from alfa.core.cli.slash.providers import SlashProvidersMixin
from alfa.core.cli.slash.servers import SlashServersMixin
from alfa.core.cli.slash.vault import SlashVaultMixin

__all__ = [
    "SlashNavigationMixin",
    "SlashProvidersMixin",
    "SlashSwarmMixin",
    "SlashServersMixin",
    "SlashVaultMixin",
    "SlashDeveloperMixin",
    "SlashExtrasMixin",
]
