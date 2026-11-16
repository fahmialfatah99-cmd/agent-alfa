"""Perintah /runs dan /lanjut untuk P1 Durable Task Runtime.

- ``/runs``   : daftar giliran terakhir + yang bisa dilanjutkan.
- ``/lanjut`` : lanjutkan satu tugas yang terputus (hanya mode ``on``).

Semua perintah fail-soft: kegagalan DB tidak boleh mematikan bot.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from alfa.bot.advanced_commands._compat import is_authorized, safe_send_message
from alfa.core.config import env_int

logger = logging.getLogger("TelegramAIAgent")

_STATUS_ICON = {
    "running": "⏳",
    "completed": "✅",
    "failed": "❌",
    "interrupted": "⏸️",
    "paused": "⏸️",
}


def _short(text: str, limit: int = 70) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def runs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /runs — daftar durable task terbaru."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    from alfa.core.db.durable_tasks import (
        durable_mode,
        list_resumable_tasks_sync,
        list_tasks_sync,
        task_count_sync,
    )

    mode = durable_mode()
    tasks = list_tasks_sync(user_id=user_id, limit=10)
    resumable = list_resumable_tasks_sync(user_id=user_id, limit=5)

    lines = [
        "🧭 *ALFA DURABLE TASK RUNTIME*",
        f"• Mode: `{mode}`",
        f"• Total baris: `{task_count_sync()}`",
        "• Status disimpan per giliran (prompt, progres tool, error).\n",
    ]
    if not tasks:
        lines.append("Belum ada giliran terekam.")
    else:
        lines.append("📋 *Giliran terakhir:*")
        for task in tasks:
            icon = _STATUS_ICON.get(str(task.get("status")), "•")
            lines.append(
                f"{icon} `{str(task.get('task_id') or '')[:10]}` "
                f"({task.get('step_index', 0)} langkah) — "
                f"{_short(str(task.get('prompt') or ''))}"
            )

    if resumable:
        lines.append("\n▶️ *Bisa dilanjutkan:*")
        for task in resumable:
            lines.append(
                f"• `{task.get('task_id')}` "
                f"(attempt {task.get('attempts', 0)}/{task.get('max_attempts', 1)})"
            )
        lines.append("\nKetik `/lanjut <task_id>` untuk melanjutkan.")
    elif mode != "on" and tasks:
        lines.append(
            "\nℹ️ Resume nonaktif. Setel `ALFA_DURABLE_TASKS=on` untuk "
            "mengaktifkan `/lanjut`."
        )
    await safe_send_message(context, chat_id, "\n".join(lines))


async def lanjut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lanjut <task_id> — lanjutkan giliran yang terputus."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    from alfa.core.db.durable_tasks import (
        claim_task_for_resume_sync,
        durable_mode,
        finish_task_sync,
    )

    if durable_mode() != "on":
        await safe_send_message(
            context,
            chat_id,
            "ℹ️ Resume durable task nonaktif. Setel `ALFA_DURABLE_TASKS=on` "
            "lalu restart bot/dashboard (jangan WA bot).",
        )
        return

    args = context.args if context and context.args else []
    task_id = str(args[0]).strip() if args else ""
    if not task_id:
        await safe_send_message(
            context, chat_id, "Format: `/lanjut <task_id>` (lihat `/runs`)."
        )
        return

    claimed = claim_task_for_resume_sync(task_id, user_id=user_id)
    if not claimed:
        await safe_send_message(
            context,
            chat_id,
            f"⚠️ Tugas `{task_id}` tidak bisa dilanjutkan (tidak ada, "
            "bukan milikmu, sudah selesai, atau attempt habis).",
        )
        return

    prompt = str(claimed.get("prompt") or "").strip()
    if not prompt:
        finish_task_sync(task_id, status="failed", error="Prompt kosong.")
        await safe_send_message(context, chat_id, "⚠️ Tugas tidak punya prompt.")
        return

    max_chars = env_int("ALFA_DURABLE_RESUME_MAX_CHARS", 8000, minimum=500)
    if len(prompt) > max_chars:
        finish_task_sync(task_id, status="failed", error="Prompt terlalu panjang.")
        await safe_send_message(
            context, chat_id, "⚠️ Prompt tugas terlalu panjang untuk dilanjutkan."
        )
        return

    await safe_send_message(
        context,
        chat_id,
        f"▶️ Melanjutkan `{task_id}` (attempt {claimed.get('attempts', 0)}/"
        f"{claimed.get('max_attempts', 1)})…",
    )
    try:
        from alfa.bot.turn_executor import run_agent_turn

        reply = await run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            chat_id=chat_id or None,
        )
        finish_task_sync(task_id, status="completed")
        if reply:
            await safe_send_message(context, chat_id, reply)
    except Exception as exc:  # noqa: BLE001 - catat status lalu laporkan
        logger.warning("Resume durable task %s gagal: %s", task_id, exc)
        finish_task_sync(task_id, status="failed", error=str(exc))
        await safe_send_message(
            context, chat_id, f"❌ Gagal melanjutkan `{task_id}`: {exc}"
        )
