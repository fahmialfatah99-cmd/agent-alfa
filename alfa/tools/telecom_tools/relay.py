"""Telegram relay of WhatsApp findings and instant anomaly alerts."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Telecom")

@register_tool(category="system")
def wa_relay_send_from_telegram(
    target_chat_name_or_id: str,
    message: str,
) -> dict[str, Any]:
    """
    RELAY TELEGRAM KE WHATSAPP (MANUAL EKSPLISIT OLEH FAHMI):
    Meneruskan dan mengirimkan pesan teks dari Telegram ke kontak atau grup WhatsApp tertentu
    secara langsung melalui API WhatsApp bot.

    HUKUM BESI KEAMANAN SISTEM:
    - HANYA BOLEH DIEKSEKUSI jika ada perintah manual dan eksplisit dari Fahmi di Telegram (contoh: 'kirim ke grup IMT: ...').
    - DILARANG KERAS MENJADI BALASAN OTOMATIS (AUTO-REPLY). Dilarang membuat loop, auto-responder, atau bot yang membalas pesan WhatsApp tanpa perintah manusia!

    Args:
        target_chat_name_or_id: Nama grup (misal: 'IMT BKL EMR FTTH Project Team') atau nomor telepon target.
        message: Isi pesan yang ingin dikirimkan.
    """
    try:
        from alfa.tools.system.integrations import wa_send_message

        target = target_chat_name_or_id.strip()
        msg = message.strip()

        if not target or not msg:
            return {"status": "error", "message": "Target tujuan dan isi pesan tidak boleh kosong."}

        logger.info("Executing manual WhatsApp relay command from Telegram to: %s", target)
        res = wa_send_message(to=target, message=msg)
        return {
            "status": "success" if res.get("status") in ("success", "ok") or not res.get("error") else "error",
            "target": target,
            "message_sent": msg,
            "raw_response": res,
            "confirmation": f"Pesan berhasil diteruskan ke WhatsApp: '{target}'." if res.get("status") != "error" else f"Gagal mengirim ke WhatsApp: {res.get('message') or res.get('error')}",
        }
    except Exception as e:
        logger.exception("Gagal relay pesan ke WhatsApp: %s", e)
        return {"status": "error", "message": f"WhatsApp relay error: {str(e)}"}

@register_tool(category="telecom")
def dispatch_instant_material_anomaly_alert(
    cluster_name: str,
    anomaly_type: str,
    details: str,
    mandor_name: str = "",
    send_telegram: bool = True,
    force_send: bool = False,
) -> dict[str, Any]:
    """
    KIRIM NOTIFIKASI INSTAN ANOMALI LAPANGAN KE TELEGRAM (ANTI-DUPLIKASI & ANTI-TABRAKAN):
    Mengirimkan kartu peringatan instan real-time bila ditemukan anomali material kritis
    (misal: retur material mendadak, pengambilan fisik tanpa DO, selisih scrap).

    ATURAN KETAT ANTI-TABRAKAN:
    - Memakai tabel deduplikasi mandiri (wa_instant_alerts).
    - TIDAK mengubah status wa_reported_messages sehingga TIDAK merusak/menduplikasi briefing pagi/sore.
    - Dilengkapi tag cluster eksplisit [ALERT: <CLUSTER>] agar laporan antar proyek terpisah bersih.

    Args:
        cluster_name: Nama cluster proyek (misal: 'Lahat', 'Curup').
        anomaly_type: Kategori anomali (misal: 'RETUR_MATERIAL', 'SELISIH_PENGAMBILAN', 'DOKUMEN_BELUM_LENGKAP').
        details: Deskripsi detail masalah dan jumlah barang.
        mandor_name: Nama mandor terkait (opsional).
        send_telegram: True jika dikirimkan langsung ke Telegram Fahmi.
        force_send: True untuk bypass deduplikasi jika memang darurat.

    Returns:
        Dict status pengiriman alert, alert_id, dan preview teks.
    """
    try:
        import hashlib

        from alfa.core.db.connection import get_sync_db

        cname_upper = cluster_name.upper().strip()
        atype_upper = anomaly_type.upper().strip()
        now_str = datetime.now().strftime("%d-%m-%Y %H:%M WIB")

        # Buat identitas unik alert
        raw_hash = hashlib.sha256(f"{cname_upper}:{atype_upper}:{details.strip()}".encode()).hexdigest()[:16]
        alert_id = f"alert_{cname_upper}_{raw_hash}"

        # 1. Pastikan tabel wa_instant_alerts tersedia dan cek deduplikasi
        with get_sync_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wa_instant_alerts (
                    alert_id TEXT PRIMARY KEY,
                    cluster TEXT,
                    anomaly_type TEXT,
                    details TEXT,
                    dispatched_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            if not force_send:
                exists = conn.execute("SELECT 1 FROM wa_instant_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
                if exists:
                    return {
                        "status": "skipped",
                        "alert_id": alert_id,
                        "message": f"Alert untuk anomali '{atype_upper}' di Cluster {cname_upper} sudah pernah dikirim (anti-duplikasi aktif).",
                    }

        # 2. Format Kartu Notifikasi Bersih & Rapi (Namespace Tegas)
        alert_card = (
            f"⚡ *[ALERT INSTAN LAPANGAN: {cname_upper}]*\n"
            f"🏢 *Cluster*: `{cname_upper}`\n"
            f"⚠️ *Kategori*: `{atype_upper}`\n"
        )
        if mandor_name:
            alert_card += f"👷 *Mandor / PIC*: {mandor_name}\n"
        alert_card += (
            f"📋 *Rincian*: {details}\n"
            f"🕒 *Waktu Terdeteksi*: `{now_str}`\n\n"
            f"💡 _Notifikasi event-driven langsung (terisolasi, tidak menduplikasi Briefing Harian)._"
        )

        # 3. Kirim ke Telegram bila diminta
        telegram_sent = False
        if send_telegram:
            try:
                from alfa.core.notification import (
                    get_telegram_runtime,
                    safe_send_message_sync,
                )
                from alfa.core.runtime_ctx import get_current_chat_id

                app, _loop = get_telegram_runtime()
                target_chat_id = get_current_chat_id()
                if app and target_chat_id:
                    res_tg = safe_send_message_sync(app, target_chat_id, alert_card)
                    telegram_sent = res_tg.get("status") == "success"
                else:
                    logger.info("Telegram runtime tidak aktif (mode non-bot/headless). Alert disimpan lokal.")
            except Exception as e:
                logger.warning("Gagal mengirim pesan Telegram alert instan: %s", e)

        # 4. Catat ke tabel wa_instant_alerts
        with get_sync_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO wa_instant_alerts (alert_id, cluster, anomaly_type, details)
                VALUES (?, ?, ?, ?)
                """,
                (alert_id, cname_upper, atype_upper, details),
            )
            conn.commit()

        return {
            "status": "success",
            "alert_id": alert_id,
            "cluster": cname_upper,
            "anomaly_type": atype_upper,
            "telegram_sent": telegram_sent,
            "preview_card": alert_card,
            "message": f"Alert instan [{cname_upper}] berhasil diproses dan disimpan ke log independen.",
        }
    except Exception as e:
        logger.exception("Gagal memproses instant material alert: %s", e)
        return {"status": "error", "message": f"Instant alert error: {str(e)}"}
