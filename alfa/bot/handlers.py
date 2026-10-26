"""Message and callback handlers for ALFA Telegram Bot."""

import asyncio
import io
import logging
import os
import sys
import time
from typing import Any

from telegram import Update, constants
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.config import (
    GEMINI_MODEL,
    _main_brain_gemini_model,
    is_authorized,
    resolve_main_gemini,
)
from alfa.bot.helpers import (
    safe_send_message,
    send_typing_loop,
    should_reply_with_text_instead_of_voice,
)
from alfa.bot.streamer import TelegramStreamer
from alfa.bot.turn_executor import run_agent_turn
from alfa.core import database
from alfa.media import tts_engine
from alfa.tools import SANDBOX_DIR, get_system_stats

logger = logging.getLogger("TelegramAIAgent")

_HANDLER_ERR = (
    TelegramError,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)

# Registry untuk melacak task yang sedang berjalan per chat_id agar bisa di-cancel instan via /cancel
ACTIVE_CHAT_TASKS: dict[int, asyncio.Task] = {}


# --- Sapaan ringan: jawab langsung TANPA agent turn / tools ----------------
# Cegah model asal memanggil tool (mis. screenshot) untuk "halo".
_GREETING_EXACT = {
    "halo", "hallo", "hello", "hi", "hai", "hei", "hey", "hola",
    "pagi", "siang", "sore", "malam",
    "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
    "assalamualaikum", "assalamu'alaikum", "salam",
    "tes", "test", "testing", "ping", "p",
    "apa kabar", "gimana kabar", "bagaimana kabar",
    "ok", "oke", "okey", "okay", "siap", "sip", "mantap",
    "makasih", "terima kasih", "thanks", "thank you", "trims",
    "baik", "noted", "hehe", "haha", "wkwk", "👍",
}


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
        except Exception:
            pass
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)


async def _run_agent_turn(*args, **kwargs):
    mod = _get_bot_module()
    if mod and hasattr(mod, "run_agent_turn"):
        raw_res = await mod.run_agent_turn(*args, **kwargs)
    else:
        raw_res = await run_agent_turn(*args, **kwargs)

    # Pre-Flight Self-Audit & Trajectory Recording (Hermes Self-Improving Loop)
    try:
        from alfa.core.brain.learning_loop import audit_against_learned_skills, record_trajectory

        user_p = kwargs.get("user_prompt") or (args[1] if len(args) > 1 else "")
        if isinstance(raw_res, str):
            is_valid, msg, corrected = audit_against_learned_skills(user_p, raw_res)
            if not is_valid and corrected:
                logger.info("Auto-corrected agent reply via learned skill compliance: %s", msg)
                raw_res = corrected
            record_trajectory(user_prompt=user_p, result_summary=raw_res[:200], success=True)
    except Exception as e:
        logger.debug("Learning loop audit bypass: %s", e)

    return raw_res


async def _check_and_send_media_artifacts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_start_time: float | None = None,
    user_prompt: str | None = None,
    executed_tools: list[str] | None = None,
):
    mod = _get_bot_module()
    if (
        mod
        and hasattr(mod, "check_and_send_media_artifacts")
        and mod.check_and_send_media_artifacts is not check_and_send_media_artifacts
    ):
        try:
            return await mod.check_and_send_media_artifacts(
                update,
                context,
                turn_start_time=turn_start_time,
                user_prompt=user_prompt,
                executed_tools=executed_tools,
            )
        except TypeError:
            try:
                return await mod.check_and_send_media_artifacts(
                    update, context, turn_start_time=turn_start_time
                )
            except TypeError:
                return await mod.check_and_send_media_artifacts(update, context)
    return await check_and_send_media_artifacts(
        update,
        context,
        turn_start_time=turn_start_time,
        user_prompt=user_prompt,
        executed_tools=executed_tools,
    )


_RECENT_DOCS: dict[int, dict[str, Any]] = {}


async def handle_doc_action_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> bool:
    """Handle 1-click interactive document export/analysis buttons."""
    if not data.startswith("docact:"):
        return False

    action = data.split(":", 1)[1]
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    doc_info = _RECENT_DOCS.get(chat_id)
    if not doc_info:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Data dokumen referensi sudah kedaluwarsa. Silakan unggah kembali dokumennya.",
        )
        return True

    turn_start_time = time.time()
    file_name = doc_info.get("file_name", "dokumen")
    txt_ctx = doc_info.get("txt_ctx", "")
    is_batch = doc_info.get("is_batch", False)
    docs_count = doc_info.get("docs_count", 1)
    file_names = doc_info.get("file_names", [file_name])

    # Bersihkan file keluaran lama di sandbox sebelum turn aksi agar tak terjadi double output
    if os.path.exists(SANDBOX_DIR):
        target_exts = {
            "excel": (".xlsx", ".xls", ".csv"),
            "pdf": (".pdf",),
        }.get(action, ())
        for f in os.listdir(SANDBOX_DIR):
            if any(f.lower().endswith(ext) for ext in target_exts):
                try:
                    os.remove(os.path.join(SANDBOX_DIR, f))
                except OSError:
                    pass

    if is_batch:
        file_list_str = ", ".join(file_names)
        action_prompts = {
            "pdf": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan SATU (1) berkas laporan PDF resmi gabungan yang rapi dan profesional "
                f"berisi rincian material dari SELURUH {docs_count} dokumen ({file_list_str}) di atas menggunakan tool generate_pdf_report. "
                "SATUKAN semua dalam 1 file PDF lengkap dengan rekapitulasi total. Pastikan berkas tersimpan ke disk."
            ),
            "excel": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan SATU (1) berkas spreadsheet Excel (.xlsx) gabungan yang komprehensif dan terstruktur rapi "
                f"berisi rincian material dari SELURUH {docs_count} berkas dokumen ({file_list_str}) di atas menggunakan tool generate_excel_spreadsheet "
                "dengan filename 'Rekap_Material_Gabungan.xlsx'.\n\n"
                "ATURAN MUTLAK:\n"
                "1. SATUKAN SEMUA rincian material dari SELURUH berkas ke dalam SATU file spreadsheet ini (DILARANG membuat file terpisah untuk masing-masing dokumen).\n"
                "2. Kolom tabel: ['No', 'Nama Dokumen / DO', 'Cluster', 'Nama Material / Item', 'QTY', 'Satuan'].\n"
                "3. HANYA panggil tool generate_excel_spreadsheet TEPAT SATU KALI untuk menghasilkan file gabungan ini.\n"
                "4. Pastikan rows_json berupa list of lists sesuai urutan headers di atas."
            ),
            "deep": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Lakukan audit dan rekonsiliasi data mendalam untuk SELURUH {docs_count} dokumen "
                f"({file_list_str}): hitung total akumulasi material antar dokumen, verifikasi varians/anomali, dan sajikan rincian matematisnya secara presisi."
            ),
        }
    else:
        action_prompts = {
            "pdf": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan berkas laporan PDF resmi yang rapi dan profesional "
                f"dari data dokumen '{file_name}' di atas menggunakan tool generate_pdf_report. Pastikan berkas tersimpan ke disk."
            ),
            "excel": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Buatkan berkas spreadsheet Excel (.xlsx) baru yang terstruktur rapi "
                f"dari data dokumen '{file_name}' di atas menggunakan tool generate_excel_spreadsheet. "
                "Gunakan kolom: ['No', 'Nama Material / Item', 'QTY', 'Satuan'] dan pastikan hanya memanggil tool tepat satu kali. Pastikan berkas tersimpan ke disk."
            ),
            "deep": (
                f"{txt_ctx}\n\nInstruksi Pengguna: Lakukan audit data mendalam pada dokumen '{file_name}': hitung total rekonsiliasi, "
                f"verifikasi varians/selisih angka, dan sajikan rincian matematisnya secara presisi."
            ),
        }

    prompt = action_prompts.get(action)
    if not prompt:
        return False

    action_labels = {
        "pdf": "📄 Menyiapkan laporan PDF resmi...",
        "excel": "📊 Menghasilkan berkas spreadsheet Excel...",
        "deep": "🔍 Menjalankan analisis data mendalam...",
    }
    status_msg = await context.bot.send_message(
        chat_id=chat_id, text=action_labels.get(action, "Memproses permintaan...")
    )

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING)
    )

    try:
        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            chat_id=chat_id,
        )
    finally:
        stop_typing.set()
        await typing_task
        try:
            await status_msg.delete()
        except (TelegramError, OSError):
            pass

    await safe_send_message(context, chat_id, reply)
    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time, user_prompt=prompt
    )
    return True


_FORWARD_BATCHES: dict[int, dict[str, Any]] = {}
_FORWARD_BATCH_LOCK = asyncio.Lock()
_RECENT_FORWARD_BATCHES: dict[int, dict[str, Any]] = {}


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
        reply = await _run_agent_turn(
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
        except Exception:
            pass

    await safe_send_message(context, chat_id, reply)
    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time, user_prompt=prompt
    )
    return True


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    if data.startswith("perm|") or data == "perm_done":
        return

    await query.answer()

    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await query.edit_message_text("⛔ Akses ditolak.")
        return

    data = query.data or ""
    if data == "budget:reset":
        from alfa.core import rate_limiter

        deleted = rate_limiter.reset_user_usage_today(user_id)
        usage = rate_limiter.get_user_usage_today(user_id)
        msg = (
            "🔄 **Kuota harian berhasil di-reset!**\n\n"
            f"• Token terpakai hari ini: **0** / {usage['budget_limit']:,} token\n"
            f"• Panggilan terpakai: **0** / {usage['call_limit']:,} panggilan\n"
            f"• Catatan pemakaian dihapus: {deleted} entri\n\n"
            "Sekarang Anda bisa kembali menggunakan AI secara normal tanpa batasan kuota."
        )
        await safe_send_message(context, chat_id, msg)
        return

    try:
        if await handle_doc_action_callback(update, context, data):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] doc_action gagal: {e}")
    try:
        if await handle_forward_action_callback(update, context, data):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] forward_action gagal: {e}")
    try:
        from alfa.bot.mode_commands import handle_persona_callback

        if await handle_persona_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] persona router gagal: {e}")
    try:
        from alfa.bot.wa_menu import handle_wa_callback

        if await handle_wa_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] wa_menu router gagal: {e}")
    try:
        from alfa.bot.advanced_commands import handle_sites_callback

        if await handle_sites_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] sites router gagal: {e}")
    try:
        from alfa.bot.cloud_menu import handle_cloud_callback

        if await handle_cloud_callback(update, context):
            return
    except _HANDLER_ERR as e:
        logger.debug(f"[callback] cloud_menu router gagal: {e}")

    if data.startswith("artcraft|"):
        from alfa.tools.desktop.artcraft import artcraft_launch_gui

        parts = data.split("|")
        app_name = parts[2] if len(parts) > 2 else "gridcraft"
        excel_path = os.path.expanduser("~/alfa_projects/lahat_material/Rekap_Pengambilan_Material_Lahat.xlsx")
        res = artcraft_launch_gui(app_name, excel_path if os.path.exists(excel_path) else None)
        await safe_send_message(context, chat_id, f"🚀 {res.get('message', 'Aplikasi diluncurkan.')}")
        return

    # Tombol menu utama → output perintah mengedit pesan menu di tempat
    from alfa.bot.helpers import clear_menu_target, set_menu_target

    set_menu_target(context, query, chat_id, back=(data != "btn_menu"))
    try:
        await _dispatch_menu_callback(update, context, data, user_id, chat_id)
    finally:
        clear_menu_target(context)


async def _dispatch_menu_callback(update, context, data, user_id, chat_id):
    if data == "btn_menu":
        from alfa.bot.basic_commands import menu_command

        await menu_command(update, context)

    elif data in ("btn_sheets", "btn_gdrive", "btn_cloud"):
        from alfa.bot.cloud_menu import (
            render_cloud_hub,
            render_drive_home,
            render_sheets_home,
        )

        if data == "btn_sheets":
            await render_sheets_home(update, context, 0)
        elif data == "btn_gdrive":
            await render_drive_home(update, context)
        else:
            await render_cloud_hub(update, context)

    elif data == "btn_stats":
        stats = get_system_stats()
        text = (
            f"📊 **Status Server / Laptop Real-Time:**\n\n"
            f"• **CPU:** `{stats.get('cpu')}`\n"
            f"• **RAM:** `{stats.get('ram')}`\n"
            f"• **Swap:** `{stats.get('swap')}`\n"
            f"• **Disk:** `{stats.get('disk')}`\n"
            f"• **Power:** `{stats.get('battery')}`\n"
            f"• **IP:** `{stats.get('ip_addresses')}`\n"
            f"• **Uptime:** `{stats.get('uptime')}`\n\n"
            f"🔥 **Top RAM:**\n"
            + "\n".join([f"  - {p}" for p in stats.get("top_ram_processes", [])])
        )
        await safe_send_message(context, chat_id, text)

    elif data == "btn_rekap_lahat":
        from alfa.tools.telecom_tools import reconcile_whatsapp_material_group

        await safe_send_message(context, chat_id, "⏳ *Menyusun Rekapitulasi Material WhatsApp Cluster Lahat...*")
        res = reconcile_whatsapp_material_group(
            group_name_or_id="pengambilan material lahat",
            auto_launch_gridcraft=False,
        )
        if res.get("status") == "success":
            card = (
                f"📦 *REKAPITULASI MATERIAL MASTER LAHAT*\n\n"
                f"• Total Bersih: *{res.get('total_net')} batang*\n"
                f"• Total Bruto: {res.get('total_bruto')} btg | Retur: {res.get('total_retur')} btg\n"
                f"• Mandor Terverifikasi: {', '.join(res.get('mandors', []))}\n"
                f"• Berkas Master: `{res.get('excel_file')}`\n\n"
                f"💡 _Data diperbarui in-place pada Master Ledger Kumulatif tanpa membuat berkas baru._"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = [
                [InlineKeyboardButton("📊 Buka GridCraft", callback_data="artcraft|open|gridcraft")],
                [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
            ]
            await safe_send_message(context, chat_id, card, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal merekap material: {res.get('message')}")

    elif data == "btn_daily_briefing":
        from alfa.tools.telecom_tools import generate_daily_executive_briefing

        await safe_send_message(context, chat_id, "⏳ *Menyiapkan Executive Daily Briefing Proyek...*")
        res = generate_daily_executive_briefing(shift="now", only_unreported=False)
        if res.get("status") == "success":
            await safe_send_message(context, chat_id, res.get("briefing_card", "Briefing selesai."))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal menyusun briefing: {res.get('message')}")

    elif data == "btn_artcraft":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        text = (
            "🎨 *ArtCraft Suite (Desktop Office & CAD Tools):*\n\n"
            "• 📊 *GridCraft*: Analisis spreadsheet Excel dinamis & formula audit.\n"
            "• 📄 *PdfCraft*: Manipulasi PDF (gabung, pisah, watermark, kompresi, enkripsi).\n"
            "• 📐 *CadCraft*: Konversi denah DWG/DXF FTTH ke PDF/SVG, kalkulasi rute kabel.\n"
            "• 🖼️ *PhotoCraft*: Pemrosesan & optimasi dokumentasi foto lapangan.\n"
            "• 💡 *LightCraft*: Penyesuaian eksposur visual foto tiang & material.\n"
            "• ✒️ *DesignCraft*: Desain diagram arsitektur jaringan & mockup vektor.\n\n"
            "Aplikasi dapat dipanggil lewat CLI maupun antarmuka visual GUI."
        )
        kb = [
            [InlineKeyboardButton("📊 Buka GridCraft Lahat", callback_data="artcraft|open|gridcraft")],
            [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
        ]
        await safe_send_message(context, chat_id, text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "btn_ram":
        from alfa.bot.advanced_commands import ram_command

        await ram_command(update, context)

    elif data == "btn_memory":
        memories = await database.get_all_memories(user_id)
        if not memories:
            await safe_send_message(
                context, chat_id, "🧠 Memori jangka panjang masih kosong."
            )
        else:
            text = f"🧠 **Memori Tersimpan ({len(memories)} item):**\n\n"
            for m in memories:
                text += f"• *[{m['category'].upper()}]* `{m['key_topic']}`:\n  {m['content']}\n\n"
            await safe_send_message(context, chat_id, text)

    elif data == "btn_toggle_voice":
        is_on = await database.toggle_voice_setting(user_id)
        status_str = "AKTIF 🔊" if is_on else "NONAKTIF 🔇"
        await safe_send_message(
            context, chat_id, f"🎙️ Mode Balasan Suara sekarang: **{status_str}**"
        )

    elif data == "btn_python_info":
        info_text = (
            "📈 **Python Sandbox & Data Plotter:**\n\n"
            "Anda dapat meminta bot untuk:\n"
            "• Menghitung data kompleks, rumus matematika, atau simulasi.\n"
            "• Membuat grafik statistik / visualisasi (misal: *'Buatkan grafik perbandingan penjualan 2024-2026'*).\n"
            "• Menjalankan snippet kode Python secara langsung.\n"
            "Grafik yang dihasilkan akan otomatis dikirimkan sebagai gambar langsung ke chat Telegram!"
        )
        await safe_send_message(context, chat_id, info_text)

    elif data == "btn_clear":
        await database.clear_user_chat_history(user_id)
        await safe_send_message(
            context, chat_id, "🧹 Konteks percakapan telah direset."
        )

    elif data == "btn_help":
        help_text = (
            "📖 **Daftar Perintah Lengkap:**\n\n"
            "🧭 **Mode Eksekusi:**\n"
            "• `/mode single|swarm|status` - Alih/lihat mode\n"
            "• `/single [tugas]` - Single agent (pindah / sekali-jalan)\n"
            "• `/status` - Status mode, swarm, agen, server\n\n"
            "⚡ **Swarm Multi-Agent:**\n"
            "• `/swarm <tugas>` - Eksekusi nyata tim agen\n"
            "• `/swarm status|cancel` - Status / hentikan misi\n"
            "• `/swarm model <id|nama> <provider> [model]` - Ganti model agen\n"
            "• `/swarm template [nama]` - Misi siap pakai\n"
            "• `/rapat <topik>` - Rapat plan (diskusi + action plan)\n"
            "• `/resume [session]` - Lanjutkan sesi swarm\n"
            "• `/cancel` - Hentikan misi berjalan\n\n"
            "🤖 **Agen & Tools:**\n"
            "• `/agents` - Daftar workforce\n"
            "• `/persona [nama|id|reset]` - Persona single-mode\n"
            "• `/tools` - 148 tools real\n"
            "• `/cekagen` - Audit kesehatan konfigurasi\n\n"
            "☁️ **Google Sheets & Drive:**\n"
            "• `/sheets` (`/sheet`) - Panel file & tab Google Sheets terhubung\n"
            "• `/drive` (`/gdrive`) - Jelajahi Google Drive cloud & mount lokal\n"
            "• `/cloud` - Hub terpadu Google Sheets & Google Drive\n"
            "• `/setsheet [link|id]` - Konfigurasi spreadsheet aktif\n\n"
            "🔁 **Otomasi:**\n"
            "• `/pipeline [list|run <id>]` - Workflow DAG\n"
            "• `/tugas` - Subagent latar & checkpoint\n"
            "• `/cron` - Tugas berulang (single/swarm)\n"
            "• `/budget` - Monitor kuota token harian\n"
            "• `/proactive` - Inisiatif ambient\n\n"
            "🧰 **Lainnya:**\n"
            "• `/menu` `/dashboard` `/sites` `/wa` `/keys` (`/vault`)\n"
            "• `/wachat` `/wamasuk` `/wakirim` `/wacari` — pantau & kirim WA\n"
            "• `/waformat` `/wareport` — atur & baca pencatatan otomatis\n"
            "• `/waringkas [format]` — digest cerdas + sorotan AI (otomatis tiap 07:00)\n"
            "• `/stats` `/memory` `/voice` `/clear` (`/reset`) `/id`\n"
            "• Alias: `/eksekusi`=`/swarm` • `/meeting`=`/rapat` • `/tasks`=`/cron` • `/stop`=`/cancel`\n"
            "• Alias: `/web` `/app`=`/dashboard` • `/washeets`=`/wa` • `/batal`=`/cancel` • `/resume_swarm`=`/resume` • `/reset`=`/clear`\n\n"
            "💬 **Contoh Perintah AI:**\n"
            "- *'Ambil screenshot desktop sekarang'* -> Mengirim foto layar aktif.\n"
            "- *'/swarm buatkan script monitoring RAM dan jalankan'* -> Misi tim.\n"
            "- *'/rapat strategi hemat token API'* -> Diskusi + action plan.\n"
            "- *'Buatkan grafik plot fungsi sinus dan cosinus'* -> Menghasilkan gambar grafik.\n"
            "- *'Cari informasi berita AI terkini hari ini'* -> Browsing real-time.\n"
            "- *'Ingat bahwa email dev saya adalah admin@example.com'* -> Simpan memori.\n"
            "- *'Ingatkan saya jam 18:00 untuk evaluasi project'* -> Set pengingat otomatis."
        )
        await safe_send_message(context, chat_id, help_text)

    elif data in ("btn_mode_single", "btn_mode_swarm", "btn_status"):
        from alfa.bot.mode_commands import (
            get_telegram_mode_sync,
            set_telegram_mode_sync,
            status_command,
        )

        if data == "btn_mode_single":
            set_telegram_mode_sync("single")
            await safe_send_message(
                context, chat_id, "🧍 **Mode SINGLE aktif.** Chat biasa ditangani 1 agen otonom."
            )
        elif data == "btn_mode_swarm":
            set_telegram_mode_sync("swarm")
            await safe_send_message(
                context,
                chat_id,
                "⚡ **Mode SWARM aktif.** Chat teks berikutnya dieksekusi tim multi-agen.\n"
                "Kembali: `/mode single` • Batal: `/cancel`",
            )
        else:
            await status_command(update, context)

    elif data in ("btn_meeting_info", "btn_swarm_info"):
        if data == "btn_meeting_info":
            await safe_send_message(
                context,
                chat_id,
                "🏛️ **Rapat AI (Plan):** `/rapat <topik>`\n"
                "Contoh: `/rapat strategi hemat token API`\n"
                "Hasil: diskusi round-table + konsensus + action plan.",
            )
        else:
            swarm_note = "(mode swarm aktif ⚡)"
            try:
                from alfa.bot.mode_commands import get_telegram_mode_sync

                if get_telegram_mode_sync() != "swarm":
                    swarm_note = "(mode single 🧍 — tetap bisa sekali-jalan)"
            except _HANDLER_ERR:
                pass
            await safe_send_message(
                context,
                chat_id,
                f"⚡ **Eksekusi Swarm:** `/swarm <tugas>` {swarm_note}\n"
                "Contoh: `/swarm buatkan script monitoring RAM dan jalankan`\n"
                "Atau aktifkan permanen: `/mode swarm` lalu chat biasa.",
            )

    elif data in ("btn_agents", "btn_tools", "btn_pipeline", "btn_tasks"):
        if data == "btn_agents":
            mod = _get_bot_module()
            fn = getattr(mod, "agents_command", None) if mod else None
            if callable(fn):
                await fn(update, context)
            else:
                from alfa.bot.advanced_commands import agents_command as _agents

                await _agents(update, context)
        elif data == "btn_tools":
            from alfa.bot.mode_commands import tools_command as _tools

            await _tools(update, context)
        elif data == "btn_pipeline":
            from alfa.bot.mode_commands import pipeline_command as _pipe

            await _pipe(update, context)
        else:
            from alfa.bot.mode_commands import tugas_command as _tugas

            await _tugas(update, context)

    elif data == "btn_persona":
        from alfa.bot.mode_commands import render_persona_menu as _pm

        await _pm(update, context)

    elif data in ("btn_keys", "btn_cekagen", "btn_cron", "btn_proactive", "btn_dashboard", "btn_wa", "btn_sites", "btn_budget"):
        mod = _get_bot_module()
        mapping = {
            "btn_keys": "keys_command",
            "btn_cekagen": "cekagen_command",
            "btn_cron": "cron_command",
            "btn_proactive": "proactive_command",
            "btn_dashboard": "dashboard_command",
            "btn_wa": "wa_command",
            "btn_sites": "sites_command",
            "btn_budget": "budget_command",
        }
        fn = getattr(mod, mapping[data], None) if mod else None
        if not callable(fn):
            from alfa.bot import advanced_commands as _ac
            from alfa.bot import basic_commands as _bc

            fn = getattr(_ac, mapping[data], None) or getattr(_bc, mapping[data], None)
        if callable(fn):
            await fn(update, context)

    elif data == "btn_wa_status":
        res = tools.manage_wa_sheets_bot("status")
        st = "🟢 RUNNING (Aktif)" if res.get("is_running") else "🔴 STOPPED (Mati)"
        await safe_send_message(
            context,
            chat_id,
            f"📱 **Status WhatsApp Bot:** {st}\n\n```\n{res.get('details', '')}\n```",
        )

    elif data == "btn_wa_restart":
        res = tools.manage_wa_sheets_bot("restart")
        await safe_send_message(
            context, chat_id, f"🔄 {res.get('message', 'Restart diproses.')}"
        )

    elif data == "btn_wa_start":
        res = tools.manage_wa_sheets_bot("start")
        await safe_send_message(
            context, chat_id, f"▶️ {res.get('message', 'Start diproses.')}"
        )

    elif data == "btn_wa_stop":
        res = tools.manage_wa_sheets_bot("stop")
        await safe_send_message(
            context, chat_id, f"⏹️ {res.get('message', 'Stop diproses.')}"
        )


def is_artifact_producing_tool(tool_name: str) -> bool:
    """Check if a tool's purpose is to produce deliverable media/documents."""
    t = (tool_name or "").lower()
    return any(
        k in t
        for k in (
            "screenshot", "screen", "webcam", "camera", "photo", "recording", "video",
            "chart", "plot", "excel", "spreadsheet", "pdf", "powerpoint", "presentation",
            "pptx", "zip", "archive", "compress", "download", "transcode", "export"
        )
    )


_ARTIFACT_INTENT_KEYWORDS = (
    "screenshot", "tangkapan layar", "ss layar", "capture layar",
    "webcam", "foto kamera", "potret",
    "grafik", "chart", "diagram", "visualisasi data", "plot",
    "excel", "spreadsheet", "xlsx", "xls", "rekap excel",
    "pdf", "dokumen pdf", "laporan pdf",
    "powerpoint", "presentasi", "pptx",
    "zip", "arsip zip", "kompres", "arsip",
    "unduh", "download", "rekam layar", "video layar",
)


def has_artifact_intent(prompt: str) -> bool:
    """Check if prompt text asks for a file, media, or visual deliverable."""
    if not prompt:
        return False
    p = prompt.lower()
    return any(k in p for k in _ARTIFACT_INTENT_KEYWORDS)


async def check_and_send_media_artifacts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_start_time: float | None = None,
    user_prompt: str | None = None,
    executed_tools: list[str] | None = None,
):
    """
    Checks if any screenshot, webcam frame, Python chart, or document (PDF, Excel, PPTX, ZIP)
    was created during this turn and dispatches it directly to the Telegram user.
    Pure conversational turns (greetings, general QA, voice notes like "apa yang kamu bisa")
    never dispatch raw files from SANDBOX_DIR.
    """
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not os.path.exists(SANDBOX_DIR):
        return

    from alfa.core.runtime_ctx import (
        get_current_executed_tools,
        get_current_turn_artifacts,
        get_current_user_prompt,
    )

    if executed_tools is None:
        executed_tools = get_current_executed_tools()
    recorded_artifacts = get_current_turn_artifacts()
    prompt = (user_prompt or get_current_user_prompt() or "").lower()

    has_prompt_intent = has_artifact_intent(prompt)
    has_tool_artifact = any(is_artifact_producing_tool(t) for t in executed_tools)
    has_recorded = len(recorded_artifacts) > 0

    # Gate check: When turn_start_time is specified (live turn context), skip artifact dispatching
    # if the turn was purely conversational without artifact intent and no artifact tool was executed.
    if turn_start_time is not None and not (has_tool_artifact or has_recorded or has_prompt_intent):
        logger.debug(
            "[check_and_send_media_artifacts] Skipping: no artifact intent or tool "
            f"(tools={executed_tools}, prompt={prompt[:50]!r})"
        )
        return

    named_media = [
        ("desktop_screen.png", "🖥️ Tangkapan Layar Desktop", ("screenshot", "screen", "tangkapan")),
        ("webcam_frame.jpg", "📷 Foto Kamera Webcam", ("webcam", "kamera", "camera")),
        ("generated_plot.png", "📊 Grafik Visualisasi Data (Python)", ("chart", "grafik", "plot", "diagram")),
        ("dataset_analysis_chart.png", "📊 Grafik Analisis Dataset", ("chart", "grafik", "dataset", "analisis")),
        ("browser_screenshot.png", "🌐 Tangkapan Layar Browser (Camofox)", ("browser", "screenshot", "web")),
    ]

    for filename, caption, triggers in named_media:
        full_path = os.path.join(SANDBOX_DIR, filename)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            mtime = os.path.getmtime(full_path)
            if turn_start_time is not None and mtime < (turn_start_time - 1.0):
                # Stale artifact from previous turn/task: delete and ignore
                try:
                    os.remove(full_path)
                except OSError:
                    pass
                continue

            # In live turns, verify that this named media matches the turn's tool execution, recorded artifacts, or intent
            if turn_start_time is not None and full_path not in recorded_artifacts:
                matched = any(
                    trig in t.lower() for trig in triggers for t in executed_tools
                ) or any(trig in prompt for trig in triggers)
                if not matched:
                    continue

            try:
                with open(full_path, "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=photo_file, caption=caption
                    )
            except _HANDLER_ERR as send_err:
                logger.error(f"Failed to send media artifact {filename}: {send_err}")
            finally:
                try:
                    os.remove(full_path)
                except OSError:
                    pass

    raw_candidates = []
    for fname in os.listdir(SANDBOX_DIR):
        fpath = os.path.join(SANDBOX_DIR, fname)
        if tools.is_internal_sandbox_artifact(fname):
            continue
        if tools.is_source_code_file(fname):
            continue
        if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
            continue

        mtime = os.path.getmtime(fpath)
        if turn_start_time is not None and mtime < (turn_start_time - 1.0):
            # Stale file from earlier tests or background jobs: cleanup and skip
            try:
                os.remove(fpath)
            except OSError:
                pass
            continue
        raw_candidates.append((fname, fpath, mtime))

    # Kelompokkan berkas gambar dan dokumen
    docs_by_ext: dict[str, list[tuple[str, str, float]]] = {}
    images_to_send: list[tuple[str, str]] = []

    for fname, fpath, mtime in raw_candidates:
        ext = os.path.splitext(fname)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
            if turn_start_time is not None and fpath not in recorded_artifacts:
                matched_img = (
                    any(is_artifact_producing_tool(t) for t in executed_tools)
                    or any(k in prompt for k in ("foto", "gambar", "image", "chart", "grafik", "plot", "screenshot"))
                )
                if not matched_img:
                    continue
            images_to_send.append((fname, fpath))
        else:
            if turn_start_time is not None and fpath not in recorded_artifacts:
                if ext == ".zip":
                    matched_doc = (
                        any(any(k in t.lower() for k in ("zip", "compress", "archive")) for t in executed_tools)
                        or any(k in prompt for k in ("zip", "kompres", "arsip"))
                    )
                elif ext in [".xlsx", ".xls", ".csv"]:
                    matched_doc = (
                        any(any(k in t.lower() for k in ("excel", "spreadsheet", "sheet")) for t in executed_tools)
                        or any(k in prompt for k in ("excel", "xlsx", "spreadsheet", "tabel"))
                    )
                elif ext == ".pdf":
                    matched_doc = (
                        any("pdf" in t.lower() for t in executed_tools)
                        or "pdf" in prompt
                    )
                elif ext in [".pptx", ".ppt"]:
                    matched_doc = (
                        any(any(k in t.lower() for k in ("powerpoint", "presentation", "pptx")) for t in executed_tools)
                        or any(k in prompt for k in ("pptx", "powerpoint", "presentasi"))
                    )
                else:
                    matched_doc = has_tool_artifact or has_prompt_intent

                if not matched_doc:
                    continue

            docs_by_ext.setdefault(ext, []).append((fname, fpath, mtime))

    # Kirim foto / grafik
    for fname, fpath in images_to_send:
        caption = (
            "📊 Grafik Visualisasi Data (Python)"
            if fname.startswith("generated_plot")
            else f"📸 Berkas Gambar: {fname}"
        )
        try:
            with open(fpath, "rb") as pf:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=pf, caption=caption
                )
        except _HANDLER_ERR as img_err:
            logger.error(f"Failed to send image {fname}: {img_err}")
        finally:
            try:
                os.remove(fpath)
            except OSError:
                pass

    # Kirim dokumen dengan proteksi anti-duplicate per tipe berkas (cegah double file Excel/PDF)
    generic_names = {".xlsx": "data.xlsx", ".pdf": "laporan.pdf", ".pptx": "presentasi.pptx"}
    for ext, file_list in docs_by_ext.items():
        if len(file_list) > 1:
            gen_name = generic_names.get(ext)
            if gen_name and any(item[0].lower() != gen_name.lower() for item in file_list):
                # Buang file generic (misal: data.xlsx) jika ada file dengan nama spesifik (misal: Rekap_Material_Gabungan.xlsx)
                kept = []
                for item in file_list:
                    if item[0].lower() == gen_name.lower():
                        try:
                            os.remove(item[1])
                        except OSError:
                            pass
                    else:
                        kept.append(item)
                file_list = kept

        # Jika masih lebih dari 1 file dengan ekstensi sama, pilih 1 file termutakhir (mtime terbesar)
        if len(file_list) > 1:
            file_list.sort(key=lambda x: x[2], reverse=True)
            for item in file_list[1:]:
                try:
                    os.remove(item[1])
                except OSError:
                    pass
            file_list = [file_list[0]]

        for fname, fpath, _ in file_list:
            try:
                with open(fpath, "rb") as df:
                    await context.bot.send_document(
                        chat_id=chat_id, document=df, caption=f"📄 Berkas: {fname}"
                    )
            except _HANDLER_ERR as doc_err:
                logger.error(f"Failed to send document {fname}: {doc_err}")
            finally:
                try:
                    os.remove(fpath)
                except OSError:
                    pass


async def _long_turn_nudge(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    turn_task: "asyncio.Task",
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


_WA_INCOMING_TRIGGERS = {
    "cek wa masuk", "cek wa", "wa masuk", "baca wa masuk", "baca wa",
    "chat wa masuk", "pesan wa masuk", "pesan wa baru", "ada wa masuk",
    "ada wa baru", "lihat wa masuk", "cek whatsapp masuk", "baca whatsapp masuk",
    "whatsapp masuk", "chat whatsapp masuk", "ada whatsapp masuk",
    "cek pesan wa", "baca pesan wa", "cek chat wa", "baca chat wa",
    "cek wa baru", "baca wa baru", "ada pesan wa", "ada pesan wa baru",
    "tolong cek wa masuk", "tolong cek wa", "tolong baca wa masuk",
    "cek wa ada apa", "cek pesan whatsapp", "baca pesan whatsapp",
}


async def try_handle_fast_wa(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> bool:
    """Deteksi perintah WA instan untuk eksekusi sub-detik tanpa membebani antrean LLM cloud."""
    norm = (user_text or "").lower().strip()
    for ch in "!?.,-—…":
        norm = norm.replace(ch, " ")
    norm = " ".join(norm.split())

    # 1. Cek Pesan Masuk WA (wamasuk)
    is_incoming = norm in _WA_INCOMING_TRIGGERS or (
        any(k in norm for k in ("wa masuk", "whatsapp masuk"))
        and any(k in norm for k in ("cek", "baca", "lihat", "ada", "ambil", "tolong"))
    )
    if is_incoming:
        from alfa.bot.advanced_commands import wamasuk_command
        await wamasuk_command(update, context)
        try:
            uid = update.effective_user.id if update.effective_user else 0
            await database.save_chat_message(uid, "user", user_text)
            await database.save_chat_message(uid, "model", "[Pesan WhatsApp masuk diperiksa via fast-path /wamasuk]")
        except Exception as dbe:
            logger.debug(f"[fast_wa] save_chat_message error: {dbe}")
        return True

    # 2. Pembersihan / Reset Buffer WA
    is_clear = (
        any(k in norm for k in ("wa", "whatsapp"))
        and any(k in norm for k in ("hapus riwayat", "bersihkan riwayat", "reset riwayat", "hapus chat", "bersihkan chat", "hapus buffer", "clear"))
    )
    if is_clear:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        from alfa import tools
        tools.wa_clear_history(target="all", clear_archive=True, clear_read_state=True)
        msg = "🗑️ **Riwayat pesan WhatsApp berhasil dibersihkan!**\nBuffer pesan masuk lokal dan arsip sudah dikosongkan."
        await safe_send_message(context, chat_id, msg)
        try:
            uid = update.effective_user.id if update.effective_user else 0
            await database.save_chat_message(uid, "user", user_text)
            await database.save_chat_message(uid, "model", msg)
        except Exception as dbe:
            logger.debug(f"[fast_wa] save_chat_message error: {dbe}")
        return True

    return False


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(
            context, chat_id, "⛔ Akses ditolak. ID Anda belum terdaftar di whitelist."
        )
        return

    user_text = update.message.text.strip()
    turn_start_time = time.time()
    swarm_files: list[str] = []

    # 1. Deteksi apakah pesan ini adalah pesan terusan (forwarded message)
    fwd_info = get_forward_info(update.message)
    if fwd_info is not None:
        async with _FORWARD_BATCH_LOCK:
            if chat_id not in _FORWARD_BATCHES:
                _FORWARD_BATCHES[chat_id] = {
                    "items": [],
                    "task": None,
                    "user_id": user_id,
                    "context": context,
                    "latest_update": update,
                    "turn_start_time": turn_start_time,
                }
            batch = _FORWARD_BATCHES[chat_id]
            batch["items"].append({
                "text": user_text,
                "sender": fwd_info.get("sender") or "Pengirim",
                "msg_id": update.message.message_id,
            })
            batch["latest_update"] = update

            if batch.get("task") and not batch["task"].done():
                batch["task"].cancel()

            async def _delayed_forward_batch_runner():
                try:
                    # Debounce 1.8 detik: tunggu seluruh rentetan pesan terusan selesai dikirim
                    await asyncio.sleep(1.8)
                except asyncio.CancelledError:
                    return

                async with _FORWARD_BATCH_LOCK:
                    ready_batch = _FORWARD_BATCHES.pop(chat_id, None)

                if ready_batch and ready_batch.get("items"):
                    await _execute_forward_batch(chat_id, ready_batch)

            batch["task"] = asyncio.create_task(_delayed_forward_batch_runner())
            return

    # 2. Jika bukan pesan terusan, periksa apakah ada batch pesan terusan yang sedang menunggu debounce
    #    (misal: pengguna meneruskan pesan lalu langsung mengetik instruksi tanpa menunggu jeda)
    active_forward_batch = None
    async with _FORWARD_BATCH_LOCK:
        if chat_id in _FORWARD_BATCHES:
            active_forward_batch = _FORWARD_BATCHES.pop(chat_id)
            if active_forward_batch.get("task") and not active_forward_batch["task"].done():
                active_forward_batch["task"].cancel()

    if active_forward_batch and active_forward_batch.get("items"):
        items = active_forward_batch["items"]
        count = len(items)
        senders = list(dict.fromkeys(item["sender"] for item in items if item.get("sender")))
        senders_str = ", ".join(senders) if senders else "seseorang"
        formatted_messages = []
        for i, it in enumerate(items, 1):
            s = it.get("sender", "Seseorang")
            txt = it.get("text", "")
            formatted_messages.append(f"[{i}. Dari: {s}]\n{txt}")
        full_forward_text = "\n\n".join(formatted_messages)

        _RECENT_FORWARD_BATCHES[chat_id] = {
            "count": count,
            "senders": senders,
            "senders_str": senders_str,
            "full_text": full_forward_text,
            "items": items,
            "user_id": user_id,
            "context": context,
            "created_at": time.time(),
            "consumed": True,
        }
        user_text = (
            f"[Kumpulan {count} Pesan Terusan dari {senders_str}]:\n\n"
            f"{full_forward_text}\n\n"
            f"Instruksi Pengguna: {user_text}"
        )

    # Fast-Path Tombol Bawah (Persistent Reply Keyboard Navigasi)
    lower_norm = user_text.lower().strip()
    if lower_norm in ("📦 rekap material lahat", "rekap material", "rekap material lahat", "rekap lahat"):
        from alfa.tools.telecom_tools import reconcile_whatsapp_material_group

        await safe_send_message(context, chat_id, "⏳ *Menyusun Rekapitulasi Material WhatsApp Cluster Lahat...*")
        res = reconcile_whatsapp_material_group(
            group_name_or_id="pengambilan material lahat",
            auto_launch_gridcraft=False,
        )
        if res.get("status") == "success":
            card = (
                f"📦 *REKAPITULASI MATERIAL MASTER LAHAT*\n\n"
                f"• Total Bersih: *{res.get('total_net')} batang*\n"
                f"• Total Bruto: {res.get('total_bruto')} btg | Retur: {res.get('total_retur')} btg\n"
                f"• Mandor Terverifikasi: {', '.join(res.get('mandors', []))}\n"
                f"• Berkas Master: `{res.get('excel_file')}`\n\n"
                f"💡 _Data diperbarui in-place pada Master Ledger Kumulatif tanpa membuat berkas baru._"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = [
                [InlineKeyboardButton("📊 Buka GridCraft", callback_data="artcraft|open|gridcraft")],
                [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
            ]
            await safe_send_message(context, chat_id, card, reply_markup=InlineKeyboardMarkup(kb))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal merekap material: {res.get('message')}")
        return

    if lower_norm in ("📋 daily briefing", "📋 executive briefing", "daily briefing", "executive briefing", "briefing harian", "briefing"):
        from alfa.tools.telecom_tools import generate_daily_executive_briefing

        await safe_send_message(context, chat_id, "⏳ *Menyiapkan Executive Daily Briefing Proyek...*")
        res = generate_daily_executive_briefing(shift="now", only_unreported=False)
        if res.get("status") == "success":
            await safe_send_message(context, chat_id, res.get("briefing_card", "Briefing selesai."))
        else:
            await safe_send_message(context, chat_id, f"⚠️ Gagal menyusun briefing: {res.get('message')}")
        return

    if lower_norm in ("🎛️ menu utama", "menu utama", "menu", "/menu"):
        from alfa.bot.basic_commands import menu_command

        await menu_command(update, context)
        return

    if lower_norm in ("📱 whatsapp hub", "whatsapp hub", "wa hub", "menu wa"):
        from alfa.bot.advanced_commands import wa_command

        await wa_command(update, context)
        return

    if lower_norm in ("🖥️ status server", "status server", "server status", "status laptop", "cek server"):
        from alfa.bot.basic_commands import stats_command

        await stats_command(update, context)
        return

    # Auto-Reflexion & Reinforcement (Hermes-Style Learning Loop)
    try:
        from alfa.core.brain.learning_loop import (
            detect_and_process_user_correction,
            is_positive_reinforcement_signal,
            is_user_correction_signal,
            record_trajectory,
        )

        if is_user_correction_signal(user_text):
            corr_res = detect_and_process_user_correction(user_text, user_id=user_id)
            if corr_res:
                logger.info("Autonomous Reflexion captured rule: %s", corr_res.get("topic"))
        elif is_positive_reinforcement_signal(user_text):
            record_trajectory(
                user_prompt=user_text,
                result_summary="User positive feedback received",
                success=True,
                feedback="positive",
            )
            logger.info("Autonomous learning loop received positive reinforcement")
    except Exception as e:
        logger.debug("Auto-learning detection bypass: %s", e)

    # Sapaan murni → jawab instan, JANGAN lewat agent (hemat token + anti tool nyasar).
    fast = greeting_reply(user_text)
    if fast is not None:
        try:
            await database.save_chat_message(user_id, "user", user_text)
            await database.save_chat_message(user_id, "model", fast)
        except _HANDLER_ERR as db_err:
            logger.debug(f"[greeting] simpan riwayat gagal: {db_err}")
        await safe_send_message(context, chat_id, fast)
        return

    # Level 5+ Apex Engine: Temporal GraphRAG Ingestion, World-Model & Compiled Fast-Path (0 Token, Sub-ms)
    try:
        from alfa.core.apex import (
            analyze_field_event_preemptively,
            ingest_text_to_temporal_graph,
            try_execute_compiled_fastpath,
        )

        ingest_text_to_temporal_graph(user_text)
        analyze_field_event_preemptively(user_text)
        fp_hit = try_execute_compiled_fastpath(user_text)
        if fp_hit and fp_hit.get("response"):
            fp_reply = fp_hit["response"]
            try:
                await database.save_chat_message(user_id, "user", user_text)
                await database.save_chat_message(user_id, "model", fp_reply)
            except _HANDLER_ERR:
                pass
            await safe_send_message(context, chat_id, fp_reply)
            return
    except Exception as e:
        logger.debug("Apex fast-path bypass: %s", e)

    # Fast-Path WhatsApp: eksekusi sub-detik tanpa membebani antrean LLM cloud.
    if await try_handle_fast_wa(update, context, user_text):
        return

    # Fast-Path Reset Kuota: eksekusi instan tanpa membebani LLM
    norm_cmd = user_text.lower().strip()
    for ch in "!?.,-—…":
        norm_cmd = norm_cmd.replace(ch, " ")
    norm_cmd = " ".join(norm_cmd.split())
    if norm_cmd in (
        "reset kuota",
        "reset kuota harian",
        "reset budget",
        "nolkan kuota",
        "nolkan kuota harian",
        "clear kuota",
    ):
        from alfa.core import rate_limiter

        deleted = rate_limiter.reset_user_usage_today(user_id)
        usage = rate_limiter.get_user_usage_today(user_id)
        msg = (
            "🔄 **Kuota harian berhasil di-reset!**\n\n"
            f"• Token terpakai hari ini: **0** / {usage['budget_limit']:,} token\n"
            f"• Panggilan terpakai: **0** / {usage['call_limit']:,} panggilan\n"
            f"• Catatan pemakaian dihapus: {deleted} entri\n\n"
            "Sekarang Anda bisa kembali menggunakan AI secara normal tanpa batasan kuota."
        )
        await safe_send_message(context, chat_id, msg)
        return

    # 3. Periksa apakah ada batch pesan terusan terbaru yang menunggu instruksi pengguna
    if not (active_forward_batch and active_forward_batch.get("items")):
        recent_fwd = _RECENT_FORWARD_BATCHES.get(chat_id)
        if recent_fwd and not recent_fwd.get("consumed", False):
            if time.time() - recent_fwd.get("created_at", 0) < 600:
                recent_fwd["consumed"] = True
                user_text = (
                    f"[Kumpulan {recent_fwd['count']} Pesan Terusan dari {recent_fwd['senders_str']}]:\n\n"
                    f"{recent_fwd['full_text']}\n\n"
                    f"Instruksi Pengguna: {user_text}"
                )

    streamer = None
    stop_typing = None
    typing_task = None
    try:
        streamer = TelegramStreamer(context=context, chat_id=chat_id, initial_text=None)
        await streamer.start()
    except _HANDLER_ERR as se:
        logger.warning(f"[TelegramStreamer] Start failed: {se}")
        streamer = None

    if not streamer:
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(
            send_typing_loop(chat_id, context, stop_typing, constants.ChatAction.TYPING)
        )

    try:
        use_swarm = False
        try:
            from alfa.bot.mode_commands import get_telegram_mode_sync

            use_swarm = get_telegram_mode_sync() == "swarm"
            if use_swarm:
                _st = user_text.strip().lower()
                if len(_st.split()) <= 2 or _st.startswith(("/", "perbaiki", "tes", "halo", "ok", "batal")):
                    use_swarm = False
        except _HANDLER_ERR:
            use_swarm = False

        if use_swarm:
            # Mode SWARM: chat teks biasa = misi tim multi-agen.
            # Satu pesan status live (di-edit berkala) agar tak terkesan diam.
            if streamer:
                try:
                    await streamer.finalize(
                        "⚡ **Mode SWARM:** misi diteruskan ke tim multi-agen..."
                    )
                except _HANDLER_ERR:
                    pass
                streamer = None
            from alfa.bot.progress import SwarmProgressReporter

            reporter = SwarmProgressReporter(context, chat_id, user_text)
            await reporter.start()
            from alfa.bot.mode_commands import format_swarm_result, run_swarm_task

            swarm_task = asyncio.create_task(run_swarm_task(user_text))
            ACTIVE_CHAT_TASKS[chat_id] = swarm_task
            try:
                result = await swarm_task
            except asyncio.CancelledError:
                from alfa.swarm.workspace_hygiene import request_cancel_swarm

                request_cancel_swarm()
                await reporter.stop("⏹ Misi dibatalkan pengguna.")
                reply = "⏹ **Misi swarm telah dihentikan atas permintaan Anda.**"
                logger.info(f"[handle_text:swarm] Swarm task untuk chat_id={chat_id} dibatalkan pengguna.")
            except _HANDLER_ERR as e:
                logger.error(f"[handle_text:swarm] gagal untuk {user_id}: {e}", exc_info=True)
                await reporter.stop("❌ Misi gagal.")
                reply = (
                    "❌ Misi swarm gagal diproses "
                    f"({type(e).__name__}: {str(e)[:200]}). "
                    "Coba `/mode single` untuk 1 agen, atau kirim ulang."
                )
            else:
                if result.get("status") == "cancelled":
                    await reporter.stop("⏹ Misi swarm dihentikan pengguna.")
                    reply = "⏹ **Misi swarm telah dihentikan.** Eksekusi dibatalkan sebelum selesai."
                    swarm_files = []
                else:
                    await reporter.stop("✅ Selesai — laporan lengkap di bawah ⬇️")
                    steps_text, final_text, files = format_swarm_result(result)
                    await safe_send_message(context, chat_id, steps_text)
                    reply = final_text
                    swarm_files = files or []
            finally:
                ACTIVE_CHAT_TASKS.pop(chat_id, None)
        else:
            turn_task = asyncio.create_task(
                _run_agent_turn(
                    user_id=user_id,
                    user_prompt=user_text,
                    chat_id=chat_id,
                    streamer=streamer,
                )
            )
            ACTIVE_CHAT_TASKS[chat_id] = turn_task
            nudge_task = asyncio.create_task(
                _long_turn_nudge(context, chat_id, turn_task, streamer)
            )
            try:
                reply = await turn_task
            except asyncio.CancelledError:
                reply = "⏹ **Proses agen telah dibatalkan atas permintaan Anda.**"
                logger.info(f"[handle_text] Single turn untuk chat_id={chat_id} dibatalkan pengguna.")
            finally:
                ACTIVE_CHAT_TASKS.pop(chat_id, None)
                nudge_task.cancel()
                try:
                    await nudge_task
                except (asyncio.CancelledError, *_HANDLER_ERR):
                    pass
    except _HANDLER_ERR as e:
        # Jangan pernah diam: kegagalan turn harus tetap dibalas ke user.
        logger.error(f"[handle_text] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, permintaannya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang perintahnya."
        )
    finally:
        if stop_typing and typing_task:
            stop_typing.set()
            await typing_task

    if streamer:
        try:
            await streamer.finalize(reply)
        except _HANDLER_ERR as fe:
            logger.error(
                f"[TelegramStreamer] Finalize failed: {fe}, fallback to safe_send_message"
            )
            await safe_send_message(context, chat_id, reply)
    else:
        await safe_send_message(context, chat_id, reply)

    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time, user_prompt=user_text
    )

    for fpath in swarm_files:
        try:
            with open(fpath, "rb") as f_doc:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f_doc,
                    filename=os.path.basename(fpath),
                    caption=f"📁 **File Deliverable Swarm:** `{os.path.basename(fpath)}`",
                )
        except _HANDLER_ERR as file_err:
            logger.warning(f"Failed to send swarm file {fpath}: {file_err}")

    # If voice mode enabled and content is conversational, send voice note
    mod = _get_bot_module()
    db_mod = getattr(mod, "database", database) if mod else database
    settings = await db_mod.get_user_settings(user_id)
    if settings.get("voice_reply") and not should_reply_with_text_instead_of_voice(
        reply
    ):
        voice_path = None
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE
            )
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as voice_file:
                await update.message.reply_voice(voice=voice_file)
        except _HANDLER_ERR as tts_err:
            logger.error(f"TTS sending error: {tts_err}")
        finally:
            if voice_path and os.path.exists(voice_path):
                try:
                    os.remove(voice_path)
                except OSError:
                    pass


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming Voice Notes & Audio.
    Smart Adaptive Reply: Sends ONLY ONE response (either Voice Note OR Text) based on content.
    """
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return
    turn_start_time = time.time()

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.RECORD_VOICE
        )
    )
    try:
        file_obj = await context.bot.get_file(voice.file_id)
        voice_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(voice_bytes_io)
        voice_bytes = voice_bytes_io.getvalue()

        from google.genai import types

        mime = getattr(voice, "mime_type", None) or "audio/ogg"
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type=mime)

        transcription_text = None
        transcribe_client, _, _ = resolve_main_gemini()
        if transcribe_client:
            transcribe_models = []
            for candidate in (
                _main_brain_gemini_model(),
                GEMINI_MODEL,
                "gemini-3.5-flash",
                "gemini-flash-lite-latest",
                "gemini-3-flash-preview",
            ):
                name = (candidate or "").strip()
                if name and name not in transcribe_models:
                    transcribe_models.append(name)
            transcribe_prompt = types.Part.from_text(
                text="Transkripsikan isi rekaman suara ini secara akurat ke dalam teks. Kembalikan HANYA teks transkripsinya tanpa kata pengantar."
            )
            for model_id in transcribe_models:
                try:
                    tr_resp = await transcribe_client.aio.models.generate_content(
                        model=model_id,
                        contents=[
                            types.Content(
                                role="user",
                                parts=[audio_part, transcribe_prompt],
                            )
                        ],
                    )
                    if tr_resp and tr_resp.text:
                        transcription_text = tr_resp.text.strip()
                        logger.info(
                            f"Transkripsi pesan suara ({model_id}): {transcription_text}"
                        )
                        break
                except _HANDLER_ERR as tr_err:
                    logger.debug(f"Fast transcription skipped ({model_id}): {tr_err}")

        fast = None
        if transcription_text:
            fast = greeting_reply(transcription_text)
            if fast is not None:
                mod = _get_bot_module()
                db_mod = getattr(mod, "database", database) if mod else database
                try:
                    await db_mod.save_chat_message(
                        user_id, "user", f'[PESAN SUARA: "{transcription_text}"]'
                    )
                    await db_mod.save_chat_message(user_id, "model", fast)
                except _HANDLER_ERR:
                    pass
                reply = fast
            else:
                prompt = f'[PESAN SUARA PENGGUNA (Transkripsi): "{transcription_text}"]\nPahami instruksi di atas dan berikan jawaban yang lengkap dan akurat.'
                reply = await _run_agent_turn(
                    user_id=user_id,
                    user_prompt=prompt,
                    multimodal_parts=[audio_part],
                    chat_id=chat_id,
                )
        else:
            prompt = "Dengarkan rekaman suara ini dengan teliti, pahami instruksi/pertanyaannya, dan berikan jawaban yang lengkap dan akurat."
            reply = await _run_agent_turn(
                user_id=user_id,
                user_prompt=prompt,
                multimodal_parts=[audio_part],
                chat_id=chat_id,
            )
    except _HANDLER_ERR as e:
        logger.error(f"[handle_voice] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, pesan suaranya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang."
        )
    finally:
        stop_typing.set()
        await typing_task

    active_prompt = (
        (transcription_text or "")
        if "fast" in locals() and fast is not None
        else (prompt if "prompt" in locals() else (transcription_text or ""))
    )
    await _check_and_send_media_artifacts(
        update, context, turn_start_time=turn_start_time, user_prompt=active_prompt
    )

    prefer_text = should_reply_with_text_instead_of_voice(reply)
    sent_voice = False

    if not prefer_text:
        voice_path = None
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=constants.ChatAction.RECORD_VOICE
            )
            voice_path = await tts_engine.text_to_speech_ogg(reply)
            with open(voice_path, "rb") as vf:
                await update.message.reply_voice(voice=vf)
            sent_voice = True
        except _HANDLER_ERR as e:
            logger.error(f"TTS voice reply error: {e}, falling back to text")
            sent_voice = False
        finally:
            if voice_path and os.path.exists(voice_path):
                try:
                    os.remove(voice_path)
                except OSError:
                    pass

    if not sent_voice:
        await safe_send_message(context, chat_id, reply)


_PHOTO_BATCHES: dict[int, dict[str, Any]] = {}
_PHOTO_BATCH_LOCK = asyncio.Lock()


async def _execute_photo_batch(chat_id: int, batch: dict[str, Any]):
    photos = batch.get("photos", [])
    if not photos:
        return
    user_id = batch.get("user_id", 0)
    context = batch.get("context")
    update = batch.get("latest_update")
    turn_start_time = batch.get("turn_start_time", time.time())
    captions = [c for c in batch.get("captions", []) if c]
    user_caption = " ".join(captions).strip() if captions else ""

    # Selalu di-set saat batch dibuat (lihat _PHOTO_BATCHES.get_or_create);
    # assert ini hanya narrowing utk mypy: CallbackContext non-opsional.
    assert context is not None

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.UPLOAD_PHOTO
        )
    )
    reply = "❌ Maaf, terjadi kesalahan saat memproses foto-fotomu."

    try:
        multimodal_parts = []
        for p in photos:
            if p.get("part") is not None:
                multimodal_parts.append(p["part"])

        if len(photos) > 1:
            photo_blocks = []
            for idx, p in enumerate(photos, 1):
                fname = p.get("file_name", f"foto_{idx}.jpg")
                tctx = (p.get("txt_ctx") or "").strip()
                if tctx:
                    photo_blocks.append(f"--- FOTO {idx}: {fname} ---\n{tctx}")
                else:
                    photo_blocks.append(f"--- FOTO {idx}: {fname} ---")

            if not user_caption:
                user_caption = "Analisis dan berikan rangkuman terpadu isi seluruh foto ini."

            prompt = (
                f"[KUMPULAN {len(photos)} FOTO/GAMBAR DIUNGGAH SEKALIGUS]:\n"
                + "\n\n".join(photo_blocks)
                + f"\n\nInstruksi Pengguna: {user_caption}\n\n"
                "[PANDUAN LAPORAN TERPADU MULTI-FOTO]:\n"
                "- WAJIB jadikan 1 LAPORAN TUNGGAL yang rapi, padat, dan terstruktur.\n"
                "- Rincikan informasi dari setiap foto (tanggal/waktu watermark, lokasi koordinat, aktivitas, mandor, dan daftar item/material).\n"
                "- Di bagian akhir, sajikan Rekapitulasi Total Akumulasi secara bersih dan nyaman dibaca di Telegram.\n"
                "- DILARANG membuat laporan terpisah-pisah untuk masing-masing foto.\n"
                "- ANTI-OMISI: Cantumkan seluruh item material dan aksesoris (Poolclam, Dead End, Suspension, Stoping, Hanger, Plat Belt, dll.) tanpa ada yang terpotong."
            )
        else:
            p = photos[0]
            txt_ctx = p.get("txt_ctx", "")
            prompt = f"{txt_ctx}\n\nInstruksi Pengguna: {user_caption}" if txt_ctx else user_caption
            if not user_caption:
                prompt = f"{txt_ctx}\n\nAnalisis gambar ini secara detail." if txt_ctx else "Analisis gambar ini secara detail."

        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            multimodal_parts=multimodal_parts if multimodal_parts else None,
            chat_id=chat_id,
        )
    except _HANDLER_ERR as e:
        logger.error(f"[_execute_photo_batch] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, foto-fotonya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang."
        )
    finally:
        stop_typing.set()
        await typing_task

    await safe_send_message(context, chat_id, reply)
    if update:
        await _check_and_send_media_artifacts(
            update, context, turn_start_time=turn_start_time, user_prompt=user_caption
        )


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos & images for vision analysis (with multi-photo debouncing)."""
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    photos = update.message.photo
    if not photos:
        return

    best_photo = photos[-1]

    try:
        photo_file = await context.bot.get_file(best_photo.file_id)
        photo_bytes_io = io.BytesIO()
        await photo_file.download_to_memory(photo_bytes_io)
        photo_bytes = photo_bytes_io.getvalue()

        from alfa.tools.filesystem import universal_file_extractor as ufe

        photo_filename = f"photo_{int(time.time())}_{user_id}.jpg"
        txt_ctx, image_part = ufe.process_uploaded_attachment(
            photo_filename, "image/jpeg", photo_bytes, save_disk=True
        )

        photo_item = {
            "file_name": photo_filename,
            "txt_ctx": txt_ctx,
            "part": image_part,
            "caption": (update.message.caption or "").strip(),
        }

        async with _PHOTO_BATCH_LOCK:
            if chat_id not in _PHOTO_BATCHES:
                _PHOTO_BATCHES[chat_id] = {
                    "photos": [],
                    "captions": [],
                    "task": None,
                    "user_id": user_id,
                    "context": context,
                    "latest_update": update,
                    "turn_start_time": time.time(),
                }
            batch = _PHOTO_BATCHES[chat_id]
            batch["photos"].append(photo_item)
            if update.message.caption:
                batch["captions"].append(update.message.caption.strip())
            batch["latest_update"] = update

            if batch.get("task") and not batch["task"].done():
                batch["task"].cancel()

            async def _delayed_photo_runner():
                try:
                    # Jeda 1.8 detik untuk menampung album atau rentetan foto berurutan
                    await asyncio.sleep(1.8)
                except asyncio.CancelledError:
                    return

                async with _PHOTO_BATCH_LOCK:
                    ready_batch = _PHOTO_BATCHES.pop(chat_id, None)

                if not ready_batch or not ready_batch.get("photos"):
                    return

                await _execute_photo_batch(chat_id, ready_batch)

            batch["task"] = asyncio.create_task(_delayed_photo_runner())
    except _HANDLER_ERR as e:
        logger.error(f"[handle_photo] download/ekstraksi gagal untuk {user_id}: {e}", exc_info=True)
        await safe_send_message(context, chat_id, f"❌ Gagal memproses berkas foto: {e}")


_DOC_BATCHES: dict[int, dict[str, Any]] = {}
_DOC_BATCH_LOCK = asyncio.Lock()


async def _execute_document_batch(chat_id: int, batch: dict[str, Any]):
    docs = batch.get("docs", [])
    if not docs:
        return
    user_id = batch.get("user_id", 0)
    context = batch.get("context")
    update = batch.get("latest_update")
    turn_start_time = batch.get("turn_start_time", time.time())
    captions = [c for c in batch.get("captions", []) if c]

    # Gabungkan caption pengguna jika ada
    user_caption = " ".join(captions).strip() if captions else ""

    # Selalu di-set saat batch dibuat; assert untuk narrowing mypy.
    assert context is not None

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        send_typing_loop(
            chat_id, context, stop_typing, constants.ChatAction.UPLOAD_DOCUMENT
        )
    )
    reply = "❌ Maaf, terjadi kesalahan saat memproses dokumenmu."

    try:
        multimodal_parts = []
        for d in docs:
            if d.get("part") is not None:
                multimodal_parts.append(d["part"])

        if len(docs) > 1:
            # Multi-dokumen: rangkum langsung jadi SATU laporan rincian terpadu
            doc_blocks = []
            file_names = []
            for idx, d in enumerate(docs, 1):
                fname = d.get("file_name", f"file_{idx}")
                file_names.append(fname)
                tctx = (d.get("txt_ctx") or "").strip()
                if tctx:
                    doc_blocks.append(f"--- DOKUMEN {idx}: {fname} ---\n{tctx}")
                else:
                    doc_blocks.append(f"--- DOKUMEN {idx}: {fname} (lampiran berkas) ---")

            if not user_caption:
                user_caption = "Analisis dan berikan rincian penting isi seluruh dokumen ini."

            prompt = (
                f"[KUMPULAN {len(docs)} BERKAS DOKUMEN DIUNGGAH SEKALIGUS]:\n"
                f"Daftar Berkas: {', '.join(file_names)}\n\n"
                + "\n\n".join(doc_blocks)
                + f"\n\nInstruksi Pengguna: {user_caption}\n\n"
                "[PANDUAN LAPORAN RINCIAN MULTI-DOKUMEN DARI PENGGUNA]:\n"
                "- FORMAT WAJIB: CUKUP NAMA DOKUMEN DAN RINCIAN MATERIALNYA SECARA RAPI (JANGAN MEMBINGUNGKAN PEMBACA).\n"
                "- WAJIB JADIKAN 1 LAPORAN TERPADU DENGAN STRUKTUR RUNUT PER BERKAS:\n"
                "  📄 Nama Dokumen / Berkas (misal: CLR56-99-263_DOEID26101705.xls)\n"
                "  • Nama Material / Item : QTY Satuan\n"
                "- Di bagian akhir, berikan Rekapitulasi Total Material secara ringkas dan bersih.\n"
                "- DILARANG bertele-tele membuat ringkasan eksekutif panjang, analisis narasi umum, detail gudang/pemohon yang tidak relevan, atau mengacak material tanpa kejelasan dokumen asalnya.\n"
                "- Sajikan dengan format rapi, bersih, to-the-point, dan nyaman dibaca di Telegram."
            )
        else:
            # Dokumen tunggal
            d = docs[0]
            fname = d.get("file_name", "file.bin")
            tctx = (d.get("txt_ctx") or "").strip()
            if not user_caption:
                user_caption = "Berikan rincian material/isi dari dokumen ini."

            doc_summary_guidance = (
                "\n\n[PANDUAN FORMAT LAPORAN DOKUMEN]:\n"
                "- FORMAT WAJIB: CUKUP NAMA DOKUMEN DAN RINCIAN MATERIAL / ITEMNYA SECARA RAPI.\n"
                "- Tampilkan per butir jelas: • Nama Material / Item : QTY Satuan.\n"
                "- DILARANG bertele-tele membuat pembuka/penutup panjang, analisis narasi teoritis, atau status audit internal.\n"
                "- Sajikan dengan format yang padat, bersih, to-the-point, dan nyaman dibaca di Telegram."
            )
            if tctx:
                prompt = f"{tctx}\n\nInstruksi Pengguna: {user_caption}{doc_summary_guidance}"
            else:
                prompt = f"Dokumen/Berkas '{fname}': {user_caption}{doc_summary_guidance}"

        reply = await _run_agent_turn(
            user_id=user_id,
            user_prompt=prompt,
            multimodal_parts=multimodal_parts or None,
            chat_id=chat_id,
        )

        if len(docs) > 1:
            file_names = [d.get("file_name", "file") for d in docs]
            combined_blocks = []
            for idx, d in enumerate(docs, 1):
                fname = d.get("file_name", f"file_{idx}")
                tctx = (d.get("txt_ctx") or "").strip()
                if tctx:
                    combined_blocks.append(f"--- DOKUMEN {idx}: {fname} ---\n{tctx}")
                else:
                    combined_blocks.append(f"--- DOKUMEN {idx}: {fname} (lampiran berkas) ---")
            combined_txt = "\n\n".join(combined_blocks)

            _RECENT_DOCS[chat_id] = {
                "is_batch": True,
                "docs_count": len(docs),
                "file_name": f"{len(docs)} Berkas Gabungan ({file_names[0]} dkk)",
                "file_names": file_names,
                "mime_type": "multipart/batch",
                "txt_ctx": combined_txt,
                "summary_reply": reply,
                "time": time.time(),
            }
        elif docs:
            d = docs[0]
            if d.get("txt_ctx"):
                _RECENT_DOCS[chat_id] = {
                    "is_batch": False,
                    "docs_count": 1,
                    "file_name": d["file_name"],
                    "file_names": [d["file_name"]],
                    "mime_type": d["mime_type"],
                    "txt_ctx": d["txt_ctx"],
                    "summary_reply": reply,
                    "time": time.time(),
                }
    finally:
        stop_typing.set()
        await typing_task

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    doc_buttons = [
        [
            InlineKeyboardButton("📄 Buat PDF Resmi", callback_data="docact:pdf"),
            InlineKeyboardButton("📊 Buat Excel Baru", callback_data="docact:excel"),
        ],
        [
            InlineKeyboardButton("🔍 Analisis Mendalam", callback_data="docact:deep"),
        ],
    ]
    doc_markup = InlineKeyboardMarkup(doc_buttons)

    await safe_send_message(context, chat_id, reply, reply_markup=doc_markup)
    if update:
        await _check_and_send_media_artifacts(
            update, context, turn_start_time=turn_start_time, user_prompt=user_caption
        )


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming documents (PDF, TXT, code, Excel, CSV, and long Audio meeting files).
    Batches documents uploaded in rapid succession / albums into a single analysis turn.
    """
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    doc = update.message.document
    if not doc:
        return

    caption = (update.message.caption or "").strip()
    file_name = doc.file_name or "file.bin"
    mime_type = doc.mime_type or "application/octet-stream"

    try:
        doc_file = await context.bot.get_file(doc.file_id)
        doc_bytes_io = io.BytesIO()
        await doc_file.download_to_memory(doc_bytes_io)
        doc_bytes = doc_bytes_io.getvalue()
    except Exception as e:
        logger.error(f"[handle_document] Gagal unduh file '{file_name}': {e}")
        await safe_send_message(
            context, chat_id, f"❌ Gagal mengunduh berkas `{file_name}`: {e}"
        )
        return

    from alfa.tools.filesystem import universal_file_extractor as ufe

    try:
        txt_ctx, part = ufe.process_uploaded_attachment(file_name, mime_type, doc_bytes)
    except Exception as e:
        logger.warning(f"[handle_document] Gagal ekstraksi '{file_name}': {e}")
        txt_ctx, part = "", None

    doc_item = {
        "file_name": file_name,
        "mime_type": mime_type,
        "txt_ctx": txt_ctx,
        "part": part,
        "caption": caption,
    }

    async with _DOC_BATCH_LOCK:
        if chat_id not in _DOC_BATCHES:
            _DOC_BATCHES[chat_id] = {
                "docs": [],
                "captions": [],
                "task": None,
                "user_id": user_id,
                "context": context,
                "latest_update": update,
                "turn_start_time": time.time(),
            }
        batch = _DOC_BATCHES[chat_id]
        batch["docs"].append(doc_item)
        if caption:
            batch["captions"].append(caption)
        batch["latest_update"] = update

        if batch["task"] and not batch["task"].done():
            batch["task"].cancel()

        async def _delayed_batch_runner():
            try:
                # Jeda 1.2 detik untuk menampung album atau berkas yang dikirim bersamaan
                await asyncio.sleep(1.2)
            except asyncio.CancelledError:
                return

            async with _DOC_BATCH_LOCK:
                ready_batch = _DOC_BATCHES.pop(chat_id, None)

            if not ready_batch or not ready_batch.get("docs"):
                return

            await _execute_document_batch(chat_id, ready_batch)

        batch["task"] = asyncio.create_task(_delayed_batch_runner())
