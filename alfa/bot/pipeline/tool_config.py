"""Pipeline Stage 2: Tool Registry Deduplication and Gemini Config Preparation."""

from __future__ import annotations

import logging
from typing import Any

import plugins
from alfa.tools import AVAILABLE_TOOLS

logger = logging.getLogger("ToolConfigPipeline")


def prepare_tools_and_configs(
    model_name: str,
    system_instruction: str,
    user_prompt: str,
    history_msgs: list,
    action_intent: bool,
) -> tuple[list, Any, Any, Any]:
    """Dedup tool registry + pilihan fungsi relevan RAG; susun konfig generation.

    Return ``(gemini_tools, config, config_force, config_wrapup)``.
    """
    from google.genai import types

    all_tools = list(AVAILABLE_TOOLS)
    try:
        plugin_tools = plugins.load_all_plugin_tools()
        if plugin_tools:
            all_tools = list(AVAILABLE_TOOLS) + plugin_tools
    except (ImportError, OSError, AttributeError, TypeError, ValueError) as e:
        logger.warning(f"Failed to load dynamic plugins: {e}")

    seen_fn_names = set()
    deduped_tools = []
    for tool_fn in all_tools:
        nm = getattr(tool_fn, "__name__", "")
        if nm and nm not in seen_fn_names:
            seen_fn_names.add(nm)
            deduped_tools.append(tool_fn)
        elif not nm and tool_fn not in deduped_tools:
            deduped_tools.append(tool_fn)
    all_tools = deduped_tools

    try:
        from alfa.bot.mode_commands import get_telegram_mode_sync

        if get_telegram_mode_sync() == "single":
            prompt_low = (user_prompt or "").lower()
            if not any(
                k in prompt_low
                for k in ("rapat", "meeting", "swarm", "musyawarah", "war room", "tim agen")
            ):
                all_tools = [
                    t for t in all_tools if getattr(t, "__name__", "") != "conduct_ai_meeting"
                ]
    except Exception:
        pass

    gemini_tools: Any = all_tools
    try:
        from alfa.tools.rag import select_relevant_functions

        gemini_tools = select_relevant_functions(
            all_tools, user_prompt or "", history=history_msgs
        )
    except (ImportError, ValueError, TypeError, KeyError):
        pass

    _afc_off = types.AutomaticFunctionCallingConfig(disable=True)
    # AUTO: model bebas memanggil tool ATAU menjawab teks (dipakai semua
    # putaran sesudah panggilan pertama agar giliran selalu ditutup
    # dengan jawaban teks nyata, bukan loop tool tanpa akhir).
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.75,
        tools=gemini_tools,
        automatic_function_calling=_afc_off,
    )
    # ANY: HANYA dipakai pada panggilan PERTAMA bila ini permintaan aksi,
    # supaya model tidak cukup menjawab basa-basi tanpa menjalankan tool.
    if action_intent:
        _allowed = sorted(
            {
                getattr(t, "__name__", "")
                for t in gemini_tools
                if getattr(t, "__name__", "")
            }
        )
        config_force = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.75,
            tools=gemini_tools,
            automatic_function_calling=_afc_off,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                    allowed_function_names=_allowed,
                )
            ),
        )
    else:
        config_force = config
    # Tanpa tool: dipakai untuk wrap-up agar model WAJIB merangkum hasil
    # nyata dalam teks saat iterasi tool habis / jawaban kosong.
    config_wrapup = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
    )
    return gemini_tools, config, config_force, config_wrapup
