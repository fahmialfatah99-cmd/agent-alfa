"""Deteksi intent media & pengiriman artefak hasil tool."""
from __future__ import annotations

import logging
import os
import time

from telegram import Update
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.handlers._compat import bot_module, sandbox_dir
from alfa.bot.handlers._state import (
    _ARTIFACT_INTENT_KEYWORDS,
    _HANDLER_ERR,
    _PROCESSED_ARTIFACT_TURNS,
)

logger = logging.getLogger("TelegramAIAgent")

async def _check_and_send_media_artifacts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_start_time: float | None = None,
    user_prompt: str | None = None,
    executed_tools: list[str] | None = None,
):
    mod = bot_module()
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

def _safe_unlink(path: str) -> None:
    """Hapus file tanpa pernah menggagalkan alur (dipakai untuk artefak)."""
    try:
        os.remove(path)
    except OSError:
        pass

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
    Equipped with strict deduplication guards to prevent double-sending of media artifacts.
    """
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not os.path.exists(sandbox_dir()):
        return

    # Turn-level idempotency guard: prevent duplicate dispatch from polling retry/re-entry
    up_id = getattr(update, "update_id", None)
    if isinstance(up_id, int):
        turn_key = f"{chat_id}:{up_id}"
        now_ts = time.time()
        if turn_key in _PROCESSED_ARTIFACT_TURNS and (now_ts - _PROCESSED_ARTIFACT_TURNS[turn_key]) < 30.0:
            logger.debug(f"[check_and_send_media_artifacts] Skipping duplicate turn {turn_key}")
            return
        _PROCESSED_ARTIFACT_TURNS[turn_key] = now_ts
        if len(_PROCESSED_ARTIFACT_TURNS) > 200:
            cutoff = now_ts - 120.0
            stale_keys = [k for k, v in _PROCESSED_ARTIFACT_TURNS.items() if v < cutoff]
            for k in stale_keys:
                _PROCESSED_ARTIFACT_TURNS.pop(k, None)

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

    sent_basenames: set[str] = set()

    named_media = [
        ("desktop_screen.png", "🖥️ Tangkapan Layar Desktop", ("screenshot", "screen", "tangkapan")),
        ("webcam_frame.jpg", "📷 Foto Kamera Webcam", ("webcam", "kamera", "camera")),
        ("generated_plot.png", "📊 Grafik Visualisasi Data (Python)", ("chart", "grafik", "plot", "diagram")),
        ("dataset_analysis_chart.png", "📊 Grafik Analisis Dataset", ("chart", "grafik", "dataset", "analisis")),
        ("browser_screenshot.png", "🌐 Tangkapan Layar Browser (Camofox)", ("browser", "screenshot", "web")),
    ]

    for filename, caption, triggers in named_media:
        full_path = os.path.join(sandbox_dir(), filename)
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
                sent_basenames.add(filename.lower())
                # Hapus HANYA kalau benar-benar terkirim. Kalau dihapus di finally,
                # satu network blip -> artefak hilang PERMANEN tanpa retry.
                _safe_unlink(full_path)
            except _HANDLER_ERR as send_err:
                logger.error(f"Failed to send media artifact {filename}: {send_err}")

    raw_candidates = []
    try:
        _sandbox_entries = os.listdir(sandbox_dir())
    except OSError:
        _sandbox_entries = []
    for fname in _sandbox_entries:
        if fname.lower() in sent_basenames:
            continue
        fpath = os.path.join(sandbox_dir(), fname)
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
            # Jika named_media sudah mengirim screenshot desktop/browser, buang gambar tangkapan layar duplikat
            if any(name in sent_basenames for name in ("desktop_screen.png", "browser_screenshot.png")):
                if any(k in fname.lower() for k in ("screen", "desktop", "tangkapan")):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
                    continue

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

    # Kirim foto / grafik dengan proteksi anti-duplicate
    for fname, fpath in images_to_send:
        if fname.lower() in sent_basenames:
            try:
                os.remove(fpath)
            except OSError:
                pass
            continue

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
            sent_basenames.add(fname.lower())
            _safe_unlink(fpath)
        except _HANDLER_ERR as img_err:
            logger.error(f"Failed to send image {fname}: {img_err}")

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
            if fname.lower() in sent_basenames:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
                continue
            try:
                with open(fpath, "rb") as df:
                    await context.bot.send_document(
                        chat_id=chat_id, document=df, caption=f"📄 Berkas: {fname}"
                    )
                sent_basenames.add(fname.lower())
                _safe_unlink(fpath)
            except _HANDLER_ERR as doc_err:
                logger.error(f"Failed to send document {fname}: {doc_err}")
