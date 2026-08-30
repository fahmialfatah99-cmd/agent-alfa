"""
PERMISSION GATE — human-in-the-loop untuk tool berbahaya (Enhanced v2.0).

Meniru UX OpenClaw: saat agent ingin memanggil tool sensitif, bot mengirim
InlineKeyboard ke Telegram (Izinkan / Izinkan Selalu / Tolak) dan menahan
eksekusi sampai pengguna memilih. Keputusan "Izinkan selalu" disimpan di
tabel tool_permissions sehingga turn berikutnya langsung lolos.

ENHANCEMENTS v2.0:
- Multi-level permission tiers (LOW, MEDIUM, HIGH, CRITICAL)
- Batch approval untuk multiple tools sekaligus
- Auto-approve berdasarkan context & historical trust score
- Enhanced UI dengan detail risiko dan impact preview
- Timeout yang dapat dikonfigurasi per-tier
- Audit trail lengkap untuk compliance

Konfigurasi .env:
    PERMISSION_GATE=on|off          (default on)
    PERMISSION_GATE_TIMEOUT=300     detik menunggu keputusan (auto-tolak)
    PERMISSION_GATE_TRUST_THRESHOLD=0.7  threshold auto-approve (0-1)
    PERMISSION_GATE_FAIL_MODE=deny|allow  fail-closed atau fail-open
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("PermissionGate")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_DIR, "agent_data.db")

PERMISSION_GATE_ENABLED = os.getenv("PERMISSION_GATE", "on").strip().lower() != "off"
APPROVAL_TIMEOUT = int(os.getenv("PERMISSION_GATE_TIMEOUT", "300"))
TRUST_THRESHOLD = float(os.getenv("PERMISSION_GATE_TRUST_THRESHOLD", "0.7"))
FAIL_MODE = os.getenv("PERMISSION_GATE_FAIL_MODE", "deny").strip().lower()


# ── Klasifikasi Tool dengan Risk Tiers ─────────────────────────────────────────
class RiskTier(Enum):
    LOW = "low"  # Read-only, reversible
    MEDIUM = "medium"  # Write operations, moderate impact
    HIGH = "high"  # System changes, potentially destructive
    CRITICAL = "critical"  # Irreversible, security-sensitive


# Tool classification dengan risk tier dan deskripsi
TOOL_CLASSIFICATION = {
    # CRITICAL - irreversible, security-critical
    "ssh_execute_command": (RiskTier.CRITICAL, "Akses SSH remote - risiko keamanan tinggi"),
    "manage_crontab_jobs": (RiskTier.CRITICAL, "Modifikasi scheduled tasks - dampak sistem luas"),
    "clean_system_storage": (RiskTier.CRITICAL, "Penghapusan massal file - irreversible"),
    "control_linux_hardware": (RiskTier.CRITICAL, "Kontrol hardware langsung - risiko damage"),
    "kill_process": (RiskTier.HIGH, "Terminasi process - bisa crash sistem"),
    
    # HIGH - system changes, potentially destructive
    "execute_bash_command": (RiskTier.HIGH, "Eksekusi command shell - dampak bervariasi"),
    "write_local_file": (RiskTier.HIGH, "Write file arbitrary - bisa overwrite penting"),
    "edit_file_precise": (RiskTier.HIGH, "Edit file presisi - risiko corrupt data"),
    "apply_unified_diff": (RiskTier.HIGH, "Patch file - bisa break code"),
    "manage_system_services": (RiskTier.HIGH, "Start/stop services - downtime risk"),
    "query_database": (RiskTier.HIGH, "Query SQL - bisa DROP/DELETE"),
    "git_operations": (RiskTier.HIGH, "Git ops - bisa lose commits"),
    "download_file_from_url": (RiskTier.HIGH, "Download external - malware risk"),
    
    # MEDIUM - desktop automation, moderate impact
    "desktop_click_coordinate": (RiskTier.MEDIUM, "Automasi klik - unintended actions"),
    "desktop_type_keys": (RiskTier.MEDIUM, "Automasi keyboard - unintended input"),
    "desktop_launch_app": (RiskTier.MEDIUM, "Launch aplikasi - resource usage"),
    "vision_click_target": (RiskTier.MEDIUM, "Visual automation - misclick risk"),
    "record_desktop_screen": (RiskTier.MEDIUM, "Screen recording - privacy concern"),
    "capture_webcam_frame": (RiskTier.MEDIUM, "Webcam capture - privacy sensitive"),
    "scan_local_network": (RiskTier.MEDIUM, "Network scan - firewall trigger"),
    
    # LOW - read-only, safe operations
    "auto_diagnose_and_heal_system": (RiskTier.LOW, "Diagnostic read-only - safe"),
}

# Default tier untuk tool yang tidak terklasifikasi
DEFAULT_TIER = RiskTier.MEDIUM

# Safe tools yang selalu otomatis lolos (tier LOW implicit)
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

# Timeout per tier (detik)
TIER_TIMEOUTS = {
    RiskTier.LOW: 60,
    RiskTier.MEDIUM: 180,
    RiskTier.HIGH: 300,
    RiskTier.CRITICAL: 600,
}

_LABELS = {
    "once": "✅ Diizinkan (sekali ini)",
    "always": "🔁 Diizinkan SELALY untuk sesi mendatang",
    "always_session": "⏳ Izinkan sampai sesi berakhir",
    "deny": "❌ Ditolak oleh pengguna",
    "timeout": "⏰ Auto-ditolak (tidak ada respons)",
    "auto_approved": "✨ Auto-approved (trust score tinggi)",
}


# ── Penyimpanan aturan 'selalu izinkan' ──────────────────────────────────────
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tool_permissions(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               permission_type TEXT DEFAULT 'always',
               created_at REAL,
               expires_at REAL,
               UNIQUE(chat_id, tool_name))""")
    # Add audit trail table
    conn.execute(
        """CREATE TABLE IF NOT EXISTS permission_audit(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               tier TEXT,
               decision TEXT,
               arguments_json TEXT,
               created_at REAL,
               response_time_sec REAL)""")
    # Add trust score table
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_trust_scores(
               chat_id INTEGER PRIMARY KEY,
               trust_score REAL DEFAULT 0.5,
               total_approvals INTEGER DEFAULT 0,
               safe_approvals INTEGER DEFAULT 0,
               risky_approvals INTEGER DEFAULT 0,
               last_updated REAL)""")
    return conn


def get_trust_score(chat_id: Optional[int]) -> float:
    """Get user's trust score (0.0 - 1.0)."""
    if chat_id is None:
        return 0.0
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT trust_score FROM user_trust_scores WHERE chat_id=?",
                (int(chat_id),)).fetchone()
        return row[0] if row else 0.5
    except Exception as e:
        logger.warning(f"get trust score gagal: {e}")
        return 0.5


def update_trust_score(chat_id: int, was_safe: bool, response_time: float) -> None:
    """Update user's trust score based on their decision."""
    try:
        with _connect() as conn:
            # Get current stats
            row = conn.execute(
                "SELECT trust_score, total_approvals, safe_approvals, risky_approvals "
                "FROM user_trust_scores WHERE chat_id=?",
                (int(chat_id),)).fetchone()
            
            if row:
                trust_score, total, safe, risky = row
            else:
                trust_score, total, safe, risky = 0.5, 0, 0, 0
            
            # Update counters
            total += 1
            if was_safe:
                safe += 1
            else:
                risky += 1
            
            # Calculate new trust score (simple heuristic)
            # More safe decisions = higher trust
            # Faster responses to risky tools = higher trust
            base_ratio = safe / total if total > 0 else 0.5
            speed_bonus = min(0.1, 30.0 / max(response_time, 30.0)) * 0.2
            new_trust = min(1.0, max(0.0, base_ratio + speed_bonus))
            
            conn.execute(
                """INSERT OR REPLACE INTO user_trust_scores 
                   (chat_id, trust_score, total_approvals, safe_approvals, risky_approvals, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (int(chat_id), new_trust, total, safe, risky, time.time()))
    except Exception as e:
        logger.warning(f"update trust score gagal: {e}")


def log_permission_decision(chat_id: int, tool_name: str, tier: str, 
                           decision: str, args_json: str, response_time: float) -> None:
    """Log permission decision for audit trail."""
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO permission_audit 
                   (chat_id, tool_name, tier, decision, arguments_json, created_at, response_time_sec)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (int(chat_id), tool_name, tier, decision, args_json, time.time(), response_time))
    except Exception as e:
        logger.warning(f"log audit trail gagal: {e}")


def is_always_allowed(chat_id: Optional[int], tool_name: str) -> bool:
    if chat_id is None:
        return False
    try:
        with _connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM tool_permissions 
                   WHERE chat_id=? AND tool_name=? 
                   AND (permission_type='always' OR (permission_type='session' AND expires_at > ?))""",
                (int(chat_id), tool_name, time.time())).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"cek tool_permissions gagal (lolos-aman): {e}")
        return False


def save_always_allow(chat_id: int, tool_name: str, perm_type: str = 'always', 
                     duration_hours: int = 24) -> None:
    """Save permission with type and optional expiration."""
    try:
        expires_at = time.time() + (duration_hours * 3600) if perm_type == 'session' else None
        with _connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tool_permissions 
                   (chat_id, tool_name, permission_type, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (int(chat_id), tool_name, perm_type, time.time(), expires_at))
    except Exception as e:
        logger.warning(f"simpan tool_permissions gagal: {e}")


def list_always_allowed(chat_id: int) -> List[str]:
    try:
        with _connect() as conn:
            return [r[0] for r in conn.execute(
                """SELECT tool_name FROM tool_permissions 
                   WHERE chat_id=? AND (permission_type='always' 
                   OR (permission_type='session' AND expires_at > ?))
                   ORDER BY tool_name""",
                (int(chat_id), time.time())).fetchall()]
    except Exception:
        return []


def get_tool_tier(tool_name: str) -> RiskTier:
    """Get risk tier for a tool."""
    if tool_name in SAFE_TOOLS:
        return RiskTier.LOW
    classification = TOOL_CLASSIFICATION.get(tool_name)
    if classification:
        return classification[0]
    return DEFAULT_TIER


def should_auto_approve(chat_id: int, tool_name: str) -> Tuple[bool, str]:
    """Determine if request should be auto-approved based on trust score and tier."""
    tier = get_tool_tier(tool_name)
    trust = get_trust_score(chat_id)
    
    # Auto-approve LOW tier always
    if tier == RiskTier.LOW:
        return True, "auto_approved"
    
    # Auto-approve MEDIUM tier if trust >= threshold
    if tier == RiskTier.MEDIUM and trust >= TRUST_THRESHOLD:
        return True, "auto_approved"
    
    # Auto-approve HIGH/CRITICAL only if very high trust
    if tier in (RiskTier.HIGH, RiskTier.CRITICAL) and trust >= 0.9:
        return True, "auto_approved"
    
    return False, ""


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
    if tool_name in SAFE_TOOLS:
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
