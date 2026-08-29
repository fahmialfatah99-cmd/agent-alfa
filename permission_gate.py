"""
PERMISSION GATE — human-in-the-loop untuk tool berbahaya.

Meniru UX OpenClaw: saat agent ingin memanggil tool sensitif, bot mengirim
InlineKeyboard ke Telegram (Izinkan / Izinkan Selalu / Tolak) dan menahan
eksekusi sampai pengguna memilih. Keputusan "Izinkan selalu" disimpan di
tabel tool_permissions sehingga turn berikutnya langsung lolos.

Konfigurasi .env:
    PERMISSION_GATE=on|off          (default on)
    PERMISSION_GATE_TIMEOUT=300     detik menunggu keputusan (auto-tolak)
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Dict, Optional

logger = logging.getLogger("PermissionGate")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_DIR, "agent_data.db")

PERMISSION_GATE_ENABLED = os.getenv("PERMISSION_GATE", "on").strip().lower() != "off"
APPROVAL_TIMEOUT = int(os.getenv("PERMISSION_GATE_TIMEOUT", "300"))

# ── Klasifikasi tool ─────────────────────────────────────────────────────────
# Tool yang menyentuh sistem/mesin secara destruktif atau sensitif.
GATED_TOOLS = {
    "execute_bash_command",
    "write_local_file",
    "edit_file_precise",
    "apply_unified_diff",
    "ssh_execute_command",
    "kill_process",
    "manage_system_services",
    "manage_crontab_jobs",
    "clean_system_storage",
    "control_linux_hardware",
    "query_database",
    "git_operations",
    "download_file_from_url",
    "desktop_click_coordinate",
    "desktop_type_keys",
    "desktop_launch_app",
    "vision_click_target",
    "record_desktop_screen",
    "capture_webcam_frame",
    "scan_local_network",
    "auto_diagnose_and_heal_system",
}

# Tool read-only/riset yang selalu otomatis lolos tanpa tanya.
SAFE_TOOLS = {
    "web_search", "fetch_web_page_content", "deep_research_topic",
    "read_local_file", "search_workspace_files", "grep_workspace",
    "find_user_files",
    "index_codebase", "search_codebase",
    "save_knowledge_memory", "search_knowledge_memory",
    "get_system_stats", "get_current_user_id", "get_current_chat_id",
    "capture_desktop_screenshot", "list_running_processes",
    "generate_secure_password", "translate_text", "token_usage_query",
}

_LABELS = {
    "once": "✅ Diizinkan (sekali ini)",
    "always": "🔁 Diizinkan SELALU untuk sesi mendatang",
    "deny": "❌ Ditolak oleh pengguna",
    "timeout": "⏰ Auto-ditolak (tidak ada respons)",
}


# ── Penyimpanan aturan 'selalu izinkan' ──────────────────────────────────────
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tool_permissions(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               created_at REAL,
               UNIQUE(chat_id, tool_name))""")
    return conn


def is_always_allowed(chat_id: Optional[int], tool_name: str) -> bool:
    if chat_id is None:
        return False
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM tool_permissions WHERE chat_id=? AND tool_name=?",
                (int(chat_id), tool_name)).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"cek tool_permissions gagal (lolos-aman): {e}")
        return False


def save_always_allow(chat_id: int, tool_name: str) -> None:
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tool_permissions(chat_id, tool_name, created_at) "
                "VALUES (?,?,?)", (int(chat_id), tool_name, time.time()))
    except Exception as e:
        logger.warning(f"simpan tool_permissions gagal: {e}")


def list_always_allowed(chat_id: int):
    try:
        with _connect() as conn:
            return [r[0] for r in conn.execute(
                "SELECT tool_name FROM tool_permissions WHERE chat_id=? ORDER BY tool_name",
                (int(chat_id),)).fetchall()]
    except Exception:
        return []


# ── Registry permintaan yang menunggu keputusan ──────────────────────────────
_PENDING: Dict[str, dict] = {}


def is_enabled() -> bool:
    return PERMISSION_GATE_ENABLED


def make_gate(chat_id: Optional[int]):
    """Kembalikan closure async gate(tool_name, args_json)->Optional[str].
    Return None = boleh jalan; str = pesan penolakan utk dimakan model."""
    if not PERMISSION_GATE_ENABLED or chat_id is None:
        return None

    async def gate(tool_name: str, arguments_json: str = "{}") -> Optional[str]:
        return await request_approval(tool_name, arguments_json, chat_id)

    return gate


async def request_approval(tool_name: str, arguments_json: str = "{}",
                           chat_id: int = None) -> Optional[str]:
    """Tanya izin ke pengguna via tombol Telegram.
    Return None bila diizinkan; string penolakan bila ditolak/timeout."""
    if not PERMISSION_GATE_ENABLED or chat_id is None:
        return None
    if tool_name not in GATED_TOOLS:
        return None
    if is_always_allowed(chat_id, tool_name):
        return None

    # Ringkas argumen agar enak dibaca di tombol/pesan
    try:
        args = json.loads(arguments_json or "{}")
        preview_parts = []
        for k, v in list(args.items())[:3]:
            s = str(v).replace("\n", " ")
            if len(s) > 120:
                s = s[:117] + "..."
            preview_parts.append(f"• {k}: {s}")
        arg_preview = "\n".join(preview_parts) if preview_parts else "(tanpa argumen)"
    except Exception:
        arg_preview = str(arguments_json)[:300]

    req_id = uuid.uuid4().hex[:10]
    ev = asyncio.Event()
    _PENDING[req_id] = {"event": ev, "decision": "", "chat_id": int(chat_id)}

    keyboard = [
        [
            ("✅ Izinkan", "once"),
            ("🔁 Izinkan Selalu", "always"),
            ("❌ Tolak", "deny"),
        ]
    ]

    sent_message = None
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        from subagents import get_telegram_app
        app = get_telegram_app()
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(text, callback_data=f"perm|{req_id}|{act}")
            for text, act in row] for row in keyboard])
        sent_message = await app.bot.send_message(
            chat_id=int(chat_id),
            text=(
                "🔐 *PERMINTAAN IZIN AGENT*\n\n"
                f"🛠 Tool: `{tool_name}`\n"
                f"{arg_preview}\n\n"
                "Agent butuh persetujuanmu untuk melanjutkan."
            ),
            reply_markup=markup,
        )
    except Exception as e:
        logger.warning(
            f"Gagal kirim keyboard izin ({e}) -> penolakan aman (fail-closed).")
        _PENDING.pop(req_id, None)
        fail_mode = os.getenv("PERMISSION_GATE_FAIL_MODE", "deny").strip().lower()
        if fail_mode == "allow":
            return None
        return (
            f"[IZIN DITOLAK] Tool '{tool_name}' tergolong sensitif dan membutuhkan "
            f"konfirmasi izin langsung dari pemilik, tetapi notifikasi Telegram tidak dapat dikirim ({e}). "
            f"Eksekusi dibatalkan demi keamanan."
        )

    # Tunggu keputusan pengguna
    decision = "timeout"
    try:
        await asyncio.wait_for(ev.wait(), timeout=APPROVAL_TIMEOUT)
        decision = _PENDING.get(req_id, {}).get("decision") or "timeout"
    except asyncio.TimeoutError:
        pass
    finally:
        _PENDING.pop(req_id, None)

    label = _LABELS.get(decision, decision)
    if sent_message is not None:
        try:
            from subagents import get_telegram_app
            app = get_telegram_app()
            base_text = sent_message.text or ""
            await app.bot.edit_message_text(
                chat_id=int(chat_id), message_id=sent_message.message_id,
                text=f"{base_text}\n\n→ {label}")
        except Exception as e:
            logger.debug(f"edit pesan izin gagal (abaikan): {e}")

    if decision == "always":
        save_always_allow(int(chat_id), tool_name)
        logger.info(f"[Gate] {tool_name} -> ALWAYS ALLOW utk chat {chat_id}")
        return None
    if decision == "once":
        logger.info(f"[Gate] {tool_name} -> allow sekali (chat {chat_id})")
        return None

    logger.info(f"[Gate] {tool_name} -> DENIED ({decision}, chat {chat_id})")
    return (
        f"[DITOLAK USER] Pengguna menolak eksekusi tool '{tool_name}' "
        f"(alasan: {label}). Jangan coba lagi dengan cara yang sama untuk "
        f"permintaan ini; tanyakan alternatif kepada pengguna."
    )


async def handle_permission_callback(update, context) -> None:
    """Handler CallbackQueryHandler utk data 'perm|<req_id>|<decision>'."""
    query = update.callback_query
    try:
        _, req_id, decision = query.data.split("|", 2)
    except Exception:
        await query.answer()
        return

    entry = _PENDING.get(req_id)
    if not entry:
        await query.answer("Permintaan sudah kedaluwarsa.", show_alert=False)
        return

    # Hanya pemilik chat yang boleh memutuskan
    try:
        if int(query.from_user.id) != entry["chat_id"]:
            await query.answer("Bukan permintaan untuk kamu.", show_alert=True)
            return
    except Exception:
        pass

    entry["decision"] = decision
    entry["event"].set()
    try:
        await query.answer(_LABELS.get(decision, decision))
    except Exception:
        pass


def wrap_tool_for_afc(fn):
    """Bungkus fungsi tool sinkron menjadi async + gate — dipakai jalur
    Gemini AFC manual bila diperlukan (reserved)."""
    import functools

    name = getattr(fn, "__name__", "")

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        denial = await request_approval(name, json.dumps(kwargs, default=str))
        if denial:
            return denial
        return fn(*args, **kwargs)

    return wrapper
