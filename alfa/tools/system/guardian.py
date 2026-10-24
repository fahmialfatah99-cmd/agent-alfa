"""Penjaga Harian — lapor kesehatan sistem/WA/CI/aktivitas ALFA — tanpa diminta.

Additive-only & read-only: TIDAK mengubah satu alur lama.
- Laporan harian: tool ``guardian_daily_report`` (kolektor) + jadwal cron
  memakai infra ``scheduled_cron_jobs`` yang sudah hidup (pola briefing).
- Peringatan segera: loop native ``guardian_wa_watchdog_loop`` pada proses
  telegram (TANPA LLM) — WA kain online tidak normal beruntun -> kirim
  peringatan SEKALI per gelombang (cooldown).

Semua kolektor gagal-lembut: satu-sumber mati tak pernah mematikan
laporan (zero-regression). Sesi WA tidak pernah disentuh satu byte.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from alfa.core.db.connection import get_sync_db
from alfa.tools.registry import register_tool

logger = logging.getLogger("Tools.Guardian")

_UNITS = (
    "telegram-ai-bot.service",
    "alfa-dashboard.service",
    "alfa-discord-bot.service",
    "wa-sheets-bot.service",
)
_GUARDIAN_TITLE = "Penjaga Harian (sistem+WA+CI)"
_WA_OK_STATES = {"READY", "CONNECTED"}
_ERR_PATTERN = re.compile(r"\b(error|fatal|traceback|exception)\b", re.IGNORECASE)
_NOISE_PATTERN = re.compile(
    r"NetworkError|httpx|httpcore|ReadError|ReadTimeout|ConnectionReset|"
    r"RemoteProtocol|Remote end closed|timed out|ConnectError|"
    r"Temporary failure|name resolution|getaddrinfo|Errno -\d+|"
    r"Too Many Requests|RetryAfter|Bad Gateway|50[23]",
    re.IGNORECASE,
)
_BOOT_WAIT_S = 240  # diam dulu sebelum watch aktif (hindari false alarm boot)


class WaWatchState:
    """Kalkulasi kapan peringatan WA harus dikirim (threshold + cooldown)."""

    def __init__(self, threshold: int = 2, cooldown_s: int = 3600):
        self.threshold = max(1, int(threshold))
        self.cooldown_s = int(cooldown_s)
        self._streak = 0
        self._last_fired = 0.0
        self._fired_once = False

    def evaluate(self, is_ok: bool, now_ts: float | None = None) -> bool:
        """True HANYA saat gagal beruntun mencapai threshold & bukan cooldown."""
        now = now_ts if now_ts is not None else time.monotonic()
        if is_ok:
            self._streak = 0
            return False
        self._streak += 1
        cooldown_ok = not self._fired_once or (
            now - self._last_fired >= self.cooldown_s
        )
        if self._streak >= self.threshold and cooldown_ok:
            self._fired_once = True
            self._last_fired = now
            return True
        return False

    def reset(self) -> None:
        self._streak = 0

    @property
    def streak(self) -> int:
        return self._streak


def _run_cmd(args: list[str], timeout: float = 10.0) -> str:
    """Perintah pendek baca-saja; gagal atau timeout -> string kosong."""
    try:
        proc = subprocess.run(  # nosec B603/B604 — argv tetap, tanpa shell
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
        return (proc.stdout or "").strip()
    except Exception:  # noqa: BLE001 — kolektor wajib gagal-lembut
        return ""


def _collect_services() -> dict[str, str]:
    out: dict[str, str] = {}
    for unit in _UNITS:
        name = unit.replace(".service", "")
        out[name] = (
            _run_cmd(["systemctl", "--user", "is-active", unit], 4.0) or "unknown"
        )
    return out


def _classify_services(states: dict[str, str]) -> tuple[list[str], list[str]]:
    """Balik (crit_list, warn_list): inactive/failed = crit, unknown = warn."""
    crit: list[str] = []
    warn: list[str] = []
    for name, state in states.items():
        if state in ("active", "activating"):
            continue
        (crit if state not in ("unknown", "inactive") else warn).append(
            f"{name}={state}"
        )
    return crit, warn


def _collect_wa() -> dict[str, Any]:
    try:
        from alfa.tools.system.integrations import wa_get_incoming

        # mark_as_read=False: PENJAGA TIDAK PERNAH menandai baca (read-only).
        snap = wa_get_incoming(limit=3, only_unread=False, mark_as_read=False)
        client = str(snap.get("client_status") or "").upper()
        if not client and snap.get("is_ready"):
            client = "READY"
        return {
            "client": client or "TIDAK-DIKETAHUI",
            "buffer": len(snap.get("incoming") or []),
            "is_ready": bool(snap.get("is_ready")),
        }
    except Exception as exc:  # noqa: BLE001 — WA gagal tak mematikan laporan
        return {"client": "ERROR", "buffer": 0, "is_ready": False,
                "detail": str(exc)[:100]}


def _collect_archive_growth() -> dict[str, Any]:
    try:
        cutoff = int(time.time()) - 86400
        with get_sync_db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM wa_incoming_archive"
            ).fetchone()[0]
            day = conn.execute(
                "SELECT COUNT(*) FROM wa_incoming_archive WHERE msg_ts >= ?",
                (cutoff,),
            ).fetchone()[0]
        return {"total": int(total), "last_24h": int(day)}
    except Exception as exc:  # noqa: BLE001 — gagal-lembut
        return {"total": -1, "last_24h": 0, "detail": str(exc)[:80]}


def _classify_journal(lines: list[str]) -> tuple[int, int]:
    """Pisahkan (red, noise) dgn pengliatan konteks blok traceback.

    Baris 'Traceback (most recent call last):' milik keluarga jaringan-net
    (httpx/NetworkError, dsb.) dianggap noise; fatal betulan tetap merah.
    """
    noise_idx = {
        i for i, ln in enumerate(lines) if _NOISE_PATTERN.search(ln)
    }
    red = 0
    noise = 0
    for i, ln in enumerate(lines):
        if not _ERR_PATTERN.search(ln):
            continue
        if i in noise_idx:
            noise += 1
            continue
        if ln.lstrip().startswith("Traceback"):
            if any(j in noise_idx for j in range(i, min(len(lines), i + 60))):
                noise += 1
                continue
        if "raise " in ln or "direct cause" in ln or "handling an update" in ln:
            if any(j in noise_idx for j in range(max(0, i - 60), i + 1)):
                noise += 1
                continue
        red += 1
    return red, noise


def _collect_journal_errors() -> dict[str, dict[str, int]]:
    """Hitung baris merah 24 jam per unit, dipisah dari guncangan jaringan.

    Guncangan transit (httpx/NetworkError/timed-out) TIDAK dihitung red —
    itu noise net yang sering; hanya keramat nyata yang bikin laporan lantang.
    """
    result: dict[str, dict[str, int]] = {}
    for unit in _UNITS:
        name = unit.replace(".service", "")
        text = _run_cmd(
            ["journalctl", "--user", "-u", unit, "--since", "-24 hours",
             "-o", "cat", "--no-pager"],
            12.0,
        )
        tail = text[-200_000:]  # ekor saja: kuncing jernal bisa panjang
        red, noise = _classify_journal(tail.splitlines())
        result[name] = {"red": red, "noise": noise}
    return result


def _collect_run_activity() -> dict[str, Any]:
    try:
        from alfa.core.db.run_trace import list_runs_sync

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = [
            r
            for r in list_runs_sync(limit=80, kind="swarm_meeting")
            if str(r.get("started_at") or "")[:10] == today
        ]
        total_steps = sum(
            int((r.get("summary") or {}).get("steps") or 0) for r in rows
        )
        error_runs = sum(1 for r in rows if (r.get("status") or "") != "ok")
        return {
            "runs_today": len(rows),
            "steps": total_steps,
            "error_runs": error_runs,
        }
    except Exception as exc:  # noqa: BLE001 — gagal-lembut
        return {"runs_today": -1, "steps": 0, "error_runs": 0,
                "detail": str(exc)[:80]}


def _collect_ci() -> dict[str, str]:
    repo = os.getenv("ALFA_GH_REPO", "fahmialfatah99-cmd/agent-alfa").strip()
    conclusion = _run_cmd(
        ["gh", "run", "list", "--repo", repo, "--limit", "1",
         "--json", "conclusion", "--jq", ".[0].conclusion"],
        12.0,
    )
    return {"last_ci": conclusion or "unavailable"}


def _primary_chat_id() -> int:
    """ID chat pemilik (entri pertama ALLOWED_USER_IDS yang sah)."""
    raw = (os.getenv("ALLOWED_USER_IDS") or "").strip()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            return int(part)
    return 0


def build_guardian_report() -> dict[str, Any]:
    """Kumpulkan semua sinyal baca-saja; bangun laporan Penjaga Harian."""
    services = _collect_services()
    wa = _collect_wa()
    archive = _collect_archive_growth()
    journals = _collect_journal_errors()
    runs = _collect_run_activity()
    ci = _collect_ci()

    crits, warns = _classify_services(services)

    total_noise = 0

    wa_client = str(wa.get("client") or "")
    wa_ok = wa_client in _WA_OK_STATES
    if not wa_ok and wa_client != "TIDAK-DIKETAHUI":
        crits.append(f"WA={wa_client}")
    elif wa_client == "TIDAK-DIKETAHUI":
        warns.append("status WA tidak terbaca")

    for name, jc in journals.items():
        red_n = int(jc.get("red", 0))
        noise_n = int(jc.get("noise", 0))
        if red_n >= 10:
            warns.append(f"red journal 24 jam {name}: {red_n} baris")
        total_noise += noise_n

    if runs.get("error_runs", 0) > 0:
        warns.append(f"{runs['error_runs']} run ALFA gagal hari ini")
    if ci.get("last_ci") not in ("success", "unavailable"):
        warns.append(f"CI terakhir: {ci.get('last_ci')}")

    if crits:
        overall = "crit"
    elif warns:
        overall = "warn"
    else:
        overall = "healthy"

    emoji = {"healthy": "🤙", "warn": "🫡", "crit": "🚨"}[overall]
    lines = [
        f"{emoji} *PENJAGA HARIAN — {datetime.now().strftime('%a %d %b %Y')}*",
        "",
        "🧅 *Layanan:* " + " | ".join(f"{n}={s}" for n, s in services.items()),
        (
            f"💬 *WA:* {wa_client or 'TIDAK-DIKETAHUI'} | buffer {wa.get('buffer')} | "
            f"arsip +{archive.get('last_24h', 0)}/24jam "
            f"(total {archive.get('total', '?')})"
        ),
        (
            "🩸 *Red journal 24 jam:* "
            + (", ".join(
                f"{n}={jc['red']}" for n, jc in journals.items() if jc["red"] > 0
            ) or "bersih semua")
            + (f" | guncangan net {total_noise}" if total_noise else "")
        ),
        (
            f"🧠 *Aktivitas ALFA hari ini:* {runs.get('runs_today', '?')} rapat, "
            f"{runs.get('steps', 0)} langkah, {runs.get('error_runs', 0)} gagal"
        ),
        f"🧪 *CI commit terakhir:* {ci.get('last_ci')}",
    ]
    if crits or warns:
        lines.append("")
        if crits:
            lines.append("🔴 *KRITIS:* " + "; ".join(crits))
        if warns:
            lines.append("⚠️ *Catatan:* " + "; ".join(warns))
    verdict = {
        "healthy": "Semua waras — lanjut kerja.",
        "warn": "Ada yang layak Anda intip, tapi tidak darurat.",
        "crit": "SEGERA intip — ada layanan utama/WA yang berhenti.",
    }[overall]
    lines.append("")
    lines.append(f"{emoji} Kesimpulan: {verdict}")

    return {
        "status": "ok",
        "overall": overall,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "services": services,
        "wa": wa,
        "archive": archive,
        "journal_errors": journals,
        "runs_today": runs,
        "ci": ci,
        "text": "\n".join(lines),
    }


def build_wa_alert_text(
    wa: dict[str, Any], services: dict[str, str] | None = None
) -> str:
    """Teks peringatan WA segera (dipanggil watchdog saat threshold tembus)."""
    st = wa.get("client") or "TIDAK-DIKETAHUI"
    extra = ""
    if services:
        crit, _warn = _classify_services(services)
        if crit:
            extra = f" | layanan jebol juga: {', '.join(crit)}"
    return (
        "🚨 *PERINGATAN WA*\n"
        f"Klien WhatsApp berstatus *{st}* beruntun.\n"
        "Cek `journalctl --user -u wa-sheets-bot -n 30` bila respons bot aneh; "
        "restart TIDAK menghapus sesi."
    ) + extra


def _watch_interval_s() -> float:
    try:
        minutes = float(os.getenv("ALFA_GUARDIAN_WATCH_MINUTES", "20") or 20)
        return max(300.0, minutes * 60)
    except (TypeError, ValueError):
        return 1200.0


async def guardian_watch_check_once(
    application: Any,
    state: WaWatchState,
    snapshot: dict[str, Any] | None = None,
    services: dict[str, str] | None = None,
) -> bool:
    """Sekali deteksi (+ kirim peringatan bila harus). Uji-tanpa-I/O-friendly."""
    from alfa.bot.helpers import safe_send_message

    data = snapshot if snapshot is not None else _collect_wa()
    ok = data.get("client") in _WA_OK_STATES
    fired = state.evaluate(ok)
    if not fired:
        return False
    chat_id = _primary_chat_id()
    if not chat_id:
        logger.warning("Penjaga WA: ALLOWED_USER_IDS kosong — alert tak terkirim.")
        return True
    try:
        await safe_send_message(
            application, chat_id, build_wa_alert_text(data, services)
        )
    except Exception as exc:  # noqa: BLE001 — alarm tak boleh mematikan loop
        logger.warning("Kirim peringatan WA gagal: %s", exc)
    return fired


async def guardian_wa_watchdog_loop(application: Any) -> None:
    """Loop native (TANPA LLM): poling status WA berkala; alarm SEKALI
    per gelombang masalah (cooldown 1 jam). Tak menyentuh sesi WA.
    """
    await asyncio.sleep(_BOOT_WAIT_S)
    interval = _watch_interval_s()
    state = WaWatchState()
    logger.info(
        "Penjaga WA aktif (interval %.0f menit, threshold %d, cooldown %d detik).",
        interval / 60,
        state.threshold,
        state.cooldown_s,
    )
    while True:
        await asyncio.sleep(interval)
        try:
            await guardian_watch_check_once(application, state)
        except Exception as exc:  # noqa: BLE001 — watchdog jangan bipak bot
            logger.warning("Penjaga WA putaran gagal (diabaikan): %s", exc)


def _guardian_prompt() -> str:
    return (
        "Panggil tool `guardian_daily_report`, lalu KIRIMKAN field 'text' "
        "dari hasilnya ke chat Telegram ini PERSIS apa adanya (verbatim, "
        "tanpa diedit atau reformat). HUKUM: laporan ini HANYA untuk "
        "Telegram, JANGAN dikirim ke WhatsApp."
    )


def schedule_guardian_daily(
    user_id: int, chat_id: int, enabled: bool, interval_minutes: int = 1440
) -> dict[str, Any]:
    """Daftar (atau matikan) jadwal cron Penjaga Harian memakai infra yang ada.

    Pakai list→delete→add dari ``alfa.core.db.tasks`` — tanpa fungsi/skema baru.
    Jadwal berbasis interval (dijalankan pertama 24 jam sejak dibuat,
    konsisten dengan infra cron ALFA).
    """
    from alfa.core.db import tasks as cron_tasks

    existing = [
        j
        for j in cron_tasks.list_cron_jobs_sync(user_id)
        if str(j.get("title") or "") == _GUARDIAN_TITLE
    ]
    removed = 0
    for j in existing:
        if cron_tasks.delete_cron_job_sync(user_id, int(j["id"])):
            removed += 1
    if not enabled:
        return {
            "status": "ok",
            "removed": removed,
            "message": f"Jadwal Penjaga Harian dimatikan ({removed} dihapus).",
        }
    interval = max(60, int(interval_minutes))
    job_id = cron_tasks.add_cron_job_sync(
        user_id=user_id,
        chat_id=chat_id,
        title=_GUARDIAN_TITLE,
        prompt_instruction=_guardian_prompt(),
        interval_minutes=interval,
        kind="single",
    )
    return {
        "status": "ok",
        "job_id": job_id,
        "interval_minutes": interval,
        "removed_old": removed,
        "message": (
            f"PENJAGA HARIAN terjadwal (job #{job_id}, tiap {interval} menit). "
            "Isi: layanan, WA, red journal, aktivitas ALFA, CI."
        ),
    }


@register_tool(category="system")
def guardian_daily_report() -> dict[str, Any]:
    """Rangkum kesehatan sistem ALFA: 4 layanan, status klien WA, arsip
    24 jam, baris merah journal, aktivitas run ALFA hari ini, dan status
    CI commit terakhir.

    Laporan read-only. Sampaikan field ``text`` VERBATIM ke pengguna.

    Returns:
        dict dengan kunci: overall (healthy/warn/crit), services, wa,
        archive, journal_errors, runs_today, ci, text (laporan siap-kirim).
    """
    return build_guardian_report()


@register_tool(category="scheduler")
def schedule_daily_guardian_task(enabled: bool = True, interval_minutes: int = 1440) -> dict[str, Any]:
    """AKTIFKAN/MATIKAN jadwal harian 'Penjaga Harian' ke Telegram Fahmi.

    Laporan otomatis (default tiap 24 jam): layanan, klien WA, arsip 24 jam,
    red journal, aktivitas run ALFA, status CI. Laporan HANYA ke Telegram.

    Args:
        enabled: True = aktifkan/memperbarui jadwal, False = matikan & hapus.
        interval_minutes: antara laporan, minimal 60 (default 1440 = harian).
    """
    try:
        from alfa.core.runtime_ctx import get_current_chat_id, get_current_user_id

        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        if not user_id:
            user_id = _primary_chat_id()
        if not chat_id:
            chat_id = user_id
        if not chat_id:
            return {"status": "error", "message": "chat id tidak diketahui"}
        return schedule_guardian_daily(
            user_id=int(user_id), chat_id=int(chat_id),
            enabled=enabled, interval_minutes=interval_minutes,
        )
    except Exception as exc:  # noqa: BLE001 — scheduler refleksif gagal-lembut
        logger.exception("schedule_daily_guardian_task gagal")
        return {"status": "error", "message": str(exc)[:120]}
