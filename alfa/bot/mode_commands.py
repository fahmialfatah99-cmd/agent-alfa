"""Telegram mode & utility commands: single/swarm switcher + real feature menus.

Single mode  = satu agen otonom (run_agent_turn, chat biasa).
Swarm mode   = tim multi-agen (conduct_multi_agent_meeting, mode=execute).
Mode disimpan persisten di system_settings[telegram_exec_mode], default single.
"""

import asyncio
import logging
import os
import socket
import sqlite3
import subprocess
import sys
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from alfa.bot.config import is_authorized
from alfa.bot.helpers import safe_send_message
from alfa.core import database

logger = logging.getLogger("TelegramAIAgent")

_MODE_ERR = (
    TelegramError,
    sqlite3.Error,
    subprocess.SubprocessError,
    OSError,
    ValueError,
    RuntimeError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    LookupError,
)

MODE_KEY = "telegram_exec_mode"
VALID_MODES = ("single", "swarm")

# Cache baca mode di memori: tiap chat teks memanggil get_telegram_mode_sync,
# jadi JANGAN antre lock SQLite (bot live bisa menahan write berdetik-detik).
_MODE_CACHE: dict[str, Any] = {"value": "single", "ts": 0.0}
_MODE_TTL = 20.0
_MODE_FAIL_TTL = 5.0


def _get_bot_module():
    return sys.modules.get("alfa.bot.telegram_bot")


def _is_authorized(user_id: int) -> bool:
    mod = _get_bot_module()
    if mod and hasattr(mod, "is_authorized"):
        return bool(mod.is_authorized(user_id))
    return is_authorized(user_id)


def _read_mode_from_db() -> str | None:
    """Baca mode langsung via koneksi kilat (timeout 2 dtk, tanpa PRAGMA berat).

    Return None bila DB terkunci / error — pemanggil pakai cache/default.
    Sengaja TIDAK memakai database.get_sync_db (busy_timeout 30 dtk + WAL
    pragma bisa menghambat tiap pesan masuk saat bot live menulis DB).
    """
    import sqlite3

    try:
        from alfa.core.db.connection import _get_db_path

        db_path = _get_db_path()
        conn = sqlite3.connect(db_path, timeout=2.0)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = ?", (MODE_KEY,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return "single"
        mode = (row["value"] or "single").strip().lower()
        return mode if mode in VALID_MODES else "single"
    except _MODE_ERR:
        return None


def get_telegram_mode_sync() -> str:
    """Baca mode eksekusi Telegram persisten (default 'single').

    Cepat & anti-blokir: cache memori 20 dtk, fallback 'single' bila DB sibuk.
    """
    import time as _time

    now = _time.monotonic()
    if now - float(_MODE_CACHE["ts"]) < _MODE_TTL:
        return str(_MODE_CACHE["value"])
    mode = _read_mode_from_db()
    if mode is None:
        # DB sibuk: jangan antre — pakai nilai terakhir, cache singkat
        _MODE_CACHE["ts"] = now - max(0.0, _MODE_TTL - _MODE_FAIL_TTL)
        return str(_MODE_CACHE["value"])
    _MODE_CACHE["value"] = mode
    _MODE_CACHE["ts"] = now
    return mode


def set_telegram_mode_sync(mode: str) -> str:
    """Simpan mode eksekusi Telegram. Return mode final."""
    import time as _time

    mode = (mode or "").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"Mode tidak valid: {mode!r} (single|swarm)")
    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (MODE_KEY, mode),
        )
        conn.commit()
    _MODE_CACHE["value"] = mode
    _MODE_CACHE["ts"] = _time.monotonic()
    return mode


def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🧍 Single Agent", callback_data="btn_mode_single"),
                InlineKeyboardButton("⚡ Swarm Multi-Agent", callback_data="btn_mode_swarm"),
            ],
            [
                InlineKeyboardButton("📊 Status", callback_data="btn_status"),
                InlineKeyboardButton("❓ Bantuan", callback_data="btn_help"),
            ],
        ]
    )


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mode [single|swarm|status] — alih & lihat mode eksekusi."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    arg = " ".join(context.args).strip().lower() if context.args else ""
    current = get_telegram_mode_sync()

    if not arg or arg == "status":
        await safe_send_message(
            context,
            chat_id,
            f"🧭 **Mode Eksekusi Telegram:** `{current.upper()}`\n\n"
            "• *single* — 1 agen otonom cepat (chat biasa, tool ReAct).\n"
            "• *swarm* — seluruh tim agen berkolaborasi (dekomposisi → eksekusi paralel → QA).\n\n"
            "Ganti: `/mode single` atau `/mode swarm`",
            reply_markup=_mode_keyboard(),
        )
        return

    if arg in ("single", "solo", "1"):
        set_telegram_mode_sync("single")
        await safe_send_message(
            context,
            chat_id,
            "🧍 **Mode SINGLE aktif.** Chat biasa ditangani 1 agen otonom.\n"
            "Panggil swarm kapan saja via `/swarm <tugas>` tanpa pindah mode.",
            reply_markup=_mode_keyboard(),
        )
    elif arg in ("swarm", "multi", "team"):
        set_telegram_mode_sync("swarm")
        await safe_send_message(
            context,
            chat_id,
            "⚡ **Mode SWARM aktif.** Setiap chat teks dieksekusi tim multi-agen.\n"
            "Kembali: `/mode single`. Batalkan misi berjalan: `/cancel`.",
            reply_markup=_mode_keyboard(),
        )
    else:
        await safe_send_message(
            context, chat_id, "Usage: `/mode [single|swarm|status]`"
        )


async def _run_single_turn(user_id: int, prompt: str, chat_id: int) -> str:
    mod = _get_bot_module()
    fn = getattr(mod, "run_agent_turn", None) if mod else None
    if callable(fn):
        res: str = await fn(user_id=user_id, user_prompt=prompt, chat_id=chat_id)
        return res
    from alfa.bot.turn_executor import run_agent_turn

    return await run_agent_turn(user_id=user_id, user_prompt=prompt, chat_id=chat_id)


async def single_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/single [tugas] — tanpa arg: pindah ke single; dengan tugas: eksekusi single sekali."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    task = " ".join(context.args).strip() if context.args else ""
    if not task:
        set_telegram_mode_sync("single")
        await safe_send_message(
            context,
            chat_id,
            "🧍 **Mode SINGLE aktif.** Kirim chat / foto / voice / dokumen seperti biasa.\n"
            "Contoh sekali-jalan: `/single cari berita AI terkini`",
        )
        return

    await safe_send_message(
        context, chat_id, f"🧍 **Single Agent mengerjakan:** _{task}_\nMohon tunggu..."
    )
    try:
        reply = await _run_single_turn(user_id, task, chat_id)
    except _MODE_ERR as e:
        logger.error(f"/single gagal: {e}", exc_info=True)
        reply = f"❌ Single agent gagal: `{type(e).__name__}: {str(e)[:200]}`"
    await safe_send_message(context, chat_id, reply)


# --- Templat misi swarm siap pakai (sekali-jalan & terjadwal) ---------------
SWARM_TEMPLATES: dict[str, str] = {
    "audit-server": (
        "Audit kesehatan server: cek CPU, RAM, disk, suhu bila tersedia, "
        "daftar 5 proses pemakan RAM terbesar, status service "
        "telegram-ai-bot, wa-sheets-bot, alfa-dashboard, 9router, dan "
        "rangkum temuan + rekomendasi dalam Bahasa Indonesia"
    ),
    "laporan-harian": (
        "Buatkan laporan harian: ringkasan pemakaian token AI hari ini "
        "per provider, status semua service systemd, dan 3 catatan WA "
        "terbaru yang paling penting"
    ),
    "bersih-cache": (
        "Bersihkan file sampah dengan aman: /tmp/opencode yang lebih dari "
        "7 hari, artefak sandbox basi, dan log jurnal user yang lebih dari "
        "14 hari (vacuum). Jangan hapus database, .env, atau file kerja. "
        "Laporkan ruang yang dibebaskan"
    ),
    "cek-keamanan": (
        "Audit keamanan cepat: port TCP yang listen, login SSH gagal "
        "terbaru dari journal, file .env yang permission-nya longgar, "
        "dan kunci API yang duplikat/nonaktif di vault. Rangkum risiko"
    ),
    "rapikan-wa": (
        "Rapikan pencatatan WA: daftar format yang keyword-nya tumpang "
        "tindih atau tidak pernah memicu catatan, dan usulkan "
        "penggabungan. Jangan hapus apa pun tanpa konfirmasi"
    ),
    "audit-situs": (
        "Audit galeri situs hasil kerja: pakai tool list_managed_sites untuk "
        "daftar situs, verifikasi tiap situs (file entry masih ada & valid, "
        "port respons bila hidup), laporkan status tiap situs + masalahnya. "
        "DILARANG mematikan situs yang sedang hidup tanpa konfirmasi"
    ),
}


async def run_swarm_task(topic: str) -> dict:
    """Jalankan misi swarm execute. Return dict hasil engine (tanpa kirim pesan)."""
    from alfa.swarm import engine as swarm_engine

    return await swarm_engine.conduct_multi_agent_meeting(
        topic=topic, rounds=1, mode="execute"
    )


def format_swarm_result(result: dict) -> tuple[str, str, list[str]]:
    """Format (steps_text, final_text, files) dari dict hasil swarm engine."""
    steps = result.get("execution_results", []) or []
    if steps:
        lines = ["⚡ **Laporan Eksekusi Tiap Agen:**\n"]
        for s in steps:
            lines.append(
                f"{s.get('avatar_emoji', '🤖')} **{s.get('agent_name', '?')}**"
                f" ({s.get('role', '-')})\n"
                f"   • Tool: `{s.get('tool_used', '-')}`"
                + (f" ({s.get('duration_ms', 0)}ms)" if s.get("duration_ms") else "")
                + "\n"
                + f"   • Output: _{str(s.get('execution_summary', ''))[:200]}_\n"
            )
        steps_text = "\n".join(lines)
    else:
        steps_text = "⚠️ Swarm selesai tanpa langkah eksekusi tercatat."

    final_text = (
        "🏆 **LAPORAN HASIL EKSEKUSI NYATA:**\n\n"
        f"{result.get('consensus', '')}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 _Sesi: #{result.get('session_id') or result.get('meeting_id')} • "
        "tersimpan di Web Dashboard_"
    )
    files = [
        s.get("deliverable_file")
        for s in steps
        if s.get("deliverable_file") and os.path.exists(s.get("deliverable_file"))
    ]
    return steps_text, final_text, files


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — hentikan misi swarm atau giliran kerja agen yang sedang berjalan."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return
    try:
        from alfa.swarm import workspace_hygiene
        from alfa.swarm.workspace_hygiene import request_cancel_swarm

        cancelled_items: list[str] = []

        # 1. Batalkan async task yang aktif di chat ini (Single turn atau Swarm task)
        try:
            from alfa.bot.handlers import ACTIVE_CHAT_TASKS

            active_task = ACTIVE_CHAT_TASKS.get(chat_id)
            if active_task and not active_task.done():
                active_task.cancel()
                cancelled_items.append("proses agen aktif dibatalkan")
        except _MODE_ERR:
            pass

        # 2. Batalkan Swarm engine jika sedang berjalan
        if workspace_hygiene.MEETING_RUNNING or request_cancel_swarm():
            request_cancel_swarm()
            workspace_hygiene.MEETING_RUNNING = False
            cancelled_items.append("misi Swarm dihentikan")

        if cancelled_items:
            await safe_send_message(
                context,
                chat_id,
                f"⏹ **Berhasil dihentikan:** {', '.join(cancelled_items)}.",
            )
        else:
            await safe_send_message(
                context,
                chat_id,
                "ℹ️ Tidak ada proses atau misi yang sedang berjalan saat ini.",
            )
    except _MODE_ERR as e:
        await safe_send_message(context, chat_id, f"❌ Gagal membatalkan: `{e}`")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — ringkasan mode, swarm, agen, server, key."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    mode = get_telegram_mode_sync()
    lines = [f"🧭 **Mode:** `{mode.upper()}`"]

    try:
        from alfa.swarm.workspace_hygiene import MEETING_RUNNING

        lines.append(
            "⚡ **Swarm:** 🟢 BERJALAN" if MEETING_RUNNING else "⚡ **Swarm:** ⚪ idle"
        )
    except _MODE_ERR:
        lines.append("⚡ **Swarm:** ?")

    try:
        from alfa.swarm.llm_client import get_agent_api_client

        agents = database.list_custom_agents_sync()
        ok = sum(1 for a in agents if get_agent_api_client(a)[1])
        lines.append(f"🤖 **Agen:** {ok}/{len(agents)} punya key aktif")
    except _MODE_ERR as e:
        lines.append(f"🤖 **Agen:** ❌ (`{e}`)")

    try:
        keys = database.list_api_keys_sync(auto_sync=False)
        active = sum(1 for k in keys if k.get("is_active"))
        lines.append(f"🔑 **Vault:** {active}/{len(keys)} key aktif")
    except _MODE_ERR:
        lines.append("🔑 **Vault:** ?")

    dash = "🟢" if _port_open(8080) else "🔴"
    r9 = "🟢" if _port_open(20128) else "🔴"
    lines.append(f"🌐 **Dashboard :8080:** {dash}   🔀 **9Router :20128:** {r9}")
    lines.append("\n`/mode single|swarm` • `/swarm <tugas>` • `/cancel` • `/cekagen`")
    await safe_send_message(context, chat_id, "\n".join(lines))


async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tools — daftar tool real yang bisa dipakai agen (148)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return
    try:
        from alfa import tools as alfa_tools

        funcs = list(alfa_tools.AVAILABLE_TOOLS or [])
    except _MODE_ERR as e:
        await safe_send_message(context, chat_id, f"❌ Gagal memuat tools: `{e}`")
        return

    groups: dict[str, list[str]] = {}
    for fn in funcs:
        name = getattr(fn, "__name__", str(fn))
        mod = (getattr(fn, "__module__", "") or "").replace("alfa.tools.", "")
        groups.setdefault(mod or "core", []).append(name)

    lines = [f"🛠️ **Tools Aktif ({len(funcs)}):**\n"]
    for mod in sorted(groups):
        names = sorted(groups[mod])
        show = ", ".join(f"`{n}`" for n in names[:12])
        more = f" (+{len(names) - 12} lain)" if len(names) > 12 else ""
        lines.append(f"• **{mod}** ({len(names)}): {show}{more}")
    lines.append("\n💡 _Panggil via chat biasa, mis. 'screenshot desktop', 'cari berita AI'_")
    await safe_send_message(context, chat_id, "\n".join(lines))


async def persona_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/persona [nama|id|reset] — lihat/ganti persona single-mode."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    target = " ".join(context.args).strip() if context.args else ""
    agents = database.list_custom_agents_sync()

    if not target or target.lower() == "list":
        settings = await database.get_user_settings(user_id)
        cur = settings.get("system_prompt_override") or "(default orchestrator)"
        lines = [f"🎭 **Persona aktif:** _{str(cur)[:120]}_\n", "**Daftar agen:**"]
        for a in agents:
            on = "" if a.get("is_enabled", 1) else " (off)"
            lines.append(
                f"• #{a['id']} {a.get('avatar_emoji', '🤖')} **{a['name']}** — *{a.get('role', '')}*{on}"
            )
        lines.append("\nGanti: `/persona <nama|id>` • Reset: `/persona reset`")
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    if target.lower() in ("reset", "default", "none", "clear"):
        with database.get_sync_db() as conn:
            conn.execute(
                "INSERT INTO user_settings (user_id, voice_reply) VALUES (?, 0) "
                "ON CONFLICT(user_id) DO UPDATE SET system_prompt_override = NULL",
                (user_id,),
            )
            conn.commit()
        await safe_send_message(
            context, chat_id, "🎭 Persona di-reset ke default orchestrator."
        )
        return

    matched = None
    if target.isdigit():
        matched = next((a for a in agents if a.get("id") == int(target)), None)
    if not matched:
        tl = target.lower()
        matched = next(
            (a for a in agents if tl in (a.get("name", "") or "").lower()), None
        )
    if not matched:
        await safe_send_message(
            context, chat_id, f"❌ Persona '{target}' tidak ditemukan. `/persona list`"
        )
        return

    sys_inst = matched.get("system_instruction") or (
        f"Kamu adalah {matched.get('name')}, seorang {matched.get('role')}."
    )
    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, voice_reply, system_prompt_override, model_name) "
            "VALUES (?, 0, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET system_prompt_override = excluded.system_prompt_override, "
            "model_name = excluded.model_name",
            (user_id, sys_inst, matched.get("model", "gemini-3.5-flash")),
        )
        conn.commit()
    await safe_send_message(
        context,
        chat_id,
        f"🎭 **Persona aktif:** {matched.get('avatar_emoji', '🤖')} **{matched.get('name')}**\n"
        f"*{matched.get('role', '')}* — berlaku untuk chat single-mode berikutnya.",
    )


async def pipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pipeline [list|run <id>] — workflow DAG JSON (storage/pipelines)."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    args = list(context.args) if context.args else []
    sub = (args[0].lower() if args else "list")

    try:
        from alfa.pipelines import engine as pipe
    except _MODE_ERR as e:
        await safe_send_message(context, chat_id, f"❌ Pipeline engine gagal dimuat: `{e}`")
        return

    if sub == "list" or not args:
        pipes = pipe.list_pipelines()
        if not pipes:
            await safe_send_message(
                context, chat_id, "ℹ️ Belum ada pipeline di `storage/pipelines/`."
            )
            return
        lines = [f"🔁 **Pipeline ({len(pipes)}):**\n"]
        for p in pipes:
            lines.append(
                f"• `{p['id']}` — **{p.get('name', p['id'])}** ({p.get('steps', 0)} step)\n"
                f"  _{p.get('description', '')[:100]}_"
            )
        lines.append("\nJalankan: `/pipeline run <id>`")
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    if sub == "show":
        if len(args) < 2:
            await safe_send_message(context, chat_id, "Usage: `/pipeline show <id>`")
            return
        try:
            data = pipe.load_pipeline(args[1])
        except _MODE_ERR as e:
            await safe_send_message(context, chat_id, f"❌ Pipeline tak ditemukan: `{e}`")
            return
        lines = [f"🔁 **{data.get('name', data.get('id'))}** (`{data.get('id')}`)\n_{data.get('description', '')}_\n"]
        for s in data.get("steps", []):
            dep = f" ⟵ {','.join(s.get('depends_on', []))}" if s.get("depends_on") else ""
            lines.append(f"• `{s.get('id')}` [{s.get('type', '?')}] {s.get('tool', s.get('text', ''))[:60]}{dep}")
        if data.get("vars"):
            lines.append(f"\nVars: `{data['vars']}`")
        lines.append("\nJalankan: `/pipeline run <id> [kunci=nilai]`")
        await safe_send_message(context, chat_id, "\n".join(lines))
        return

    if sub == "run":
        if len(args) < 2:
            await safe_send_message(context, chat_id, "Usage: `/pipeline run <id> [kunci=nilai ...]`")
            return
        pid = args[1]
        overrides = {}
        for a in args[2:]:
            if "=" in a:
                k, v = a.split("=", 1)
                if k.strip():
                    overrides[k.strip()] = v.strip()
        await safe_send_message(
            context, chat_id, f"🔁 Menjalankan pipeline `{pid}`..."
            + (f" (vars: `{overrides}`)" if overrides else "")
        )
        try:
            res = await asyncio.wait_for(pipe.run_pipeline(pid, overrides or None), timeout=280)
        except asyncio.TimeoutError:
            await safe_send_message(
                context, chat_id, f"⏱ Pipeline `{pid}` melebihi 280 dtk — cek dashboard."
            )
            return
        except _MODE_ERR as e:
            await safe_send_message(
                context, chat_id, f"❌ Pipeline gagal: `{type(e).__name__}: {str(e)[:200]}`"
            )
            return
        status = res.get("status", "?")
        icon = "✅" if status == "success" else "❌"
        trace = res.get("trace", []) or []
        ok_steps = sum(1 for t in trace if t.get("status") == "ok")
        await safe_send_message(
            context,
            chat_id,
            f"{icon} **Pipeline `{pid}`: {status}** ({ok_steps}/{len(trace)} step ok)"
            + (f"\n`{res.get('error', '')[:300]}`" if res.get("error") else ""),
        )
        return

    await safe_send_message(context, chat_id, "Usage: `/pipeline [list|run <id> [k=v]|show <id>]`")


async def tugas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tugas — daftar background subagent + checkpoint swarm resumable."""
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if not _is_authorized(user_id):
        return

    lines = ["📋 **Tugas Latar & Sesi:**\n"]
    try:
        tasks = database.list_subagent_tasks_sync(limit=10)
        if not tasks:
            lines.append("• Subagent latar: _kosong_")
        else:
            for t in tasks:
                lines.append(
                    f"• `{t.get('id', '?')}` {t.get('task_description', '')[:80]} "
                    f"[{t.get('status', '?')}]"
                )
    except _MODE_ERR as e:
        lines.append(f"• Subagent: ❌ `{e}`")

    try:
        from alfa.swarm.checkpoint import SwarmCheckpoint

        resumable = SwarmCheckpoint.list_resumable()
        if resumable:
            lines.append(f"\n🔄 **Swarm resumable ({len(resumable)}):**")
            for r in resumable[:5]:
                lines.append(
                    f"• `{r['session_id']}` — _{str(r.get('topic', ''))[:60]}_ "
                    f"({r.get('steps_done', 0)}/{r.get('steps_total', '?')})"
                )
            lines.append("Lanjutkan: `/resume <session_id>`")
        else:
            lines.append("\n🔄 Swarm resumable: _tidak ada_")
    except _MODE_ERR:
        pass

    try:
        jobs = database.list_cron_jobs_sync(user_id)
        active = sum(1 for j in jobs if j.get("is_active"))
        lines.append(f"\n⏰ Cron: {active}/{len(jobs)} aktif (`/cron` detail)")
    except _MODE_ERR:
        pass
    await safe_send_message(context, chat_id, "\n".join(lines))


__all__ = [
    "MODE_KEY",
    "cancel_command",
    "format_swarm_result",
    "get_telegram_mode_sync",
    "handle_persona_callback",
    "mode_command",
    "persona_command",
    "pipeline_command",
    "render_persona_menu",
    "run_swarm_task",
    "set_telegram_mode_sync",
    "single_command",
    "status_command",
    "SWARM_TEMPLATES",
    "tools_command",
    "tugas_command",
]


async def render_persona_menu(update, context) -> None:
    """Menu persona interaktif: ketuk agen untuk mengaktifkan (edit di tempat)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.error import BadRequest

    query = update.callback_query
    user_id = update.effective_user.id
    agents = database.list_custom_agents_sync()
    settings = await database.get_user_settings(user_id)
    cur = (settings.get("system_prompt_override") or "")[:60]

    kb = []
    for a in agents:
        if not a.get("is_enabled", 1):
            continue
        label = f"{a.get('avatar_emoji', '🤖')} {a.get('name', '?')}"[:32]
        kb.append([InlineKeyboardButton(label, callback_data=f"px|set|{a.get('id')}")])
    kb.append([InlineKeyboardButton("↩️ Default Orchestrator", callback_data="px|reset")])
    kb.append([InlineKeyboardButton("◀️ Menu Utama", callback_data="btn_menu")])
    text = "🎭 **Pilih Persona Single-Mode:**" + (
        f"\nAktif: _{cur}…_" if cur and "default" not in cur.lower() else "\nAktif: _default orchestrator_"
    )
    try:
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    except BadRequest:
        pass
    except _MODE_ERR as e:
        logger.debug(f"[persona_menu] {e}")


async def handle_persona_callback(update, context) -> bool:
    """Router callback px|*. Return True bila ditangani."""
    query = update.callback_query
    if not query:
        return False
    data = query.data or ""
    if not data.startswith("px|"):
        return False
    if not _is_authorized(update.effective_user.id):
        await query.answer()
        return True
    await query.answer()
    parts = data.split("|")
    action = parts[1] if len(parts) > 1 else ""
    try:
        if action == "list":
            await render_persona_menu(update, context)
        elif action == "set" and len(parts) > 2:
            context.args = [parts[2]]
            await persona_command(update, context)
            await render_persona_menu(update, context)
        elif action == "reset":
            context.args = ["reset"]
            await persona_command(update, context)
            await render_persona_menu(update, context)
    except _MODE_ERR as e:
        logger.warning(f"[persona_menu] {e}")
    return True
