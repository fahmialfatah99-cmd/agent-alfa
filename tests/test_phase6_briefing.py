"""Phase 6 coverage: executive briefing harian + penjadwalannya.

Hermetic: SQLite diarahkan ke ``tmp_path`` (tabel arsip WA buatan), psutil dan
perekam laporan di-mock; tidak menyentuh DB produksi atau mengirim pesan apa pun.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from types import SimpleNamespace

import pytest

NOW = int(time.time())

#: (msg_id, chat_name, sender, body, offset_detik_lalu | None)
MESSAGES = [
    # A. Grup pengambilan material (ada kuantitas + koordinasi + noise)
    ("a1", "GRUP PENGAMBILAN MATERIAL RONGGO", "Budi", "tanam tiang 7m 3 batang", 3600),
    ("a2", "GRUP PENGAMBILAN MATERIAL RONGGO", "Budi", "tarik kabel 100 meter", 3500),
    ("a3", "GRUP PENGAMBILAN MATERIAL RONGGO", "Andi", "fdt 2 unit", 3400),
    ("a4", "GRUP PENGAMBILAN MATERIAL RONGGO", "Andi", "fat 1 box", 3300),
    ("a5", "GRUP PENGAMBILAN MATERIAL RONGGO", "Andi", "serah terima bon material", 3200),
    ("a6", "GRUP PENGAMBILAN MATERIAL RONGGO", "Dewi", "besok kita rapat koordinasi jam 8", 3100),
    ("a7", "GRUP PENGAMBILAN MATERIAL RONGGO", "Dewi", "siap mas", 3000),
    # B. Pengambilan tanpa material fisik (catatan saja)
    ("b1", "GRUP PENGAMBILAN MATERIAL PATI", "Rian", "kita ambil barang besok pagi", 2900),
    # C. Grup proyek (skor 3/2/1, kuantitas, noise)
    ("c1", "FTTH ODN RONGGO", "Tono", "recon selesai .kmz", 2800),
    ("c2", "FTTH ODN RONGGO", "Tono", "clamp pole 50 unit mas", 2700),
    ("c3", "FTTH ODN RONGGO", "Tono", "siap", 2600),
    ("c4", "FTTH ODN RONGGO", "Dewi", "kabel putus di tiang 3", 2500),
    ("c5", "FTTH ODN RONGGO", "Dewi", "tarik kabel 100 meter", 2400),
    ("c6", "FTTH ODN RONGGO", "Rian", "T72: 10 btg", 2300),
    ("c7", "FTTH ODN RONGGO", "Rian", "fat 2 box", 2200),
    ("c8", "FTTH ODN RONGGO", "Rian", "fdt 1 unit", 2100),
    # D. Grup proyek tanpa update valid (hanya noise)
    ("d1", "FTTH BKL", "Tono", "siap", 2000),
    ("d2", "FTTH BKL", "Tono", "[sticker]", 1950),
    ("d3", "FTTH BKL", "Dewi", "/9j/AAAA" + "x" * 50, 1940),
    # E/F. Grup yang diabaikan (TO & personal/non-proyek)
    ("e1", "TO Proyek Alpha", "Teknisi", "tarik kabel 999 meter", 1900),
    ("f1", "Test Verification", "Sistem", "halo", 1800),
]

#: Baris khusus: cluster mandek, grup TO yang dikecualikan, dan ts NULL.
OLD_ROWS = [
    ("g1", "IMT PATI", "Teknisi", "laporan lama", 60 * 3600),
    ("h1", "TO BKL Cluster", "Teknisi", "laporan lama", 70 * 3600),
]


@pytest.fixture
def briefing():
    from alfa.tools.telecom_tools import briefing as mod

    return mod


def _create_db(tmp_path):
    db = tmp_path / "briefing.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE wa_incoming_archive ("
        "msg_id TEXT PRIMARY KEY, chat_id TEXT, chat_name TEXT, "
        "sender_name TEXT, body TEXT, msg_ts INTEGER)"
    )
    conn.execute(
        "CREATE TABLE wa_reported_messages ("
        "msg_id TEXT PRIMARY KEY, reported_at TEXT, shift TEXT)"
    )
    for mid, chat, sender, body, offset in MESSAGES:
        conn.execute(
            "INSERT INTO wa_incoming_archive "
            "(msg_id, chat_id, chat_name, sender_name, body, msg_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mid, "chat-1", chat, sender, body, NOW - offset),
        )
    for mid, chat, sender, body, offset in OLD_ROWS:
        conn.execute(
            "INSERT INTO wa_incoming_archive "
            "(msg_id, chat_id, chat_name, sender_name, body, msg_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mid, "chat-1", chat, sender, body, NOW - offset),
        )
    # Cluster dengan ts NULL -> dilewati cabang stalled.
    conn.execute(
        "INSERT INTO wa_incoming_archive "
        "(msg_id, chat_id, chat_name, sender_name, body, msg_ts) "
        "VALUES (?, ?, ?, ?, ?, NULL)",
        ("i1", "chat-1", "FTTH BKL GANTENG", "Teknisi", "tanpa waktu"),
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def db_env(monkeypatch, tmp_path):
    from alfa.core.db import connection as conn_mod

    db = _create_db(tmp_path)

    def factory():
        return contextlib.closing(sqlite3.connect(db))

    monkeypatch.setattr(conn_mod, "get_sync_db", factory)

    # Patch fungsi psutil nyata (modul tetap utuh -> psutil.Error dsb. tetap ada).
    import psutil as real_psutil

    monkeypatch.setattr(
        real_psutil, "cpu_percent", lambda interval=None: 12.5
    )
    monkeypatch.setattr(
        real_psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=42.0, available=2 * 1024**3),
    )

    reported: list[dict] = []
    from alfa.core.db import wa_tracking

    monkeypatch.setattr(
        wa_tracking,
        "record_wa_messages_reported_sync",
        lambda msgs, shift=None: reported.append({"msgs": msgs, "shift": shift}),
    )
    return SimpleNamespace(db=db, reported=reported, factory=factory)


def test_briefing_full_report(db_env, briefing):
    out = briefing.generate_daily_executive_briefing(shift="now")
    assert out["status"] == "success"
    card = out["briefing_card"]
    stats = out["stats"]

    # Judul & shift realtime.
    assert "DAILY EXECUTIVE BRIEFING ALFA OS" in card
    assert "REALTIME" in card

    # Grup pengambilan material.
    assert "RECORD GRUP PENGAMBILAN MATERIAL" in card
    assert "GRUP PENGAMBILAN MATERIAL RONGGO" in card
    assert "(7 aktivitas baru)" in card
    assert "Tiang: `3 btg`" in card
    assert "FDT: `2 unit`" in card
    assert "FAT: `1 box`" in card
    assert "Kabel: `100.0 m`" in card
    # 3 bukti materil terbaru (urutan msg_ts DESC) tampil sebagai kutipan.
    assert "serah terima bon material" in card
    assert "fat 1 box" in card
    assert "fdt 2 unit" in card
    assert "Koordinasi/Rencana" in card
    # Grup pengambilan tanpa material fisik.
    assert "GRUP PENGAMBILAN MATERIAL PATI" in card
    assert "Belum ada input fisik barang keluar gudang" in card

    # Point penting proyek (skor 3 > 2 > 1) & grup tanpa update.
    assert "POINT PENTING TIAP GRUP PROYEK (KECUALI TO)" in card
    assert "kabel putus di tiang 3" in card
    assert "tarik kabel 100 meter" in card
    assert "⚠️" in card
    assert "Dokumentasi foto/media pekerjaan lapangan" in card
    # Grup TO & personal tidak muncul.
    assert "TO Proyek Alpha" not in card
    assert "Test Verification" not in card
    assert "999 meter" not in card

    # Cluster mandek >48 jam (TO dikecualikan, NULL dilewati).
    assert "CLUSTER PROYEK MANDEK" in card
    assert "IMT PATI" in card
    assert "60.0 jam" in card
    assert "TO BKL Cluster" not in card

    # Kendala & kesehatan sistem.
    assert "CATATAN KENDALA & FOLLOW-UP LAPANGAN (1 Poin)" in card
    assert "KESEHATAN SISTEM ALFA" in card
    assert "CPU: `12.5%`" in card
    assert "RAM: `42.0%`" in card
    assert "Tersedia: 2.0 GB" in card

    # Konsolidasi nonaktif (default env).
    assert "dinonaktifkan sementara" in card
    assert "0 meter (nonaktif)" in card

    # Statistik.
    assert stats["active_clusters"] == 4
    assert stats["stalled_clusters"] == 1
    assert stats["issues_count"] == 1
    assert stats["new_unreported_messages"] == 19
    by = stats["by_cluster"]
    assert by["GRUP PENGAMBILAN MATERIAL RONGGO"] == {
        "cable_meters": 100.0,
        "poles_pcs": 3,
        "fdt_boxes": 2,
        "fat_boxes": 1,
        "messages": 7,
    }
    assert by["GRUP PENGAMBILAN MATERIAL PATI"]["messages"] == 1
    assert by["GRUP PENGAMBILAN MATERIAL PATI"]["cable_meters"] == 0.0
    assert by["FTTH ODN RONGGO"] == {
        "cable_meters": 100.0,
        "poles_pcs": 10,
        "fdt_boxes": 1,
        "fat_boxes": 2,
        "messages": 8,
    }
    assert by["FTTH BKL"]["messages"] == 3
    assert by["FTTH BKL"]["cable_meters"] == 0.0

    # Total hanya dihitung dari grup proyek.
    assert stats["total_cable_meters"] == 100.0
    assert stats["total_poles_pcs"] == 10
    assert stats["total_fdt_boxes"] == 1
    assert stats["total_fat_boxes"] == 2

    # Perekam laporan dipanggil dengan semua pesan terpilih.
    assert len(db_env.reported) == 1
    assert db_env.reported[0]["shift"] == "now"
    reported_ids = [m["msg_id"] for m in db_env.reported[0]["msgs"]]
    expected_ids = {m[0] for m in MESSAGES[:19]}  # e1 & f1 dikeluarkan
    assert set(reported_ids) == expected_ids
    assert len(reported_ids) == 19
    assert db_env.reported[0]["msgs"][0]["msg_id"] == "d3"
    assert db_env.reported[0]["msgs"][0]["chat_name"] == "FTTH BKL"
    assert db_env.reported[0]["msgs"][0]["msg_ts"] == NOW - 1940


def test_briefing_consolidation_enabled(db_env, briefing, monkeypatch):
    monkeypatch.setattr(briefing, "FIELD_CONSOLIDATION_ENABLED", True)
    out = briefing.generate_daily_executive_briefing()
    card = out["briefing_card"]
    assert "dinonaktifkan sementara" not in card
    assert "Total Kabel Terpasang*: `100.0 meter`" in card
    assert "Total Tiang Tertanam*: `10 batang`" in card
    assert "Total FDT Terpasang*: `1 unit`" in card
    assert "Total FAT/ODP Terpasang*: `2 box`" in card
    assert "(4 Grup Terpantau)" in card


@pytest.mark.parametrize(
    ("shift", "expected"),
    [
        ("morning", "PAGI (TARGET & PERSIAPAN)"),
        ("evening", "SORE (PROGRESS CLOSING)"),
        # Perilaku asli: tanpa .strip(), spasi di ujung -> jatuh ke REALTIME.
        ("  Morning ", "REALTIME"),
        ("sembarang", "REALTIME"),
    ],
)
def test_briefing_shift_titles(
    tmp_path, briefing, monkeypatch, shift, expected
):
    # DB kosong: tidak ada grup sama sekali.
    db = tmp_path / "kosong.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE wa_incoming_archive ("
        "msg_id TEXT PRIMARY KEY, chat_id TEXT, chat_name TEXT, "
        "sender_name TEXT, body TEXT, msg_ts INTEGER)"
    )
    conn.execute(
        "CREATE TABLE wa_reported_messages (msg_id TEXT PRIMARY KEY, "
        "reported_at TEXT, shift TEXT)"
    )
    conn.commit()
    conn.close()

    from alfa.core.db import connection as conn_mod
    from alfa.core.db import wa_tracking

    calls: list[list] = []
    monkeypatch.setattr(
        conn_mod,
        "get_sync_db",
        lambda: contextlib.closing(sqlite3.connect(db)),
    )
    monkeypatch.setattr(
        wa_tracking,
        "record_wa_messages_reported_sync",
        lambda msgs, shift=None: calls.append(msgs),
    )
    import psutil as real_psutil

    monkeypatch.setattr(
        real_psutil, "cpu_percent", lambda interval=None: 0.0
    )
    monkeypatch.setattr(
        real_psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=10.0, available=1024**3),
    )

    out = briefing.generate_daily_executive_briefing(shift=shift)

    assert out["status"] == "success"
    assert expected in out["briefing_card"]
    # Tidak ada laporan baru.
    assert "Semua laporan lapangan sebelumnya" in out["briefing_card"]
    assert "Tidak ada pengambilan material baru" in out["briefing_card"]
    assert "Tidak ada update aktivitas proyek baru" in out["briefing_card"]
    assert out["stats"]["active_clusters"] == 0
    assert out["stats"]["new_unreported_messages"] == 0
    # Tidak ada pesan -> perekam tidak dipanggil.
    assert calls == []


def test_briefing_only_unreported_filter(db_env, briefing):
    # Tandai c5 sebagai sudah dilaporkan.
    conn = sqlite3.connect(db_env.db)
    conn.execute(
        "INSERT INTO wa_reported_messages (msg_id, reported_at, shift) "
        "VALUES ('c5', 'x', 'evening')"
    )
    conn.commit()
    conn.close()

    out = briefing.generate_daily_executive_briefing(only_unreported=True)
    # c5 (100 m) hilang dari analisis.
    assert out["stats"]["total_cable_meters"] == 0.0
    assert out["stats"]["by_cluster"]["FTTH ODN RONGGO"]["cable_meters"] == 0.0
    assert out["stats"]["new_unreported_messages"] == 18

    out2 = briefing.generate_daily_executive_briefing(only_unreported=False)
    assert out2["stats"]["total_cable_meters"] == 100.0
    assert out2["stats"]["new_unreported_messages"] == 19


def test_briefing_mark_as_reported_false(db_env, briefing):
    out = briefing.generate_daily_executive_briefing(mark_as_reported=False)
    assert out["status"] == "success"
    assert db_env.reported == []


def test_briefing_db_error(db_env, briefing, monkeypatch):
    def boom():
        raise RuntimeError("database terkunci")  # noqa: TRY003

    from alfa.core.db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "get_sync_db", boom)
    out = briefing.generate_daily_executive_briefing()
    assert out["status"] == "error"
    assert "Executive briefing error" in out["message"]
    assert "database terkunci" in out["message"]


# ---------------------------------------------------------------------------
# schedule_daily_briefing_task
# ---------------------------------------------------------------------------


@pytest.fixture
def sched_env(monkeypatch):
    from alfa.core import database, runtime_ctx

    executed: list[str] = []
    commits: list[int] = []
    cron_calls: list[dict] = []

    conn = SimpleNamespace(
        execute=lambda sql: executed.append(sql),
        commit=lambda: commits.append(1),
        close=lambda: None,
    )

    monkeypatch.setattr(runtime_ctx, "get_current_user_id", lambda: "user-9")
    monkeypatch.setattr(runtime_ctx, "get_current_chat_id", lambda: 77)
    monkeypatch.setattr(
        database, "get_sync_db", lambda: contextlib.closing(conn), raising=False
    )

    def fake_cron(**kwargs):
        cron_calls.append(kwargs)
        return 42

    monkeypatch.setattr(
        database, "add_cron_job_sync", fake_cron, raising=False
    )
    return SimpleNamespace(executed=executed, commits=commits, cron_calls=cron_calls)


def test_schedule_disable(sched_env, briefing):
    out = briefing.schedule_daily_briefing_task(enabled=False)
    assert out["status"] == "success"
    assert "dinonaktifkan" in out["message"]
    assert any("is_active = 0" in sql for sql in sched_env.executed)
    assert sched_env.commits
    assert sched_env.cron_calls == []


def test_schedule_enable(sched_env, briefing):
    out = briefing.schedule_daily_briefing_task(
        enabled=True,
        morning_hour=6,
        morning_minute=15,
        evening_hour=19,
        evening_minute=45,
    )
    assert out["status"] == "success"
    assert out["job_id"] == 42
    assert "#42" in out["message"]
    assert len(sched_env.cron_calls) == 1
    call = sched_env.cron_calls[0]
    assert call["user_id"] == "user-9"
    assert call["chat_id"] == 77
    assert call["title"] == "Daily Project Executive Briefing (Telegram Only)"
    assert call["interval_minutes"] == 720
    assert call["kind"] == "single"
    assert "generate_daily_executive_briefing" in call["prompt_instruction"]
    assert sched_env.executed == []


def test_schedule_error(sched_env, briefing, monkeypatch):
    from alfa.core import runtime_ctx

    def boom():
        raise RuntimeError("konteks runtime hilang")  # noqa: TRY003

    monkeypatch.setattr(runtime_ctx, "get_current_user_id", boom)
    out = briefing.schedule_daily_briefing_task(enabled=True)
    assert out["status"] == "error"
    assert "Schedule daily briefing error" in out["message"]
    assert "konteks runtime hilang" in out["message"]
