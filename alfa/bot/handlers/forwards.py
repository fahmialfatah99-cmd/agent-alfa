"""Pesan ter-forward & aksi batch forward."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from telegram import Update, constants
from telegram.ext import ContextTypes

from alfa.bot.handlers._compat import (
    check_artifacts_turn,
    run_agent_turn,
    safe_send_message,
    send_typing_loop,
)
from alfa.bot.handlers._state import (
    _RECENT_FORWARD_BATCHES,
)

logger = logging.getLogger("TelegramAIAgent")

def get_forward_info(msg: Any) -> dict[str, Any] | None:
    """Deteksi apakah pesan Telegram adalah pesan terusan (forwarded message)."""
    if not msg:
        return None
    origin = getattr(msg, "forward_origin", None)
    if not origin:
        if (
            getattr(msg, "forward_date", None)
            or getattr(msg, "forward_from", None)
            or getattr(msg, "forward_from_chat", None)
            or getattr(msg, "forward_sender_name", None)
        ):
            sender = ""
            if getattr(msg, "forward_from", None):
                sender = msg.forward_from.full_name or msg.forward_from.username or ""
            elif getattr(msg, "forward_from_chat", None):
                sender = msg.forward_from_chat.title or ""
            elif getattr(msg, "forward_sender_name", None):
                sender = msg.forward_sender_name
            return {"sender": sender or "Pengirim", "type": "legacy"}
        return None

    sender = ""
    otype = str(getattr(origin, "type", "") or "")
    if otype == "user":
        u = getattr(origin, "sender_user", None)
        if u:
            sender = getattr(u, "full_name", "") or getattr(u, "username", "")
    elif otype == "hidden_user":
        sender = getattr(origin, "sender_user_name", "")
    elif otype == "chat":
        c = getattr(origin, "sender_chat", None)
        if c:
            sender = getattr(c, "title", "")
    elif otype == "channel":
        ch = getattr(origin, "chat", None)
        if ch:
            sender = getattr(ch, "title", "")
    else:
        # Fallback check
        if getattr(origin, "sender_user", None):
            sender = getattr(origin.sender_user, "full_name", "") or getattr(origin.sender_user, "username", "")
        elif getattr(origin, "sender_user_name", None):
            sender = origin.sender_user_name
        elif getattr(origin, "sender_chat", None):
            sender = getattr(origin.sender_chat, "title", "")
        elif getattr(origin, "chat", None):
            sender = getattr(origin.chat, "title", "")

    return {"sender": sender or "Pengirim", "type": str(otype)}

async def _execute_forward_batch(chat_id: int, batch: dict[str, Any]) -> None:
    """Eksekusi setelah seluruh batch pesan terusan selesai terkirim (debounced)."""
    items = batch.get("items", [])
    if not items:
        return

    user_id = batch.get("user_id", 0)
    context = batch.get("context")

    count = len(items)
    senders = list(dict.fromkeys(item["sender"] for item in items if item.get("sender")))
    senders_str = ", ".join(senders) if senders else "seseorang"

    # Format seluruh pesan terusan
    formatted_messages = []
    for i, it in enumerate(items, 1):
        sender = it.get("sender", "Seseorang")
        txt = it.get("text", "")
        formatted_messages.append(f"[{i}. Dari: {sender}]\n{txt}")
    full_forward_text = "\n\n".join(formatted_messages)

    # Simpan ke cache referensi agar bisa diakses via tombol 1-click atau chat lanjutan
    _RECENT_FORWARD_BATCHES[chat_id] = {
        "count": count,
        "senders": senders,
        "senders_str": senders_str,
        "full_text": full_forward_text,
        "items": items,
        "user_id": user_id,
        "context": context,
        "created_at": time.time(),
        "consumed": False,
    }

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if count == 1:
        msg_header = f"📩 Aku terima 1 pesan terusan dari *{senders_str}*."
    else:
        msg_header = f"📩 Aku sudah menampung *{count} pesan terusan* dari *{senders_str}*."

    question_text = (
        f"{msg_header}\n\n"
        "Semua pesan sudah selesai terkirim. Mau diapakan nih?\n\n"
        "• Mau dirangkum poin pentingnya?\n"
        "• Dianalisis masalah / isinya?\n"
        "• Dibuatkan draf balasannya?\n"
        "• Disimpan ke catatan / memori?\n\n"
        "_Ketik langsung perintahmu, atau pilih opsi di bawah:_"
    )

    kb = [
        [
            InlineKeyboardButton("📝 Rangkum Poin Penting", callback_data="fwdact:summarize"),
            InlineKeyboardButton("🔍 Analisis Isi", callback_data="fwdact:analyze"),
        ],
        [
            InlineKeyboardButton("✉️ Draf Balasan", callback_data="fwdact:reply"),
            InlineKeyboardButton("💾 Simpan ke Catatan", callback_data="fwdact:save"),
        ],
    ]

    await safe_send_message(
        context,
        chat_id,
        question_text,
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def handle_forward_action_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> bool:
    """Handle 1-click interactive action buttons for forwarded message batch."""
    if not data.startswith("fwdact:"):
        return False

    action = data.split(":", 1)[1]
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    batch_info = _RECENT_FORWARD_BATCHES.get(chat_id)
    if not batch_info:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Kumpulan pesan terusan sudah kedaluwarsa. Silakan teruskan kembali pesannya.",
        )
        return True

    batch_info["consumed"] = True

    turn_start_time = time.time()
    count = batch_info.get("count", 1)
    senders_str = batch_info.get("senders_str", "seseorang")
    full_text = batch_info.get("full_text", "")

    action_prompts = {
        "summarize": (
            f"Berikut kumpulan {count} pesan terusan dari {senders_str}:\n\n"
            f"{full_text}\n\n"
            "Instruksi Pengguna: Rangkum seluruh poin penting, keputusan, dan informasi kunci "
            "dari pesan-pesan terusan di atas secara padat, jelas, terstruktur, dan mudah dipahami. "
            "Jika pesan berisi catatan material/surat jalan lapangan: WAJIB buat 1 LAPORAN TUNGGAL TERPADU "
            "yang menyajikan Rincian Harian per tanggal dan Rekapitulasi Total Global lengkap seluruh item "
            "(kabel, tiang, dan semua aksesoris penunjang tanpa ada yang terpotong/dihilangkan)."
        ),
        "analyze": (
            f"Berikut kumpulan {count} pesan terusan dari {senders_str}:\n\n"
            f"{full_text}\n\n"
            "Instruksi Pengguna: Analisis isi pesan-pesan terusan di atas secara mendalam. "
            "Identifikasi konteks masalah, pihak yang terlibat, urgensi, dan saran langkah tindak lanjut yang tepat."
        ),
        "reply": (
            f"Berikut kumpulan {count} pesan terusan dari {senders_str}:\n\n"
            f"{full_text}\n\n"
            "Instruksi Pengguna: Buatkan draf balasan pesan yang profesional, ramah, dan solutif "
            f"untuk menanggapi pesan terusan dari {senders_str} di atas."
        ),
        "save": (
            f"Berikut kumpulan {count} pesan terusan dari {senders_str}:\n\n"
            f"{full_text}\n\n"
            "Instruksi Pengguna: Simpan fakta dan informasi penting dari pesan-pesan terusan di atas "
            "ke memori jangka panjang ALFA menggunakan tool save_knowledge_memory."
        ),
    }

    prompt = action_prompts.get(action)
    if not prompt:
        return False

    action_labels = {
        "summarize": "📝 Merangkum poin-poin penting pesan terusan...",
        "analyze": "🔍 Menganalisis konteks & fakta pesan terusan...",
        "reply": "✉️ Menyiapkan draf balasan pesan...",
        "save": "💾 Menyimpan informasi penting ke memori ALFA...",
    }
    status_msg = await context.bot.send_message(
        chat_id=chat_id, text=action_labels.get(action, "Memproses pesan terusan...")
    )

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING)
    )

    try:
        reply = await run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            chat_id=chat_id,
        )
    finally:
        stop_typing.set()
        await typing_task
        try:
            del_res = status_msg.delete()
            if asyncio.iscoroutine(del_res):
                await del_res
        except Exception as exc:
            logger.debug("Kegagalan tak terduga di handle_forward_action_callback: %s", exc)

    await safe_send_message(context, chat_id, reply)
    await check_artifacts_turn(
        update, context, turn_start_time=turn_start_time, user_prompt=prompt
    )
    return True
