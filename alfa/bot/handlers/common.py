"""Utilitas bersama: sapaan, otorisasi, agent turn, nudge."""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from telegram.ext import ContextTypes

from alfa.bot.config import is_authorized
from alfa.bot.handlers._compat import agent_turn_impl, bot_module, safe_send_message
from alfa.bot.handlers._state import (
    _GREETING_EXACT,
    _HANDLER_ERR,
)

logger = logging.getLogger("TelegramAIAgent")

def greeting_reply(text: str) -> str | None:
    """Balasan sapaan instan, atau None bila bukan sapaan murni.

    Hanya cocok bila SELURUH pesan = sapaan (tanpa permintaan lain),
    jadi 'oke tolong screenshot' tetap masuk agent seperti biasa.
    """
    norm = (text or "").lower().strip()
    for ch in "!?.,-—…":
        norm = norm.replace(ch, " ")
    norm = " ".join(norm.split())
    if norm in _GREETING_EXACT:
        return (
            "Halo juga! 👋 Saya **ALFA**, asisten AI otonom.\n"
            "Ada yang bisa dibantu? Ketik `/menu` untuk lihat semua fitur."
        )
    return None

def _get_bot_module():
    """Retrieve telegram_bot module to support mocking in tests."""
    if "alfa.bot.telegram_bot" not in sys.modules:
        try:
            import importlib
            return importlib.import_module("alfa.bot.telegram_bot")
        except Exception as exc:
            logger.debug("Kegagalan tak terduga di _get_bot_module: %s", exc)
    return sys.modules.get("alfa.bot.telegram_bot")

def _is_authorized(user_id: int) -> bool:
    mod = bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)

async def _run_agent_turn(*args, **kwargs):
    turn_started_at = time.time()
    mod = bot_module()
    if mod and hasattr(mod, "run_agent_turn"):
        raw_res = await mod.run_agent_turn(*args, **kwargs)
    else:
        raw_res = await agent_turn_impl(*args, **kwargs)

    # Pre-Flight Self-Audit, Trajectory Recording & GraphRAG Model Ingestion
    try:
        from alfa.core.apex.temporal_graphrag import ingest_text_to_temporal_graph
        from alfa.core.brain.learning_loop import (
            audit_against_learned_skills,
            record_trajectory,
        )
        from alfa.core.runtime_ctx import (
            get_current_executed_tool_calls,
            get_current_executed_tools,
        )

        user_p = kwargs.get("user_prompt") or (args[1] if len(args) > 1 else "")
        exec_tools = get_current_executed_tools()
        exec_tool_calls = get_current_executed_tool_calls()
        if isinstance(raw_res, str):
            is_valid, msg, corrected = audit_against_learned_skills(user_p, raw_res)
            if not is_valid and corrected:
                logger.info("Auto-corrected agent reply via learned skill compliance: %s", msg)
                raw_res = corrected
            record_trajectory(
                user_prompt=user_p,
                tool_calls=exec_tool_calls or [{"tool": t} for t in exec_tools],
                result_summary=raw_res[:200],
                success=True,
            )
            ingest_text_to_temporal_graph(raw_res)
    except Exception as e:
        logger.debug("Learning loop audit bypass: %s", e)

    # Guard lapis kedua: pastikan peringatan verifikasi artefak tidak hilang
    # bila audit learning-loop mengganti teks balasan di atas.
    try:
        from alfa.core.brain.artifact_verify import apply_artifact_guard

        if isinstance(raw_res, str):
            raw_res, _ = apply_artifact_guard(raw_res, turn_started_at)
    except Exception as e:  # noqa: BLE001 - guard tidak boleh mematikan turn
        logger.debug("Artifact guard bypass: %s", e)

    return raw_res

async def _long_turn_nudge(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    turn_task: asyncio.Task,
    streamer,
    first_delay: float = 12.0,
) -> None:
    """Kirim pesan penenang bertahap bila turn single-mode lama tanpa update agar pengguna tahu bot aktif bekerja."""
    try:
        await asyncio.sleep(first_delay)
        if turn_task.done():
            return
        has_content = bool(streamer and getattr(streamer, "buffer", "").strip())
        if not has_content:
            await safe_send_message(
                context,
                chat_id,
                "⏳ Sedang menghubungkan ke server AI & memproses... Mohon tunggu sebentar ya!",
            )
        await asyncio.sleep(45.0)
        if turn_task.done():
            return
        has_content = bool(streamer and getattr(streamer, "buffer", "").strip())
        if not has_content:
            await safe_send_message(
                context,
                chat_id,
                "🧠 Masih diproses (server AI membutuhkan waktu respons lebih lama dari biasanya). Hasil segera dikirim setelah selesai.",
            )
    except asyncio.CancelledError:
        pass
    except _HANDLER_ERR as e:
        logger.debug(f"[nudge] gagal: {e}")
