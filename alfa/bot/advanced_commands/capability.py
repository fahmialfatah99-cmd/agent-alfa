"""Perintah /capability — kelola grant keamanan berlingkup (P2)."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from alfa.bot.advanced_commands._compat import is_authorized, safe_send_message

logger = logging.getLogger("TelegramAIAgent")


def _fmt_grants(grants: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in grants:
        status = "✅" if item.get("valid") else "⛔"
        max_uses = int(item.get("max_uses") or 0)
        uses = int(item.get("uses") or 0)
        use_text = f"{uses}/{max_uses}" if max_uses else f"{uses}/∞"
        lines.append(
            f"{status} `{item.get('grant_id')}` → `{item.get('tool_name')}` "
            f"(pakai {use_text})"
        )
    return lines


async def capability_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /capability [status|list|grant|revoke]."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    from alfa.core.perm.capabilities import (
        format_capability_status,
        grant_capability_sync,
        list_capabilities_sync,
        revoke_capability_sync,
    )

    args = [str(a).strip() for a in (context.args or []) if str(a).strip()]
    sub = args[0].lower() if args else "status"

    if sub in {"status", "list", "daftar"}:
        grants = list_capabilities_sync(chat_id=chat_id, limit=25)
        lines = [
            "🔐 *ALFA CAPABILITY SECURITY*",
            format_capability_status(chat_id),
            "",
        ]
        if grants:
            lines.append("📋 *Grant terbaru:*")
            lines.extend(_fmt_grants(grants))
        else:
            lines.append("Belum ada grant di chat ini.")
        lines.append(
            "\n*Perintah:*\n"
            "• `/capability grant <tool> [menit] [max_pakai]`\n"
            "• `/capability revoke <grant_id|tool>`"
        )
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    if sub in {"grant", "izinkan", "beri"}:
        if len(args) < 2:
            await safe_send_message(
                context,
                chat_id,
                "Format: `/capability grant <tool> [menit] [max_pakai]`",
            )
            return
        tool = args[1]
        ttl = int(args[2]) if len(args) > 2 and args[2].isdigit() else None
        max_uses = int(args[3]) if len(args) > 3 and args[3].isdigit() else None
        granted = grant_capability_sync(
            chat_id,
            tool,
            user_id=user_id,
            ttl_minutes=ttl,
            max_uses=max_uses,
            source="telegram_command",
            note="Grant via /capability",
        )
        if granted is None:
            await safe_send_message(
                context,
                chat_id,
                "⚠️ Grant gagal (mode `off` atau nama tool kosong).",
            )
            return
        enforce = "ENFORCED" if granted.get("enforced") else "SHADOW (belum enforced)"
        await safe_send_message(
            context,
            chat_id,
            "✅ *CAPABILITY GRANT DIBUAT*\n"
            f"• Grant ID: `{granted.get('grant_id')}`\n"
            f"• Tool: `{granted.get('tool_name')}`\n"
            f"• Berlaku: `{granted.get('ttl_minutes')}` menit\n"
            f"• Maks pakai: `{granted.get('max_uses') or '∞'}`\n"
            f"• Status: *{enforce}*",
        )
        return

    if sub in {"revoke", "cabut", "hapus"}:
        if len(args) < 2:
            await safe_send_message(
                context, chat_id, "Format: `/capability revoke <grant_id|tool>`"
            )
            return
        target = args[1]
        if target.startswith("cap_"):
            removed = revoke_capability_sync(target, user_id=user_id)
        else:
            removed = revoke_capability_sync(chat_id=chat_id, tool_name=target)
        await safe_send_message(
            context,
            chat_id,
            f"{'✅' if removed else 'ℹ️'} {removed} grant dicabut untuk `{target}`.",
        )
        return

    await safe_send_message(
        context,
        chat_id,
        "Format: `/capability [status|grant <tool> [menit] [max_pakai]|revoke <id|tool>]`",
    )


__all__ = ["capability_command"]
