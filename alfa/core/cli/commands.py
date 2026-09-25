"""Combined command mixin for ALFA CLI."""

from alfa.core.cli.basic_commands import CliBasicCommandsMixin
from alfa.core.cli.slash_commands import CliSlashCommandsMixin


class CliCommandsMixin(CliSlashCommandsMixin, CliBasicCommandsMixin):
    """Aggregates advanced slash commands and basic server commands."""

    pass
