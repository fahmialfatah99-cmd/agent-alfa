"""Phase 5 coverage: proactive loops (reminder, cron, digest, guardian, ambient, watchdog).

Hermetic: setiap loop dihentikan lewat sentinel ``asyncio.sleep``; tidak ada
systemctl/Telegram/WA sungguhan yang dipanggil (subprocess & socket di-mock).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from alfa.bot import proactive as pa


class _StopLoopError(Exception):
    """Sentinel untuk keluar dari ``while True`` setelah satu/beberapa iterasi."""


def _stop_after(monkeypatch, module, calls: int = 1, on_sleep=None):
    """Patch ``asyncio.sleep`` agar melempar sentinel setelah ``calls`` panggilan."""
    state = {"calls": 0, "delays": []}

    async def fake_sleep(delay):
        state["calls"] += 1
        state["delays"].append(delay)
        if on_sleep:
            on_sleep(state["calls"])
        if state["calls"] >= calls:
            raise _StopLoopError

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    return state


def _app():
    async def _noop(*args, **kwargs):
        return None

    return SimpleNamespace(
        bot=SimpleNamespace(
            send_message=_noop,
            send_photo=_noop,
            send_document=_noop,
        )
    )


def _run(coro):
    with pytest.raises(_StopLoopError):
        asyncio.run(coro)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ALLOWED_USER_IDS", "123")
    monkeypatch.setattr(pa, "ALLOWED_USER_IDS", ["123"])
    return home


# ── reminder loop ────────────────────────────────────────────────────────────


def test_reminder_loop_sends_and_marks(monkeypatch):
    sent = []

    async def due():
        return [
            {
                "id": 1,
                "chat_id": 123,
                "message": "minum air",
                "reminder_time": "2026-11-19 09:00:00",
            }
        ]

    async def send(app, chat_id, text):
        sent.append((chat_id, text))

    async def mark(rem_id):
        sent.append(("mark", rem_id))

    monkeypatch.setattr(pa.database, "get_due_reminders", due)
    monkeypatch.setattr(pa, "safe_send_message", send)
    monkeypatch.setattr(pa.database, "mark_reminder_executed", mark)
    _stop_after(monkeypatch, pa)

    _run(pa.proactive_reminder_loop(_app()))
    assert sent[0][0] == 123
    assert "PENGINGAT OTOMATIS" in sent[0][1]
    assert ("mark", 1) in sent


def test_reminder_loop_drops_overdue_after_send_failure(monkeypatch):
    marked = []
    old = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

    async def due():
        return [
            {"id": 1, "chat_id": 1, "message": "a", "reminder_time": old},
            {"id": 2, "chat_id": 1, "message": "b", "reminder_time": "rusak"},
        ]

    async def send(app, chat_id, text):
        msg = "telegram down"
        raise pa.TelegramError(msg)

    async def mark(rem_id):
        marked.append(rem_id)

    monkeypatch.setattr(pa.database, "get_due_reminders", due)
    monkeypatch.setattr(pa, "safe_send_message", send)
    monkeypatch.setattr(pa.database, "mark_reminder_executed", mark)
    _stop_after(monkeypatch, pa)

    _run(pa.proactive_reminder_loop(_app()))
    assert marked == [1, 2]


def test_reminder_loop_survives_database_error(monkeypatch):
    async def boom():
        msg = "db mati"
        raise OSError(msg)

    monkeypatch.setattr(pa.database, "get_due_reminders", boom)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_reminder_loop(_app()))


# ── scheduled swarm job ──────────────────────────────────────────────────────


def _patch_swarm(monkeypatch, *, result, run_error=None, reporter_errors=True):
    from alfa.bot import mode_commands, progress

    async def fake_run(prompt):
        if run_error:
            raise run_error
        return result

    monkeypatch.setattr(mode_commands, "run_swarm_task", fake_run)
    monkeypatch.setattr(
        mode_commands,
        "format_swarm_result",
        lambda res: ("LANGKAH", "HASIL AKHIR", res.get("files", [])),
    )

    class FakeReporter:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            if reporter_errors:
                msg = "reporter start gagal"
                raise ValueError(msg)

        async def stop(self, text=""):
            if reporter_errors:
                msg = "reporter stop gagal"
                raise ValueError(msg)

    monkeypatch.setattr(progress, "SwarmProgressReporter", FakeReporter)


def test_scheduled_swarm_job_sends_result_and_files(monkeypatch, tmp_path):
    deliverable = tmp_path / "hasil.txt"
    deliverable.write_text("isi", encoding="utf-8")
    _patch_swarm(monkeypatch, result={"files": [str(deliverable)]})
    sent = []
    docs = []

    async def send(app, chat_id, text):
        sent.append((chat_id, text))

    async def send_doc(chat_id, document, caption=""):
        docs.append((chat_id, caption))

    monkeypatch.setattr(pa, "safe_send_message", send)
    app = _app()
    app.bot.send_document = send_doc

    asyncio.run(pa._run_scheduled_swarm_job(app, 9, 123, 123, "Misi", "prompt"))
    assert "MISI SWARM TERJADWAL #9" in sent[0][1]
    assert docs[0][0] == 123
    assert "hasil.txt" in docs[0][1]


def test_scheduled_swarm_job_reports_failure(monkeypatch):
    _patch_swarm(monkeypatch, result={}, run_error=RuntimeError("swarm mati"))
    sent = []

    async def send(app, chat_id, text):
        sent.append(text)

    monkeypatch.setattr(pa, "safe_send_message", send)
    asyncio.run(pa._run_scheduled_swarm_job(_app(), 3, 1, 123, "Gagal", "prompt"))
    assert "gagal" in sent[0].lower()


# ── cron watchdog ────────────────────────────────────────────────────────────


def _cron_job(**overrides):
    job = {
        "id": 5,
        "user_id": 0,
        "chat_id": 0,
        "title": "Laporan",
        "prompt_instruction": "buat file laporan",
        "interval_minutes": 30,
        "kind": "single",
    }
    job.update(overrides)
    return job


def _patch_cron(monkeypatch, jobs, *, run_result="hasil turn", run_error=None):
    async def due():
        return jobs

    async def update(job_id, interval):
        return None

    async def run_turn(**kwargs):
        if run_error:
            raise run_error
        return run_result

    monkeypatch.setattr(pa.database, "get_due_cron_jobs", due)
    monkeypatch.setattr(pa.database, "update_cron_job_after_run", update)
    monkeypatch.setattr(pa, "run_agent_turn", run_turn)


def test_cron_watchdog_skips_job_without_chat(monkeypatch):
    monkeypatch.setattr(pa, "ALLOWED_USER_IDS", [])
    _patch_cron(monkeypatch, [_cron_job()])
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_cron_watchdog_loop(_app()))


def test_cron_watchdog_runs_single_job_and_attaches_fresh_files(
    monkeypatch, tmp_path
):
    _patch_cron(monkeypatch, [_cron_job()])
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    fresh_png = sandbox / "grafik.png"
    fresh_png.write_bytes(b"png")
    fresh_pdf = sandbox / "laporan.pdf"
    fresh_pdf.write_bytes(b"pdf")
    future = datetime.now().timestamp() + 3600
    os.utime(fresh_png, (future, future))
    os.utime(fresh_pdf, (future, future))
    stale = sandbox / "lama.pdf"
    stale.write_bytes(b"pdf")
    old = datetime.now().timestamp() - 3600
    os.utime(stale, (old, old))
    (sandbox / "kosong.pdf").write_bytes(b"")
    (sandbox / "kode.py").write_text("print(1)", encoding="utf-8")
    (sandbox / "internal.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(pa, "SANDBOX_DIR", str(sandbox))
    monkeypatch.setattr(pa.tools, "is_internal_sandbox_artifact", lambda n: n == "internal.json")
    monkeypatch.setattr(pa.tools, "is_source_code_file", lambda n: n.endswith(".py"))

    sent, photos, docs = [], [], []

    async def send(app, chat_id, text):
        sent.append((chat_id, text))

    async def photo(chat_id, photo, caption=""):
        photos.append(caption)

    async def document(chat_id, document, caption=""):
        docs.append(caption)

    monkeypatch.setattr(pa, "safe_send_message", send)
    app = _app()
    app.bot.send_photo = photo
    app.bot.send_document = document

    _stop_after(monkeypatch, pa)
    _run(pa.proactive_cron_watchdog_loop(app))

    assert sent[0][0] == 123
    assert "WATCHDOG / CRON TASK #5" in sent[0][1]
    assert len(photos) == 1 and "grafik.png" in photos[0]
    assert len(docs) == 1 and "laporan.pdf" in docs[0]
    assert not fresh_png.exists()
    assert not fresh_pdf.exists()


def test_cron_watchdog_dispatches_swarm_job(monkeypatch):
    _patch_cron(monkeypatch, [_cron_job(kind="swarm")])
    called = []

    async def fake_swarm(app, job_id, user_id, chat_id, title, prompt):
        called.append((job_id, chat_id, title))

    monkeypatch.setattr(pa, "_run_scheduled_swarm_job", fake_swarm)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_cron_watchdog_loop(_app()))
    assert called == [(5, 123, "Laporan")]


def test_cron_watchdog_survives_turn_error(monkeypatch):
    _patch_cron(monkeypatch, [_cron_job()], run_error=RuntimeError("llm mati"))
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_cron_watchdog_loop(_app()))


# ── WA digest ────────────────────────────────────────────────────────────────


def _patch_digest(monkeypatch, *, enabled=True, send_ok=True, setting_error=False):
    from alfa.bot import wa_digest

    now_hhmm = datetime.now().strftime("%H:%M")
    stored = {}

    def setting(key, default=""):
        if setting_error:
            msg = "setting rusak"
            raise ValueError(msg)
        return stored.get(key, default)

    async def send(app, chat_id):
        return send_ok

    monkeypatch.setattr(wa_digest, "digest_enabled", lambda: enabled)
    monkeypatch.setattr(wa_digest, "digest_hours", lambda: [now_hhmm])
    monkeypatch.setattr(wa_digest, "_setting", setting)
    monkeypatch.setattr(wa_digest, "_set_setting", lambda k, v: stored.update({k: v}))
    monkeypatch.setattr(wa_digest, "send_digest", send)
    return stored


def test_wa_digest_sends_once_per_day(monkeypatch):
    stored = _patch_digest(monkeypatch)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_wa_digest_loop(_app()))
    assert stored["wa_digest_last_date"] == datetime.now().strftime("%Y-%m-%d")


def test_wa_digest_skips_when_disabled(monkeypatch):
    _patch_digest(monkeypatch, enabled=False)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_wa_digest_loop(_app()))


def test_wa_digest_does_not_mark_when_send_fails(monkeypatch):
    stored = _patch_digest(monkeypatch, send_ok=False)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_wa_digest_loop(_app()))
    assert "wa_digest_last_date" not in stored


def test_wa_digest_survives_setting_error(monkeypatch):
    _patch_digest(monkeypatch, setting_error=True)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_wa_digest_loop(_app()))


# ── sites watch ──────────────────────────────────────────────────────────────


def test_sites_watch_notifies_and_cleans_pending(monkeypatch, _home):
    from alfa.tools.system import sites

    alfa_dir = _home / ".alfa"
    alfa_dir.mkdir()
    pending = alfa_dir / "sites_pending_notify.json"
    pending.write_text(json.dumps(["toko", "desa"]), encoding="utf-8")
    monkeypatch.setattr(
        sites,
        "refresh_registry",
        lambda: {
            "toko": {"title": "Toko Online"},
            "desa": {"title": "Website Desa"},
        },
    )
    monkeypatch.setattr(pa, "ALLOWED_USER_IDS", ["1", "2"])
    sent = []

    async def send(app, chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))

    monkeypatch.setattr(pa, "safe_send_message", send)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_sites_watch_loop(_app()))

    assert [s[0] for s in sent] == [1, 2]
    assert "Toko Online" in sent[0][1]
    assert sent[0][2] is not None
    assert not pending.exists()


def test_sites_watch_ignores_corrupt_or_empty_pending(monkeypatch, _home):
    alfa_dir = _home / ".alfa"
    alfa_dir.mkdir()
    pending = alfa_dir / "sites_pending_notify.json"
    pending.write_text("[rusak", encoding="utf-8")
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_sites_watch_loop(_app()))
    assert pending.exists()


def test_sites_watch_without_pending_file(monkeypatch):
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_sites_watch_loop(_app()))


# ── focus sessions ───────────────────────────────────────────────────────────


def test_focus_loop_marks_done_even_when_send_fails(monkeypatch):
    completed = []

    async def due():
        return [
            {"id": 1, "chat_id": 123, "title": "Belajar", "duration_minutes": 25, "notes": ""},
            {"id": 2, "chat_id": 123, "title": "Kerja", "duration_minutes": 50, "notes": "fokus"},
        ]

    async def send(app, chat_id, text):
        if "Kerja" in text:
            msg = "telegram error"
            raise pa.TelegramError(msg)

    async def mark(session_id):
        completed.append(session_id)

    monkeypatch.setattr(pa.database, "get_due_focus_sessions", due)
    monkeypatch.setattr(pa, "safe_send_message", send)
    monkeypatch.setattr(pa.database, "mark_focus_session_completed", mark)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_focus_session_loop(_app()))
    assert completed == [1, 2]


# ── system guardian ──────────────────────────────────────────────────────────


def _guardian_env(monkeypatch, _home, config):
    alfa_dir = _home / ".alfa"
    alfa_dir.mkdir(exist_ok=True)
    (alfa_dir / "guardian_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    return alfa_dir


def _low_usage(monkeypatch):
    monkeypatch.setattr(pa.psutil, "cpu_percent", lambda interval=1: 5.0)
    monkeypatch.setattr(
        pa.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=20.0, used=2 * 1024**3, total=8 * 1024**3),
    )
    monkeypatch.setattr(
        pa.psutil, "disk_usage", lambda path: SimpleNamespace(percent=40.0, free=100 * 1024**3)
    )
    monkeypatch.setattr(pa.psutil, "sensors_battery", lambda: None)


def test_guardian_creates_default_config_and_stays_quiet(monkeypatch, _home):
    _low_usage(monkeypatch)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_system_guardian_loop(_app()))
    config = json.loads((_home / ".alfa" / "guardian_config.json").read_text())
    assert config["enabled"] is True
    assert config["cpu_threshold"] == 90


def test_guardian_sends_alerts_and_respects_cooldown(monkeypatch, _home):
    alfa_dir = _guardian_env(
        monkeypatch,
        _home,
        {"enabled": True, "cpu_threshold": 1, "ram_threshold": 1,
         "disk_threshold": 1, "battery_critical": 50, "cooldown_minutes": 120},
    )
    monkeypatch.setattr(pa.psutil, "cpu_percent", lambda interval=1: 99.0)
    monkeypatch.setattr(
        pa.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=99.0, used=7 * 1024**3, total=8 * 1024**3),
    )
    monkeypatch.setattr(
        pa.psutil, "disk_usage", lambda path: SimpleNamespace(percent=99.0, free=1)
    )
    monkeypatch.setattr(
        pa.psutil,
        "sensors_battery",
        lambda: SimpleNamespace(percent=5, power_plugged=False),
    )
    sent = []

    async def send(app, uid, text):
        sent.append((uid, text))

    monkeypatch.setattr(pa, "safe_send_message", send)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_system_guardian_loop(_app()))

    assert len(sent) == 1 and sent[0][0] == "123"
    assert "SYSTEM GUARDIAN ALERT" in sent[0][1]
    assert "Baterai KRITIS" in sent[0][1]
    state = json.loads((alfa_dir / "guardian_state.json").read_text())
    assert "guardian:baterai+cpu+disk+ram" in state

    # Iterasi kedua: alert masih dalam cooldown -> tidak dikirim ulang.
    sent.clear()
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_system_guardian_loop(_app()))
    assert sent == []


def test_guardian_auto_kill_ram_hogs(monkeypatch, _home):
    alfa_dir = _guardian_env(
        monkeypatch,
        _home,
        {"enabled": True, "cpu_threshold": 90, "ram_threshold": 1,
         "disk_threshold": 90, "battery_critical": 10,
         "auto_kill_ram_hogs": True, "cooldown_minutes": 0},
    )
    monkeypatch.setattr(pa.psutil, "cpu_percent", lambda interval=1: 1.0)
    monkeypatch.setattr(
        pa.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=95.0, used=7 * 1024**3, total=8 * 1024**3),
    )
    monkeypatch.setattr(
        pa.psutil, "disk_usage", lambda path: SimpleNamespace(percent=1.0, free=1)
    )
    monkeypatch.setattr(pa.psutil, "sensors_battery", lambda: None)
    killed = []

    def proc(name, rss_mb):
        return SimpleNamespace(
            info={"name": name, "memory_info": SimpleNamespace(rss=rss_mb * 1024 * 1024)},
            terminate=lambda: killed.append(name),
        )

    monkeypatch.setattr(
        pa.psutil,
        "process_iter",
        lambda attrs: iter([proc("python3", 900), proc("chrome", 800), proc("kecil", 100)]),
    )
    sent = []

    async def send(app, uid, text):
        sent.append(text)

    monkeypatch.setattr(pa, "safe_send_message", send)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_system_guardian_loop(_app()))
    assert killed == ["chrome"]
    assert "Auto-Kill" in sent[0]
    state = json.loads((alfa_dir / "guardian_state.json").read_text())
    assert "guardian:autokill+ram" in state


def test_guardian_disabled_and_invalid_config(monkeypatch, _home):
    _guardian_env(monkeypatch, _home, {"enabled": False})
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_system_guardian_loop(_app()))

    (_home / ".alfa" / "guardian_config.json").write_text("{rusak", encoding="utf-8")
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_system_guardian_loop(_app()))


# ── ambient proactive agent ──────────────────────────────────────────────────


class _FixedDateTime(datetime):
    fixed = datetime(2026, 11, 19, 9, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


@pytest.fixture
def ambient(monkeypatch, _home):
    _FixedDateTime.fixed = datetime(2026, 11, 19, 9, 0, 0)
    monkeypatch.setattr(pa, "datetime", _FixedDateTime)
    config_path = _home / ".alfa" / "proactive_config.json"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "min_hours_between_pings": 3,
                "quiet_hours_start": 23,
                "quiet_hours_end": 7,
                "max_pings_per_day": 4,
            }
        ),
        encoding="utf-8",
    )
    sent, saved, usage = [], [], []

    async def send(app, chat_id, text):
        sent.append((chat_id, text))

    async def save(uid, role, text):
        saved.append((uid, role, text))

    async def memories(uid):
        return [{"key_topic": "proyek", "content": "jalan"}]

    monkeypatch.setattr(pa, "safe_send_message", send)
    monkeypatch.setattr(pa.database, "save_chat_message", save)
    monkeypatch.setattr(pa.database, "get_all_memories", memories)
    monkeypatch.setattr(
        pa.token_usage,
        "from_gemini_response",
        lambda *a, **k: usage.append(k),
    )
    return SimpleNamespace(config_path=config_path, sent=sent, saved=saved, usage=usage)


class _FakeClient:
    def __init__(self, text="Halo, bagaimana progres proyek hari ini?"):
        self.text = text
        self.calls = []

        async def generate_content(model, contents):
            self.calls.append(model)
            return SimpleNamespace(text=self.text)

        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def test_ambient_sends_initiative_and_persists(monkeypatch, ambient):
    client = _FakeClient()
    monkeypatch.setattr(pa, "gemini_client", object())
    monkeypatch.setattr(pa, "resolve_main_gemini", lambda: (client, 7, "Gemini"))
    monkeypatch.setattr(pa, "_main_brain_gemini_model", lambda: "m")
    _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))

    assert ambient.sent[0][0] == "123"
    assert "INISIATIF MANDIRI" in ambient.sent[0][1]
    assert ambient.saved[0][1] == "model"
    assert ambient.usage[0]["context"] == "proactive"
    config = json.loads(ambient.config_path.read_text())
    assert config["pings_today"] == 1
    assert "last_ping_time" in config


def test_ambient_skips_no_action(monkeypatch, ambient):
    client = _FakeClient(text="NO_ACTION")
    monkeypatch.setattr(pa, "gemini_client", object())
    monkeypatch.setattr(pa, "resolve_main_gemini", lambda: (client, 7, "Gemini"))
    monkeypatch.setattr(pa, "_main_brain_gemini_model", lambda: "m")
    _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))
    assert ambient.sent == []
    config = json.loads(ambient.config_path.read_text())
    assert config["pings_today"] == 1


def test_ambient_quiet_hour_runs_memory_consolidation(monkeypatch, ambient):
    _FixedDateTime.fixed = datetime(2026, 11, 19, 3, 0, 0)
    config = json.loads(ambient.config_path.read_text())
    config["quiet_hours_start"] = 0
    config["quiet_hours_end"] = 24
    ambient.config_path.write_text(json.dumps(config), encoding="utf-8")
    from alfa.memory import graph_rag

    calls = []
    monkeypatch.setattr(
        graph_rag,
        "consolidate_memory_sleep_cycle",
        lambda **kwargs: calls.append(kwargs) or "ok",
    )
    _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))
    assert calls and calls[0]["user_id"] == "123"
    saved = json.loads(ambient.config_path.read_text())
    assert saved["last_memory_consolidation_date"] == "2026-11-19"


def test_ambient_429_backs_off_one_hour(monkeypatch, ambient):
    monkeypatch.setattr(pa, "gemini_client", object())

    async def boom(uid):
        msg = "429 RESOURCE_EXHAUSTED"
        raise RuntimeError(msg)

    monkeypatch.setattr(pa.database, "get_all_memories", boom)
    monkeypatch.setattr(pa, "resolve_main_gemini", lambda: (_FakeClient(), 7, "G"))
    monkeypatch.setattr(pa, "_main_brain_gemini_model", lambda: "m")
    state = _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))
    assert state["delays"][-1] == 3600


def test_ambient_without_key_or_client(monkeypatch, ambient):
    monkeypatch.setattr(pa, "gemini_client", None)
    _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))

    monkeypatch.setattr(pa, "gemini_client", object())
    monkeypatch.setattr(pa, "resolve_main_gemini", lambda: (None, None, ""))
    _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))


def test_ambient_respects_daily_ping_limit(monkeypatch, ambient):
    config = json.loads(ambient.config_path.read_text())
    config["pings_today"] = 4
    config["last_ping_date"] = _FixedDateTime.fixed.strftime("%Y-%m-%d")
    ambient.config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(pa, "gemini_client", object())
    client = _FakeClient()
    monkeypatch.setattr(pa, "resolve_main_gemini", lambda: (client, 7, "G"))
    _stop_after(monkeypatch, pa, calls=2)
    _run(pa.proactive_ambient_agent_loop(_app()))
    assert ambient.sent == []
    assert client.calls == []


# ── ecosystem / WhatsApp watchdog ────────────────────────────────────────────


class _FakeResponse:
    status = 200

    def __init__(self, payload=b"{}"):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_watchdog(monkeypatch, state="inactive", online=True):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=state + "\n")

    monkeypatch.setattr(pa.subprocess, "run", fake_run)
    if online:
        monkeypatch.setattr(socket, "create_connection", lambda *a, **k: object())
    else:
        def offline(*a, **k):
            msg = "offline"
            raise OSError(msg)

        monkeypatch.setattr(socket, "create_connection", offline)
    return calls


def test_ecosystem_watchdog_starts_inactive_service(monkeypatch, _home):
    calls = _patch_watchdog(monkeypatch, state="inactive")
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_ecosystem_watchdog_loop(_app()))
    assert ["systemctl", "--user", "start", "wa-sheets-bot.service"] in calls


def test_ecosystem_watchdog_offline_skips_actions(monkeypatch, _home):
    calls = _patch_watchdog(monkeypatch, online=False)
    _stop_after(monkeypatch, pa)
    _run(pa.proactive_ecosystem_watchdog_loop(_app()))
    assert calls == []


def test_ecosystem_watchdog_alerts_after_three_unresponsive_checks(monkeypatch, _home):
    _patch_watchdog(monkeypatch, state="active")
    import urllib.error
    import urllib.request

    def dead(*args, **kwargs):
        msg = "connection refused"
        raise urllib.error.URLError(msg)

    monkeypatch.setattr(urllib.request, "urlopen", dead)
    sent = []

    async def send_message(chat_id, text, parse_mode=""):
        sent.append((chat_id, text))

    app = _app()
    app.bot.send_message = send_message
    _stop_after(monkeypatch, pa, calls=3)
    _run(pa.proactive_ecosystem_watchdog_loop(app))
    assert len(sent) == 1
    assert "WhatsApp Bot Status Notice" in sent[0][1]


def test_ecosystem_watchdog_syncs_incoming_every_20_cycles(monkeypatch, _home):
    _patch_watchdog(monkeypatch, state="active")
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(b'{"incoming": [{"body": "halo"}]}'),
    )
    archived = []

    def fake_archive(incoming):
        archived.append(incoming)
        return 5

    from alfa.core.db import wa_tracking

    monkeypatch.setattr(wa_tracking, "archive_wa_messages_sync", fake_archive)
    _stop_after(monkeypatch, pa, calls=20)
    _run(pa.proactive_ecosystem_watchdog_loop(_app()))
    assert archived == [[{"body": "halo"}]]


def test_ecosystem_watchdog_alarm_on_logout(monkeypatch, _home):
    _patch_watchdog(monkeypatch, state="active")
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResponse())
    status_file = _home / ".alfa" / "wa_status.json"
    status_file.parent.mkdir(exist_ok=True)
    status_file.write_text(json.dumps({"status": "READY", "qr": ""}), encoding="utf-8")
    sent = []

    async def send_message(chat_id, text, parse_mode=""):
        sent.append((chat_id, text))

    app = _app()
    app.bot.send_message = send_message

    def on_sleep(n):
        if n == 1:
            status_file.write_text(
                json.dumps({"status": "LOGGED_OUT", "qr": ""}), encoding="utf-8"
            )

    _stop_after(monkeypatch, pa, calls=2, on_sleep=on_sleep)
    _run(pa.proactive_ecosystem_watchdog_loop(app))
    assert any("ALARM: WhatsApp" in text for _, text in sent)
