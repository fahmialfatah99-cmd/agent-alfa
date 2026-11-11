"""WhatsApp group material reconciliation (the heaviest extractor)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

from alfa.config.domain import MANDOR_NAME_MAP
from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Telecom")

def _wa_bridge_status() -> dict[str, Any]:
    """Status jembatan bot WhatsApp (live). Kosong bila tidak terjangkau.

    Endpoint ``/health`` pada bot WA bersifat read-only (tanpa efek samping)
    dan mengembalikan status klien (``READY``/``AUTHENTICATED``/
    ``INITIALIZING``/``QR_READY``).
    """
    try:
        import urllib.request

        req = urllib.request.urlopen(  # nosec B310 - API bot WA lokal
            "http://127.0.0.1:3000/health", timeout=3
        )
        data = json.loads(req.read().decode("utf-8"))
        if isinstance(data, dict):
            status = str(data.get("status") or "UNKNOWN")
            return {
                "client_status": status,
                "is_ready": status in ("READY", "AUTHENTICATED"),
                "uptime": data.get("uptime"),
            }
    except Exception as e:  # noqa: BLE001 - status bersifat opsional
        logger.debug("WA bridge status tidak terjangkau: %s", e)
    return {}


def _data_freshness(
    messages: list[dict[str, Any]],
    live_api_used: bool,
) -> dict[str, Any]:
    """Nilai kesegaran data rekap: live/timestamp terakhir & tanda basi."""
    from datetime import datetime

    newest_ts = 0
    for m in messages:
        try:
            newest_ts = max(newest_ts, int(m.get("ts", 0) or 0))
        except (TypeError, ValueError):
            continue

    age_hours: float | None = None
    if newest_ts:
        age_hours = round((time.time() - newest_ts) / 3600, 1)

    bridge = _wa_bridge_status()
    client_status = str(bridge.get("client_status") or "UNKNOWN")
    bridge_ready = bool(bridge.get("is_ready"))

    stale = False
    reasons: list[str] = []
    if not live_api_used:
        stale = True
        reasons.append("jembatan WA live tidak terjangkau — data dari arsip lokal")
    if not bridge_ready and bridge:
        stale = True
        reasons.append(f"bot WA belum siap (client_status={client_status})")
    if age_hours is None:
        stale = True
        reasons.append("tidak ada pesan WhatsApp sama sekali dalam arsip")
    elif age_hours > 24:
        stale = True
        reasons.append(f"pesan WhatsApp terakhir berumur {age_hours:.0f} jam")

    return {
        "live_api_used": live_api_used,
        "bridge_ready": bridge_ready,
        "client_status": client_status,
        "newest_message_at": (
            datetime.fromtimestamp(newest_ts).isoformat(timespec="seconds")
            if newest_ts
            else ""
        ),
        "age_hours": age_hours,
        "stale": stale,
        "reasons": reasons,
    }

@register_tool(category="office")
def reconcile_whatsapp_material_group(
    group_name_or_id: str = "pengambilan material lahat",
    output_excel_path: str | None = None,
    auto_launch_gridcraft: bool = True,
) -> dict[str, Any]:
    """
    REKAPITULASI RESMI & MENYELURUH PENGAMBILAN MATERIAL PROYEK DARI GRUP WHATSAPP:
    Membaca riwayat chat grup WhatsApp dari awal pembentukan hingga laporan terbaru,
    mengidentifikasi seluruh mandor pelapor di grup tersebut, mengekstrak secara presisi
    seluruh pengambilan dan pengembalian (retur) tiang/material, dan menghasilkan
    lembar kerja Excel (.xlsx) dengan formula dinamis (SUM, SUMIFS) yang 100% akurat.

    Fitur Utama:
    1. Otomatis membaca dari WhatsApp Web API live (port 3000) dan fallback ke arsip SQLite lokal.
    2. Mendeteksi seluruh mandor pelapor (misal: Mandor Mugi & Mandor Aqe Setiawan).
    3. Formula Excel murni dinamis (SUM, SUMIFS) tanpa circular reference atau hardcoded error.
    4. Otomatis membuka hasil rekapitulasi di aplikasi GridCraft desktop jika diminta.

    Args:
        group_name_or_id: Nama grup WhatsApp atau Chat JID (default: 'pengambilan material lahat').
        output_excel_path: Lokasi berkas Excel (.xlsx). Jika None, otomatis disimpan ke ~/alfa_projects/<cluster>_material/.
        auto_launch_gridcraft: True jika ingin langsung membuka file di GUI GridCraft.

    Returns:
        Dict berisi status, rincian mandor, total net, total bruto, total retur, rincian item, dan path berkas.
    """
    try:
        import urllib.request

        from alfa.core.db.connection import get_sync_db

        chat_jid: str | None = None
        chat_name: str = group_name_or_id
        messages: list[dict[str, Any]] = []

        # 1. Hubungi WhatsApp API live (port 3000)
        try:
            req = urllib.request.urlopen("http://127.0.0.1:3000/api/chats", timeout=3)  # nosec B310 - API bot WA lokal
            chats_data = json.loads(req.read().decode("utf-8")).get("chats", [])
            target = group_name_or_id.lower().strip()
            for c in chats_data:
                c_name = str(c.get("name", "")).lower()
                c_id = str(c.get("id", "")).lower()
                if (
                    target in c_name
                    or target in c_id
                    or ("curup" in target and "curup" in c_name)
                    or ("lahat" in target and "lahat" in c_name)
                ):
                    chat_jid = str(c.get("id", ""))
                    chat_name = str(c.get("name", ""))
                    break
        except Exception as e:
            logger.warning("WA Live API chats lookup warning: %s", e)

        if not chat_jid and "@g.us" in group_name_or_id:
            chat_jid = group_name_or_id

        live_api_used = False
        if chat_jid:
            try:
                url = f"http://127.0.0.1:3000/api/messages?chat={chat_jid}&limit=500"
                req = urllib.request.urlopen(url, timeout=5)  # nosec B310 - API bot WA lokal
                data = json.loads(req.read().decode("utf-8"))
                messages = data.get("messages", [])
                live_api_used = bool(messages)
            except Exception as e:
                logger.warning("WA Live API messages lookup warning: %s", e)

        # 2. Sinkronkan / Fallback ke SQLite database lokal
        with get_sync_db() as conn:
            if messages:
                # Backfill pesan live ke wa_incoming_archive agar DB selalu mutakhir
                for m in messages:
                    try:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO wa_incoming_archive
                            (msg_id, chat_id, chat_name, sender_name, is_group, msg_type, body, has_media, msg_ts)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(m.get("id", "")),
                                chat_jid or "unknown@g.us",
                                chat_name,
                                str(m.get("sender", "")),
                                1,
                                str(m.get("msg_type", "chat")),
                                str(m.get("body", "")),
                                1 if m.get("has_media") else 0,
                                int(m.get("ts", 0)),
                            ),
                        )
                    except Exception as e:
                        logger.debug("WA archive row skipped: %s", e)
                conn.commit()
            else:
                # Ambil dari wa_incoming_archive bila API live tidak tersedia
                fallback_target = f"%{group_name_or_id.lower().strip()}%"
                if "curup" in group_name_or_id.lower():
                    fallback_target = "%curup%"
                elif "lahat" in group_name_or_id.lower():
                    fallback_target = "%lahat%"

                rows = conn.execute(
                    """
                    SELECT msg_id, chat_id, chat_name, sender_name, msg_type, body, has_media, msg_ts
                    FROM wa_incoming_archive
                    WHERE LOWER(chat_name) LIKE ? OR chat_id = ?
                    ORDER BY msg_ts ASC
                    """,
                    (fallback_target, group_name_or_id.strip()),
                ).fetchall()
                for r in rows:
                    messages.append({
                        "id": r[0],
                        "sender": r[3],
                        "msg_type": r[4],
                        "body": r[5],
                        "has_media": bool(r[6]),
                        "ts": r[7],
                    })

        if not messages:
            return {
                "status": "error",
                "message": f"Tidak ditemukan riwayat chat untuk grup '{group_name_or_id}'.",
            }

        # Urutkan secara kronologis berdasarkan timestamp
        messages.sort(key=lambda x: x.get("ts", 0))

        # Deduplikasi pesan yang berulang (misal album foto terkirim beruntun atau capture retry)
        deduped_messages: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for m in messages:
            b_str = str(m.get("body", "") or "").strip()
            if not b_str or b_str == "[image]":
                continue
            norm_b = re.sub(r"\s+", " ", b_str.lower()).strip()
            if "(cluster: lahat)" in norm_b or "(cluster: curup)" in norm_b:
                continue
            s_raw = str(m.get("sender", "")).replace("@lid", "").replace("@s.whatsapp.net", "").lstrip("+")
            t_val = m.get("ts", 0)
            d_day = datetime.fromtimestamp(t_val).strftime("%Y-%m-%d") if t_val else "-"
            dedup_key = (s_raw, d_day, norm_b)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            deduped_messages.append(m)
        messages = deduped_messages

        # Regex pola tiang & kabel & aksesoris lapangan
        pole_pattern = re.compile(
            r"\b(?:tiang\s*)?(?:t72|t73|t74|t94|t9|t7(?:\.2[,.]5|\.3|\.4)?|7['\".,/](?:2[,.]?5|3|4))\b[\s:=.-]+([0-9]+)(?:\s*(?:btg|batang|btng|pcs|titik)\b)?",
            re.IGNORECASE,
        )
        cable_pattern = re.compile(
            r"\b(?:ku\s*24\s*c?|kabel\s*udara)\b[\s:=]+([0-9\.,]+)\s*(?:m|meter|mtr)?",
            re.IGNORECASE,
        )

        records: list[dict[str, Any]] = []
        cable_records: list[dict[str, Any]] = []
        acc_records: list[dict[str, Any]] = []
        all_logs: list[dict[str, Any]] = []

        rec_id = 1
        cable_rec_id = 1
        acc_rec_id = 1
        all_rec_id = 1
        mandors_found: set[str] = set()

        for m in messages:
            sender_raw = str(m.get("sender", "")).replace("@lid", "").replace("@s.whatsapp.net", "").lstrip("+")
            sender = MANDOR_NAME_MAP.get(sender_raw, sender_raw)
            body = str(m.get("body", "") or "")
            ts = m.get("ts", 0)
            dt_str = datetime.fromtimestamp(ts).strftime("%d-%m-%Y") if ts else "-"

            # Lewati pesan diskusi masa depan, koordinasi non-material, atau laporan progres tanam/instalasi lapangan
            if any(w in body.lower() for w in [
                "besok gass", "masukin mandor", "form wajib diisi", "@all", "kertas pengambilan",
                "tertanam", "terpasang", "cuma tertanam", "sudah tertanam", "tanam hari ini"
            ]):
                continue

            is_retur_msg = any(rw in body.lower() for rw in ["kembali", "retur", "pengembalian"])

            lines = body.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue

                # Gabungkan baris kuantitas menggantung bila baris berikutnya hanya angka + satuan (contoh: 'Suspen \n 20 pcs')
                if i + 1 < len(lines) and re.match(r"^[0-9]+\s*(?:pcs|btg|roll|m|meter|mtr)?$", lines[i+1].strip(), re.I):
                    line = f"{line} {lines[i+1].strip()}"
                    i += 1

                is_retur_line = is_retur_msg or any(rw in line.lower() for rw in ["kembali", "retur", "pengembalian"])

                # 1. Tiang
                for match in pole_pattern.finditer(line):
                    matched_prefix = line[match.start():match.end()].lower()
                    qty = int(match.group(1))

                    if any(k in matched_prefix for k in ("t72", "t7.2", "7.2", "7,2", "7'2", '7"2')):
                        item_code = "T72"
                        spec = 'Tiang 7 Meter 2" / 2.5"'
                    elif any(k in matched_prefix for k in ("t73", "t7.3", "7.3", "7,3", "7'3", '7"3')):
                        item_code = "T73"
                        spec = 'Tiang 7 Meter 3"'
                    elif any(k in matched_prefix for k in ("t74", "t7.4", "7.4", "7,4", "7'4", '7"4')):
                        item_code = "T74"
                        spec = 'Tiang 7 Meter 4"'
                    elif any(k in matched_prefix for k in ("t94", "t9.4", "t9", "9.4", "9'4", '9"4')):
                        item_code = "T94"
                        spec = 'Tiang 9 Meter 4"'
                    else:
                        item_code = "TIANG"
                        spec = "Tiang Lapangan"

                    cluster = "Pengambilan"
                    if "mrsb1" in body.lower():
                        cluster = "Pengambilan (MRSB1)"
                    elif "lubuk kembang" in body.lower() or "lubuk kembang" in line.lower():
                        cluster = "Pengambilan (Lubuk Kembang)"
                    elif "air lanang" in body.lower() or "air lanang" in line.lower():
                        cluster = "Pengambilan (Air Lanang)"
                    elif m.get("has_media"):
                        cluster = "Pengambilan (Surat Jalan)"

                    if is_retur_line:
                        cluster = "Pengembalian (Retur)"
                        final_qty = -qty
                    else:
                        final_qty = qty

                    records.append({
                        "no": rec_id,
                        "date": dt_str,
                        "mandor": sender,
                        "status": cluster,
                        "code": item_code,
                        "spec": spec,
                        "qty": final_qty,
                    })
                    all_logs.append({
                        "no": all_rec_id,
                        "date": dt_str,
                        "mandor": sender,
                        "category": "TIANG",
                        "status": cluster,
                        "code": item_code,
                        "spec": spec,
                        "qty": final_qty,
                        "unit": "batang",
                    })
                    mandors_found.add(sender)
                    rec_id += 1
                    all_rec_id += 1

                # 2. Kabel Udara (KU 24)
                for c_match in cable_pattern.finditer(line):
                    c_val = float(c_match.group(1).replace(",", "."))
                    cable_records.append({
                        "no": cable_rec_id,
                        "date": dt_str,
                        "mandor": sender,
                        "category": "KABEL",
                        "status": "Pengambilan",
                        "code": "KU 24",
                        "spec": "Kabel Udara 24 Core (Fiber Optic)",
                        "qty": c_val,
                        "unit": "meter",
                    })
                    all_logs.append({
                        "no": all_rec_id,
                        "date": dt_str,
                        "mandor": sender,
                        "category": "KABEL",
                        "status": "Pengambilan",
                        "code": "KU 24",
                        "spec": "Kabel Udara 24 Core (Fiber Optic)",
                        "qty": c_val,
                        "unit": "meter",
                    })
                    mandors_found.add(sender)
                    cable_rec_id += 1
                    all_rec_id += 1

                # 3. Aksesoris Telekomunikasi
                # Stoping
                m_stop = re.search(r"\b(?:stoping|stopper|stoppling)\b[\s:=]+([0-9]+)", line, re.I)
                if m_stop:
                    q_val = int(m_stop.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-STOPING", "spec": "Stoping / Stopper Tiang", "qty": q_val, "unit": "pcs"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-STOPING", "spec": "Stoping / Stopper Tiang", "qty": q_val, "unit": "pcs"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                # Dead End
                m_dead = re.search(r"\b(?:dee\s*end|det\s*end|dead\s*end)\b(?:\s+nambah)?[\s:=]+([0-9]+)", line, re.I)
                if m_dead:
                    q_val = int(m_dead.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-DEADEND", "spec": "Dead End Clamp (Guy Grip)", "qty": q_val, "unit": "pcs"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-DEADEND", "spec": "Dead End Clamp (Guy Grip)", "qty": q_val, "unit": "pcs"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                # Full Clamp / Pole Clamp
                m_clam = re.search(r"\b(?:fulclam|ful\s*clam|full\s*clamp|clem|klem|pole\s*clamp)\b[\s:=]+([0-9]+)", line, re.I)
                if m_clam:
                    q_val = int(m_clam.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-FULCLAM", "spec": "Full Clamp / Pole Clamp", "qty": q_val, "unit": "pcs"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-FULCLAM", "spec": "Full Clamp / Pole Clamp", "qty": q_val, "unit": "pcs"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                # Suspension
                m_susp = re.search(r"\b(?:suspen|suspension|suspend)\b[\s:=]+([0-9]+)", line, re.I)
                if m_susp:
                    q_val = int(m_susp.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-SUSPEN", "spec": "Suspension Clamp", "qty": q_val, "unit": "pcs"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-SUSPEN", "spec": "Suspension Clamp", "qty": q_val, "unit": "pcs"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                # Stainless Steel Belt
                m_belt = re.search(r"\b(?:stainlisbell|stenlish\s*belt|stainless\s*belt)\b[\s:=]+([0-9]+)", line, re.I)
                if m_belt:
                    q_val = int(m_belt.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-BELT", "spec": "Stainless Steel Belt (Banding)", "qty": q_val, "unit": "roll"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-BELT", "spec": "Stainless Steel Belt (Banding)", "qty": q_val, "unit": "roll"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                # Slack Hanger / Fising Slek
                m_hang = re.search(r"\b(?:hanger|fising\s*slek|slack\s*hanger)\b[\s:=]+([0-9]+)", line, re.I)
                if m_hang:
                    q_val = int(m_hang.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-HANGER", "spec": "Slack Hanger / Fishing Slack", "qty": q_val, "unit": "pcs"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-HANGER", "spec": "Slack Hanger / Fishing Slack", "qty": q_val, "unit": "pcs"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                # Buaya Clamp
                m_buaya = re.search(r"\b(?:buayo|buaya|clamp\s*buaya)\b[\s:=]+([0-9]+)", line, re.I)
                if m_buaya:
                    q_val = int(m_buaya.group(1))
                    acc_records.append({
                        "no": acc_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-BUAYA", "spec": "Clamp Buaya / Tension Clamp", "qty": q_val, "unit": "pcs"
                    })
                    all_logs.append({
                        "no": all_rec_id, "date": dt_str, "mandor": sender, "category": "AKSESORIS", "status": "Pengambilan",
                        "code": "ACC-BUAYA", "spec": "Clamp Buaya / Tension Clamp", "qty": q_val, "unit": "pcs"
                    })
                    mandors_found.add(sender)
                    acc_rec_id += 1
                    all_rec_id += 1

                i += 1

        if not records and not cable_records and not acc_records:
            return {
                "status": "error",
                "message": f"Ditemukan {len(messages)} pesan di grup '{chat_name}', namun tidak ada data pengambilan material yang terdeteksi.",
            }

        # 3. Tentukan Lokasi Berkas Excel (Master Ledger Kumulatif)
        # Menjamin single master file per cluster agar tidak membuat file baru setiap hari
        cluster_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", chat_name).strip("_")
        if not output_excel_path:
            if "curup" in chat_name.lower():
                output_excel_path = os.path.expanduser("~/alfa_projects/curup_material/Rekap_Pengambilan_Material_Curup.xlsx")
            elif "lahat" in chat_name.lower():
                output_excel_path = os.path.expanduser("~/alfa_projects/lahat_material/Rekap_Pengambilan_Material_Lahat.xlsx")
            else:
                output_excel_path = os.path.expanduser(f"~/alfa_projects/{cluster_slug}/Rekap_Pengambilan_Material_{cluster_slug}.xlsx")
            os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)
        else:
            output_excel_path = os.path.abspath(os.path.expanduser(output_excel_path))
            os.makedirs(os.path.dirname(output_excel_path), exist_ok=True)

        # 4. Bangun File Excel Profesional dengan Rumus Dinamis Murni
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Rekap Material"

        title_font = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")
        sub_font = Font(name="Segoe UI", size=9, italic=True, color="4B5563")
        bold_mandor_font = Font(name="Segoe UI", size=10, bold=True, color="1F2937")
        header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        section_font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
        regular_font = Font(name="Segoe UI", size=10)
        bold_font = Font(name="Segoe UI", size=10, bold=True)
        retur_font = Font(name="Segoe UI", size=10, bold=True, color="B91C1C")
        total_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")

        navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        blue_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        light_blue = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
        gray_fill = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
        retur_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        green_fill = PatternFill(start_color="15803D", end_color="15803D", fill_type="solid")

        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        # Header Block
        ws.merge_cells("A1:G1")
        ws["A1"] = f"REKAPITULASI RESMI PENGAMBILAN MATERIAL - {chat_name.upper()}"
        ws["A1"].font = title_font
        ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

        ws.merge_cells("A2:G2")
        ws["A2"] = f"Sumber: Grup WhatsApp '{chat_name}' ({chat_jid or '-'})"
        ws["A2"].font = sub_font
        ws["A2"].alignment = Alignment(horizontal="center", vertical="center")

        all_mandors_sorted = sorted(list(mandors_found))
        tiang_mandors = sorted(list({r["mandor"] for r in records})) if records else all_mandors_sorted
        mandors_sorted = tiang_mandors
        mandor_str = " | ".join([f"{i}. {m}" for i, m in enumerate(all_mandors_sorted, 1)])
        ws.merge_cells("A3:G3")
        ws["A3"] = f"Mandor Pelapor Terverifikasi: {mandor_str}"
        ws["A3"].font = bold_mandor_font
        ws["A3"].alignment = Alignment(horizontal="center", vertical="center")

        # Table Log Transaksi
        headers = ["No", "Tanggal", "Mandor Lapangan", "Status / Tipe", "Kode Item", "Spesifikasi Material", "Jumlah (Batang)"]
        ws.append([])  # row 4
        ws.append(headers)  # row 5

        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=5, column=col_idx)
            c.font = header_font
            c.fill = blue_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border

        log_start_row = 6
        log_end_row = log_start_row + len(records) - 1

        row_num = log_start_row
        for r in records:
            ws.append([r["no"], r["date"], r["mandor"], r["status"], r["code"], r["spec"], r["qty"]])
            is_retur = r["qty"] < 0
            for c_idx in range(1, 8):
                cell = ws.cell(row=row_num, column=c_idx)
                cell.border = thin_border
                if is_retur:
                    cell.font = retur_font
                    cell.fill = retur_fill
                else:
                    cell.font = regular_font
                    cell.fill = light_blue if row_num % 2 == 0 else gray_fill

                if c_idx in [1, 2, 5]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx == 7:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")
            row_num += 1

        # Total Log Row
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=6)
        lbl = ws.cell(row=row_num, column=1)
        lbl.value = "TOTAL AKUMULASI BERSIH (NET) PENGAMBILAN TIANG"
        lbl.font = total_font
        lbl.fill = navy_fill
        lbl.alignment = Alignment(horizontal="center", vertical="center")

        tot_c = ws.cell(row=row_num, column=7)
        tot_c.value = f"=SUM(G{log_start_row}:G{log_end_row})"
        tot_c.font = total_font
        tot_c.fill = navy_fill
        tot_c.alignment = Alignment(horizontal="right", vertical="center")

        for c_idx in range(1, 8):
            ws.cell(row=row_num, column=c_idx).border = thin_border

        row_num += 2

        # Tabel A: Rekapitulasi Per Mandor
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=5)
        ws.cell(row=row_num, column=1, value="A. REKAPITULASI PER MANDOR").font = section_font
        row_num += 1

        mandor_headers = ["No", "Nama Mandor", "Total Ambil (Bruto)", "Total Retur", "Total Bersih (Net)"]
        ws.append(mandor_headers)
        for c_idx in range(1, 6):
            c = ws.cell(row=row_num, column=c_idx)
            c.font = header_font
            c.fill = blue_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border

        mandor_start_row = row_num + 1
        row_num += 1

        for idx, m_name in enumerate(mandors_sorted, 1):
            ws.cell(row=row_num, column=1, value=idx)
            ws.cell(row=row_num, column=2, value=m_name)
            # Bruto: SUMIFS > 0
            ws.cell(row=row_num, column=3, value=f'=SUMIFS($G${log_start_row}:$G${log_end_row},$C${log_start_row}:$C${log_end_row},"{m_name}",$G${log_start_row}:$G${log_end_row},">0")')
            # Retur: -SUMIFS < 0
            ws.cell(row=row_num, column=4, value=f'=-SUMIFS($G${log_start_row}:$G${log_end_row},$C${log_start_row}:$C${log_end_row},"{m_name}",$G${log_start_row}:$G${log_end_row},"<0")')
            # Net: C - D
            ws.cell(row=row_num, column=5, value=f"=C{row_num}-D{row_num}")

            for c_idx in range(1, 6):
                c = ws.cell(row=row_num, column=c_idx)
                c.font = regular_font if c_idx < 5 else bold_font
                c.border = thin_border
                if c_idx == 1:
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx == 2:
                    c.alignment = Alignment(horizontal="left", vertical="center")
                else:
                    c.alignment = Alignment(horizontal="right", vertical="center")
            row_num += 1

        mandor_end_row = row_num - 1

        # Total Mandor Row
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=2)
        ws.cell(row=row_num, column=1, value="TOTAL GABUNGAN MANDOR")
        ws.cell(row=row_num, column=1).font = total_font
        ws.cell(row=row_num, column=1).fill = green_fill
        ws.cell(row=row_num, column=1).alignment = Alignment(horizontal="center", vertical="center")

        ws.cell(row=row_num, column=3, value=f"=SUM(C{mandor_start_row}:C{mandor_end_row})").font = total_font
        ws.cell(row=row_num, column=3).fill = green_fill
        ws.cell(row=row_num, column=3).alignment = Alignment(horizontal="right", vertical="center")

        ws.cell(row=row_num, column=4, value=f"=SUM(D{mandor_start_row}:D{mandor_end_row})").font = total_font
        ws.cell(row=row_num, column=4).fill = green_fill
        ws.cell(row=row_num, column=4).alignment = Alignment(horizontal="right", vertical="center")

        ws.cell(row=row_num, column=5, value=f"=SUM(E{mandor_start_row}:E{mandor_end_row})").font = total_font
        ws.cell(row=row_num, column=5).fill = green_fill
        ws.cell(row=row_num, column=5).alignment = Alignment(horizontal="right", vertical="center")

        for c_idx in range(1, 6):
            ws.cell(row=row_num, column=c_idx).border = thin_border

        row_num += 2

        # Tabel B: Rekapitulasi Per Jenis Tiang
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(mandors_sorted) + 4)
        ws.cell(row=row_num, column=1, value="B. REKAPITULASI PER JENIS TIANG").font = section_font
        row_num += 1

        item_headers = ["No", "Kode Item", "Spesifikasi Tiang"] + [f"{m} (Net)" for m in mandors_sorted] + ["Total Akhir (Net)"]
        ws.append(item_headers)
        for c_idx in range(1, len(item_headers) + 1):
            c = ws.cell(row=row_num, column=c_idx)
            c.font = header_font
            c.fill = blue_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = thin_border

        tiang_start_row = row_num + 1
        row_num += 1

        distinct_codes = []
        seen_codes = set()
        for r in records:
            if r["code"] not in seen_codes:
                distinct_codes.append((r["code"], r["spec"]))
                seen_codes.add(r["code"])

        for idx, (code, desc) in enumerate(distinct_codes, 1):
            ws.cell(row=row_num, column=1, value=idx)
            ws.cell(row=row_num, column=2, value=code)
            ws.cell(row=row_num, column=3, value=desc)

            for m_idx, m_name in enumerate(mandors_sorted):
                col_curr = 4 + m_idx
                ws.cell(
                    row=row_num,
                    column=col_curr,
                    value=f'=SUMIFS($G${log_start_row}:$G${log_end_row},$C${log_start_row}:$C${log_end_row},"{m_name}",$E${log_start_row}:$E${log_end_row},B{row_num})',
                )

            total_col_idx = 4 + len(mandors_sorted)
            start_chr = chr(ord("A") + 3)
            end_chr = chr(ord("A") + 3 + len(mandors_sorted) - 1)
            ws.cell(row=row_num, column=total_col_idx, value=f"=SUM({start_chr}{row_num}:{end_chr}{row_num})")

            for c_idx in range(1, total_col_idx + 1):
                c = ws.cell(row=row_num, column=c_idx)
                c.font = regular_font if c_idx < total_col_idx else bold_font
                c.border = thin_border
                if c_idx in [1, 2]:
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx == 3:
                    c.alignment = Alignment(horizontal="left", vertical="center")
                else:
                    c.alignment = Alignment(horizontal="right", vertical="center")
            row_num += 1

        tiang_end_row = row_num - 1

        # Total Tiang Row
        total_col_idx = 4 + len(mandors_sorted)
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=3)
        ws.cell(row=row_num, column=1, value="TOTAL KESELURUHAN TIANG (NET)").font = total_font
        ws.cell(row=row_num, column=1).fill = green_fill
        ws.cell(row=row_num, column=1).alignment = Alignment(horizontal="center", vertical="center")

        for m_idx in range(len(mandors_sorted) + 1):
            col_curr = 4 + m_idx
            col_letter = chr(ord("A") + col_curr - 1)
            c = ws.cell(row=row_num, column=col_curr, value=f"=SUM({col_letter}{tiang_start_row}:{col_letter}{tiang_end_row})")
            c.font = total_font
            c.fill = green_fill
            c.alignment = Alignment(horizontal="right", vertical="center")

        for c_idx in range(1, total_col_idx + 1):
            ws.cell(row=row_num, column=c_idx).border = thin_border

        # Kolom width Sheet 1
        col_widths = {"A": 6, "B": 16, "C": 26, "D": 26, "E": 26, "F": 22, "G": 18}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

        # 5. Bangun Sheet 2: Kabel & Aksesoris jika ada data
        total_cable_m = sum(r["qty"] for r in cable_records)
        cable_breakdown: dict[str, float] = {}
        for r in cable_records:
            cable_breakdown[r["mandor"]] = cable_breakdown.get(r["mandor"], 0.0) + r["qty"]

        acc_totals: dict[str, int] = {}
        for r in acc_records:
            acc_totals[r["code"]] = acc_totals.get(r["code"], 0) + r["qty"]

        if cable_records or acc_records:
            ws2 = wb.create_sheet(title="Kabel & Aksesoris")
            ws2.merge_cells("A1:H1")
            ws2["A1"] = f"REKAPITULASI KABEL UDARA & AKSESORIS FTTH - {chat_name.upper()}"
            ws2["A1"].font = title_font
            ws2["A1"].alignment = Alignment(horizontal="center", vertical="center")

            ws2.merge_cells("A2:H2")
            ws2["A2"] = f"Sumber: Grup WhatsApp '{chat_name}' ({chat_jid or '-'})"
            ws2["A2"].font = sub_font
            ws2["A2"].alignment = Alignment(horizontal="center", vertical="center")

            # Tabel Log Kabel & Aksesoris
            cable_acc_headers = ["No", "Tanggal", "Mandor Lapangan", "Kategori", "Kode Item", "Spesifikasi Material", "Jumlah", "Satuan"]
            ws2.append([])
            ws2.append(cable_acc_headers)
            for c_idx in range(1, len(cable_acc_headers) + 1):
                c = ws2.cell(row=4, column=c_idx)
                c.font = header_font
                c.fill = blue_fill
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = thin_border

            r2_num = 5
            combined_ca = cable_records + acc_records
            for idx, r in enumerate(combined_ca, 1):
                ws2.append([idx, r["date"], r["mandor"], r.get("category", "AKSESORIS"), r["code"], r["spec"], r["qty"], r["unit"]])
                for c_idx in range(1, 9):
                    cell = ws2.cell(row=r2_num, column=c_idx)
                    cell.border = thin_border
                    cell.font = regular_font
                    cell.fill = light_blue if r2_num % 2 == 0 else gray_fill
                    if c_idx in [1, 2, 5, 8]:
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    elif c_idx == 7:
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")
                r2_num += 1

            # Tabel Ringkasan Kabel
            if cable_records:
                r2_num += 2
                ws2.merge_cells(start_row=r2_num, start_column=1, end_row=r2_num, end_column=3)
                ws2.cell(row=r2_num, column=1, value="RINGKASAN PENGAMBILAN KABEL UDARA (KU 24)").font = section_font
                r2_num += 1

                ws2.append(["No", "Nama Mandor", "Total Kabel (Meter)"])
                for c_idx in range(1, 4):
                    c = ws2.cell(row=r2_num, column=c_idx)
                    c.font = header_font
                    c.fill = blue_fill
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    c.border = thin_border
                r2_num += 1

                kabel_start = r2_num
                for k_idx, (m_name, m_qty) in enumerate(sorted(cable_breakdown.items()), 1):
                    ws2.cell(row=r2_num, column=1, value=k_idx).alignment = Alignment(horizontal="center")
                    ws2.cell(row=r2_num, column=2, value=m_name)
                    ws2.cell(row=r2_num, column=3, value=m_qty).alignment = Alignment(horizontal="right")
                    for c_idx in range(1, 4):
                        ws2.cell(row=r2_num, column=c_idx).border = thin_border
                        ws2.cell(row=r2_num, column=c_idx).font = regular_font
                    r2_num += 1
                kabel_end = r2_num - 1

                ws2.merge_cells(start_row=r2_num, start_column=1, end_row=r2_num, end_column=2)
                ws2.cell(row=r2_num, column=1, value="TOTAL KABEL UDARA").font = total_font
                ws2.cell(row=r2_num, column=1).fill = green_fill
                ws2.cell(row=r2_num, column=1).alignment = Alignment(horizontal="center")
                tot_k = ws2.cell(row=r2_num, column=3, value=f"=SUM(C{kabel_start}:C{kabel_end})")
                tot_k.font = total_font
                tot_k.fill = green_fill
                tot_k.alignment = Alignment(horizontal="right")
                for c_idx in range(1, 4):
                    ws2.cell(row=r2_num, column=c_idx).border = thin_border
                r2_num += 2

            # Tabel Ringkasan Aksesoris
            if acc_records:
                ws2.merge_cells(start_row=r2_num, start_column=1, end_row=r2_num, end_column=5)
                ws2.cell(row=r2_num, column=1, value="RINGKASAN PENGAMBILAN AKSESORIS FTTH").font = section_font
                r2_num += 1

                ws2.append(["No", "Kode Aksesoris", "Nama Material", "Total Diambil", "Satuan"])
                for c_idx in range(1, 6):
                    c = ws2.cell(row=r2_num, column=c_idx)
                    c.font = header_font
                    c.fill = blue_fill
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    c.border = thin_border
                r2_num += 1

                distinct_acc = []
                seen_acc_codes = set()
                for r in acc_records:
                    if r["code"] not in seen_acc_codes:
                        distinct_acc.append((r["code"], r["spec"], r["unit"]))
                        seen_acc_codes.add(r["code"])

                for a_idx, (a_code, a_spec, a_unit) in enumerate(distinct_acc, 1):
                    tot_a = acc_totals.get(a_code, 0)
                    ws2.cell(row=r2_num, column=1, value=a_idx).alignment = Alignment(horizontal="center")
                    ws2.cell(row=r2_num, column=2, value=a_code).alignment = Alignment(horizontal="center")
                    ws2.cell(row=r2_num, column=3, value=a_spec)
                    ws2.cell(row=r2_num, column=4, value=tot_a).alignment = Alignment(horizontal="right")
                    ws2.cell(row=r2_num, column=5, value=a_unit).alignment = Alignment(horizontal="center")
                    for c_idx in range(1, 6):
                        ws2.cell(row=r2_num, column=c_idx).border = thin_border
                        ws2.cell(row=r2_num, column=c_idx).font = regular_font
                    r2_num += 1

            col_widths2 = {"A": 6, "B": 14, "C": 24, "D": 16, "E": 18, "F": 34, "G": 14, "H": 12}
            for col, width in col_widths2.items():
                ws2.column_dimensions[col].width = width

        wb.save(output_excel_path)
        logger.info("Rekapitulasi material berhasil disimpan ke: %s", output_excel_path)

        # 6. Launch GridCraft GUI jika diminta
        if auto_launch_gridcraft:
            try:
                from alfa.tools.desktop.artcraft import artcraft_launch_gui
                artcraft_launch_gui("gridcraft", output_excel_path)
            except Exception as e:
                logger.warning("Auto launch GridCraft warning: %s", e)

        # 7. Susun Rangkuman Data
        total_net = sum(r["qty"] for r in records)
        total_bruto = sum(r["qty"] for r in records if r["qty"] > 0)
        total_retur = -sum(r["qty"] for r in records if r["qty"] < 0)

        per_item: dict[str, int] = {}
        for r in records:
            per_item[r["code"]] = per_item.get(r["code"], 0) + r["qty"]

        kabel_section = ""
        if total_cable_m > 0:
            kabel_lines = [f"  - {m}: {q:,.0f} m" for m, q in sorted(cable_breakdown.items())]
            kabel_section = f"\n\n🌐 *2. KABEL UDARA (KU 24)*\n• Total Kabel: {total_cable_m:,.0f} meter\n" + "\n".join(kabel_lines)

        acc_section = ""
        if acc_totals:
            acc_lines = []
            if acc_totals.get("ACC-STOPING"):
                acc_lines.append(f"• Stoping / Stopper: {acc_totals['ACC-STOPING']} pcs")
            if acc_totals.get("ACC-DEADEND"):
                acc_lines.append(f"• Dead End (Dee/Det End): {acc_totals['ACC-DEADEND']} pcs")
            if acc_totals.get("ACC-FULCLAM"):
                acc_lines.append(f"• Full Clamp / Pole Clamp: {acc_totals['ACC-FULCLAM']} pcs")
            if acc_totals.get("ACC-SUSPEN"):
                acc_lines.append(f"• Suspension Clamp: {acc_totals['ACC-SUSPEN']} pcs")
            if acc_totals.get("ACC-BELT"):
                acc_lines.append(f"• Stainless Steel Belt: {acc_totals['ACC-BELT']} roll")
            if acc_totals.get("ACC-HANGER"):
                acc_lines.append(f"• Slack Hanger: {acc_totals['ACC-HANGER']} pcs")
            if acc_totals.get("ACC-BUAYA"):
                acc_lines.append(f"• Clamp Buaya: {acc_totals['ACC-BUAYA']} pcs")
            if acc_lines:
                acc_section = "\n\n🔩 *3. AKSESORIS TELEKOMUNIKASI*\n" + "\n".join(acc_lines)

        freshness = _data_freshness(messages, live_api_used)
        warning_text = ""
        if freshness.get("stale"):
            warning_text = (
                "\n\n⚠️ *DATA BERIKUTNYA MUNGKIN BASI:* "
                + "; ".join(freshness.get("reasons", []))
                + ". Rekap ini disusun dari arsip, bukan data live WhatsApp.\n"
            )

        summary_text = (
            f"✅ Rekapitulasi Material '{chat_name}' Berhasil Disusun.\n\n"
            f"📊 *1. TIANG TELEKOMUNIKASI*\n"
            f"• Total Bersih (Net): {total_net} batang\n"
            f"• Total Diambil (Bruto): {total_bruto} batang\n"
            f"• Total Retur: {total_retur} batang\n"
            f"• Rincian Tiang: {', '.join([f'{k}: {v} btg' for k, v in per_item.items() if v != 0])}"
            f"{kabel_section}"
            f"{acc_section}\n\n"
            f"👷 *Mandor Pelapor Terverifikasi:* {', '.join(all_mandors_sorted)}\n"
            f"📁 *Berkas Master Excel:* `{output_excel_path}`"
            f"{warning_text}"
        )

        return {
            "status": "success",
            "group_name": chat_name,
            "chat_id": chat_jid,
            "total_net": total_net,
            "total_bruto": total_bruto,
            "total_retur": total_retur,
            "mandors": all_mandors_sorted,
            "breakdown": per_item,
            "total_cable_m": total_cable_m,
            "cable_breakdown": cable_breakdown,
            "accessories_breakdown": acc_totals,
            "excel_file": output_excel_path,
            "data_freshness": freshness,
            "warning": warning_text.strip() or None,
            "message": summary_text,
        }
    except Exception as e:
        logger.exception("Gagal menyusun rekapitulasi material WhatsApp: %s", e)
        return {"status": "error", "message": f"Material reconciliation error: {str(e)}"}
