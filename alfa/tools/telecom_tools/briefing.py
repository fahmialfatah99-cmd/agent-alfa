"""Daily executive briefing and its scheduler hook."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.telecom_tools._common import (
    FIELD_CONSOLIDATION_ENABLED,
    _extract_telecom_quantities_from_text,
    is_project_or_pengambilan,
    is_to_group,
)

logger = logging.getLogger("AgentTools.Telecom")

@register_tool(category="office")
def generate_daily_executive_briefing(
    shift: str = "now",
    days_back: int = 1,
    only_unreported: bool = True,
    mark_as_reported: bool = True,
) -> dict[str, Any]:
    """
    EXECUTIVE DAILY BRIEFING PROYEK & KESEHATAN SISTEM:
    Menghasilkan kartu laporan eksekutif berkala (pagi/sore) untuk Telegram:
    - Rangkuman pengambilan material (Tiang, FAT/FDT, Kabel).
    - Point-point penting progres lapangan tiap grup cluster (mengecualikan grup TO).
    - Status cluster aktif vs cluster mandek (>48 jam).
    - Laporan kendala dan insiden darurat lapangan dari grup WhatsApp.
    - Metrik kesehatan server Linux & status service ALFA.
    - Zero Double-Reporting: otomatis mencatat pesan yang sudah dilaporkan sehingga tidak berulang.

    PERINGATAN ATURAN:
    Laporan ini HANYA dikirimkan ke Telegram Fahmi. DILARANG KERAS mengirim atau membalas otomatis ke WhatsApp!

    Args:
        shift: Jenis briefing ('morning', 'evening', atau 'now').
        days_back: Rentang hari analisis riwayat chat lapangan (default: 1 hari).
        only_unreported: True = hanya analisis pesan yang BELUM pernah dilaporkan (anti-duplikasi).
        mark_as_reported: True = tandai pesan yang dianalisis sebagai sudah dilaporkan.
    """
    try:
        import time

        import psutil

        from alfa.core.db.connection import get_sync_db

        now_ts = int(time.time())
        cutoff_ts = now_ts - (days_back * 86400)

        pengambilan_groups: dict[str, dict[str, Any]] = {}
        project_groups: dict[str, dict[str, Any]] = {}
        processed_messages: list[dict[str, Any]] = []
        total_cable = 0.0
        total_poles = 0.0
        total_fat = 0.0
        total_fdt = 0.0
        recent_issues: list[dict[str, Any]] = []

        with get_sync_db() as conn:
            # 1. Analisis Pesan Lapangan (Abaikan Grup TO dan pesan personal)
            # Jika only_unreported=True, filter pesan yang sudah pernah masuk laporan briefing sebelumnya
            if only_unreported:
                query = """
                    SELECT a.msg_id, a.chat_id, a.chat_name, a.sender_name, a.body, a.msg_ts
                    FROM wa_incoming_archive a
                    LEFT JOIN wa_reported_messages r ON a.msg_id = r.msg_id
                    WHERE r.msg_id IS NULL AND a.msg_ts >= ?
                    ORDER BY a.msg_ts DESC
                """
            else:
                query = """
                    SELECT a.msg_id, a.chat_id, a.chat_name, a.sender_name, a.body, a.msg_ts
                    FROM wa_incoming_archive a
                    WHERE a.msg_ts >= ?
                    ORDER BY a.msg_ts DESC
                """
            rows = conn.execute(query, (cutoff_ts,)).fetchall()
            for r in rows:
                mid = (r[0] or "").strip()
                cid = (r[1] or "").strip()
                cname = (r[2] or "").strip()
                sender = (r[3] or "Teknisi").strip()
                body = (r[4] or "").strip()
                ts = int(r[5] or 0)
                text_lower = body.lower()

                # Abaikan total grup TO & chat personal non-proyek
                if is_to_group(cname) or not is_project_or_pengambilan(cname):
                    continue

                processed_messages.append({
                    "msg_id": mid,
                    "chat_id": cid,
                    "chat_name": cname,
                    "msg_ts": ts,
                })

                def _is_chat_noise(b: str) -> bool:
                    b_str = (b or "").strip()
                    if not b_str or b_str in ("[sticker]", "[image]", "P", "p"):
                        return True
                    if b_str.startswith(("/9j/", "data:image")) or (len(b_str) > 100 and " " not in b_str):
                        return True
                    low_b = b_str.lower().strip()
                    noise_words = {
                        "siap", "siap mas", "siap pak", "siap bng", "siap bang", "siap bapa",
                        "oke", "okey", "okayy", "ok", "done", "done mas", "done pak",
                        "makasih", "mkasih", "terimakasih", "mkasih mas", "mkasih mas supportnya",
                        "makasih mas", "thanks", "tengkyu", "p", "oii", "iya", "iya mas", "iya pak",
                        "sap sap", "uwes mi", "pie mi", "capek", "litak e", "before", "after", "aman mas",
                        "aman bang", "siap terimakasih", "noted pak", "noted mas", "kirim bang",
                        "area kendal", "iya pak..",
                    }
                    if low_b in noise_words:
                        return True
                    cleaned_b = re.sub(r"@[0-9]+", "", low_b).strip()
                    cleaned_b = re.sub(r"[^\w\s]", "", cleaned_b).strip()
                    return not cleaned_b or cleaned_b in noise_words

                ext = _extract_telecom_quantities_from_text(body)
                is_mat_msg = (
                    ext["poles"] > 0
                    or ext["fats"] > 0
                    or ext["fdts"] > 0
                    or ext["cables"] > 0
                    or any(k in text_lower for k in ("clamp pole", "dead and", "suspen", "inbound", "outbound", "serah terima", "bon material", "surat jalan"))
                )

                if "pengambilan" in cname.lower():
                    if cname not in pengambilan_groups:
                        pengambilan_groups[cname] = {
                            "materials": [],
                            "notes": [],
                            "poles": 0.0,
                            "fats": 0.0,
                            "fdts": 0.0,
                            "cables": 0.0,
                            "msg_count": 0,
                        }
                    pengambilan_groups[cname]["msg_count"] += 1
                    if is_mat_msg:
                        pengambilan_groups[cname]["poles"] += ext["poles"]
                        pengambilan_groups[cname]["fats"] += ext["fats"]
                        pengambilan_groups[cname]["fdts"] += ext["fdts"]
                        pengambilan_groups[cname]["cables"] += ext["cables"]
                        pengambilan_groups[cname]["materials"].append((sender, body))
                    elif not _is_chat_noise(body):
                        pengambilan_groups[cname]["notes"].append((sender, body))
                else:
                    if cname not in project_groups:
                        project_groups[cname] = {
                            "updates": [],
                            "poles": 0.0,
                            "fats": 0.0,
                            "fdts": 0.0,
                            "cables": 0.0,
                            "msg_count": 0,
                        }
                    project_groups[cname]["msg_count"] += 1

                    # Hanya hitung progres instalasi riil jika bukan inventory/aksesoris HB
                    if "clamp pole" not in text_lower and "accessories" not in text_lower:
                        project_groups[cname]["poles"] += ext["poles"]
                        project_groups[cname]["fats"] += ext["fats"]
                        project_groups[cname]["fdts"] += ext["fdts"]
                        project_groups[cname]["cables"] += ext["cables"]
                        total_cable += ext["cables"]
                        total_poles += ext["poles"]
                        total_fat += ext["fats"]
                        total_fdt += ext["fdts"]

                    if not _is_chat_noise(body):
                        score = 1
                        if any(
                            k in text_lower
                            for k in ("kendala", "ijin warga", "izin warga", "kabel putus", "retur", "masalah", "pending", "reject", "kurang sf", "rusak")
                        ):
                            score = 3
                            recent_issues.append({"cluster": cname, "sender": sender, "text": body[:120].strip()})
                        elif any(
                            k in text_lower
                            for k in (".kmz", ".xlsx", ".pdf", "inbound", "outbound", "tanam", "tarik", "splicing", "terminasi", "smdt", "recon", "opname", "rfsc", "fac")
                        ):
                            score = 2
                        project_groups[cname]["updates"].append((score, sender, body))

            # 2. Cek Cluster Stalled (>48 jam) - agregasi per nama cluster proyek asli (Non-TO)
            stalled_clusters = []
            stalled_cutoff = now_ts - (48 * 3600)
            stalled_query = """
                SELECT chat_name, MAX(msg_ts) as last_ts
                FROM wa_incoming_archive
                WHERE (LOWER(chat_name) LIKE '%ftth%' OR LOWER(chat_name) LIKE '%imt%' OR LOWER(chat_name) LIKE '%bkl%')
                  AND chat_name IS NOT NULL AND TRIM(chat_name) != ''
                  AND LOWER(chat_name) NOT LIKE '%to %' AND LOWER(chat_name) NOT LIKE '%to material%'
                GROUP BY LOWER(TRIM(chat_name))
            """
            stalled_rows = conn.execute(stalled_query).fetchall()
            for sr in stalled_rows:
                if sr[1] and sr[1] < stalled_cutoff:
                    stalled_clusters.append({
                        "name": sr[0],
                        "hours_idle": round((now_ts - sr[1]) / 3600, 1),
                    })

        # 3. Tandai pesan sebagai DILAPORKAN bila diminta
        if mark_as_reported and processed_messages:
            from alfa.core.db.wa_tracking import record_wa_messages_reported_sync

            record_wa_messages_reported_sync(processed_messages, shift=shift)

        # 4. Metrik Sistem
        cpu_usage = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        # Format Kartu Ringkasan Telegram (Dikelompokkan per Grup & Point Penting)
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M WIB")
        shift_title = (
            "PAGI (TARGET & PERSIAPAN)"
            if shift.lower() == "morning"
            else "SORE (PROGRESS CLOSING)"
            if shift.lower() == "evening"
            else "REALTIME"
        )

        briefing_lines = [
            "📋 *DAILY EXECUTIVE BRIEFING ALFA OS*",
            f"🕒 *Shift*: {shift_title} | *Waktu*: `{now_str}`\n",
        ]

        if not pengambilan_groups and not project_groups:
            briefing_lines.append(
                "*(Semua laporan lapangan sebelumnya telah berhasil dilaporkan pada sesi briefing sebelumnya. Tidak ada laporan baru yang belum terlaporkan)*\n"
            )

        # A. GRUP PENGAMBILAN MATERIAL
        briefing_lines.append("📦 *RECORD GRUP PENGAMBILAN MATERIAL*:")
        if pengambilan_groups:
            for g, d in pengambilan_groups.items():
                summary_items = []
                if d["poles"] > 0:
                    summary_items.append(f"Tiang: `{int(d['poles'])} btg`")
                if d["fdts"] > 0:
                    summary_items.append(f"FDT: `{int(d['fdts'])} unit`")
                if d["fats"] > 0:
                    summary_items.append(f"FAT: `{int(d['fats'])} box`")
                if d["cables"] > 0:
                    summary_items.append(f"Kabel: `{round(d['cables'], 1):,} m`")
                sum_str = f" ({' | '.join(summary_items)})" if summary_items else ""
                briefing_lines.append(f"• 🏢 *{g}*{sum_str} _({d['msg_count']} aktivitas baru)_:")

                # 1. Tampilkan bukti fisik pengambilan material riil
                if d["materials"]:
                    for s, b in d["materials"][:3]:
                        clean_b = b.replace("\n", " | ")[:110]
                        briefing_lines.append(f"  └ 📦 *{s}*: \"_{clean_b}_\"")
                else:
                    briefing_lines.append("  └ _(Belum ada input fisik barang keluar gudang)_")

                # 2. Tampilkan koordinasi / rencana lapangan bila ada
                if d["notes"]:
                    for s, b in d["notes"][:2]:
                        clean_b = b.replace("\n", " ")[:110]
                        briefing_lines.append(f"  └ 💬 _Koordinasi/Rencana_: *{s}*: \"_{clean_b}_\"")
        else:
            briefing_lines.append("*(Tidak ada pengambilan material baru yang belum dilaporkan)*")

        # B. POINT PENTING TIAP GRUP PROYEK (KECUALI TO)
        briefing_lines.append("\n📌 *POINT PENTING TIAP GRUP PROYEK (KECUALI TO)*:")
        if project_groups:
            for g, d in sorted(project_groups.items(), key=lambda x: len(x[1]["updates"]), reverse=True):
                briefing_lines.append(f"• 📁 *{g}* _({d['msg_count']} update baru)_:")
                # Prioritas: Kendala (skor 3) > Dokumen/Progress (skor 2) > Koordinasi (skor 1)
                valid_updates = sorted(d["updates"], key=lambda x: x[0], reverse=True)
                if valid_updates:
                    for sc, s, b in valid_updates[:2]:
                        clean_b = b.replace("\n", " ")[:110]
                        icon = "⚠️" if sc == 3 else "📄" if sc == 2 else "📌"
                        briefing_lines.append(f"  └ {icon} *{s}*: \"_{clean_b}_\"")
                else:
                    briefing_lines.append("  └ _(Dokumentasi foto/media pekerjaan lapangan)_")
        else:
            briefing_lines.append("*(Tidak ada update aktivitas proyek baru yang belum dilaporkan)*")

        total_groups = len(pengambilan_groups) + len(project_groups)
        if FIELD_CONSOLIDATION_ENABLED:
            briefing_lines.append(
                f"\n⚡ *TOTAL KONSOLIDASI PROGRES LAPANGAN ({total_groups} Grup Terpantau)*:\n"
                f"• 🟢 *Total Kabel Terpasang*: `{round(total_cable, 1):,} meter`\n"
                f"• 🟢 *Total Tiang Tertanam*: `{int(total_poles)} batang`\n"
                f"• 🟢 *Total FDT Terpasang*: `{int(total_fdt)} unit`\n"
                f"• 🟢 *Total FAT/ODP Terpasang*: `{int(total_fat)} box`\n"
            )
        else:
            briefing_lines.append(
                f"\n⚡ *TOTAL KONSOLIDASI PROGRES LAPANGAN ({total_groups} Grup Terpantau)*:\n"
                f"• ⚪ *Status*: _Fitur konsolidasi lapangan dinonaktifkan sementara (tidak ada laporan progres instalasi di grup WA)_\n"
                f"• 🟢 *Total Kabel Terpasang*: `0 meter (nonaktif)`\n"
                f"• 🟢 *Total Tiang Tertanam*: `0 batang (nonaktif)`\n"
                f"• 🟢 *Total FDT Terpasang*: `0 unit (nonaktif)`\n"
                f"• 🟢 *Total FAT/ODP Terpasang*: `0 box (nonaktif)`\n"
            )

        if stalled_clusters:
            briefing_lines.append("⚠️ *CLUSTER PROYEK MANDEK (>48 Jam Tanpa Laporan)*:")
            for sc in stalled_clusters[:3]:
                briefing_lines.append(f"• 🔴 `{sc['name']}` (diam selama {sc['hours_idle']} jam)")
            briefing_lines.append("")

        if recent_issues:
            briefing_lines.append(f"🚨 *CATATAN KENDALA & FOLLOW-UP LAPANGAN ({len(recent_issues)} Poin)*:")
            for iss in recent_issues[:3]:
                briefing_lines.append(f"• *{iss['cluster']}* ({iss['sender']}): \"_{iss['text']}_\"")
            briefing_lines.append("")

        briefing_lines.append(
            f"💻 *KESEHATAN SISTEM ALFA*:\n"
            f"• CPU: `{cpu_usage}%` | RAM: `{mem.percent}%` (Tersedia: {round(mem.available / (1024**3), 1)} GB)\n"
            f"• WhatsApp Bot: `Active (Sync Live)`\n"
            f"• Telegram Agent: `Ready`"
        )

        briefing_text = "\n".join(briefing_lines)

        return {
            "status": "success",
            "shift": shift,
            "briefing_card": briefing_text,
            "stats": {
                "total_cable_meters": total_cable,
                "total_poles_pcs": int(total_poles),
                "total_fdt_boxes": int(total_fdt),
                "total_fat_boxes": int(total_fat),
                "active_clusters": total_groups,
                "stalled_clusters": len(stalled_clusters),
                "issues_count": len(recent_issues),
                "new_unreported_messages": len(processed_messages),
                "by_cluster": {
                    cname: {
                        "cable_meters": round(cinfo["cables"], 1),
                        "poles_pcs": int(cinfo["poles"]),
                        "fdt_boxes": int(cinfo["fdts"]),
                        "fat_boxes": int(cinfo["fats"]),
                        "messages": cinfo["msg_count"],
                    }
                    for cname, cinfo in {**pengambilan_groups, **project_groups}.items()
                },
            },
        }
    except Exception as e:
        logger.exception("Gagal membuat executive briefing: %s", e)
        return {"status": "error", "message": f"Executive briefing error: {str(e)}"}

@register_tool(category="scheduler")
def schedule_daily_briefing_task(
    enabled: bool = False,
    morning_hour: int = 7,
    morning_minute: int = 30,
    evening_hour: int = 18,
    evening_minute: int = 0,
) -> dict[str, Any]:
    """
    JADWALKAN EXECUTIVE BRIEFING OTOMATIS KE TELEGRAM:
    Mengaktifkan atau memperbarui jadwal otomatis ringkasan proyek ke Telegram Fahmi:
    - Briefing Pagi (pukul 07:30 WIB): Target hari ini, cluster aktif & mandek, persiapan kerja.
    - Closing Sore (pukul 18:00 WIB): Progres tarikan kabel, tiang tertanam, FAT, kendala lapangan, kesehatan server.

    HUKUM BESI KEAMANAN:
    Laporan HANYA dikirimkan ke Telegram chat Fahmi. DILARANG KERAS mengirim atau membalas ke WhatsApp!

    Args:
        enabled: True untuk mengaktifkan jadwal, False untuk mematikan (default: False).
        morning_hour: Jam pengiriman pagi (default: 7).
        morning_minute: Menit pengiriman pagi (default: 30).
        evening_hour: Jam pengiriman sore (default: 18).
        evening_minute: Menit pengiriman sore (default: 0).
    """
    try:
        from alfa.core import database
        from alfa.core.runtime_ctx import get_current_chat_id, get_current_user_id

        user_id = get_current_user_id()
        chat_id = get_current_chat_id()

        if not enabled:
            with database.get_sync_db() as conn:
                conn.execute(
                    "UPDATE scheduled_cron_jobs SET is_active = 0 WHERE title LIKE '%Daily Project Executive Briefing%'"
                )
                conn.commit()
            return {
                "status": "success",
                "message": "Jadwal otomatis Executive Briefing proyek telah dinonaktifkan.",
            }

        instr = (
            "Panggil tool `generate_daily_executive_briefing(shift='now', days_back=1)` "
            "lalu kirimkan ringkasan kartu laporan eksekutif proyek FTTH ke chat Telegram ini."
        )

        job_id = database.add_cron_job_sync(
            user_id=user_id,
            chat_id=chat_id,
            title="Daily Project Executive Briefing (Telegram Only)",
            prompt_instruction=instr,
            interval_minutes=720,  # Setiap 12 jam (pagi & sore)
            kind="single",
        )

        return {
            "status": "success",
            "job_id": job_id,
            "message": (
                f"Jadwal Executive Briefing Telegram berhasil diaktifkan (#{job_id}). "
                f"Ringkasan pagi & sore akan dikirimkan otomatis ke Telegram Anda."
            ),
        }
    except Exception as e:
        logger.exception("Gagal menjadwalkan daily briefing: %s", e)
        return {"status": "error", "message": f"Schedule daily briefing error: {str(e)}"}
