"""Jembatan API bot WhatsApp (chat, pesan, arsip, format, status)."""
import json
import logging
import os
import sqlite3
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Integrations")

#: Error realistis untuk akses arsip/DB bot WA.
_WA_DB_ERR = (sqlite3.Error, TypeError, ValueError, AttributeError, ImportError)
_WA_READ_ERR = (sqlite3.Error, OSError, TypeError, ValueError, AttributeError)


@register_tool(category="system")
def wa_get_chats(
    limit: int = 15,
    only_unread: bool = False,
    only_unreplied: bool = False,
    chat_type: str = "all",
    search: str = "",
) -> dict[str, Any]:
    """
    Daftar chat WhatsApp terbaru dengan filter cerdas (belum terbuka/unread, belum dibalas, grup vs pribadi/japri, pencarian).

    Args:
        limit: Jumlah chat maksimal yang ditampilkan (1-50, default 15).
        only_unread: True = hanya tampilkan chat yang memiliki pesan belum dibaca (belum dibuka).
        only_unreplied: True = hanya tampilkan chat yang BELUM DIBALAS oleh pengguna (pesan terakhir dari lawan bicara / last_from_me is False).
        chat_type: 'all' (semua), 'personal' (hanya chat pribadi / japri), 'group' (hanya grup WhatsApp).
        search: Filter pencarian nama kontak atau nama grup (case-insensitive).
    """
    needs_client_filtering = only_unreplied or (chat_type in ("personal", "group")) or bool(search)
    fetch_limit = min(50, max(limit * 3, 40)) if needs_client_filtering else limit
    res = _wa_call("GET", "/api/chats", {"limit": fetch_limit, "unread": "1" if only_unread else "0"})

    if isinstance(res, dict) and res.get("status") == "success":
        chats = res.get("chats", [])
        if isinstance(chats, list):
            if only_unread:
                chats = [c for c in chats if (c.get("unread") or 0) > 0]
            if only_unreplied:
                chats = [c for c in chats if not c.get("last_from_me")]
            if chat_type == "personal":
                chats = [c for c in chats if not c.get("is_group")]
            elif chat_type == "group":
                chats = [c for c in chats if c.get("is_group")]
            if search:
                s_low = search.lower().strip()
                chats = [c for c in chats if s_low in str(c.get("name") or "").lower() or s_low in str(c.get("id") or "").lower()]

            res["chats"] = chats[:limit]
            res["total"] = len(res["chats"])
            res["filter_applied"] = {
                "only_unread": only_unread,
                "only_unreplied": only_unreplied,
                "chat_type": chat_type,
                "search": search,
            }
    return res

@register_tool(category="system")
def wa_get_messages(
    chat: str,
    limit: int = 20,
    mark_as_seen: bool = False,
    only_unread: bool = False,
    mark_as_read: bool = True,
    order: str = "desc",
) -> dict[str, Any]:
    """
    Baca riwayat pesan sebuah chat WhatsApp (terbaru didahulukan).

    ATURAN PRESENTASI KE PENGGUNA: Sampaikan PESAN ASLI apa adanya (verbatim).
    DILARANG mengubah, mengedit, atau memparafrasekan teks isi pesan WhatsApp.
    Tampilkan pengirim, waktu, dan teks pesan persis seperti aslinya.

    Args:
        chat: ID/nomor/nama chat (mis. '62812xxxx', 'Keluarga', 'xxx@g.us').
        limit: Jumlah pesan (1-60, default 20).
        mark_as_seen: True = tandai pesan chat ini sebagai sudah dibaca di WhatsApp Web (sendSeen).
        only_unread: True = HANYA ambil pesan yang belum pernah dibaca/dilihat (mencegah membaca ulang).
        mark_as_read: True = otomatis catat pesan ke database SQLite sebagai sudah dibaca.
        order: Urutan pesan: 'desc' = terbaru di awal (default), 'asc' = terlama di awal.
    """
    fetch_limit = min(60, max(limit * 2, 30)) if only_unread else limit
    params: dict[str, Any] = {"chat": chat, "limit": fetch_limit}
    if mark_as_seen:
        params["mark_seen"] = "1"
    res = _wa_call("GET", "/api/messages", params)
    if isinstance(res, dict) and res.get("status") == "success":
        msgs = res.get("messages", [])
        if isinstance(msgs, list):
            # Check read state in SQLite
            msg_ids = [str(m.get("id") or m.get("msg_id") or "").strip() for m in msgs]
            read_ids: set[str] = set()
            try:
                from alfa.core.db.wa_tracking import (
                    get_read_wa_msg_ids_sync,
                    record_wa_messages_read_sync,
                )

                read_ids = get_read_wa_msg_ids_sync(msg_ids)
            except _WA_DB_ERR:
                read_ids = set()

            for m in msgs:
                mid = str(m.get("id") or m.get("msg_id") or "").strip()
                m["is_read"] = bool(mid in read_ids)

            # Sort by timestamp (default desc: newest first)
            reverse = (order.lower() != "asc")
            msgs.sort(key=lambda m: int(m.get("ts") or 0), reverse=reverse)

            unread_count = sum(1 for m in msgs if not m.get("is_read") and not m.get("from_me"))

            if only_unread:
                msgs = [m for m in msgs if not m.get("is_read") and not m.get("from_me")]
                if not msgs:
                    res["messages"] = []
                    res["total"] = 0
                    res["unread_count"] = 0
                    res["message"] = f"Tidak ada pesan baru di chat '{res.get('chat_name', chat)}'. Semua pesan sudah dibaca."
                    return res

            msgs = msgs[:limit]

            if mark_as_read and msgs:
                to_mark = [m for m in msgs if not m.get("is_read")]
                if to_mark:
                    try:
                        record_wa_messages_read_sync(to_mark)
                        for m in to_mark:
                            m["is_read"] = True
                    except _WA_DB_ERR as exc:
                        logger.debug("Kegagalan tak terduga di wa_get_messages: %s", exc)

            res["messages"] = msgs
            res["total"] = len(msgs)
            res["unread_count"] = unread_count
    return res

@register_tool(category="system")
def wa_search_messages(query: str, search_live_wa: bool = True) -> dict[str, Any]:
    """
    Cari kata kunci di riwayat pesan WhatsApp (arsip lokal permanen & live WA Web).

    Args:
        query: Kata kunci pencarian.
        search_live_wa: True = cari juga di sesi aktif WhatsApp Web (default True).
    """
    local_hits = []
    try:
        from alfa.core.db.wa_tracking import search_wa_archive_sync

        local_hits = search_wa_archive_sync(query=query, limit=20)
    except _WA_DB_ERR:
        local_hits = []

    live_hits: list[dict[str, Any]] = []
    if search_live_wa:
        res = _wa_call("GET", "/api/search", {"q": query})
        if isinstance(res, dict) and res.get("status") == "success":
            live_hits = res.get("hits", []) or []

    seen_keys = set()
    combined = []
    for h in local_hits + live_hits:
        key = str(h.get("msg_id") or h.get("id") or f"{h.get('sender')}_{h.get('ts')}_{h.get('body')}")
        if key not in seen_keys:
            seen_keys.add(key)
            combined.append(h)

    return {
        "status": "success",
        "query": query,
        "total": len(combined),
        "local_archive_hits": len(local_hits),
        "live_wa_hits": len(live_hits),
        "hits": combined[:30],
    }

@register_tool(category="system")
def wa_get_history_archive(chat: str = "", query: str = "", sender: str = "", limit: int = 20) -> dict[str, Any]:
    """
    Cari dan baca riwayat arsip pesan WhatsApp lokal di database SQLite permanen.
    Sangat cepat, tidak terikat batas buffer 250, dan tidak bergantung pada beban browser.

    ATURAN PRESENTASI: Tampilkan kutipan teks asli secara verbatim.

    Args:
        chat: Filter berdasarkan nama grup / nomor chat (opsional).
        query: Kata kunci isi pesan (opsional).
        sender: Filter nama pengirim (opsional).
        limit: Jumlah pesan maksimal (default 20, max 100).
    """
    try:
        from alfa.core.db.wa_tracking import search_wa_archive_sync

        records = search_wa_archive_sync(query=query, chat_id=chat, sender=sender, limit=limit)
        return {
            "status": "success",
            "total": len(records),
            "chat": chat,
            "query": query,
            "messages": records,
        }
    except _WA_READ_ERR as e:
        return {"status": "error", "message": f"Gagal membaca arsip WA: {e}"}

@register_tool(category="system")
def wa_get_incoming(
    limit: int = 20,
    only_unread: bool = True,
    mark_as_read: bool = True,
    order: str = "desc",
    only_group: bool = False,
) -> dict[str, Any]:
    """
    Pesan WhatsApp MASUK terbaru yang terekam bot.

    ATURAN PRESENTASI KE PENGGUNA: Sampaikan PESAN ASLI apa adanya (verbatim).
    DILARANG mengubah, mengedit, atau memparafrasekan teks isi pesan WhatsApp.
    Tampilkan pengirim, grup/kontak, waktu, dan teks pesan persis seperti aslinya.

    Args:
        limit: Jumlah pesan (default 20, max 100).
        only_unread: True (default) = HANYA ambil pesan yang belum pernah dibaca/dilaporkan oleh bot (mencegah pesan dibaca berulang-ulang). Set False untuk melihat riwayat pesan masuk lama.
        mark_as_read: True = Otomatis catat pesan yang dibaca ke database agar tidak dibaca ulang pada pengecekan pesan baru berikutnya.
        order: Urutan pesan: 'desc' = terbaru di awal (default), 'asc' = terlama di awal.
        only_group: True = HANYA ambil pesan dari GRUP WhatsApp (abaikan chat pribadi). Gunakan saat user menanyakan pesan/obrolan grup.
    """
    fetch_limit = max(limit, 250) if only_unread else limit
    res = _wa_call("GET", "/api/incoming", {"limit": fetch_limit})
    if isinstance(res, dict) and "incoming" in res and isinstance(res["incoming"], list):
        client_status = str(res.get("client_status") or "").upper()
        is_offline = (res.get("is_ready") is False) or (client_status in ("QR_READY", "INITIALIZING", "DISCONNECTED"))

        ignored_types = {
            "e2e_notification",
            "notification_template",
            "notification",
            "protocol",
            "gp2",
            "broadcast_notification",
            "ciphertext",
            "revoked",
        }

        filtered = []
        seen_keys = set()
        for it in res["incoming"]:
            if not isinstance(it, dict) or it.get("from_me"):
                continue
            if only_group and not it.get("is_group"):
                continue
            mtype = str(it.get("msg_type") or "chat").lower()
            if mtype in ignored_types:
                continue
            body = str(it.get("body") or "").strip()
            if body.lower() in ("[e2e_notification]", "[notification_template]", "[protocol]", "[ciphertext]", "[gp2]"):
                continue
            if not body and not it.get("has_media") and mtype != "chat":
                continue
            if any(
                bad in str(it.get("chat", "")) or bad in str(it.get("sender", "")) or bad in str(it.get("author", ""))
                for bad in ("@broadcast", "@newsletter")
            ):
                continue
            mid = str(it.get("msg_id") or it.get("id") or "").strip()
            if not mid:
                chat_id = str(it.get("chat") or it.get("chat_id") or "").strip()
                sender = str(it.get("sender_name") or it.get("sender") or it.get("author") or "").strip()
                msg_ts = int(it.get("msg_ts") or it.get("ts") or 0)
                body_sub = body[:40]
                import hashlib
                hash_key = f"{chat_id}_{sender}_{msg_ts}_{body_sub}"
                # md5 HANYA utk id dedup deterministik (bukan kriptografi)
                mid = "wa_" + hashlib.md5(
                    hash_key.encode("utf-8"), usedforsecurity=False
                ).hexdigest()[:16]
                it["msg_id"] = mid

            dedup_key = mid if mid else f"{it.get('chat')}_{body}_{it.get('msg_ts')}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            filtered.append(it)

        # Permanently archive all genuine incoming messages into SQLite
        try:
            from alfa.core.db.wa_tracking import archive_wa_messages_sync

            archive_wa_messages_sync(filtered)
        except _WA_DB_ERR as exc:
            logger.debug("Kegagalan tak terduga di wa_get_incoming: %s", exc)

        # Check read status in SQLite
        msg_ids = [str(it.get("msg_id") or it.get("id") or "").strip() for it in filtered]
        read_ids: set[str] = set()
        try:
            from alfa.core.db.wa_tracking import (
                get_read_wa_msg_ids_sync,
                record_wa_messages_read_sync,
            )

            read_ids = get_read_wa_msg_ids_sync(msg_ids)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error):
            read_ids = set()

        for it in filtered:
            mid = str(it.get("msg_id") or it.get("id") or "").strip()
            is_read = bool(mid in read_ids)
            it["is_read"] = is_read
            it["status_dibaca"] = "SUDAH DIBACA" if is_read else "BELUM DIBACA"

        # Sort by timestamp (default: newest first)
        reverse = (order.lower() != "asc")
        filtered.sort(
            key=lambda m: (int(m.get("msg_ts") or 0), str(m.get("ts") or "")),
            reverse=reverse,
        )

        total_unread = sum(1 for it in filtered if not it.get("is_read"))

        # Check offline / QR_READY warning
        if is_offline:
            if client_status == "QR_READY":
                res["warning"] = "⚠️ WhatsApp bot saat ini BELUM TERHUBUNG (Status: QR_READY). Sesi WhatsApp terputus atau menunggu scan QR via /wa."
            else:
                res["warning"] = f"⚠️ WhatsApp bot saat ini BELUM SIAP (Status: {client_status or 'OFFLINE'})."

        if only_unread:
            # If the WhatsApp bot is not live/connected, never report cached buffer as fresh unread messages
            if is_offline:
                res["incoming"] = []
                res["count"] = 0
                res["total"] = 0
                res["unread_count"] = 0
                if client_status == "QR_READY":
                    res["message"] = "Tidak ada pesan baru. Perhatian: WhatsApp bot saat ini BELUM TERHUBUNG (Status: QR_READY). Silakan scan QR via /wa."
                else:
                    res["message"] = f"Tidak ada pesan baru. Perhatian: WhatsApp bot saat ini BELUM SIAP (Status: {client_status or 'OFFLINE'})."
                return res

            filtered = [it for it in filtered if not it.get("is_read")]
            if not filtered:
                res["incoming"] = []
                res["count"] = 0
                res["total"] = 0
                res["unread_count"] = 0
                res["message"] = "Semua pesan WhatsApp masuk sudah dibaca. Tidak ada pesan baru."
                return res

        filtered = filtered[:limit]

        if mark_as_read and filtered:
            to_mark = [it for it in filtered if not it.get("is_read")]
            if to_mark:
                try:
                    record_wa_messages_read_sync(to_mark)
                    for it in to_mark:
                        it["is_read"] = True
                        it["status_dibaca"] = "SUDAH DIBACA"
                except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as exc:
                    logger.debug("Kegagalan tak terduga di wa_get_incoming: %s", exc)

        res["incoming"] = filtered
        res["count"] = len(filtered)
        res["total"] = len(filtered)
        res["unread_count"] = total_unread
        if not only_unread and all(it.get("is_read") for it in filtered):
            res["note"] = "Semua pesan di atas adalah RIWAYAT PESAN LAMA yang SUDAH DIBACA sebelumnya. Tidak ada pesan baru."
    return res

@register_tool(category="system")
def wa_clear_history(
    target: str = "incoming",
    clear_archive: bool = False,
    clear_read_state: bool = False,
) -> dict[str, Any]:
    """
    Hapus atau bersihkan riwayat buffer pesan WhatsApp dan/atau arsip lokal.
    Gunakan saat pengguna meminta menghapus riwayat chat WA, membersihkan pesan masuk lama, atau mereset buffer pesan.

    Args:
        target: 'incoming' = bersihkan buffer pesan masuk (recent_incoming.json) di bot WA lokal.
                'all' = bersihkan buffer incoming sekaligus arsip SQLite.
        clear_archive: True = bersihkan juga arsip pesan di SQLite (wa_incoming_archive).
        clear_read_state: True = reset riwayat status baca di SQLite (wa_read_messages).
    """
    results: dict[str, Any] = {"status": "success", "cleared_targets": []}

    # 1. Clear incoming buffer via WA API
    try:
        api_res = _wa_call("POST", "/api/incoming/clear")
        if isinstance(api_res, dict) and api_res.get("status") == "success":
            results["cleared_targets"].append("buffer_incoming_api")
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
        logger.debug("Failed to call wa /api/incoming/clear: %s", e)

    # Fallback/Direct disk clear of recent_incoming.json
    try:
        wa_bot_incoming_file = os.getenv(
            "WA_BOT_INCOMING_FILE",
            os.path.expanduser("~/wa-sheets-bot/recent_incoming.json"),
        )
        if os.path.exists(wa_bot_incoming_file):
            with open(wa_bot_incoming_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            results["cleared_targets"].append("buffer_incoming_file")
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
        logger.debug("Failed to clear recent_incoming.json: %s", e)

    # 2. Clear SQLite archive if requested or target == 'all'
    if clear_archive or target.lower() == "all":
        try:
            from alfa.core.db.wa_tracking import clear_wa_archive_sync

            count = clear_wa_archive_sync()
            results["cleared_archive_count"] = count
            results["cleared_targets"].append("sqlite_archive")
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
            results["archive_error"] = str(e)

    # 3. Clear read state if requested or target == 'all'
    if clear_read_state or target.lower() == "all":
        try:
            from alfa.core.db.wa_tracking import clear_wa_read_state_sync

            count = clear_wa_read_state_sync()
            results["cleared_read_state_count"] = count
            results["cleared_targets"].append("sqlite_read_state")
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
            results["read_state_error"] = str(e)

    results["message"] = "Riwayat pesan WhatsApp berhasil dibersihkan/dikosongkan."
    return results

@register_tool(category="system")
def wa_mark_read(chat: str = "", msg_id: str = "", send_seen_to_wa: bool = False) -> dict[str, Any]:
    """
    Tandai pesan WhatsApp atau chat tertentu sebagai sudah dibaca, agar bot tidak membacanya ulang.

    Args:
        chat: ID/nama chat yang ingin ditandai sudah dibaca (misal nama grup atau nomor).
        msg_id: ID pesan tertentu jika ingin menandai satu pesan spesifik.
        send_seen_to_wa: True = kirim juga sinyal 'read receipt' (centang biru) ke WhatsApp Web.
    """
    marked_db = 0
    try:
        from alfa.core.db.wa_tracking import (
            mark_chat_read_sync,
            record_wa_messages_read_sync,
        )

        if chat:
            marked_db += mark_chat_read_sync(chat)
        if msg_id:
            record_wa_messages_read_sync([{"msg_id": msg_id, "chat": chat}])
            marked_db += 1
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as e:
        logger.debug("Failed local mark read: %s", e)

    wa_result: dict[str, Any] = {}
    if send_seen_to_wa and chat:
        wa_result = _wa_call("POST", "/api/seen", body={"chat": chat})

    return {
        "status": "success",
        "chat": chat,
        "msg_id": msg_id,
        "marked_in_db": marked_db,
        "wa_seen_result": wa_result,
    }

@register_tool(category="system")
def wa_get_me() -> dict[str, Any]:
    """Info akun WhatsApp yang login di bot (nama, nomor)."""
    return _wa_call("GET", "/api/me")

@register_tool(category="system")
def wa_send_message(to: str, message: str) -> dict[str, Any]:
    """
    Kirim pesan teks WhatsApp ke nomor/nama grup.

    Args:
        to: Nomor ('62812xxx'/'0812xxx'), nama grup, atau JID ('xxx@c.us'/'xxx@g.us').
        message: Isi pesan (max 2000 karakter).
    """
    return _wa_call("POST", "/api/send", body={"to": to, "message": message})

@register_tool(category="system")
def wa_post_status(text: str, background_color: str = "") -> dict[str, Any]:
    """
    Posting status / story teks ke WhatsApp pribadi (feed status@broadcast).

    Args:
        text: Isi teks status (max 700 karakter).
        background_color: Kode warna heksadesimal latar belakang (opsional, misal '#0b3296', '#075E54', '#702963').
    """
    body: dict[str, Any] = {"text": text}
    if background_color:
        body["backgroundColor"] = background_color
    return _wa_call("POST", "/api/status", body=body)

@register_tool(category="system")
def wa_list_formats() -> dict[str, Any]:
    """Daftar format pencatatan WA otomatis (keyword → tab Sheets, on/off)."""
    return _wa_call("GET", "/api/formats")

@register_tool(category="system")
def wa_toggle_format(name: str, enabled: bool = True) -> dict[str, Any]:
    """
    Hidup/matikan satu format pencatatan WA otomatis.

    Args:
        name: Nama format (mis. 'Stok', 'TJHIN').
        enabled: True = catat otomatis, False = abaikan.
    """
    return _wa_call("POST", "/api/formats/toggle", body={"name": name, "enabled": enabled})

@register_tool(category="system")
def wa_add_format(name: str, keywords: str = "", tab: str = "") -> dict[str, Any]:
    """
    Tambah format pencatatan WA baru (pesan mengandung keyword → tersimpan ke tab Sheets).

    Args:
        name: Nama format baru.
        keywords: Keyword pemicu dipisah koma (default = nama format). Mis. 'serah terima, bast'.
        tab: Nama tab Sheets tujuan (default = nama format).
    """
    kws = [k.strip() for k in keywords.split(",") if k.strip()]
    return _wa_call("POST", "/api/formats", body={"name": name, "keywords": kws, "tab": tab or name})

@register_tool(category="system")
def wa_delete_format(name: str) -> dict[str, Any]:
    """
    Hapus format pencatatan WA (berhenti mencatat pesan berkeyword itu).

    Args:
        name: Nama format yang dihapus.
    """
    return _wa_call("DELETE", "/api/formats", body={"name": name})

@register_tool(category="system")
def wa_get_records(report_format: str = "", limit: int = 10) -> dict[str, Any]:
    """
    Baca catatan laporan WA yang terekam (terbaru dulu).

    Args:
        report_format: Filter nama format (kosongkan = semua).
        limit: Jumlah catatan (1-50, default 10).
    """
    return _wa_call("GET", "/api/records", {"format": report_format, "limit": limit})


def _wa_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Panggil API bot WA lewat paket publik.

    Lookup dilakukan dinamis supaya patch/mock pada
    ``alfa.tools.system.integrations._wa_api`` tetap berlaku. Argumen
    diteruskan apa adanya agar call signature mock tetap identik.
    """
    from alfa.tools.system import integrations as _pkg

    return _pkg._wa_api(*args, **kwargs)
