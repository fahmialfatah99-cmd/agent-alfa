"""ALFA Bot Execution Pipeline.

Modular stages for autonomous agent turn execution:
- context_builder: Memory retrieval, rolling compaction, and system prompt formatting
- tool_config: Tool selection, dynamic plugins, and Gemini tool configs
- audit_pass: Anti-hallucination auditor and claim verification pass
- provider_adapter: Alternative provider support (OpenAI-compatible, OpenRouter, Groq)
"""

from alfa.bot.pipeline.audit_pass import audit_correction_pass
from alfa.bot.pipeline.context_builder import (
    build_memory_block,
    build_system_instruction,
    format_compaction,
    maybe_compact_history,
    summarize_chunk,
)
from alfa.bot.pipeline.provider_adapter import (
    openai_compat_turn,
    try_alt_provider_keys,
)
from alfa.bot.pipeline.tool_config import prepare_tools_and_configs

__all__ = [
    "audit_correction_pass",
    "build_memory_block",
    "build_system_instruction",
    "format_compaction",
    "maybe_compact_history",
    "openai_compat_turn",
    "prepare_tools_and_configs",
    "summarize_chunk",
    "try_alt_provider_keys",
]
