"""Pesan foto: batch unggahan foto lapangan."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any

from telegram import Update, constants
from telegram.ext import ContextTypes

from alfa.bot.handlers._compat import (
    check_artifacts_turn,
    is_authorized,
    run_agent_turn,
    safe_send_message,
    send_typing_loop,
)
from alfa.bot.handlers._state import (
    _HANDLER_ERR,
    _PHOTO_BATCH_LOCK,
    _PHOTO_BATCHES,
)

logger = logging.getLogger("TelegramAIAgent")


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

        reply = await run_agent_turn(
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
        await check_artifacts_turn(
            update, context, turn_start_time=turn_start_time, user_prompt=user_caption
        )

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos & images for vision analysis (with multi-photo debouncing)."""
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
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
