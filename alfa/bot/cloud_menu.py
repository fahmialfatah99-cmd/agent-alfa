"""Interactive Google Sheets & Google Drive UI for Telegram Bot.

Provides intuitive inline menus, tab previews, and cloud/local file browsing.
Callback schema: cx|<domain>|<action>|<arg1>|<arg2>... (strict <= 64 bytes)
"""

import datetime
import logging
import os
import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, RetryAfter
from telegram.ext import ContextTypes

from alfa.bot.config import is_authorized
from alfa.bot.helpers import safe_send_message
from alfa.integrations import google_sheets
from alfa.integrations.gdrive import (
    gdrive_list_files,
    gdrive_list_mounted_files,
    gdrive_status,
)

logger = logging.getLogger("TelegramAIAgent.CloudMenu")

_PAGE_ITEMS = 6
_PAGE_TABS = 8

# Cache per user to store objects and use short numeric indices for callbacks
_CACHE: dict[int, dict[str, Any]] = {}
_CACHE_TTL = 300.0  # 5 minutes


def _is_authed(user_id: int) -> bool:
    return is_authorized(user_id)


def _cache_get(user_id: int, key: str, default: Any = None) -> Any:
    slot = _CACHE.get(user_id)
    if not slot or time.monotonic() - slot.get("ts", 0) > _CACHE_TTL:
        return default if default is not None else []
    return slot.get(key, default if default is not None else [])


def _cache_put(user_id: int, key: str, value: Any) -> None:
    slot = _CACHE.get(user_id) or {"ts": time.monotonic()}
    slot[key] = value
    slot["ts"] = time.monotonic()
    _CACHE[user_id] = slot


def _fmt_size(num_bytes: int | float) -> str:
    if not num_bytes or num_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def _fmt_time(ts_str: str) -> str:
    if not ts_str:
        return "-"
    try:
        # ISO timestamp 2026-10-20T19:01:24.957Z
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean)
        return dt.strftime("%d/%m/%y %H:%M")
    except Exception:
        return ts_str[:16].replace("T", " ")


def _esc(text: str) -> str:
    if not text:
        return ""
    # Escape Markdown v1 chars
    for ch in ["_", "*", "`", "[", "]"]:
        text = text.replace(ch, f"\\{ch}")
    return text


def _nav_row(prefix: str, page: int, total_pages: int, extra: str = "") -> list[InlineKeyboardButton]:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"cx|{prefix}|{page - 1}{extra}"))
    row.append(InlineKeyboardButton(f"{page + 1}/{max(1, total_pages)}", callback_data="cx|noop"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("▶️", callback_data=f"cx|{prefix}|{page + 1}{extra}"))
    return row


async def _edit_or_send(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    if query:
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="Markdown")
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
        except RetryAfter:
            return
        except Exception:
            pass

    await safe_send_message(context, chat_id, text, reply_markup=markup)


# ---------------------------------------------------------------------------
# Cloud Hub (Unified Sheets & Drive)
# ---------------------------------------------------------------------------


async def render_cloud_hub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render unified Google Cloud Hub (Sheets & Drive)."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    sid = google_sheets.get_spreadsheet_id()

    # Sheets summary
    sheets_title = "Tidak Terhubung"
    tabs_count = 0
    if sid:
        try:
            meta = google_sheets.get_spreadsheet_metadata(sid)
            if meta.get("status") == "success":
                sheets_title = meta.get("title", "-")
                tabs_count = meta.get("total_tabs", 0)
        except Exception:
            pass

    # Drive summary
    drive_conn = "🔴 Mati"
    drive_user = "-"
    try:
        dst = gdrive_status()
        if dst.get("status") == "success" and dst.get("connected"):
            drive_conn = "🟢 Terhubung"
            drive_user = dst.get("user", {}).get("displayName") or dst.get("user", {}).get("emailAddress", "OK")
    except Exception:
        pass

    text = (
        "☁️ **Google Cloud Services Agent**\n\n"
        "Integrasi aktif Google Sheets & Google Drive dengan Agent ALFA:\n\n"
        f"📊 **Google Sheets Aktif:**\n"
        f"• Judul: `{_esc(sheets_title)}`\n"
        f"• Total Tab: `{tabs_count} tab`\n"
        f"• ID: `{sid[:14]}...`\n\n"
        f"📁 **Google Drive Cloud:**\n"
        f"• Status: {drive_conn}\n"
        f"• Akun: `{_esc(drive_user[:35])}`\n"
        f"• Mount Lokal: `GDrive1` (Aktif 🟢)\n\n"
        "Pilih layanan di bawah untuk melihat file dan isi data:"
    )

    kb = [
        [
            InlineKeyboardButton("📊 Buka Google Sheets", callback_data="cx|sh|home"),
            InlineKeyboardButton("📁 Buka Google Drive", callback_data="cx|dr|home"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh Status", callback_data="cx|hub"),
            InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu"),
        ],
    ]

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


# ---------------------------------------------------------------------------
# Google Sheets UI
# ---------------------------------------------------------------------------


async def render_sheets_home(
    update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
) -> None:
    """Render Google Sheets viewer home: current spreadsheet, status, and worksheets list."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    sid = google_sheets.get_spreadsheet_id()
    if not sid:
        text = (
            "📊 **Google Sheets Belum Terhubung**\n\n"
            "Agent belum memiliki Spreadsheet ID aktif.\n"
            "Gunakan perintah:\n"
            "`/setsheet <Link_atau_ID_Spreadsheet>`"
        )
        kb = [[InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")]]
        await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))
        return

    meta = google_sheets.get_spreadsheet_metadata(sid)
    if meta.get("status") != "success":
        err_msg = meta.get("message", "Akses ditolak")
        text = (
            f"⚠️ **Gagal Mengakses Google Sheets**\n\n"
            f"• **ID:** `{sid}`\n"
            f"• **Pesan:** {err_msg}\n\n"
            "Pastikan Service Account memiliki hak akses **Editor**."
        )
        kb = [
            [InlineKeyboardButton("🔄 Coba Lagi", callback_data="cx|sh|home")],
            [InlineKeyboardButton("📚 Cari Sheet Lain", callback_data="cx|sh|all|0")],
            [InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")],
        ]
        await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))
        return

    title = meta.get("title", "Spreadsheet")
    url = meta.get("url", f"https://docs.google.com/spreadsheets/d/{sid}/edit")
    tabs = meta.get("tabs", [])
    _cache_put(user_id, "sheet_tabs", tabs)
    _cache_put(user_id, "current_sid", sid)

    total_tabs = len(tabs)
    pages = max(1, (total_tabs + _PAGE_TABS - 1) // _PAGE_TABS)
    page = max(0, min(page, pages - 1))
    chunk = tabs[page * _PAGE_TABS : page * _PAGE_TABS + _PAGE_TABS]

    text = (
        f"📊 **Google Sheets Agent: {_esc(title)}**\n"
        f"• **Status:** Terhubung 🟢\n"
        f"• **ID:** `{sid}`\n"
        f"• **Jumlah Tab:** `{total_tabs} lembar kerja`\n\n"
        "Pilih tab di bawah untuk melihat rincian & isi data terkini:"
    )

    kb = []
    # Grid 2 columns for tabs
    row = []
    for i, t in enumerate(chunk):
        idx = page * _PAGE_TABS + i
        tname = t.get("title", f"Tab {idx+1}")
        label = f"📋 {_esc(tname[:16])}"
        row.append(InlineKeyboardButton(label, callback_data=f"cx|sh|t|{idx}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    if pages > 1:
        kb.append(_nav_row("sh|h", page, pages))

    kb.append([
        InlineKeyboardButton("🌐 Buka di Browser", url=url),
        InlineKeyboardButton("🔄 Refresh", callback_data="cx|sh|home"),
    ])
    kb.append([
        InlineKeyboardButton("📚 Semua File Sheets", callback_data="cx|sh|all|0"),
        InlineKeyboardButton("📁 Google Drive", callback_data="cx|dr|home"),
    ])
    kb.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")])

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


async def render_tab_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE, tab_idx: int
) -> None:
    """Preview contents, headers, and recent rows of a chosen sheet tab."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    tabs = _cache_get(user_id, "sheet_tabs")
    sid = _cache_get(user_id, "current_sid") or google_sheets.get_spreadsheet_id()

    if not tabs or not (0 <= tab_idx < len(tabs)):
        await render_sheets_home(update, context, 0)
        return

    tab_meta = tabs[tab_idx]
    tab_name = tab_meta.get("title", "")

    preview = google_sheets.get_tab_preview(spreadsheet_id=sid, tab_name=tab_name, limit=6)
    if preview.get("status") != "success":
        await _edit_or_send(
            query,
            context,
            chat_id,
            f"⚠️ {preview.get('message', 'Gagal memuat tab.')}",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Kembali", callback_data="cx|sh|home")]]),
        )
        return

    total_rows = preview.get("total_rows", 0)
    data_count = preview.get("data_rows_count", 0)
    headers = preview.get("headers", [])
    recent_rows = preview.get("recent_rows", [])
    tab_url = preview.get("url") or f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid={preview.get('sheet_id')}"

    # Format headers summary
    hdrs_clean = [str(h).strip() for h in headers if str(h).strip()]
    hdrs_str = " | ".join(hdrs_clean[:6])
    if len(hdrs_clean) > 6:
        hdrs_str += f" (+{len(hdrs_clean) - 6} kolom)"

    # Format recent data rows
    entries_lines = []
    for r_idx, r in enumerate(recent_rows):
        vals = [str(v).strip() for v in r if str(v).strip()]
        if not vals:
            continue
        # Truncate and show top fields
        entry_preview = " • ".join(vals[:4])
        if len(entry_preview) > 100:
            entry_preview = entry_preview[:97] + "..."
        entries_lines.append(f"`{r_idx + 1}.` {_esc(entry_preview)}")

    entries_text = "\n".join(entries_lines) if entries_lines else "_(Belum ada baris data)_"

    text = (
        f"📋 **Tab Sheets: {_esc(tab_name)}**\n"
        f"• **Spreadsheet:** `{_esc(preview.get('spreadsheet_title', '-'))}`\n"
        f"• **Total Baris:** `{total_rows}` (Data: `{data_count}` baris)\n"
        f"• **Kolom ({len(headers)}):**\n`{_esc(hdrs_str or '-')}`\n\n"
        f"📌 **Data Terbaru (5-6 baris terakhir):**\n"
        f"{entries_text}\n"
    )

    kb = [
        [InlineKeyboardButton("🌐 Buka Tab Ini di Sheets", url=tab_url)],
        [
            InlineKeyboardButton("🔄 Refresh Tab", callback_data=f"cx|sh|t|{tab_idx}"),
            InlineKeyboardButton("◀️ Daftar Tab", callback_data="cx|sh|home"),
        ],
        [InlineKeyboardButton("🏠 Menu Sheets", callback_data="cx|sh|home")],
    ]

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


async def render_all_sheets(
    update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0
) -> None:
    """List all spreadsheet files discovered in Google Drive & local mount."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    all_sheets = google_sheets.list_accessible_spreadsheets()
    _cache_put(user_id, "all_sheets", all_sheets)

    if not all_sheets:
        kb = [[InlineKeyboardButton("◀️ Kembali", callback_data="cx|sh|home")]]
        await _edit_or_send(
            query, context, chat_id, "📊 Tidak ada file spreadsheet ditemukan.", InlineKeyboardMarkup(kb)
        )
        return

    pages = max(1, (len(all_sheets) + _PAGE_ITEMS - 1) // _PAGE_ITEMS)
    page = max(0, min(page, pages - 1))
    chunk = all_sheets[page * _PAGE_ITEMS : page * _PAGE_ITEMS + _PAGE_ITEMS]

    text = (
        f"📚 **Daftar Seluruh Spreadsheet ({len(all_sheets)} file)**\n"
        "File Google Sheets di Cloud Drive & Spreadsheet lokal:\n"
    )

    kb = []
    for i, item in enumerate(chunk):
        idx = page * _PAGE_ITEMS + i
        active_tag = " [AKTIF 🟢]" if item.get("is_active") else ""
        src_icon = "💾" if item.get("source") == "local" else "📊"
        name = _esc(item.get("title", "Sheet")[:25])
        label = f"{src_icon} {name}{active_tag}"
        kb.append([InlineKeyboardButton(label, callback_data=f"cx|sh|sel|{idx}")])

    if pages > 1:
        kb.append(_nav_row("sh|all", page, pages))

    kb.append([
        InlineKeyboardButton("🔄 Refresh", callback_data="cx|sh|all|0"),
        InlineKeyboardButton("◀️ Kembali ke Sheets", callback_data="cx|sh|home"),
    ])

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


async def render_sheet_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int
) -> None:
    """Detail view of a specific spreadsheet selected from the all-sheets list."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    all_sheets = _cache_get(user_id, "all_sheets")
    if not all_sheets or not (0 <= idx < len(all_sheets)):
        await render_all_sheets(update, context, 0)
        return

    target = all_sheets[idx]
    is_active = target.get("is_active", False)
    title = target.get("title", "-")
    sid = target.get("id", "-")
    source = target.get("source", "Drive")
    url = target.get("url", "")
    is_local = target.get("is_local", False)

    status_tag = "Aktif Digunakan Agent 🟢" if is_active else "Bukan Sheet Aktif"

    text = (
        f"📊 **Informasi File Spreadsheet**\n\n"
        f"• **Nama:** `{_esc(title)}`\n"
        f"• **Sumber:** `{source}`\n"
        f"• **Status:** {status_tag}\n"
        f"• **Identifier:**\n`{_esc(sid)}`\n"
    )

    kb = []
    if url and not is_local:
        kb.append([InlineKeyboardButton("🌐 Buka di Google Sheets", url=url)])

    if not is_active and not is_local and len(sid) > 15:
        kb.append([InlineKeyboardButton("⭐ Jadikan Sheet Aktif Agent", callback_data=f"cx|sh|set|{idx}")])

    kb.append([
        InlineKeyboardButton("◀️ Daftar Semua Sheet", callback_data="cx|sh|all|0"),
        InlineKeyboardButton("🏠 Menu Sheets", callback_data="cx|sh|home"),
    ])

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


# ---------------------------------------------------------------------------
# Google Drive UI
# ---------------------------------------------------------------------------


async def render_drive_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Render Google Drive main hub: connection status, accounts, and folders/mounts."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0

    st = gdrive_status()
    is_conn = st.get("status") == "success" and st.get("connected")
    status_tag = "🟢 Terhubung" if is_conn else "🔴 Belum Terhubung"

    user_info = st.get("user", {})
    account_email = user_info.get("emailAddress") or user_info.get("displayName") or "Service Account"
    auth_mode = st.get("auth_mode", "service_account")

    def_folder = st.get("default_folder_name", "alfa agent")
    def_folder_url = st.get("default_folder_url", "")

    # Mounted drives
    mounts = st.get("mounted_drives", [])
    mounts_str = []
    for m in mounts:
        active_tag = "🟢" if m.get("active") else "⚪"
        mounts_str.append(f"• {active_tag} **{m.get('name')}:** `{m.get('items_count', 0)} item`")
    mounts_desc = "\n".join(mounts_str) if mounts_str else "• Tidak ada folder lokal ter-mount"

    text = (
        "📁 **Google Drive Agent Explorer**\n\n"
        f"• **Status Koneksi:** {status_tag}\n"
        f"• **Akun Terhubung:** `{_esc(account_email[:35])}`\n"
        f"• **Mode Autentikasi:** `{auth_mode}`\n"
        f"• **Folder Default Cloud:** `{_esc(def_folder)}`\n\n"
        f"💾 **Drive Lokal (Mount Rclone / Fuse):**\n"
        f"{mounts_desc}\n\n"
        "Pilih salah satu explorer untuk melihat dan menjelajahi file:"
    )

    kb = [
        [InlineKeyboardButton("☁️ Jelajahi Cloud Drive (API)", callback_data="cx|dr|c|0|all")],
        [
            InlineKeyboardButton("💾 GDrive1 (Lokal)", callback_data="cx|dr|m|1|0|0"),
            InlineKeyboardButton("💾 GDrive2 (Lokal)", callback_data="cx|dr|m|2|0|0"),
        ],
        [
            InlineKeyboardButton("📊 Buka Google Sheets", callback_data="cx|sh|home"),
            InlineKeyboardButton("🔄 Refresh", callback_data="cx|dr|home"),
        ],
    ]
    if def_folder_url:
        kb.insert(1, [InlineKeyboardButton(f"🌐 Buka Folder '{def_folder}' di Web", url=def_folder_url)])

    kb.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")])

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


def _get_file_icon(mime: str, is_dir: bool = False, name: str = "") -> str:
    if is_dir or mime == "application/vnd.google-apps.folder":
        return "📁"
    name_l = name.lower()
    if "spreadsheet" in mime or name_l.endswith((".xlsx", ".xls", ".csv")):
        return "📊"
    if "document" in mime or name_l.endswith((".docx", ".doc", ".txt", ".md")):
        return "📝"
    if "pdf" in mime or name_l.endswith(".pdf"):
        return "📄"
    if "image" in mime or name_l.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "🖼️"
    if "audio" in mime or name_l.endswith((".mp3", ".ogg", ".wav", ".m4a")):
        return "🎵"
    if "video" in mime or name_l.endswith((".mp4", ".mkv", ".mov")):
        return "🎥"
    if "zip" in mime or "rar" in mime or name_l.endswith((".zip", ".rar", ".tar", ".gz")):
        return "📦"
    return "📄"


async def render_cloud_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    folder_ref: str = "all",
) -> None:
    """Browse files and folders inside Google Drive Cloud via API."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    # Resolve folder ID from cache if numeric index
    folder_id = folder_ref
    folder_name = "Cloud Drive"
    if folder_ref.isdigit():
        folder_cache = _cache_get(user_id, "folder_cache", {})
        cached_info = folder_cache.get(int(folder_ref), {})
        folder_id = cached_info.get("id", "all")
        folder_name = cached_info.get("name", "Folder")
    elif folder_ref == "all":
        folder_name = "Semua File Cloud"

    res = gdrive_list_files(folder_id=folder_id, limit=50)
    if res.get("status") != "success":
        await _edit_or_send(
            query,
            context,
            chat_id,
            f"⚠️ {res.get('message', 'Gagal membaca isi Google Drive.')}",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Kembali", callback_data="cx|dr|home")]]),
        )
        return

    files = res.get("files", [])
    _cache_put(user_id, "cloud_files", files)
    _cache_put(user_id, "current_cloud_folder_ref", folder_ref)

    if not files:
        kb = []
        if folder_ref != "all":
            kb.append([InlineKeyboardButton("⬆️ Folder Atas", callback_data="cx|dr|c|0|all")])
        kb.append([InlineKeyboardButton("🏠 Menu Drive", callback_data="cx|dr|home")])
        await _edit_or_send(
            query,
            context,
            chat_id,
            f"📁 **Folder: {_esc(folder_name)}**\n\n_(Folder kosong / tidak ada file)_",
            InlineKeyboardMarkup(kb),
        )
        return

    pages = max(1, (len(files) + _PAGE_ITEMS - 1) // _PAGE_ITEMS)
    page = max(0, min(page, pages - 1))
    chunk = files[page * _PAGE_ITEMS : page * _PAGE_ITEMS + _PAGE_ITEMS]

    text = (
        f"☁️ **Google Drive: {_esc(folder_name)}**\n"
        f"Ditemukan `{len(files)} item` (Halaman {page + 1}/{pages}):\n"
        "Ketuk file untuk lihat detail atau folder untuk membuka isinya:"
    )

    kb = []
    # Build folder cache to keep callbacks short
    folder_cache = _cache_get(user_id, "folder_cache", {})
    next_fidx = len(folder_cache)

    for i, f in enumerate(chunk):
        idx = page * _PAGE_ITEMS + i
        fname = f.get("name", "Unnamed")
        mime = f.get("mimeType", "")
        is_folder = mime == "application/vnd.google-apps.folder"
        icon = _get_file_icon(mime, is_dir=is_folder, name=fname)

        if is_folder:
            fidx = next_fidx
            folder_cache[fidx] = {"id": f.get("id"), "name": fname}
            next_fidx += 1
            kb.append([InlineKeyboardButton(f"{icon} {_esc(fname[:26])}", callback_data=f"cx|dr|c|0|{fidx}")])
        else:
            kb.append([InlineKeyboardButton(f"{icon} {_esc(fname[:26])}", callback_data=f"cx|dr|f|{idx}")])

    _cache_put(user_id, "folder_cache", folder_cache)

    if pages > 1:
        kb.append(_nav_row("dr|c", page, pages, f"|{folder_ref}"))

    bottom_row = []
    if folder_ref != "all":
        bottom_row.append(InlineKeyboardButton("⬆️ Root/Semua", callback_data="cx|dr|c|0|all"))
    bottom_row.append(InlineKeyboardButton("🏠 Menu Drive", callback_data="cx|dr|home"))
    kb.append(bottom_row)

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


async def render_cloud_file_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE, file_idx: int
) -> None:
    """Detail view of a specific cloud file with direct open link."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    files = _cache_get(user_id, "cloud_files")
    folder_ref = _cache_get(user_id, "current_cloud_folder_ref", "all")

    if not files or not (0 <= file_idx < len(files)):
        await render_cloud_files(update, context, 0, folder_ref)
        return

    f = files[file_idx]
    fname = f.get("name", "File")
    mime = f.get("mimeType", "-")
    fid = f.get("id", "-")
    size_str = _fmt_size(int(f.get("size", 0)))
    mod_time = _fmt_time(f.get("modifiedTime", ""))
    url = f.get("webViewLink") or f.get("webContentLink") or ""
    icon = _get_file_icon(mime, name=fname)

    text = (
        f"{icon} **Detail File Cloud Google Drive**\n\n"
        f"• **Nama:** `{_esc(fname)}`\n"
        f"• **Tipe:** `{_esc(mime)}`\n"
        f"• **Ukuran:** `{size_str}`\n"
        f"• **Terakhir Diubah:** `{mod_time}`\n"
        f"• **File ID:**\n`{_esc(fid)}`\n"
    )

    kb = []
    if url:
        kb.append([InlineKeyboardButton("🌐 Buka di Google Drive", url=url)])

    # If it's a spreadsheet, offer to open in Sheets viewer directly!
    if mime == "application/vnd.google-apps.spreadsheet":
        kb.append([InlineKeyboardButton("📊 Buka di Sheets Viewer", callback_data="cx|sh|home")])

    kb.append([
        InlineKeyboardButton("◀️ Kembali ke File", callback_data=f"cx|dr|c|0|{folder_ref}"),
        InlineKeyboardButton("🏠 Menu Drive", callback_data="cx|dr|home"),
    ])

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


async def render_mounted_drive_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    drive_idx: int = 1,
    subpath_idx: int = 0,
    page: int = 0,
) -> None:
    """Browse locally mounted Google Drive folders (e.g. ~/GDrive1)."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    # Resolve subpath from cache
    mount_cache = _cache_get(user_id, f"mount_cache_{drive_idx}", {})
    subpath = mount_cache.get(subpath_idx, "")

    res = gdrive_list_mounted_files(drive_index=drive_idx, subpath=subpath, limit=60)
    if res.get("status") != "success":
        await _edit_or_send(
            query,
            context,
            chat_id,
            f"⚠️ {res.get('message', 'Direktori tidak dapat dibaca.')}",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Kembali", callback_data="cx|dr|home")]]),
        )
        return

    files = res.get("files", [])
    _cache_put(user_id, f"mounted_files_{drive_idx}", files)
    _cache_put(user_id, f"current_mount_subpath_idx_{drive_idx}", subpath_idx)

    display_path = f"~/GDrive{drive_idx}/{subpath}".rstrip("/") if subpath else f"~/GDrive{drive_idx}"

    if not files:
        kb = []
        if subpath:
            parent_subpath = os.path.dirname(subpath)
            p_idx = len(mount_cache)
            mount_cache[p_idx] = parent_subpath
            _cache_put(user_id, f"mount_cache_{drive_idx}", mount_cache)
            kb.append([InlineKeyboardButton("⬆️ Folder Atas", callback_data=f"cx|dr|m|{drive_idx}|{p_idx}|0")])
        kb.append([InlineKeyboardButton("🏠 Menu Drive", callback_data="cx|dr|home")])
        await _edit_or_send(
            query,
            context,
            chat_id,
            f"💾 **Mount: `{_esc(display_path)}`**\n\n_(Folder kosong)_",
            InlineKeyboardMarkup(kb),
        )
        return

    pages = max(1, (len(files) + _PAGE_ITEMS - 1) // _PAGE_ITEMS)
    page = max(0, min(page, pages - 1))
    chunk = files[page * _PAGE_ITEMS : page * _PAGE_ITEMS + _PAGE_ITEMS]

    text = (
        f"💾 **Mount: `{_esc(display_path)}`**\n"
        f"Total: `{len(files)} item` (Halaman {page + 1}/{pages}):\n"
        "Ketuk untuk membuka subfolder atau melihat rincian file:"
    )

    kb = []
    next_pidx = len(mount_cache)

    for i, item in enumerate(chunk):
        name = item.get("name", "-")
        is_dir = item.get("is_dir", False)
        icon = _get_file_icon("", is_dir=is_dir, name=name)
        size_lbl = f" ({_fmt_size(item.get('size', 0))})" if not is_dir else ""

        if is_dir:
            dir_sub = os.path.join(subpath, name) if subpath else name
            dir_idx = next_pidx
            mount_cache[dir_idx] = dir_sub
            next_pidx += 1
            kb.append([
                InlineKeyboardButton(
                    f"{icon} {_esc(name[:24])}",
                    callback_data=f"cx|dr|m|{drive_idx}|{dir_idx}|0",
                )
            ])
        else:
            file_idx = page * _PAGE_ITEMS + i
            kb.append([
                InlineKeyboardButton(
                    f"{icon} {_esc(name[:22])}{size_lbl}",
                    callback_data=f"cx|dr|mf|{drive_idx}|{file_idx}",
                )
            ])

    _cache_put(user_id, f"mount_cache_{drive_idx}", mount_cache)

    if pages > 1:
        kb.append(_nav_row(f"dr|m|{drive_idx}|{subpath_idx}", page, pages))

    nav_row_btns = []
    if subpath:
        parent_sub = os.path.dirname(subpath)
        p_idx = next_pidx
        mount_cache[p_idx] = parent_sub
        _cache_put(user_id, f"mount_cache_{drive_idx}", mount_cache)
        nav_row_btns.append(InlineKeyboardButton("⬆️ Folder Atas", callback_data=f"cx|dr|m|{drive_idx}|{p_idx}|0"))
    nav_row_btns.append(InlineKeyboardButton("🏠 Menu Drive", callback_data="cx|dr|home"))
    kb.append(nav_row_btns)

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


async def render_mounted_file_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE, drive_idx: int, file_idx: int
) -> None:
    """Detail view of a local mounted file."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    files = _cache_get(user_id, f"mounted_files_{drive_idx}")
    subpath_idx = _cache_get(user_id, f"current_mount_subpath_idx_{drive_idx}", 0)

    if not files or not (0 <= file_idx < len(files)):
        await render_mounted_drive_files(update, context, drive_idx, subpath_idx, 0)
        return

    f = files[file_idx]
    fname = f.get("name", "File")
    fpath = f.get("path", "")
    size_str = _fmt_size(f.get("size", 0))
    icon = _get_file_icon("", is_dir=False, name=fname)

    text = (
        f"{icon} **Detail File Mount Lokal: GDrive{drive_idx}**\n\n"
        f"• **Nama File:** `{_esc(fname)}`\n"
        f"• **Ukuran:** `{size_str}`\n"
        f"• **Path:**\n`{_esc(fpath)}`\n\n"
        "💡 _File ini tersinkronisasi otomatis via rclone/mount ke Google Drive cloud._"
    )

    kb = [
        [
            InlineKeyboardButton("◀️ Kembali ke Folder", callback_data=f"cx|dr|m|{drive_idx}|{subpath_idx}|0"),
            InlineKeyboardButton("🏠 Menu Drive", callback_data="cx|dr|home"),
        ]
    ]

    await _edit_or_send(query, context, chat_id, text, InlineKeyboardMarkup(kb))


# ---------------------------------------------------------------------------
# Callback Router cx|*
# ---------------------------------------------------------------------------


async def handle_cloud_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Router callback cx|*. Return True if handled."""
    query = update.callback_query
    if not query:
        return False
    data = query.data or ""
    if not data.startswith("cx|"):
        return False

    user_id = update.effective_user.id if update.effective_user else 0
    if not _is_authed(user_id):
        await query.answer()
        return True

    await query.answer()
    parts = data.split("|")
    domain = parts[1] if len(parts) > 1 else ""

    try:
        # Cloud Hub
        if domain == "hub":
            await render_cloud_hub(update, context)
            return True

        # Google Sheets domain
        if domain == "sh":
            action = parts[2] if len(parts) > 2 else "home"
            if action == "home":
                await render_sheets_home(update, context, 0)
            elif action == "h":
                page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                await render_sheets_home(update, context, page)
            elif action == "t":
                tidx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                await render_tab_detail(update, context, tidx)
            elif action == "all":
                page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                await render_all_sheets(update, context, page)
            elif action == "sel":
                sidx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                await render_sheet_selection(update, context, sidx)
            elif action == "set":
                sidx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                all_sheets = _cache_get(user_id, "all_sheets")
                if all_sheets and 0 <= sidx < len(all_sheets):
                    target_id = all_sheets[sidx].get("id", "")
                    google_sheets.set_spreadsheet_id(target_id)
                await render_sheets_home(update, context, 0)
            return True

        # Google Drive domain
        if domain == "dr":
            action = parts[2] if len(parts) > 2 else "home"
            if action == "home":
                await render_drive_home(update, context)
            elif action == "c":
                page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                folder_ref = parts[4] if len(parts) > 4 else "all"
                await render_cloud_files(update, context, page, folder_ref)
            elif action == "f":
                fidx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                await render_cloud_file_detail(update, context, fidx)
            elif action == "m":
                didx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
                spidx = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
                page = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
                await render_mounted_drive_files(update, context, didx, spidx, page)
            elif action == "mf":
                didx = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
                fidx = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
                await render_mounted_file_detail(update, context, didx, fidx)
            return True

        if domain == "noop":
            pass

    except Exception as e:
        logger.warning(f"[cloud_menu] Callback error for '{data}': {e}")

    return True


# ---------------------------------------------------------------------------
# Slash Commands (/sheets, /gdrive, /cloud)
# ---------------------------------------------------------------------------


async def sheets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sheets or /sheet command to open Google Sheets UI."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not _is_authed(user_id):
        return
    await render_sheets_home(update, context, 0)


async def drive_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /drive or /gdrive command to open Google Drive UI."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not _is_authed(user_id):
        return
    await render_drive_home(update, context)


async def cloud_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cloud command to open unified Google Cloud Hub."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not _is_authed(user_id):
        return
    await render_cloud_hub(update, context)


__all__ = [
    "cloud_command",
    "drive_command",
    "handle_cloud_callback",
    "render_cloud_files",
    "render_cloud_hub",
    "render_drive_home",
    "render_sheets_home",
    "render_tab_detail",
    "sheets_command",
]
