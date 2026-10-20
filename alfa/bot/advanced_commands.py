"""Telegram bot command handlers."""

import json
import logging
import os
import sys

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa import tools
from alfa.bot.config import is_authorized
from alfa.bot.helpers import safe_send_message
from alfa.core import database

logger = logging.getLogger("TelegramAIAgent")

_ADV_ERR = (
    TelegramError,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
)


def _get_bot_module():
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)


async def wa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wa or /washeets command to control WhatsApp Google Sheets Bot."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
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
            InlineKeyboardButton("💬 Chat", callback_data="wx|chats|0"),
            InlineKeyboardButton("📥 Masuk", callback_data="wx|in|0"),
        ],
        [
            InlineKeyboardButton("📋 Format", callback_data="wx|fmt"),
            InlineKeyboardButton("📊 Laporan", callback_data="wx|rep|0|-1"),
        ],
        [
            InlineKeyboardButton("🔄 Restart", callback_data="btn_wa_restart"),
            InlineKeyboardButton("📊 Cek Status", callback_data="btn_wa_status"),
        ],
        [
            InlineKeyboardButton("▶️ Start", callback_data="btn_wa_start"),
            InlineKeyboardButton("⏹️ Stop", callback_data="btn_wa_stop"),
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

    auth_desc = (
        "✅ Terhubung (Logged In)"
        if wa_auth_status == "READY"
        else f"⚠️ {wa_auth_status} (Perlu Scan QR)"
    )

    text = (
        f"📱 **Manajer WhatsApp Google Sheets Bot:**\n\n"
        f"• **Status Layanan:** {status_icon}\n"
        f"• **Status Akun WA:** `{auth_desc}`\n"
        f"• **Auto-Start Saat Boot/Internet:** `{'Aktif 🟢' if res.get('enabled_on_boot') else 'Nonaktif 🔴'}`\n"
        f"• **Service Name:** `wa-sheets-bot.service`\n\n"
        f"✉️ Kirim pesan via `/wakirim <nomor|nama grup> <pesan>`.\n"
        f"💡 _Bot WhatsApp ini otomatis aktif saat laptop online dan diawasi 24/7 oleh Ecosystem Watchdog._"
    )

    if wa_auth_status == "QR_READY" and qr_str:
        try:
            import io

            import qrcode

            img = qrcode.make(qr_str)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=buf,
                caption=f"📲 **SCAN QR CODE WHATSAPP SEKARANG**\n\n{text}",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return
        except _ADV_ERR as e:
            logger.error(f"Failed to generate QR photo: {e}")

    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)


# --- /sites: registry + hidupkan situs hasil kerja agent -------------------
_SITES_CACHE: dict[int, tuple[float, list[dict]]] = {}
_SITES_TTL = 300.0


def _lan_ip() -> str:
    try:
        import socket as _s

        s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ip)
    except OSError:
        return "127.0.0.1"


def _sites_cached(user_id: int) -> list[dict]:
    import time as _t

    now = _t.monotonic()
    hit = _SITES_CACHE.get(user_id)
    if hit and now - hit[0] < _SITES_TTL:
        return hit[1]
    rows = tools.serve_site(action="status").get("sites", []) or []
    _SITES_CACHE[user_id] = (now, rows)
    return rows


def _site_kb(rows: list[dict]) -> InlineKeyboardMarkup:
    kb = []
    for i, s in enumerate(rows):
        dot = "🟢" if (s.get("backend_on") or s.get("frontend_on")) else "⚪"
        label = f"{dot} {_wa_esc(s.get('title', s.get('slug', '?'))[:28])}"
        kb.append([InlineKeyboardButton(label, callback_data=f"st|view|{i}")])
    kb.append([InlineKeyboardButton("🔄 Refresh", callback_data="st|list")])
    return InlineKeyboardMarkup(kb)


async def sites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sites — daftar website/proyek hasil agent, hidupkan dari Telegram."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    _SITES_CACHE.pop(user_id, None)
    rows = _sites_cached(user_id)
    if not rows:
        await safe_send_message(
            context, chat_id,
            "🌐 Belum ada situs terdaftar. Misi swarm website otomatis masuk sini setelah harvest.",
        )
        return
    on = sum(1 for s in rows if s.get("backend_on") or s.get("frontend_on"))
    await safe_send_message(
        context, chat_id,
        f"🌐 **Galeri Hasil Kerja Agent ({on}/{len(rows)} hidup):**\nKetuk untuk kelola:",
        reply_markup=_site_kb(rows),
    )


async def handle_sites_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Router callback st|*. Return True bila ditangani."""
    query = update.callback_query
    if not query or not (query.data or "").startswith("st|"):
        return False
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        await query.answer()
        return True
    await query.answer()
    parts = (query.data or "").split("|")
    action = parts[1] if len(parts) > 1 else ""
    idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1

    async def _edit(text, markup=None):
        try:
            await query.edit_message_text(text=text, reply_markup=markup, parse_mode="Markdown")
        except _ADV_ERR:
            await safe_send_message(context, chat_id, text, reply_markup=markup)

    try:
        if action == "list":
            _SITES_CACHE.pop(user_id, None)
            rows = _sites_cached(user_id)
            on = sum(1 for s in rows if s.get("backend_on") or s.get("frontend_on"))
            await _edit(
                f"🌐 **Galeri Hasil Kerja Agent ({on}/{len(rows)} hidup):**\nKetuk untuk kelola:",
                _site_kb(rows),
            )
            return True
        rows = _sites_cached(user_id)
        if not (0 <= idx < len(rows)):
            await _edit("⏳ Daftar kedaluwarsa — muat ulang:", _site_kb(_sites_cached(user_id)))
            return True
        slug = rows[idx]["slug"]
        if action == "view":
            s = tools.serve_site(action="status").get("sites", []) or []
            hit = next((x for x in s if x.get("slug") == slug), rows[idx])
            stack = hit.get("stack", {}) or {}
            runnable = bool(
                stack.get("has_backend") or stack.get("has_frontend") or stack.get("has_php")
            )
            if not runnable:
                # Proyek non-server: tanpa tombol start/stop, tampilkan cara pakai.
                try:
                    info = tools.serve_site(action="start", slug=slug)
                    howto = info.get("note", "proyek non-server")
                except _ADV_ERR:
                    howto = "proyek non-server"
                kb = [[InlineKeyboardButton("◀️ Galeri", callback_data="st|list")]]
                await _edit(
                    f"📦 **{_wa_esc(hit.get('title', slug))}**\n`{slug}`\n"
                    f"_{_wa_esc(howto)}_\n\n"
                    "Jalankan manual dari terminal atau suruh agent via chat.",
                    InlineKeyboardMarkup(kb),
                )
                return True
            ip = _lan_ip()
            lines = [f"{'🟢' if hit.get('backend_on') else '⚪'} Backend"]
            if hit.get("backend_port"):
                lines[0] += f" — `http://{ip}:{hit['backend_port']}`"
            lines.append(f"{'🟢' if hit.get('frontend_on') else '⚪'} Frontend")
            if hit.get("frontend_port"):
                lines[1] += f" — `http://{ip}:{hit['frontend_port']}`"
            kb = [
                [InlineKeyboardButton("▶️ Hidupkan", callback_data=f"st|start|{idx}"),
                 InlineKeyboardButton("⏹️ Matikan", callback_data=f"st|stop|{idx}")],
                [InlineKeyboardButton("📜 Log", callback_data=f"st|logs|{idx}"),
                 InlineKeyboardButton("◀️ Galeri", callback_data="st|list")],
            ]
            await _edit(
                f"🌐 **{_wa_esc(hit.get('title', slug))}**\n`{slug}`\n" + "\n".join(lines),
                InlineKeyboardMarkup(kb),
            )
        elif action in ("start", "stop"):
            res = tools.serve_site(action=action, slug=slug)
            _SITES_CACHE.pop(user_id, None)
            if res.get("status") == "error":
                await _edit(f"❌ {res.get('message')}")
            else:
                det = [f"• {k}: `{v}`" for k, v in res.items() if k not in ("status", "slug", "title")]
                await _edit(
                    f"{'🟢' if action == 'start' else '⏹️'} **{_wa_esc(res.get('title', slug))}** "
                    f"{'hidup' if action == 'start' else 'mati'}.\n" + "\n".join(det),
                    InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Galeri", callback_data="st|list")]]),
                )
        elif action == "logs":
            res = tools.serve_site(action="logs", slug=slug)
            chunks = []
            for k, v in (res.get("logs") or {}).items():
                tail = (v or "").strip().split("\n")[-12:]
                chunks.append(f"**{k}:**\n```\n" + "\n".join(tail[-12:]) + "\n```")
            await _edit(
                f"📜 **Log {slug}:**\n" + ("\n".join(chunks) if chunks else "_kosong_"),
                InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Galeri", callback_data="st|list")]]),
            )
    except _ADV_ERR as e:
        logger.warning(f"[sites_menu] {e}")
    return True


def _wa_esc(text: str) -> str:
    """Netralkan karakter Markdown yang rentan merusak entity parse Telegram."""
    return (
        str(text or "")
        .replace("`", "'")
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


async def wachat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wachat [kosong|N|nama/nomor] — daftar chat terbaru atau riwayat satu chat."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
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

    res = tools.wa_get_messages(chat=arg, limit=15)
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    msgs = res.get("messages", []) or []
    lines = [f"💬 **{res.get('chat_name', arg)}** ({len(msgs)} pesan):\n"]
    for m in msgs:
        who = "kamu" if m.get("from_me") else _wa_esc(m.get("sender", "?"))
        body = _wa_esc(m.get("body", ""))[:300]
        lines.append(f"[{_wa_time(m.get('ts', 0))}] **{who}:** {body}")
    await safe_send_message(context, chat_id, "\n".join(lines) or "💬 Kosong.")


async def wamasuk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wamasuk [limit|baru] — pesan WA masuk terbaru yang terekam bot."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    lim = 10
    only_unread = False
    if context.args:
        for a in context.args:
            if a.isdigit():
                lim = max(1, min(int(a), 40))
            elif a.lower() in ("baru", "unread", "new"):
                only_unread = True

    res = tools.wa_get_incoming(limit=lim, only_unread=only_unread, mark_as_read=True)
    err = _wa_not_ready(res)
    if err:
        await safe_send_message(context, chat_id, f"📵 {err}")
        return
    items = res.get("incoming", []) or []
    if not items:
        msg_empty = "📥 Tidak ada pesan WA baru yang belum dibaca." if only_unread else "📥 Belum ada pesan WA masuk terekam."
        await safe_send_message(context, chat_id, msg_empty)
        return
    header = f"📥 **{len(items)} Pesan WA Masuk ({'Hanya Baru' if only_unread else 'Terbaru'}):**\n"
    lines = [header]
    for it in items:
        icon = _WA_TYPE_ICON.get(str(it.get("msg_type") or ""), "")
        icon = icon or ("👥" if it.get("is_group") else "👤")
        chat = _wa_esc(it.get("chat_name") or "")
        if not chat:
            raw = str(it.get("chat") or "").split("@")[0]
            chat = ("…" + raw[-4:]) if raw.isdigit() and len(raw) > 8 else (raw or "?")
        when = _wa_time_iso(it.get("ts", ""))
        body = _wa_esc(it.get("body", ""))[:200] or "_(kosong)_"
        status_tag = "" if it.get("is_read") else " `[BARU]`"
        if it.get("is_group") and not it.get("from_me"):
            lines.append(f"{icon} **{chat}** — {_wa_sender(it)} · {when}{status_tag}\n   {body}")
        else:
            lines.append(f"{icon} **{chat}** · {when}{status_tag}\n   {body}")
    await safe_send_message(context, chat_id, "\n".join(lines))


async def wakirim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wakirim <tujuan> <pesan> — kirim pesan WA ke nomor/nama grup."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
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
    if not _is_authorized(user_id):
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
    if not _is_authorized(user_id):
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
    if not _is_authorized(user_id):
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
    if not _is_authorized(user_id):
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


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dashboard, /web, or /app command."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    res = tools.open_web_dashboard(port=8080)
    tma_url = os.getenv(
        "ALFA_WEBAPP_URL", res.get("network_url") or "http://127.0.0.1:8080"
    )

    keyboard = []
    magic_ok = False
    try:
        from alfa.dashboard.routes.auth import create_telegram_link

        # CATATAN: tombol URL localhost DITOLAK API Telegram (400 utk SELURUH pesan).
        # Semua tombol pakai base LAN — laptop satu WiFi membukanya normal.
        lan_base = (res.get("network_url") or "").rstrip("/")
        if lan_base:
            tok_hp = create_telegram_link(user_id)
            tok_laptop = create_telegram_link(user_id)
            keyboard.append(
                [InlineKeyboardButton("📱 Buka di HP (WiFi, auto-login)", url=f"{lan_base}/t/{tok_hp}")]
            )
            keyboard.append(
                [InlineKeyboardButton("💻 Buka di Laptop (auto-login)", url=f"{lan_base}/t/{tok_laptop}")]
            )
            magic_ok = bool(keyboard)
    except _ADV_ERR as link_err:
        logger.debug(f"[dashboard] magic link gagal: {link_err}")
    if tma_url and tma_url.startswith("https://"):
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📱 Buka ALFA Mini App", web_app=WebAppInfo(url=tma_url)
                )
            ]
        )
    else:
        web_url = res.get("network_url") or res.get("local_url") or ""
        if web_url and not web_url.startswith("http://localhost") and not magic_ok:
            keyboard.append(
                [InlineKeyboardButton("🌐 Buka Web Dashboard", url=web_url)]
            )

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    text = (
        "🛸 **ALFA SOVEREIGN COMMAND CENTER:**\n\n"
        + (
            "Ketuk tombol di bawah untuk masuk otomatis (tanpa login).\n"
            "Berlaku 10 menit, sekali pakai.\n"
            if magic_ok
            else (
                f"• **Akses Lokal (Laptop):** `{res.get('local_url')}`\n"
                f"• **Akses Jaringan (HP / WiFi):** `{res.get('network_url')}`\n"
            )
        )
        + "\n⚡ **Pusat Kontrol Terintegrasi:**\n"
        "1. 📊 Telemetri Hardware & CPU/RAM Real-time\n"
        "2. ⚡ 130+ Tools Interaktif & Browser Otomatis\n"
        "3. 🧠 Second Brain & Vector Memory\n"
        "4. 🛡️ 24/7 System Guardian & Background Watchdogs\n"
        "5. 💬 Web AI Interactive Console\n"
        "6. 🤖 Ruang Rapat AI (Swarm Multi-Agent Engine)\n"
        "7. 🔑 Multi-Provider Vault & API Keys Manager"
    )
    await safe_send_message(context, chat_id, text, reply_markup=reply_markup)


async def keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /keys command to manage API keys vault."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    keys = database.list_api_keys_sync()
    if not keys:
        text = "🔑 **API Key Vault Kosong.** Tambahkan via Web Dashboard (http://localhost:8080) atau gunakan perintah tool."
    else:
        text = "🔑 **Multi-Provider API Key Vault:**\n\n"
        for k in keys:
            act = "🟢 *[ACTIVE]*" if k["is_active"] else "⚪"
            text += f"{act} **{k['name']}** (`{k['provider'].upper()}`)\n"
            text += f"   • Key: `{k['masked_key']}` | Model: `{k['default_model']}`\n\n"
        text += "💡 _Kelola, uji koneksi, & tambah key baru dengan mudah via Web Dashboard di tab API Key Vault._"
    await safe_send_message(context, chat_id, text)


async def agents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /agents or /swarm command to view autonomous AI workforce."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    agents = database.list_custom_agents_sync()
    if not agents:
        text = "🤖 **Belum ada AI Agent terdaftar.**"
    else:
        text = "🤖 **ALFA Autonomous AI Agent Workforce:**\n\n"
        for a in agents:
            status = "🟢 Aktif" if a.get("is_enabled", 1) else "🔴 Nonaktif"
            text += f"{a.get('avatar_emoji', '🤖')} **{a['name']}** ({status})\n"
            text += f"   • Role: *{a['role']}*\n"
            text += f"   • Model: `{a['provider']}/{a['model']}`\n\n"
        text += "💡 _Mulai rapat antar agent dengan perintah `/rapat <topik>` atau via Web Dashboard!_"
    await safe_send_message(context, chat_id, text)


async def rapat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rapat or /meeting command to conduct an autonomous round-table meeting (Plan Mode)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        text = (
            "🏛️ **Panduan Ruang Rapat AI (Mode 1: Plan):**\n\n"
            "Format: `/rapat <topik / masalah yang ingin dibahas>`\n\n"
            "**Contoh:**\n"
            "• `/rapat Desain arsitektur database baru untuk auto-sync WhatsApp ke cloud`\n"
            "• `/rapat Strategi meningkatkan performa agent bot dan penghematan token API`\n\n"
            "💡 _Para agent akan berdebat, berdiskusi, dan merumuskan Action Plan!_\n"
            "⚡ _Untuk menyuruh agent langsung bekerja & mengeksekusi tugas nyata, gunakan `/swarm <perintah>`!_"
        )
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"🏛️ **Membuka Rapat Perencanaan AI...**\n\n"
        f"📋 **Agenda:** _{topic}_\n"
        f"👥 Memanggil para agent spesialis untuk memulai diskusi round-table. Mohon tunggu...",
    )

    from alfa.bot.progress import SwarmProgressReporter

    reporter = SwarmProgressReporter(context, chat_id, topic, header="🏛️ **Rapat**")
    await reporter.start()

    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.conduct_multi_agent_meeting(
            topic=topic, rounds=2, mode="plan"
        )
    except _ADV_ERR as e:
        await reporter.stop("❌ Rapat gagal.")
        logger.error(f"Error during Telegram /rapat meeting: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat rapat agent: {str(e)}"
        )
        return

    await reporter.stop("✅ Diskusi selesai — transkrip di bawah ⬇️")

    try:
        transcript = result.get("dialogue_transcript", [])
        dialogue_text = "🗣️ **Transkrip Diskusi Antar Agent:**\n\n"
        for d in transcript[:6]:
            dialogue_text += f"{d.get('avatar_emoji', '🤖')} **{d['agent_name']}** ({d['role']}):\n{d['message'][:350]}...\n\n"

        await safe_send_message(context, chat_id, dialogue_text)

        final_text = (
            f"🎯 **KONSENSUS & KEPUTUSAN RAPAT:**\n\n"
            f"{result.get('consensus', '')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **ACTION PLAN / LANGKAH KERJA:**\n\n"
            f"{result.get('action_plan', '')}\n\n"
            f"🌐 _Transkrip lengkap tersimpan di Web Dashboard (ID: #{result.get('meeting_id')})_"
        )
        await safe_send_message(context, chat_id, final_text)

    except _ADV_ERR as e:
        logger.error(f"Error during Telegram /rapat meeting: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat rapat agent: {str(e)}"
        )


async def swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /swarm — subcommands (model|status|cancel) atau eksekusi langsung (Execute Mode)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    raw = " ".join(context.args).strip() if context.args else ""
    first = (raw.split(maxsplit=1)[0].lower() if raw else "")
    rest = (raw.split(maxsplit=1)[1] if " " in raw else "")

    if first in ("model", "set-model"):
        # Reuse CLI helper logic via direct DB update path
        import shlex

        from alfa.core import database as _db
        from alfa.core.cli.direct_ai import PROVIDERS_CATALOG, normalize_provider

        try:
            parts = shlex.split(rest)
        except ValueError:
            parts = rest.strip().split()
        agents = _db.list_custom_agents_sync()
        if not parts:
            await safe_send_message(
                context,
                chat_id,
                "Usage: `/swarm model <id|nama> <provider> [model]`\n"
                "Contoh: `/swarm model 2 9router antigravity`",
            )
            return
        target_agent = parts[0]
        matched = None
        if target_agent.isdigit():
            matched = next((a for a in agents if a.get("id") == int(target_agent)), None)
        if not matched:
            tl = target_agent.lower()
            matched = next((a for a in agents if tl in a.get("name", "").lower()), None)
        if not matched:
            await safe_send_message(context, chat_id, f"❌ Agen '{target_agent}' tidak ditemukan. `/agents`")
            return
        if len(parts) < 2:
            await safe_send_message(
                context, chat_id,
                f"Agen: **{matched.get('name')}** — `{matched.get('provider')}/{matched.get('model')}`\n"
                f"Ubah: `/swarm model \"{matched.get('name')}\" <provider> [model]`",
            )
            return
        provider = normalize_provider(parts[1])
        cat = PROVIDERS_CATALOG.get(provider, {})
        model = parts[2] if len(parts) > 2 else (cat.get("default_model") or "default")
        res = _db.update_custom_agent_sync(matched["id"], {"provider": provider, "model": model})
        if res.get("status") == "success":
            await safe_send_message(context, chat_id, f"✅ **{matched.get('name')}** → `{provider}/{model}`")
        else:
            await safe_send_message(context, chat_id, f"❌ Gagal: `{res.get('message')}`")
        return

    if first in ("status", "info"):
        from alfa.bot.mode_commands import status_command as _status

        await _status(update, context)
        return

    if first in ("cancel", "stop", "batal"):
        from alfa.bot.mode_commands import cancel_command as _cancel

        await _cancel(update, context)
        return

    if first in ("single", "solo"):
        from alfa.bot.mode_commands import set_telegram_mode_sync

        set_telegram_mode_sync("single")
        await safe_send_message(context, chat_id, "🧍 **Mode SINGLE aktif.**")
        return

    if first in ("swarm", "on", "multi"):
        from alfa.bot.mode_commands import set_telegram_mode_sync

        set_telegram_mode_sync("swarm")
        await safe_send_message(context, chat_id, "⚡ **Mode SWARM aktif.** Chat teks dieksekusi tim.")
        return

    if first in ("template", "templates", "templat"):
        from alfa.bot.mode_commands import SWARM_TEMPLATES

        if not rest:
            rows = [f"• `{n}` — {t[:90]}…" for n, t in SWARM_TEMPLATES.items()]
            await safe_send_message(
                context,
                chat_id,
                "📦 **Templat Misi Swarm:**\n\n" + "\n".join(rows)
                + "\n\nJalankan: `/swarm template <nama>`\nJadwalkan: *'Jadwalkan misi swarm <nama> tiap <N> menit/jam'*",
            )
            return
        tpl = SWARM_TEMPLATES.get(rest.strip().lower())
        if not tpl:
            await safe_send_message(
                context, chat_id,
                f"❌ Templat '{rest.strip()}' tidak ada. Lihat `/swarm template`.",
            )
            return
        raw = tpl  # alir ke `topic = raw` di bawah → eksekusi misi templat

    topic = raw
    if not topic:
        text = (
            "⚡ **Panduan Swarm Eksekusi Langsung (Mode 2: Bekerja Nyata):**\n\n"
            "Format: `/swarm <perintah / tugas nyata yang ingin dikerjakan bersama>`\n\n"
            "**Contoh:**\n"
            "• `/swarm Scrape 20 mouse gaming terlaris di Shopee & Tokopedia dan buatkan CSV-nya`\n"
            "• `/swarm Buatkan script Python monitoring RAM/CPU dan jalankan di sandbox`\n"
            "• `/swarm Audit port lokal dan status keamanan server`\n\n"
            "**Subcommand:**\n"
            "• `/swarm status` — status swarm & key agen\n"
            "• `/swarm cancel` — hentikan misi berjalan\n"
            "• `/swarm template [nama]` — misi siap pakai\n"
            "• `/swarm model <id|nama> <provider> [model]` — ganti model agen\n"
            "• `/mode swarm` — semua chat teks jadi misi swarm\n\n"
            "💡 _Seluruh tim agen AI akan langsung membagi tugas, menjalankan tools live, dan mengirimkan file hasil ke Telegram kamu!_"
        )
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"⚡ **Membangunkan AI Swarm & Mengeksekusi Tugas Nyata...**\n\n"
        f"📌 **Tugas:** _{topic}_\n"
        f"🛠️ Alpha Lead, Researcher Prime, Code Crafter, dan Cyber Sentry sedang mengeksekusi tools. Mohon tunggu...",
    )

    from alfa.bot.progress import SwarmProgressReporter

    reporter = SwarmProgressReporter(context, chat_id, topic)
    await reporter.start()

    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.conduct_multi_agent_meeting(
            topic=topic, rounds=1, mode="execute"
        )
    except _ADV_ERR as e:
        await reporter.stop("❌ Misi gagal.")
        logger.error(f"Error during Telegram /swarm execution: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat eksekusi swarm: {str(e)}"
        )
        return

    await reporter.stop("✅ Selesai — laporan lengkap di bawah ⬇️")

    try:
        steps = result.get("execution_results", [])
        steps_text = "⚡ **Laporan Eksekusi Tiap Agen:**\n\n"
        for s in steps:
            steps_text += (
                f"{s.get('avatar_emoji', '🤖')} **{s['agent_name']}** ({s['role']})\n"
            )
            steps_text += f"   • Tool: `{s['tool_used']}` ({s['duration_ms']}ms)\n"
            steps_text += f"   • Output: _{s['execution_summary'][:200]}_\n\n"

        await safe_send_message(context, chat_id, steps_text)

        final_text = (
            f"🏆 **LAPORAN HASIL EKSEKUSI NYATA:**\n\n"
            f"{result.get('consensus', '')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 _ID Sesi: #{result.get('meeting_id')} • Tersimpan di Web Dashboard & Dokumen_"
        )
        await safe_send_message(context, chat_id, final_text)

        for s in steps:
            fpath = s.get("deliverable_file")
            if fpath and os.path.exists(fpath):
                try:
                    with open(fpath, "rb") as f_doc:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=f_doc,
                            filename=os.path.basename(fpath),
                            caption=f"📁 **File Deliverable Hasil Swarm ({s['agent_name']}):**\n`{os.path.basename(fpath)}`",
                        )
                except _ADV_ERR as file_err:
                    logger.warning(
                        f"Failed to send deliverable file to Telegram: {file_err}"
                    )
    except _ADV_ERR as e:
        logger.error(f"Error sending Telegram /swarm report: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Gagal mengirim laporan swarm: {str(e)}"
        )


async def resume_swarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume_swarm or /resume to resume an interrupted/cancelled swarm session."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    from alfa.swarm.checkpoint import SwarmCheckpoint

    resumable = SwarmCheckpoint.list_resumable()

    session_id = (context.args[0].strip()) if context.args else ""
    if not session_id:
        if not resumable:
            await safe_send_message(
                context,
                chat_id,
                "ℹ️ Tidak ada sesi swarm yang tertunda atau bisa dilanjutkan saat ini.",
            )
            return

        text = "🔄 **Daftar Sesi Swarm yang Bisa Dilanjutkan (Checkpoints):**\n\n"
        for r in resumable[:5]:
            text += (
                f"• `{r['session_id']}` [{r['status'].upper()}]\n"
                f"  📌 Topik: _{r['topic']}_\n"
                f"  📊 Progres: {r['steps_done']}/{r['steps_total']} langkah\n"
                f"  🕒 Update: `{r['updated_at'][:19]}`\n\n"
            )
        text += "Gunakan `/resume <session_id>` untuk melanjutkan sesi."
        await safe_send_message(context, chat_id, text)
        return

    await safe_send_message(
        context,
        chat_id,
        f"🔄 **Melanjutkan sesi swarm `{session_id}` dari checkpoint...**",
    )
    from alfa.bot.progress import SwarmProgressReporter

    reporter = SwarmProgressReporter(context, chat_id, session_id, header="🔄 **Resume Swarm**")
    await reporter.start()
    try:
        from alfa.swarm import engine as swarm_engine

        result = await swarm_engine.resume_swarm_session(session_id)
        await reporter.stop("✅ Lanjutan selesai — hasil di bawah ⬇️")
        if result.get("status") == "error":
            await safe_send_message(
                context,
                chat_id,
                f"❌ Gagal resume: {result.get('message', 'Unknown error')}",
            )
            return

        steps = result.get("execution_results", [])
        steps_text = "⚡ **Hasil Lanjutan Sesi Swarm:**\n\n"
        for s in steps:
            steps_text += (
                f"{s.get('avatar_emoji', '🤖')} **{s['agent_name']}** ({s['role']})\n"
            )
            steps_text += f"   • Tool: `{s['tool_used']}`\n"
            steps_text += f"   • Output: _{s['execution_summary'][:200]}_\n\n"
        await safe_send_message(context, chat_id, steps_text)

        final_text = (
            f"🏆 **LAPORAN HASIL LANJUTAN EKSEKUSI:**\n\n{result.get('consensus', '')}"
        )
        await safe_send_message(context, chat_id, final_text)
    except _ADV_ERR as e:
        try:
            await reporter.stop("❌ Resume gagal.")
        except _ADV_ERR:
            pass
        logger.error(f"Error during /resume_swarm: {e}")
        await safe_send_message(
            context, chat_id, f"❌ Terjadi kesalahan saat resume: {str(e)}"
        )


async def ram_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ram atau /bersihkan — pantau dan optimalkan pemakaian RAM (ALFA Bot, Chromium, & WA Sheets Bot)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    from alfa.tools.system.management import system_clean_memory_and_cache

    do_recycle = False
    if context.args and any(a.lower() in ("wa", "restart", "full", "recycle") for a in context.args):
        do_recycle = True

    res = system_clean_memory_and_cache(recycle_wa_if_needed=do_recycle)
    sys_ram = res.get("system_ram", {})
    alfa_mb = res.get("alfa_bot_mb", 0)
    wa_mb = res.get("wa_sheets_bot_mb", 0)
    wa_procs = res.get("wa_process_count", 0)
    gc_objs = res.get("python_gc_objects_collected", 0)
    cleaned_tmp = res.get("cleaned_orphaned_tmp_dirs", 0)
    recycled = res.get("wa_recycled", False)

    lines = [
        "🧹 **Optimasi & Diagnostik Memori (RAM)**\n",
        f"🖥️ **Sistem:** {sys_ram.get('used_mb', 0)} MB / {sys_ram.get('total_mb', 0)} MB ({sys_ram.get('used_percent', 0)}% terpakai)",
        f"   • Tersedia: `{sys_ram.get('available_mb', 0)} MB`\n",
        f"🤖 **ALFA Python Bot:** `{alfa_mb} MB`",
        f"📱 **WA Sheets Bot & Chrome:** `{wa_mb} MB` ({wa_procs} proses)\n",
        "♻️ **Hasil Pembersihan:**",
        f"   • Python GC: {gc_objs} objek dibebaskan",
        f"   • Temp Chromium: {cleaned_tmp} direktori yatim dibersihkan",
    ]
    if recycled:
        lines.append("   • WA Sheets Bot: **Berhasil di-recycle & RAM di-reset fresh!** ✅")
    elif wa_mb > 1000:
        lines.append(f"\n⚠️ _Pemakaian RAM WA Bot cukup tinggi ({wa_mb} MB). Ketik `/ram full` untuk me-restart fresh._")

    await safe_send_message(context, chat_id, "\n".join(lines))
