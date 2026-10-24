"""Unit hermetik: Threads Watch — parser SSR, dedupe DB, jadwal, registrasi.

Tanpa network nyata: fetch dimainkan; DB lewat conftest (teralihkan dari
DB produksi). Kasus profil kosong & profil berpost dua-duanya diuji.
"""

from __future__ import annotations

from alfa.core.db import tasks as cron_tasks
from alfa.tools.system import threads_watch

_FAKE_EMPTY = (
    '<html><head>'
    '<meta property="og:site_name" content="Threads"/>'
    '<meta property="og:type" content="profile"/>'
    '<meta property="og:title" content="fahmi alfatah (&#064;xalf._1) '
    '&#x2022; Threads, Say more"/>'
    '<meta property="og:description" content="39 Followers &#x2022; '
    '0 Threads &#x2022; Fahmi al fatah"/>'
    '<meta property="og:url" content="https://www.threads.com/&#064;xalf._1"/>'
    '</head></html>'
)

_FAKE_WITH_POSTS = (
    "<html><head>"
    '<meta property="og:type" content="profile"/>'
    '<meta property="og:title" content="fahmi alfatah ('
    "&#x40;xalf._1) &#x2022; Threads, Say more\"/>"
    '<meta property="og:description" content="1,234 Followers &#x2022; '
    '2 Threads &#x2022; Fahmi"/>'
    '<meta property="og:url" content="https://www.threads.com/&#064;xalf._1"/>'
    "<meta property=\"og:type\" content=\"article\"/>"
    '<meta property="og:title" content="post pertama"/>'
    '<meta property="og:url" content="https://www.threads.com/&#064;xalf._1/post/C123abc"/>'
    '<meta property="og:description" content="Halo dunia, ini post kabisat &quot;yang pertama&quot;"/>'
    "<meta property=\"og:type\" content=\"article\"/>"
    '<meta property="og:title" content="post kedua"/>'
    '<meta property="og:url" content="https://www.threads.com/&#064;xalf._1/post/C999zzz"/>'
    '<meta property="og:description" content="Update cluster 1: 12% beres"/>'
    "</head></html>"
)


def test_parse_empty_profile():
    parsed = threads_watch._parse_profile(_FAKE_EMPTY)
    assert parsed["name"] == "fahmi alfatah"
    assert parsed["followers"] == 39
    assert parsed["threads_n"] == 0
    assert parsed["posts"] == []


def test_parse_with_two_posts():
    parsed = threads_watch._parse_profile(_FAKE_WITH_POSTS)
    assert parsed["followers"] == 1234
    assert parsed["threads_n"] == 2
    ids = [p["post_id"] for p in parsed["posts"]]
    assert ids == ["C123abc", "C999zzz"]
    assert "post kabisat" in parsed["posts"][0]["text"]
    assert "cluster 1" in parsed["posts"][1]["text"]
    assert all(p["url"].startswith("https://www.threads.com/@xalf._1")
               for p in parsed["posts"])


def test_watch_check_dedup_second_time(monkeypatch):
    monkeypatch.setattr(
        threads_watch, "_fetch_profile_html",
        lambda h: (_FAKE_WITH_POSTS, "https://www.threads.net/@h"),
    )
    first = threads_watch.threads_watch_check("@xalf._1")
    assert first["status"] == "ok"
    assert first["new_count"] == 2
    assert "2 post baru" in first["digest_text"]
    second = threads_watch.threads_watch_check("xalf._1")
    assert second["new_count"] == 0
    assert "Tidak ada post baru" in second["digest_text"]


def test_watch_check_fail_soft_when_unreadable(monkeypatch):
    monkeypatch.setattr(threads_watch, "_fetch_profile_html", lambda h: ("", ""))
    res = threads_watch.threads_watch_check("xalf._1")
    assert res["status"] == "error"
    assert "digest_text" in res


def test_handle_norm():
    assert threads_watch._handle_norm("@xalf._1?foo") == "xalf._1"
    assert threads_watch._handle_norm(" XALf._1/extra ") == "XALf._1"


def test_schedule_threads_watch_explicit_ids(monkeypatch):
    """Pola guardian: uji fungsi inti dengan user/chat id eksplisit."""
    calls: list = []

    monkeypatch.setattr(cron_tasks, "list_cron_jobs_sync",
                        lambda _uid: [{"id": 41, "title": "Threads Watch (@xalf._1)"}])
    deleted: list = []
    monkeypatch.setattr(cron_tasks, "delete_cron_job_sync",
                        lambda uid, jid: deleted.append(jid) or True)
    monkeypatch.setattr(cron_tasks, "add_cron_job_sync",
                        lambda **kw: calls.append(kw) or 9001)

    res = threads_watch.schedule_threads_watch(
        9, 9, handle="@xalf._1", enabled=True, interval_minutes=360
    )
    assert res["status"] == "ok" and res["job_id"] == 9001
    assert deleted == [41]
    assert calls[0]["interval_minutes"] == 360
    assert calls[0]["user_id"] == 9 and calls[0]["chat_id"] == 9
    assert "threads_watch_check" in calls[0]["prompt_instruction"]
    assert "xalf._1" in calls[0]["prompt_instruction"]

    off = threads_watch.schedule_threads_watch(
        9, 9, handle="xalf._1", enabled=False
    )
    assert off["status"] == "ok" and off["removed"] == 1


def test_schedule_threads_watch_task_requires_real_ids(monkeypatch):
    """Wrapper tool tanpa konteks runtime & tanpa ALLOWED_USER_IDS → error lembut."""
    from alfa.core import runtime_ctx as rt

    monkeypatch.setattr(rt, "get_current_user_id", lambda: None, raising=True)
    monkeypatch.setattr(rt, "get_current_chat_id", lambda: None, raising=True)
    monkeypatch.setattr(
        threads_watch, "_primary_chat_id", lambda: 0, raising=True
    )
    res = threads_watch.schedule_threads_watch_task("xalf._1")
    assert res["status"] == "error"
    assert "chat id" in res["message"]


def test_tools_registered():
    import alfa.tools

    registry = getattr(alfa.tools, "TOOL_REGISTRY", {})
    for name in (
        "threads_watch_check",
        "threads_fetch_profile",
        "threads_watch_last",
        "schedule_threads_watch_task",
    ):
        assert name in registry, f"{name} belum terdaftar"
