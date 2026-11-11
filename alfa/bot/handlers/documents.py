"""Dokumen lapangan: cache dokumen, aksi dokumen, batch dokumen."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import tempfile
import time
from typing import Any

from telegram import Update, constants
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa.bot.handlers._compat import (
    check_artifacts_turn,
    is_authorized,
    run_agent_turn,
    safe_send_message,
    sandbox_dir,
    send_typing_loop,
)
from alfa.bot.handlers._state import (
    _DOC_BATCH_LOCK,
    _DOC_BATCHES,
    _HANDLER_ERR,
    _RECENT_DOCS,
    _RECENT_DOCS_CACHE_PATH,
    ensure_upload_cache_dir,
)

logger = logging.getLogger("TelegramAIAgent")

def _save_recent_docs_cache() -> None:
    """Simpan _RECENT_DOCS ke disk agar restart service bot tidak membuat tombol aksi dokumen kedaluwarsa."""
    try:
        os.makedirs(os.path.dirname(_RECENT_DOCS_CACHE_PATH), exist_ok=True)
        serializable = {str(k): v for k, v in _RECENT_DOCS.items() if isinstance(v, dict)}
        with open(_RECENT_DOCS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[_save_recent_docs_cache] Gagal menyimpan cache dokumen: {e}")

def _get_or_recover_recent_doc(chat_id: int, user_id: int = 0) -> dict[str, Any] | None:
    """Ambil doc_info dari RAM, disk cache, atau auto-recovery dari chat_history SQLite."""
    if chat_id in _RECENT_DOCS:
        return _RECENT_DOCS[chat_id]

    # 1. Coba muat dari disk cache (folder privat per-user)
    if os.path.exists(_RECENT_DOCS_CACHE_PATH):
        try:
            with open(_RECENT_DOCS_CACHE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if isinstance(v, dict):
                    _RECENT_DOCS[int(k)] = v
            if chat_id in _RECENT_DOCS:
                return _RECENT_DOCS[chat_id]
        except Exception as e:
            logger.debug(f"[_get_or_recover_recent_doc] Gagal membaca disk cache: {e}")

    # 2. Fallback Auto-Recovery dari tabel chat_history SQLite jika service baru di-restart
    import re
    import sqlite3

    from alfa.core.db.connection import DB_PATH

    target_uid = user_id or chat_id
    conn = None
    try:
        # CATATAN: `with sqlite3.connect(...)` TIDAK menutup koneksi (hanya commit/
        # rollback) -> file descriptor bocor tiap panggilan. Tutup eksplisit di finally.
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        if True:
            c = conn.cursor()
            c.execute(
                """
                SELECT id, content FROM chat_history
                WHERE user_id = ? AND role = 'user'
                  AND (
                      content LIKE '%[LOCAL_DISK_PATH:%'
                      OR content LIKE '%[SPREADSHEET EXCEL:%'
                      OR content LIKE '%[DOKUMEN PDF:%'
                      OR content LIKE '%[DOKUMEN WORD:%'
                      OR content LIKE '%[BERKAS CSV/TSV:%'
                      OR content LIKE '%[KUMPULAN % BERKAS DOKUMEN%'
                  )
                ORDER BY id DESC LIMIT 1
                """,
                (target_uid,),
            )
            row = c.fetchone()
            if row:
                msg_id, raw_content = row[0], row[1] or ""
                c.execute(
                    """
                    SELECT content FROM chat_history
                    WHERE user_id = ? AND role IN ('assistant', 'model') AND id > ?
                    ORDER BY id ASC LIMIT 1
                    """,
                    (target_uid, msg_id),
                )
                ans_row = c.fetchone()
                summary_reply = ans_row[0] if ans_row and ans_row[0] else ""

                txt_ctx = raw_content.split("\n\nInstruksi Pengguna:")[0].strip()
                file_name = "Dokumen_Referensi"
                m_path = re.search(r"\[LOCAL_DISK_PATH:\s*([^\]]+)\]", txt_ctx)
                m_tag = re.search(
                    r"\[(?:SPREADSHEET EXCEL|DOKUMEN PDF|DOKUMEN WORD|BERKAS CSV/TSV|DOKUMEN TEKS/KODE):\s*([^\]]+)\]",
                    txt_ctx,
                )
                if m_path:
                    local_p = m_path.group(1).strip()
                    file_name = os.path.basename(local_p)
                    ext = os.path.splitext(file_name)[1].lower()
                    if os.path.isfile(local_p) and ext in (".xlsx", ".xls", ".ods"):
                        try:
                            from alfa.tools.filesystem import (
                                universal_file_extractor as ufe,
                            )

                            with open(local_p, "rb") as lf:
                                fresh_excel = ufe._extract_excel(lf.read(), file_name, ext)
                            if fresh_excel:
                                path_hdr = (
                                    f"[LOCAL_DISK_PATH: {local_p}]\n"
                                    f"[SPREADSHEET EXCEL: {file_name}]\n"
                                )
                                txt_ctx = f"{path_hdr}\n{fresh_excel}".strip()
                        except Exception as exc:
                            logger.debug("Kegagalan tak terduga di _get_or_recover_recent_doc: %s", exc)
                elif m_tag:
                    file_name = m_tag.group(1).strip()

                is_batch = raw_content.startswith("[KUMPULAN ")
                recovered = {
                    "is_batch": is_batch,
                    "docs_count": 1,
                    "file_name": file_name,
                    "file_names": [file_name],
                    "mime_type": "application/octet-stream",
                    "txt_ctx": txt_ctx,
                    "summary_reply": summary_reply,
                    "time": time.time(),
                }
                _RECENT_DOCS[chat_id] = recovered
                _save_recent_docs_cache()
                logger.info(
                    f"[_get_or_recover_recent_doc] Berhasil memulihkan dokumen '{file_name}' untuk chat_id={chat_id} dari chat_history (id={msg_id})."
                )
                return recovered
    except Exception as e:
        logger.warning(f"[_get_or_recover_recent_doc] Gagal memulihkan dari SQLite: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as exc:
                logger.debug("Kegagalan tak terduga di _get_or_recover_recent_doc: %s", exc)

    return None

def _parse_summary_into_table(summary_reply: str) -> list[list[str]]:
    """Ekstrak butir-butir laporan ('• Item : Nilai') dari summary_reply menjadi tabel 2D terstruktur."""
    if not summary_reply:
        return []
    rows: list[list[str]] = [["No", "Kategori / Bagian", "Nama Material / Parameter", "Rincian / Kuantitas"]]
    current_section = "Ringkasan Umum"
    idx = 1
    for raw_line in summary_reply.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Deteksi subjudul bagian seperti *KABEL FIBER OPTIK:* atau ### Bagian
        if (line.startswith("*") and line.endswith("*")) or line.startswith("#"):
            sec = line.strip("*# :").replace("\\_", "_")
            if sec and not sec.lower().startswith("dokumen:"):
                current_section = sec
            continue
        if line.startswith(("•", "-", "▫️", "* ")) and ":" in line:
            clean_item = line.lstrip("•-▫️* ").replace("\\_", "_").strip()
            name_part, val_part = clean_item.split(":", 1)
            rows.append([str(idx), current_section, name_part.strip(), val_part.strip()])
            idx += 1
    return rows if len(rows) > 1 else []

async def handle_doc_action_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> bool:
    """Handle 1-click interactive document export/analysis buttons."""
    if not data.startswith("docact:"):
        return False

    action = data.split(":", 1)[1]
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    doc_info = _get_or_recover_recent_doc(chat_id, user_id)
    if not doc_info:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Data dokumen referensi sudah kedaluwarsa. Silakan unggah kembali dokumennya.",
        )
        return True

    turn_start_time = time.time()
    file_name = doc_info.get("file_name", "dokumen")
    txt_ctx = doc_info.get("txt_ctx", "")
    summary_reply = (doc_info.get("summary_reply") or "").strip()
    is_batch = doc_info.get("is_batch", False)
    docs_count = doc_info.get("docs_count", 1)
    file_names = doc_info.get("file_names", [file_name])

    # Bersihkan file keluaran lama di sandbox sebelum turn aksi agar tak terjadi double output
    if os.path.exists(sandbox_dir()):
        target_exts = {
            "excel": (".xlsx", ".xls", ".csv"),
            "pdf": (".pdf",),
        }.get(action, ())
        for f in os.listdir(sandbox_dir()):
            if any(f.lower().endswith(ext) for ext in target_exts):
                try:
                    os.remove(os.path.join(sandbox_dir(), f))
                except OSError:
                    pass

    # JALUR INSTAN ZERO-TOKEN (<0.3 detik, 0 token LLM) untuk PDF & Excel bila hasil analisis sudah tersedia
    if action in ("pdf", "excel") and summary_reply:
        import re as _re

        base_stem = _re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(file_name)[0]).strip("_") or "Dokumen"
        parsed_table = _parse_summary_into_table(summary_reply)
        clean_summary_txt = (
            summary_reply.replace("*", "")
            .replace("\\_", "_")
            .replace("`", "")
            .strip()
        )
        try:
            if action == "pdf":
                from alfa.tools.media.pdf_builder import generate_pdf_report

                out_pdf_name = f"Laporan_Resmi_{base_stem}.pdf"
                res = generate_pdf_report(
                    title=f"Laporan Resmi: {file_name}",
                    summary=clean_summary_txt,
                    table_data_json=json.dumps(parsed_table, ensure_ascii=False) if parsed_table else "",
                    filename=out_pdf_name,
                )
                if res.get("status") == "success":
                    await safe_send_message(
                        context,
                        chat_id,
                        f"✅ **Laporan PDF Resmi Berhasil Dibuat (Instan 0-Token)**\n📄 Berkas: `{out_pdf_name}`",
                    )
                    await check_artifacts_turn(
                        update,
                        context,
                        turn_start_time=turn_start_time,
                        user_prompt="buat laporan pdf",
                        executed_tools=["generate_pdf_report"],
                    )
                    return True
            elif action == "excel" and parsed_table:
                from alfa.tools.data.office_suite import generate_excel_spreadsheet

                out_xlsx_name = f"Rekap_Resmi_{base_stem}.xlsx"
                res = generate_excel_spreadsheet(
                    filename=out_xlsx_name,
                    sheet_title="Rekap Dokumen",
                    headers_json=json.dumps(parsed_table[0], ensure_ascii=False),
                    rows_json=json.dumps(parsed_table[1:], ensure_ascii=False),
                )
                if res.get("status") == "success":
                    await safe_send_message(
                        context,
                        chat_id,
                        f"✅ **Spreadsheet Excel Baru Berhasil Dibuat (Instan 0-Token)**\n📊 Berkas: `{out_xlsx_name}`",
                    )
                    await check_artifacts_turn(
                        update,
                        context,
                        turn_start_time=turn_start_time,
                        user_prompt="buat excel",
                        executed_tools=["generate_excel_spreadsheet"],
                    )
                    return True
        except Exception as fast_err:
            logger.warning(f"[handle_doc_action_callback] Fast-builder fallback ke LLM: {fast_err}")

    # Pangkas txt_ctx jika terlalu besar agar putaran LLM tetap hemat token (<16 KB)
    if len(txt_ctx) > 16000:
        txt_ctx = (
            txt_ctx[:14000]
            + "\n\n...[tabel sampel dipangkas otomatis untuk penghematan token]..."
        )
    if summary_reply:
        txt_ctx = f"{txt_ctx}\n\n[HASIL ANALISIS DOKUMEN SEBELUMNYA]:\n{summary_reply}"

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
        reply = await run_agent_turn(
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
    await check_artifacts_turn(
        update, context, turn_start_time=turn_start_time, user_prompt=prompt
    )
    return True

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

        reply = await run_agent_turn(
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
            _save_recent_docs_cache()
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
                _save_recent_docs_cache()
    except _HANDLER_ERR as e:
        # Tanpa except ini, exception melompat keluar dari task -> asyncio diam-diam
        # membuangnya -> user upload dokumen dapat BALASAN KOSONG dan tombol
        # PDF/Excel tidak pernah muncul.
        logger.error(f"[_execute_document_batch] turn gagal untuk {user_id}: {e}", exc_info=True)
        reply = (
            "❌ Maaf, dokumennya gagal diproses "
            f"({type(e).__name__}: {str(e)[:200]}). "
            "Coba kirim ulang."
        )
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
        await check_artifacts_turn(
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
    if not is_authorized(user_id):
        await safe_send_message(context, chat_id, "⛔ Akses ditolak.")
        return

    doc = update.message.document
    if not doc:
        return

    caption = (update.message.caption or "").strip()
    file_name = doc.file_name or "file.bin"
    mime_type = doc.mime_type or "application/octet-stream"

    doc_bytes: bytes | None = None
    local_resolved_path: str = ""
    try:
        doc_file = await context.bot.get_file(doc.file_id)
        doc_bytes_io = io.BytesIO()
        await doc_file.download_to_memory(doc_bytes_io)
        doc_bytes = doc_bytes_io.getvalue()
        # Simpan salinan lokal di folder cache per-user agar tool REA / bash /
        # installer memiliki path fisik (folder privat mode 0700).
        upload_cache_dir = ensure_upload_cache_dir()
        safe_fname = os.path.basename(file_name)
        local_resolved_path = os.path.join(upload_cache_dir, safe_fname)
        with open(local_resolved_path, "wb") as uf:
            uf.write(doc_bytes)
    except Exception as e:
        logger.warning(f"[handle_document] Unduh cloud gagal untuk '{file_name}' ({e}); mencari di penyimpanan lokal...")
        # Fallback Cerdas: Cari berkas dengan nama yang sama di folder lokal laptop (Unduhan, Desktop, Dokumen, Home)
        search_roots = [
            os.path.expanduser("~/Unduhan"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Dokumen"),
            os.path.expanduser("~"),
            tempfile.gettempdir(),
        ]
        safe_fname = os.path.basename(file_name)
        # Hanya file yang BARU SAJA dibuat (user baru saja mengirimnya). Tanpa
        # batas waktu ini, bot bisa mengambil file pribadi tak berkaitan yang kebetulan
        # namanya sama dan memprosesnya.
        _fresh_cutoff = time.time() - 24 * 3600
        _candidates: list[tuple[float, str]] = []
        for sroot in search_roots:
            candidate = os.path.join(sroot, safe_fname)
            try:
                if os.path.isfile(candidate) and os.path.getmtime(candidate) >= _fresh_cutoff:
                    _candidates.append((os.path.getmtime(candidate), candidate))
            except OSError:
                continue
        if _candidates:
            # Ambil yang paling baru
            _candidates.sort(reverse=True)
            local_resolved_path = _candidates[0][1]

        if local_resolved_path:
            size_mb = round(os.path.getsize(local_resolved_path) / (1024 * 1024), 2)
            logger.info(
                f"[handle_document] Berkas '{file_name}' ({size_mb} MB) ditemukan di disk lokal: {local_resolved_path}"
            )
            await safe_send_message(
                context,
                chat_id,
                f"⚡ Berkas `{file_name}` (`{size_mb} MB` > batas 20MB Telegram Cloud) berhasil ditemukan langsung di disk lokal:\n`{local_resolved_path}`\nMemproses dengan mesin ALFA...",
            )
        else:
            logger.error(f"[handle_document] Gagal unduh file '{file_name}': {e}")
            await safe_send_message(
                context,
                chat_id,
                f"❌ Gagal mengunduh berkas `{file_name}` ({e}) dan berkas tidak ditemukan di folder `~/Unduhan` atau `~/Desktop`.",
            )
            return

    from alfa.tools.filesystem import universal_file_extractor as ufe

    txt_ctx: str = ""
    part = None
    if doc_bytes is not None:
        try:
            raw_ctx, part = ufe.process_uploaded_attachment(file_name, mime_type, doc_bytes)
            txt_ctx = str(raw_ctx or "")
        except Exception as e:
            logger.warning(f"[handle_document] Gagal ekstraksi '{file_name}': {e}")
            txt_ctx, part = "", None

    if local_resolved_path:
        path_header = (
            f"[LOCAL_DISK_PATH: {local_resolved_path}]\n"
            f"(Gunakan path `{local_resolved_path}` ini secara langsung jika perlu memanggil tool REA seperti "
            f"`rea_clone_and_build_app`, `rea_synthesize_skill_from_code`, `rea_inspect_binary_or_wasm`, atau `execute_bash_command`).\n"
        )
        txt_ctx = f"{path_header}\n{txt_ctx}".strip()

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
