"""Combined command mixin for ALFA CLI."""

from alfa.core.cli.basic_commands import CliBasicCommandsMixin
from alfa.core.cli.slash_commands import CliSlashCommandsMixin


class CliCommandsMixin(CliBasicCommandsMixin, CliSlashCommandsMixin):
    """Aggregates basic commands and advanced slash commands."""
    pass
