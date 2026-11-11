"""Perintah WhatsApp (/wa, /wachat, /wamasuk, /wakirim, ...)."""
from __future__ import annotations

import json
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.advanced_commands._common import _ADV_ERR
from alfa.bot.advanced_commands._compat import is_authorized, safe_send_message

logger = logging.getLogger("TelegramAIAgent")

def _wa_esc(text: str) -> str:
    """Netralkan karakter Markdown yang rentan merusak entity parse Telegram."""
    return (
        str(text or "")
        .replace("`", "'")
        .replace("*", "")
        .replace("_", " ")
        .replace("[", "(")
        .replace("]", ")")
    )

def _wa_time(ts: int) -> str:
    try:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(int(ts)).strftime("%d/%m %H:%M")
    except (ValueError, TypeError, OSError):
        return ""

def _wa_time_iso(ts: str) -> str:
    """Format ISO UTC (2026-10-14T14:16:22) -> lokal '14/10 21:16'."""
    try:
        import datetime as _dt

        s = str(ts or "").replace("Z", "+00:00")
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone().strftime("%d/%m %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts or "")[:16]

_WA_TYPE_ICON = {
    "chat": "💬",
    "image": "🖼️",
    "video": "🎥",
    "audio": "🔊",
    "ptt": "🎤",
    "document": "📄",
    "sticker": "🌟",
    "location": "📍",
    "vcard": "👤",
    "call_log": "📞",
}

def _wa_sender(it: dict) -> str:
    """Nama pengirim: sender_name > author > chat, tanpa JID mentah bila ada nama."""
    name = (it.get("sender_name") or "").strip()
    if name:
        return _wa_esc(name)
    for key in ("author", "chat", "sender"):
        raw = str(it.get(key) or "")
        if raw:
            num = raw.split("@")[0].split(":")[0]
            return num[-4:] if num.isdigit() and len(num) > 8 else (num or "?")
    return "?"

def _wa_not_ready(res: dict) -> str | None:
    if isinstance(res, dict) and res.get("status") == "error":
        return res.get("message") or "WA error."
    return None

async def wa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wa or /washeets command to control WhatsApp Google Sheets Bot."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    res = tools.manage_wa_sheets_bot("status")
    is_running = res.get("is_running", False)
    status_icon = "🟢 RUNNING (Aktif)" if is_running else "🔴 STOPPED (Mati)"

    # URL dashboard: pakai network_url (IP LAN) — Telegram menolak URL localhost.
    dash_url = ""
    try:
        dash_url = (tools.open_web_dashboard(port=8080).get("network_url") or "")
    except _ADV_ERR:
        dash_url = ""

    wa_auth_status = "UNKNOWN"
    qr_str = ""
    qr_data_url = None

    # Ambil live QR segar langsung dari HTTP API wa-sheets-bot
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:3000/api/qr?refresh=1",
            headers={"User-Agent": "ALFA-Bot"},
        )
        # URL hardcoded localhost terpercaya (wa-sheets-bot), timeout diset
        with urllib.request.urlopen(req, timeout=4.0) as resp:  # nosec B310 — 127.0.0.1 hardcoded
            data = json.loads(resp.read().decode())
            wa_auth_status = data.get("status", "UNKNOWN")
            qr_str = data.get("qr_string", "")
            qr_data_url = data.get("qr_data_url")
    except Exception:
        # Fallback ke cache file lokal jika HTTP API belum merespons
        status_file = os.path.expanduser("~/.alfa/wa_status.json")
        if os.path.exists(status_file):
            try:
                with open(status_file) as f:
                    wa_data = json.load(f)
                wa_auth_status = wa_data.get("status", "UNKNOWN")
                qr_str = wa_data.get("qr", "")
            except (OSError, ValueError, TypeError):
                pass

    keyboard = [
        [
            InlineKeyboardButton("💬 Riwayat Chat", callback_data="wx|chats|0"),
            InlineKeyboardButton("📥 Pesan Masuk", callback_data="wx|in|0"),
        ],
        [
            InlineKeyboardButton("📦 Rekap Material Lahat", callback_data="btn_rekap_lahat"),
            InlineKeyboardButton("📋 Format Catatan", callback_data="wx|fmt"),
        ],
        [
            InlineKeyboardButton("📊 Status Koneksi WA", callback_data="btn_wa_status"),
            InlineKeyboardButton("📊 Laporan Masuk", callback_data="wx|rep|0|-1"),
        ],
        [
            InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu"),
        ],
    ]
    if dash_url and not dash_url.startswith("http://localhost"):
        keyboard.insert(
            len(keyboard) - 1, [InlineKeyboardButton("🌐 Buka Web Dashboard", url=dash_url)]
        )
    reply_markup = InlineKeyboardMarkup(keyboard)

    if wa_auth_status in ("READY", "AUTHENTICATED"):
        auth_desc = "✅ Terhubung (Logged In)"
    elif wa_auth_status == "INITIALIZING":
        auth_desc = "⏳ Menyiapkan QR Code baru..."
    elif wa_auth_status == "QR_READY":
        auth_desc = "⚠️ Menunggu Scan QR Code"
    else:
        auth_desc = f"⚠️ {wa_auth_status} (Perlu Scan QR)"

    text = (
        f"📱 **Manajer WhatsApp Google Sheets Bot:**\n\n"
        f"• **Status Layanan:** {status_icon}\n"
        f"• **Status Akun WA:** `{auth_desc}`\n"
        f"• **Auto-Start Saat Boot/Internet:** `{'Aktif 🟢' if res.get('enabled_on_boot') else 'Nonaktif 🔴'}`\n"
        f"• **Service Name:** `wa-sheets-bot.service`\n\n"
        f"✉️ Kirim pesan via `/wakirim <nomor|nama grup> <pesan>`.\n"
        f"💡 _Bot WhatsApp ini otomatis aktif saat laptop online dan diawasi 24/7 oleh Ecosystem Watchdog._"
    )

    if (wa_auth_status == "QR_READY" or qr_str or qr_data_url) and wa_auth_status not in ("READY", "AUTHENTICATED"):
        try:
            import base64
            import io

            buf = io.BytesIO()
            if qr_data_url and "base64," in qr_data_url:
                raw_b64 = qr_data_url.split("base64,")[1]
                buf.write(base64.b64decode(raw_b64))
            elif qr_str:
                import qrcode
                img = qrcode.make(qr_str)
                img.save(buf, format="PNG")

            if buf.tell() > 0 or len(buf.getvalue()) > 0:
                buf.seek(0)
                qr_caption = (
                    f"📲 **SCAN QR CODE WHATSAPP SEKARANG** ⚡\n"
                    f"⏱️ _QR Code baru aktif (berlaku ~20 detik)_\n\n"
                    f"1️⃣ Buka WhatsApp di ponsel Anda\n"
                    f"2️⃣ Buka menu **Perangkat Tertaut** > **Tautkan Perangkat**\n"
                    f"3️⃣ Arahkan kamera ke gambar QR di atas\n\n"
                    f"{text}"
                )
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=buf,
                    caption=qr_caption,
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                )
                return
        except _ADV_ERR as e:
            logger.error(f"Failed to generate QR photo: {e}")

    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)

async def wachat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wachat [kosong|N|nama/nomor] — daftar chat terbaru atau riwayat satu chat."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    arg = " ".join(context.args).strip() if context.args else ""
    if not arg:
        res = tools.wa_get_chats(limit=10)
        err = _wa_not_ready(res)
        if err:
            await safe_send_message(context, chat_id, f"📵 {err}\nCek `/wa` untuk scan QR.")
            return
        chats = res.get("chats", []) or []
        if not chats:
            await safe_send_message(context, chat_id, "💬 Belum ada chat WA.")
            return
        lines = ["💬 **Chat WhatsApp Terbaru:**\n"]
        for c in chats:
            icon = "👥" if c.get("is_group") else "👤"
            unread = f" ({c['unread']} baru)" if c.get("unread") else ""
            prev = _wa_esc(c.get("last_preview", ""))[:80]
            who = "kamu" if c.get("last_from_me") else "mereka"
            lines.append(
                f"{icon} **{_wa_esc(c.get('name', '?'))}**{unread}\n"
                f"   _{prev}_ — {who}, {_wa_time(c.get('last_ts', 0))}"
            )
        lines.append("\nBaca isi: `/wachat <nama/nomor>` • Masuk: `/wamasuk`")
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    if arg.isdigit():
        res = tools.wa_get_chats(limit=min(int(arg), 30))
        err = _wa_not_ready(res)
        if err:
            await safe_send_message(context, chat_id, f"📵 {err}")
            return
        chats = res.get("chats", []) or []
        lines = [f"💬 **{len(chats)} Chat Terbaru:**\n"]
        for c in chats:
            icon = "👥" if c.get("is_group") else "👤"
            lines.append(f"{icon} **{_wa_esc(c.get('name', '?'))}** — _{_wa_esc(c.get('last_preview', ''))[:60]}_")
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    only_unread = False
    clean_parts = []
    if context and context.args:
        for a in context.args:
            if a.lower() in ("baru", "unread", "new"):
                only_unread = True
            else:
                clean_parts.append(a)
    arg = " ".join(clean_parts).strip() if clean_parts else arg

    try:
        res = tools.wa_get_messages(chat=arg, limit=15, only_unread=only_unread, mark_as_read=True)
    except TypeError:
        res = tools.wa_get_messages(chat=arg, limit=15)
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    msgs = res.get("messages", []) or []
    if not msgs:
        if only_unread:
            await safe_send_message(
                context,
                chat_id,
                f"💬 **{res.get('chat_name', arg)}**: Tidak ada pesan baru yang belum dibaca.\n"
                f"Ketik `/wachat {arg}` untuk melihat seluruh riwayat.",
            )
        else:
            await safe_send_message(context, chat_id, f"💬 **{res.get('chat_name', arg)}**: Riwayat kosong.")
        return

    tag_str = " (Hanya Baru 🟢)" if only_unread else ""
    lines = [f"💬 **{res.get('chat_name', arg)}** ({len(msgs)} pesan{tag_str}):\n"]
    for m in msgs:
        who = "kamu" if m.get("from_me") else _wa_esc(m.get("sender", "?"))
        body = _wa_esc(m.get("body", ""))[:300]
        status_tag = "" if only_unread else ("" if m.get("is_read") else " `[BARU]`")
        lines.append(f"[{_wa_time(m.get('ts', 0))}] **{who}:**{status_tag} {body}")
    await safe_send_message(context, chat_id, "\n".join(lines) or "💬 Kosong.")

async def wamasuk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wamasuk [limit|semua|baru] — pesan WA masuk terbaru yang terekam bot."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    lim = 10
    only_unread = True
    if context.args:
        for a in context.args:
            if a.isdigit():
                lim = max(1, min(int(a), 40))
            elif a.lower() in ("semua", "all", "history", "riwayat"):
                only_unread = False
            elif a.lower() in ("baru", "unread", "new"):
                only_unread = True

    res = tools.wa_get_incoming(limit=lim, only_unread=only_unread, mark_as_read=True)
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    items = [it for it in (res.get("incoming", []) or []) if not it.get("from_me")]
    warn = res.get("warning")
    if not items:
        msg_empty = (
            "📥 **Semua pesan WA sudah dilihat.**\n"
            "Tidak ada pesan baru yang belum dibaca.\n\n"
            "💡 _Ketik `/wamasuk semua` untuk melihat riwayat pesan masuk sebelumnya._"
            if only_unread
            else "📥 Belum ada pesan WA masuk terekam."
        )
        if warn:
            msg_empty = f"{warn}\n\n{msg_empty}"
        await safe_send_message(context, chat_id, msg_empty)
        return
    header = f"📥 *{len(items)} Pesan WA Masuk ({'Hanya Baru 🟢' if only_unread else 'Terbaru'}):*\n"
    if warn:
        header = f"{warn}\n\n{header}"
    lines = [header]
    for it in items:
        icon = _WA_TYPE_ICON.get(str(it.get("msg_type") or ""), "")
        icon = icon or ("👥" if it.get("is_group") else "👤")
        chat = _wa_esc(it.get("chat_name") or "")
        if not chat:
            raw = str(it.get("chat") or "").split("@")[0]
            chat = ("…" + raw[-4:]) if raw.isdigit() and len(raw) > 8 else (raw or "?")
        when = _wa_time(int(it.get("msg_ts") or 0)) if it.get("msg_ts") else _wa_time_iso(it.get("ts", ""))
        body = _wa_esc(it.get("body", ""))[:200] or "(kosong)"
        status_tag = "" if only_unread else ("" if it.get("is_read") else " *(BARU)*")
        if it.get("is_group") and not it.get("from_me"):
            lines.append(f"{icon} *{chat}* — {_wa_sender(it)} · {when}{status_tag}\n   {body}")
        else:
            lines.append(f"{icon} *{chat}* · {when}{status_tag}\n   {body}")
    await safe_send_message(context, chat_id, "\n".join(lines))

async def wakirim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wakirim <tujuan> <pesan> — kirim pesan WA ke nomor/nama grup."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    args = list(context.args) if context.args else []
    if len(args) < 2:
        await safe_send_message(
            context,
            chat_id,
            "Usage: `/wakirim <nomor|nama grup> <pesan>`\n"
            "Contoh: `/wakirim 081234567890 halo dari bot`",
        )
        return
    res = tools.wa_send_message(to=args[0], message=" ".join(args[1:]))
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    await safe_send_message(
        context, chat_id, f"✅ Pesan WA terkirim ke `{res.get('to', args[0])}`."
    )

async def waformat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/waformat [list|on <nama>|off <nama>|add <nama>|<kw>|del <nama>] — atur pencatatan otomatis."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    args = list(context.args) if context.args else []
    sub = (args[0].lower() if args else "list")

    if sub == "list" or not args:
        res = tools.wa_list_formats()
        err = _wa_not_ready(res)
        if err:
            await safe_send_message(context, chat_id, f"📵 {err}")
            return
        fmts = res.get("formats", []) or []
        on = sum(1 for f in fmts if f.get("enabled", True))
        lines = [f"📋 **Format Pencatatan WA ({on}/{len(fmts)} aktif):**\n"]
        for f in fmts:
            icon = "✅" if f.get("enabled", True) else "⛔"
            kws = ", ".join(f"`{k}`" for k in (f.get("keywords") or [])[:4]) or "–"
            lines.append(
                f"{icon} **{_wa_esc(f.get('name', '?'))}** → tab `{_wa_esc(f.get('tab', ''))}`\n"
                f"   keyword: {kws}"
            )
        lines.append(
            "\n**Atur:** `/waformat off <nama>` • `/waformat on <nama>`\n"
            "**Tambah:** `/waformat add Nama | kw1, kw2 | TabTujuan`\n"
            "**Hapus:** `/waformat del <nama>`\n"
            "**Lihat hasil:** `/wareport [nama]`"
        )
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    if sub in ("on", "off") and len(args) >= 2:
        name = " ".join(args[1:])
        res = tools.wa_toggle_format(name=name, enabled=(sub == "on"))
        if isinstance(res, dict) and res.get("status") == "error":
            await safe_send_message(context, chat_id, f"❌ {res.get('message')}")
            return
        state = "diaktifkan ✅" if (sub == "on") else "dimatikan ⛔"
        await safe_send_message(
            context, chat_id, f"Format **{_wa_esc(name)}** {state}."
        )
        return

    if sub == "add":
        rest = " ".join(args[1:])
        parts = [p.strip() for p in rest.split("|")]
        if not parts or not parts[0]:
            await safe_send_message(
                context, chat_id, "Usage: `/waformat add Nama | kw1, kw2 | TabTujuan`"
            )
            return
        name = parts[0]
        kws = parts[1] if len(parts) > 1 else ""
        tab = parts[2] if len(parts) > 2 else name
        res = tools.wa_add_format(name=name, keywords=kws, tab=tab)
        if isinstance(res, dict) and res.get("status") == "error":
            await safe_send_message(context, chat_id, f"❌ {res.get('message')}")
            return
        await safe_send_message(
            context,
            chat_id,
            f"✅ Format **{_wa_esc(name)}** ditambahkan (tab `{_wa_esc(tab)}`). "
            "Pesan berkeyword langsung tercatat otomatis.",
        )
        return

    if sub in ("del", "delete", "hapus") and len(args) >= 2:
        name = " ".join(args[1:])
        res = tools.wa_delete_format(name=name)
        if isinstance(res, dict) and res.get("status") == "error":
            await safe_send_message(context, chat_id, f"❌ {res.get('message')}")
            return
        await safe_send_message(
            context, chat_id, f"🗑️ Format **{_wa_esc(name)}** dihapus."
        )
        return

    await safe_send_message(
        context, chat_id, "Usage: `/waformat [list|on|off|add|del]` — contoh: `/waformat off Stok`"
    )

async def wareport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wareport [nama_format] [limit] — baca catatan laporan WA yang terekam."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    args = list(context.args) if context.args else []
    fmt, lim = "", 8
    for a in args:
        if a.isdigit():
            lim = max(1, min(int(a), 30))
        elif not fmt:
            fmt = a
    res = tools.wa_get_records(report_format=fmt, limit=lim)
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    recs = res.get("records", []) or []
    title = f" format **{_wa_esc(fmt)}**" if fmt else ""
    if not recs:
        await safe_send_message(
            context, chat_id, f"📊 Belum ada catatan{title}."
        )
        return
    lines = [f"📊 **{len(recs)} Catatan Terbaru{title}:**\n"]
    for r in recs:
        sync = "☁️" if r.get("synced_to_sheets") else "💾"
        body = _wa_esc(str(r.get("body", ""))[:220]).replace("\n", " ")
        lines.append(
            f"{sync} **{_wa_esc(r.get('format_name', r.get('tab', '?')))}** · "
            f"{_wa_esc(r.get('timestamp', ''))}\n"
            f"   👤 {_wa_esc(r.get('sender', '?'))} di **{_wa_esc(r.get('group', '?'))}**\n"
            f"   _{body}_"
        )
    await safe_send_message(context, chat_id, "\n".join(lines))

async def waringkas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/waringkas [nama_format] — digest cerdas: statistik + sorotan AI + terbaru."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    args = list(context.args) if context.args else []
    fmt = " ".join(a for a in args if not a.isdigit())
    await safe_send_message(context, chat_id, "🧠 Menyusun digest cerdas...")
    from alfa.bot.wa_digest import send_digest

    ok = await send_digest(context, chat_id, report_format=fmt)
    if not ok:
        await safe_send_message(context, chat_id, "❌ Digest gagal disusun. Coba lagi.")

async def wacari_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wacari <kata> — cari kata kunci di pesan WA terbaru."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not is_authorized(user_id):
        return

    q = " ".join(context.args).strip() if context.args else ""
    if not q:
        await safe_send_message(context, chat_id, "Usage: `/wacari <kata kunci>`")
        return
    res = tools.wa_search_messages(query=q)
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    hits = res.get("hits", []) or []
    if not hits:
        await safe_send_message(context, chat_id, f"🔍 Tidak ada hasil untuk '{q}'.")
        return
    lines = [f"🔍 **{len(hits)} hasil untuk '{_wa_esc(q)}':**\n"]
    for h in hits[:15]:
        who = "kamu" if h.get("from_me") else _wa_esc(h.get("sender", "?"))
        lines.append(
            f"• **{_wa_esc(h.get('chat', '?'))}** [{_wa_time(h.get('ts', 0))}] {who}: "
            f"{_wa_esc(h.get('body', ''))[:150]}"
        )
    await safe_send_message(context, chat_id, "\n".join(lines))
