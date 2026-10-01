"""Backward-compatibility facade for the split DirectAI modules.

Provider catalog data lives in `alfa.core.cli.providers_catalog`,
the LLM client in `alfa.core.cli.client`; all public names are
re-exported here so existing imports keep working unchanged.
"""

from alfa.core.cli.client import DirectAIClient as DirectAIClient
from alfa.core.cli.providers_catalog import (
    DEFAULT_SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT,
)
from alfa.core.cli.providers_catalog import PRESETS as PRESETS
from alfa.core.cli.providers_catalog import PROVIDERS_CATALOG as PROVIDERS_CATALOG
from alfa.core.cli.providers_catalog import normalize_provider as normalize_provider
from alfa.core.cli.providers_catalog import (
    sync_providers_catalog as sync_providers_catalog,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "PRESETS",
    "PROVIDERS_CATALOG",
    "DirectAIClient",
    "normalize_provider",
    "sync_providers_catalog",
]
