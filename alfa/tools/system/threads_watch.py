"""Threads Watch — baca profil publik Threads (Meta) & laporkan post baru.

Additive-only, read-only, tanpa login, dan tegas pada batas robots.txt
(hanya halaman profil publik `@handle`, tanpa /p/ /comments/ /liked_by/).
Laporan HANYA ke Telegram (pola Penjaga Harian). Akun publik @xalf._1
(fahmi alfatah) dipantau: post baru, jumlah followers, jumlah Threads.

Bila halaman tidak menyajikan data (anti-bot bertahap), alat berstatus
gagal-lembut — TIDAK pernah mengganggu jalur lain (zero-regression).
"""

from __future__ import annotations

import html as html_mod
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from alfa.core.db.connection import get_sync_db
from alfa.tools.registry import register_tool
from alfa.tools.system.guardian import _primary_chat_id

logger = logging.getLogger("Tools.ThreadsWatch")

_THREADS_URLS = (
    "https://www.threads.net/@{handle}",
    "https://www.threads.com/@{handle}",
)
_USER_AGENTS = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
)
_PROFILE_HTML_OK = 'property="og:type" content="profile"'
_POST_RE = re.compile(
    r"https://www\.threads\.(?:net|com)/@[A-Za-z0-9._]+/post/([A-Za-z0-9]+)"
)
_OG_META_RE = re.compile(
    r'property="og:(?P<key>[a-z_:]+)"\s*content="(?P<val>[^"]*)"'
)
_STATS_RE = re.compile(
    r"(?P<f>\d[\d.,]*)\s*Followers\s*[•|]?\s*(?P<t>\d[\d.,]*)\s*Threads",
    re.IGNORECASE,
)


def _handle_norm(handle: str) -> str:
    """Bersihkan input: buang @, spasi, dan query apapun."""
    raw = (handle or "").strip().lstrip("@")
    return raw.split("/")[0].split("?")[0].strip()


def _default_handle() -> str:
    return _handle_norm(os.getenv("ALFA_THREADS_HANDLE", "xalf._1"))


def _fetch_profile_html(handle: str) -> tuple[str, str]:
    """Ambil HTML profil publik (SSR) — coba UA/domain beruntun; gagal → ''. """
    target = _handle_norm(handle)
    for ua in _USER_AGENTS:
        for url_tpl in _THREADS_URLS:
            url = url_tpl.format(handle=urllib.parse.quote(target))
            try:
                req = urllib.request.Request(url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310 — https tetap
                    text = (resp.read() or b"").decode(
                        resp.headers.get_content_charset() or "utf-8", "replace"
                    )
                if _PROFILE_HTML_OK in text:
                    return text, url
            except Exception:  # noqa: BLE001 — pembaca wajib gagal-lembut
                continue
    return "", ""


def _clean(val: str) -> str:
    return html_mod.unescape(val or "").strip()


def _to_int(raw: str) -> int:
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


def _parse_profile(raw_html: str) -> dict[str, Any]:
    """Parse profil SSR: nama, followers, jumlah threads, + post bila ada."""
    og_pairs = [
        ("og:" + m.group("key"), _clean(m.group("val")))
        for m in _OG_META_RE.finditer(raw_html)
    ]

    title = next(
        (v for k, v in og_pairs if k == "og:title"), ""
    )
    stats = {"followers": 0, "threads_n": 0}
    for m in _STATS_RE.finditer(html_mod.unescape(raw_html)):
        stats = {
            "followers": _to_int(m.group("f")),
            "threads_n": _to_int(m.group("t")),
        }
        break

    # Post: og:url yang mengandung /post/<ID> → teks = og:description
    # SESUDAH og:url itu (urutan SSR: url dulu baru deskripsi).
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, (key, val) in enumerate(og_pairs):
        if key != "og:url" or "/post/" not in val:
            continue
        post_match = _POST_RE.search(_clean(val))
        if not post_match:
            continue
        post_id = post_match.group(1)
        if post_id in seen:
            continue
        seen.add(post_id)
        desc = ""
        for next_key, next_val in og_pairs[i + 1 : i + 12]:
            if next_key == "og:url":
                break
            if next_key == "og:description" and next_val:
                desc = next_val
                break
        handle_part = _clean(val).split("/@", 1)[-1]
        posts.append(
            {
                "post_id": post_id,
                "url": f"https://www.threads.com/@{handle_part}",
                "text": (desc or "")[:280],
            }
        )
    name = ""
    if title:
        name = re.sub(r"\s*\(.*?\)\s*[•|]\s*Threads.*$", "", title).strip()
    return {
        "name": name,
        "followers": stats["followers"],
        "threads_n": stats["threads_n"],
        "posts": posts,
    }


# ── Penyimpanan lokal (tabel additive) ──────────────────────────────────────

_SQL_POSTS_TABLE = """
        CREATE TABLE IF NOT EXISTS threads_posts (
            post_id TEXT PRIMARY KEY,
            handle TEXT NOT NULL,
            text TEXT,
            url TEXT,
            crawled_at TEXT
        )
        """
_SQL_STATE_TABLE = """
        CREATE TABLE IF NOT EXISTS threads_profile_state (
            handle TEXT PRIMARY KEY,
            name TEXT,
            followers INTEGER NOT NULL DEFAULT 0,
            threads_n INTEGER NOT NULL DEFAULT 0,
            last_seen_post_id TEXT,
            updated_at TEXT
        )
        """


def _ensure_tables(conn) -> None:
    conn.execute(_SQL_POSTS_TABLE)
    conn.execute(_SQL_STATE_TABLE)


def _save_profile_and_posts(
    handle: str, profile: dict[str, Any]
) -> list[dict[str, Any]]:
    """Insert post baru (dedup saja PK) + mutakhirkan state profil.

    Balik daftar post yang BARU terlihat (belum pernah terekam).
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_posts: list[dict[str, Any]] = []
    with get_sync_db() as conn:
        _ensure_tables(conn)
        for post in profile.get("posts", []):
            cur = conn.execute(
                "INSERT OR IGNORE INTO threads_posts "
                "(post_id, handle, text, url, crawled_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    post["post_id"],
                    handle,
                    post.get("text") or "",
                    post.get("url") or "",
                    now,
                ),
            )
            if cur.rowcount > 0:
                new_posts.append(post)
        last_seen = (
            profile.get("posts", [{}])[-1].get("post_id") if profile.get("posts") else None
        )
        conn.execute(
            "INSERT INTO threads_profile_state (handle, name, followers, "
            "threads_n, last_seen_post_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(handle) DO UPDATE SET "
            "name=excluded.name, followers=excluded.followers, "
            "threads_n=excluded.threads_n, last_seen_post_id="
            "COALESCE(excluded.last_seen_post_id, threads_profile_state."
            "last_seen_post_id), updated_at=excluded.updated_at",
            (
                handle,
                profile.get("name") or "",
                int(profile.get("followers") or 0),
                int(profile.get("threads_n") or 0),
                last_seen,
                now,
            ),
        )
        conn.commit()
    return new_posts


def _list_known_posts(handle: str, limit: int = 10) -> list[dict[str, Any]]:
    import sqlite3

    from alfa.core.db.connection import get_sync_db

    with get_sync_db() as conn:
        _ensure_tables(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT post_id, handle, text, url, crawled_at FROM threads_posts "
            "WHERE handle = ? ORDER BY crawled_at DESC LIMIT ?",
            (handle, max(1, min(int(limit), 50))),
        ).fetchall()
    return [dict(r) for r in rows]


def _digest_text(
    handle: str,
    profile: dict[str, Any],
    new_posts: list[dict[str, Any]],
) -> str:
    emoji = "🧵"
    head = f"{emoji} *THREADS WATCH @{handle}*"
    stats = (
        f"👥 {profile.get('followers', '?')} followers | "
        f"🪡 {profile.get('threads_n', '?')} threads"
    )
    if not new_posts:
        return (
            f"{head}\n{stats}\n"
            "🫥 Tidak ada post baru sejak cek terakhir."
        )
    lines = [head, stats, f"🆕 {len(new_posts)} post baru:"]
    for p in new_posts[:8]:
        text = (p.get("text") or "").replace("\n", " ").strip()
        snippet = (text[:160] + ("…" if len(text) > 160 else "")) or "(teks kosong)"
        lines.append(f"• {snippet}\n  {p.get('url') or ''}")
    return "\n".join(lines)


# ── Tools ───────────────────────────────────────────────────────────────────


@register_tool(category="system")
def threads_watch_check(handle: str = "") -> dict[str, Any]:
    """Cek profil publik Threads SEKARANG: post baru + statistik akun.

    Read-only (tanpa login, hormat robots.txt — hanya halaman profil @).
    Laporkan field ``digest_text`` VERBATIM ke pengguna bila diminta kirim.

    Args:
        handle: username Threads (tanpa @; default akun pemilik: xalf._1).
    """
    target = _handle_norm(handle) or _default_handle()
    raw, url = _fetch_profile_html(target)
    if not raw:
        logger.warning("Threads profile @%s tidak terbaca (SSR kosong).", target)
        return {
            "status": "error",
            "message": (
                f"Halaman @{target} tidak menyajikan data publik sekarang "
                "(halaman banteng/anti-bot). Coba lagi nanti."
            ),
            "digest_text": (
                f"🧵 *THREADS WATCH @{target}*\n"
                "❓ Halaman publik tak terbaca saat ini (anti-bot). "
                "Dicoba lagi di jadwal berikutnya."
            ),
        }
    profile = _parse_profile(raw)
    new_posts = _save_profile_and_posts(target, profile)
    return {
        "status": "ok",
        "handle": target,
        "new_count": len(new_posts),
        "profile": {
            "name": profile.get("name"),
            "followers": profile.get("followers"),
            "threads_n": profile.get("threads_n"),
        },
        "new_posts": new_posts,
        "digest_text": _digest_text(target, profile, new_posts),
    }


@register_tool(category="system")
def threads_fetch_profile(handle: str = "") -> dict[str, Any]:
    """Ambil snapshot hidup profil publik Threads (baca-saja, tanpa DB).

    Mirip ``threads_watch_check`` tapi TIDAK menyimpan & TIDAK membanding
    dedupe — murni penglihatan profil hari ini.
    """
    target = _handle_norm(handle) or _default_handle()
    raw, _url = _fetch_profile_html(target)
    if not raw:
        return {"status": "error", "message": "halaman publik tak terbaca"}
    else:
        parsed = _parse_profile(raw)
        parsed["handle"] = target
        parsed["status"] = "ok"
        return parsed


@register_tool(category="system")
def threads_watch_last(handle: str = "", limit: int = 10) -> dict[str, Any]:
    """Daftar post yang pernah TEREKAM watcher dari DB lokal (baca DB saja)."""
    target = _handle_norm(handle) or _default_handle()
    rows = _list_known_posts(target, limit)
    return {"status": "ok", "handle": target, "count": len(rows), "posts": rows}


@register_tool(category="scheduler")
def schedule_threads_watch_task(
    handle: str = "", enabled: bool = True, interval_minutes: int = 360
) -> dict[str, Any]:
    """AKTIFKAN/MATIKAN jadwal pemantau akun Threads ke Telegram Fahmi.

    Tiap interval: cek profil publik @handle → kalau ada post baru, kirim
    digest. Laporan HANYA ke Telegram (bukan WhatsApp).

    Args:
        handle: username Threads (tanpa @; default xalf._1).
        enabled: True aktif/perbarui jadwal; False hapus.
        interval_minutes: minimal 60 (default 360 = tiap 6 jam).
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
        return schedule_threads_watch(
            user_id=int(user_id), chat_id=int(chat_id),
            handle=handle, enabled=enabled,
            interval_minutes=interval_minutes,
        )
    except Exception as exc:  # noqa: BLE001 — scheduler refleksif gagal-lembut
        logger.exception("schedule_threads_watch_task gagal")
        return {"status": "error", "message": str(exc)[:120]}


def schedule_threads_watch(
    user_id: int, chat_id: int, handle: str = "", enabled: bool = True,
    interval_minutes: int = 360,
) -> dict[str, Any]:
    """Inti scheduler (pola guardian) — user/chat id eksplisit, uji-hermetik."""
    target = _handle_norm(handle) or _default_handle()
    try:
        from alfa.core.db import tasks as cron_tasks

        if not int(user_id) or not int(chat_id):
            return {"status": "error", "message": "user/chat id tidak diketahui"}

        title = f"Threads Watch (@{target})"
        existing = [
            j
            for j in cron_tasks.list_cron_jobs_sync(int(user_id))
            if str(j.get("title") or "").startswith("Threads Watch (@")
        ]
        removed = sum(
            1
            for j in existing
            if cron_tasks.delete_cron_job_sync(int(user_id), int(j["id"]))
        )
        if not enabled:
            return {
                "status": "ok",
                "removed": removed,
                "message": f"Pemantauan Threads @{target} dimatikan.",
            }
        prompt = (
            f"Panggil tool `threads_watch_check(handle='{target}')`, lalu "
            "KIRIMKAN field 'digest_text' hasilnya ke chat Telegram ini "
            "PERSIS apa adanya (verbatim). Jika status error, kutip "
            "'digest_text'-nya juga. HUKUM: hanya Telegram, JANGAN kirim "
            "ke WhatsApp."
        )
        interval = max(60, int(interval_minutes))
        job_id = cron_tasks.add_cron_job_sync(
            user_id=int(user_id),
            chat_id=int(chat_id),
            title=title,
            prompt_instruction=prompt,
            interval_minutes=interval,
            kind="single",
        )
    except Exception as exc:  # noqa: BLE001 — scheduler gagal-lembut
        logger.exception("schedule_threads_watch gagal")
        return {"status": "error", "message": str(exc)[:120]}
    return {
        "status": "ok",
        "job_id": job_id,
        "interval_minutes": interval,
        "removed_old": removed,
        "message": (
            f"THREADS WATCH @{target} terjadwal (#{job_id}, tiap "
            f"{interval} menit). Post baru akan masuk laporan Telegram."
        ),
    }
