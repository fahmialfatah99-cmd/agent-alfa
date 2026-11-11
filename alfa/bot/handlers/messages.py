"""Pesan teks, voice note, dan fast-path pesan masuk WhatsApp."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time

from telegram import Update, constants
from telegram.ext import ContextTypes

from alfa.bot.config import (
    GEMINI_MODEL,
    _main_brain_gemini_model,
    resolve_main_gemini,
)
from alfa.bot.handlers._compat import (
    bot_module,
    check_artifacts_turn,
    is_authorized,
    run_agent_turn,
    safe_send_message,
    send_typing_loop,
    telegram_streamer,
)
from alfa.bot.handlers._state import (
    _FORWARD_BATCH_LOCK,
    _FORWARD_BATCHES,
    _HANDLER_ERR,
    _RECENT_FORWARD_BATCHES,
    _WA_INCOMING_TRIGGERS,
    ACTIVE_CHAT_TASKS,
)
from alfa.bot.handlers.common import (
    _long_turn_nudge,
    greeting_reply,
)
from alfa.bot.handlers.forwards import _execute_forward_batch, get_forward_info
from alfa.bot.helpers import should_reply_with_text_instead_of_voice
from alfa.core import database
from alfa.media import tts_engine

logger = logging.getLogger("TelegramAIAgent")

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

def _wa_stale_notice(res: dict) -> str:
    """Peringatan kesegaran data rekap WA (bila rekap disusun dari arsip basi)."""
    warning = str(res.get("warning") or "").strip()
    if not warning:
        return ""
    freshness = res.get("data_freshness") or {}
    newest = str(freshness.get("newest_message_at") or "")[:16].replace("T", " ")
    extra = f"\n🕒 _Pesan terakhir: {newest}_" if newest else ""
    return f"\n\n{warning}{extra}"


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
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
            tot_cable = res.get("total_cable_m", 0)
            cable_str = f"🌐 *Kabel Udara (KU 24):* *{tot_cable:,.0f} meter*\n" if tot_cable > 0 else ""
            acc_map = res.get("accessories_breakdown", {})
            acc_str = ""
            if acc_map:
                acc_str = (
                    f"🔩 *Aksesoris FTTH:*\n"
                    f"• Stoping: {acc_map.get('ACC-STOPING', 0)} pcs | Dead End: {acc_map.get('ACC-DEADEND', 0)} pcs\n"
                    f"• Full Clamp: {acc_map.get('ACC-FULCLAM', 0)} pcs | Suspen: {acc_map.get('ACC-SUSPEN', 0)} pcs\n"
                    f"• Stainless Belt: {acc_map.get('ACC-BELT', 0)} roll | Slack Hanger: {acc_map.get('ACC-HANGER', 0)} pcs\n\n"
                )

            card = (
                f"📦 *REKAPITULASI MATERIAL MASTER LAHAT*\n\n"
                f"📊 *Tiang Lapangan:*\n"
                f"• Total Bersih: *{res.get('total_net')} batang*\n"
                f"• Total Bruto: {res.get('total_bruto')} btg | Retur: {res.get('total_retur')} btg\n\n"
                f"{cable_str}"
                f"{acc_str}"
                f"👷 *Mandor Terverifikasi:* {', '.join(res.get('mandors', []))}\n"
                f"📁 *Berkas Master:* `{res.get('excel_file')}`\n\n"
                f"💡 _Data diperbarui in-place pada Master Ledger Kumulatif tanpa membuat berkas baru._"
                f"{_wa_stale_notice(res)}"
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

    if lower_norm in ("📦 rekap material curup", "rekap material curup", "rekap curup", "pengambilan curup", "pengambilan mandor curup"):
        from alfa.tools.telecom_tools import reconcile_whatsapp_material_group

        await safe_send_message(context, chat_id, "⏳ *Menyusun Rekapitulasi Material WhatsApp Cluster Curup...*")
        res = reconcile_whatsapp_material_group(
            group_name_or_id="Laporan pengambilan mandor curup",
            auto_launch_gridcraft=False,
        )
        if res.get("status") == "success":
            tot_cable = res.get("total_cable_m", 0)
            cable_str = f"🌐 *Kabel Udara (KU 24):* *{tot_cable:,.0f} meter*\n" if tot_cable > 0 else ""
            acc_map = res.get("accessories_breakdown", {})
            acc_str = ""
            if acc_map:
                acc_lines = []
                if acc_map.get('ACC-STOPING'):
                    acc_lines.append(f"• Stoping: {acc_map['ACC-STOPING']} pcs")
                if acc_map.get('ACC-DEADEND'):
                    acc_lines.append(f"• Dead End: {acc_map['ACC-DEADEND']} pcs")
                if acc_map.get('ACC-FULCLAM'):
                    acc_lines.append(f"• Full Clamp/Pole Clamp: {acc_map['ACC-FULCLAM']} pcs")
                if acc_map.get('ACC-SUSPEN'):
                    acc_lines.append(f"• Suspen: {acc_map['ACC-SUSPEN']} pcs")
                if acc_map.get('ACC-HANGER'):
                    acc_lines.append(f"• Slack Hanger: {acc_map['ACC-HANGER']} pcs")
                if acc_map.get('ACC-BUAYA'):
                    acc_lines.append(f"• Clamp Buaya: {acc_map['ACC-BUAYA']} pcs")
                if acc_map.get('ACC-BELT'):
                    acc_lines.append(f"• Stainless Belt: {acc_map['ACC-BELT']} roll")
                if acc_lines:
                    acc_str = "🔩 *Aksesoris FTTH:*\n" + "\n".join(acc_lines) + "\n\n"

            pole_breakdown = res.get("breakdown", {})
            pole_str = ""
            if pole_breakdown:
                pole_items = [f"{k}: {v} btg" for k, v in pole_breakdown.items() if v != 0]
                if pole_items:
                    pole_str = f" ({', '.join(pole_items)})"

            card = (
                f"📦 *REKAPITULASI MATERIAL MASTER CURUP*\n\n"
                f"📊 *Tiang Lapangan:*\n"
                f"• Total Bersih: *{res.get('total_net')} batang*{pole_str}\n"
                f"• Total Bruto: {res.get('total_bruto')} btg | Retur: {res.get('total_retur')} btg\n\n"
                f"{cable_str}"
                f"{acc_str}"
                f"👷 *Mandor Terverifikasi:* {', '.join(res.get('mandors', []))}\n"
                f"📁 *Berkas Master:* `{res.get('excel_file')}`\n\n"
                f"💡 _Data diperbarui in-place pada Master Ledger Kumulatif tanpa membuat berkas baru._"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = [
                [InlineKeyboardButton("📊 Buka GridCraft Curup", callback_data="artcraft|open|gridcraft|curup")],
                [InlineKeyboardButton("📦 Rekap Lahat", callback_data="btn_rekap_lahat")],
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
        streamer = telegram_streamer(context=context, chat_id=chat_id, initial_text=None)
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
                try:
                    await reporter.stop("⏹ Misi dibatalkan pengguna.")
                except Exception as exc:
                    logger.debug("Kegagalan tak terduga di handle_text_message: %s", exc)
                logger.info(f"[handle_text:swarm] Swarm task untuk chat_id={chat_id} dibatalkan pengguna.")
                # Notifikasi user DULU, baru teruskan cancellation (kontrak asyncio:
                # CancelledError harus diteruskan, tidak ditelan).
                try:
                    await safe_send_message(
                        context,
                        chat_id,
                        "⏹ **Misi swarm telah dihentikan atas permintaan Anda.**",
                    )
                except Exception as exc:
                    logger.debug("Kegagalan tak terduga di handle_text_message: %s", exc)
                raise
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
                run_agent_turn(
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

    await check_artifacts_turn(
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
    mod = bot_module()
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
    if not is_authorized(user_id):
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
    # WAJIB di-init SEBELUM try: unduhan voice bisa gagal sebelum variabel di bawah
    # di-assign, dan aksesnya di luar try akan memicu UnboundLocalError -> user
    # tidak mendapat balasan sama sekali.
    transcription_text: str | None = None
    prompt: str = ""
    fast: str | None = None
    try:
        file_obj = await context.bot.get_file(voice.file_id)
        voice_bytes_io = io.BytesIO()
        await file_obj.download_to_memory(voice_bytes_io)
        voice_bytes = voice_bytes_io.getvalue()

        from google.genai import types

        mime = getattr(voice, "mime_type", None) or "audio/ogg"
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type=mime)

        transcribe_client, _, _ = resolve_main_gemini()
        if transcribe_client:
            transcribe_models = []
            # Model transkripsi khusus DICOBAH LEBIH DAHULU (murah & akurat untuk
            # audio), lalu fallback ke model chat umum.
            for candidate in (
                "gemini-3.5-transcribe",
                _main_brain_gemini_model(),
                GEMINI_MODEL,
                "gemini-3.8-flash",
                "gemini-3.6-flash",
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
                mod = bot_module()
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
                reply = await run_agent_turn(
                    user_id=user_id,
                    user_prompt=prompt,
                    multimodal_parts=[audio_part],
                    chat_id=chat_id,
                )
        else:
            prompt = "Dengarkan rekaman suara ini dengan teliti, pahami instruksi/pertanyaannya, dan berikan jawaban yang lengkap dan akurat."
            reply = await run_agent_turn(
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
        if fast is not None
        else (prompt or (transcription_text or ""))
    )
    await check_artifacts_turn(
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
