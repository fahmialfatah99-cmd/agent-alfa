"""Unit hermetik: Penjaga Harian (guardian) — kolektor, state machine,
jadwal cron, watchdog WA.Tanpa network, tanpa subprocces nyata, tanpa DB prod."""

from __future__ import annotations

import asyncio

from alfa.core.db import tasks as cron_tasks
from alfa.tools.system import guardian

# ── State machine WaWatchState ──────────────────────────────────────────────


def test_watch_state_threshold_then_cooldown():
    state = guardian.WaWatchState(threshold=2, cooldown_s=3600)
    assert state.evaluate(False, 0.0) is False  # fail #1
    assert state.streak == 1
    assert state.evaluate(True, 5.0) is False  # sehat → reset
    assert state.streak == 0
    assert state.evaluate(False, 6.0) is False  # fail #1 lagi
    assert state.evaluate(False, 7.0) is True  # fail #2 → BUNYIKAN
    assert state.evaluate(False, 8.0) is False  # cooldown menahan
    assert state.evaluate(False, 99999.0) is True  # cooldown lewat → bunyi lagi


def test_watch_state_ok_resets_streak():
    state = guardian.WaWatchState(threshold=3)
    for ts in (1, 2, 3, 4):
        state.evaluate(False, ts)
    assert state.evaluate(True, 5) is False
    assert state.streak == 0


# ── build_guardian_report: agregasi & teks ──────────────────────────────────


def _patch_collectors(monkeypatch, **overrides):
    services = overrides.get("services", {u.replace(".service", ""): "active" for u in guardian._UNITS})
    wa = overrides.get("wa", {"client": "READY", "buffer": 5, "is_ready": True})
    archive = overrides.get("archive", {"total": 200, "last_24h": 12})
    journals = overrides.get(
        "journals",
        {u.replace(".service", ""): {"red": 0, "noise": 0} for u in guardian._UNITS},
    )
    runs = overrides.get("runs", {"runs_today": 2, "steps": 7, "error_runs": 0})
    ci = overrides.get("ci", {"last_ci": "success"})
    monkeypatch.setattr(guardian, "_collect_services", lambda: services)
    monkeypatch.setattr(guardian, "_collect_wa", lambda: wa)
    monkeypatch.setattr(guardian, "_collect_archive_growth", lambda: archive)
    monkeypatch.setattr(guardian, "_collect_journal_errors", lambda: journals)
    monkeypatch.setattr(guardian, "_collect_run_activity", lambda: runs)
    monkeypatch.setattr(guardian, "_collect_ci", lambda: ci)
    return dict(services=services, wa=wa, archive=archive,
                journals=journals, runs=runs, ci=ci)


def test_report_healthy_has_categories_and_verdict(monkeypatch):
    _patch_collectors(monkeypatch)
    rep = guardian.build_guardian_report()
    assert rep["overall"] == "healthy"
    assert rep["status"] == "ok"
    assert "PENJAGA HARIAN" in rep["text"]
    for marker in ("Layanan", "WA:", "Red journal", "Aktivitas ALFA", "CI commit"):
        assert marker in rep["text"]
    assert "lanjut kerja" in rep["text"].lower()
    assert rep["wa"]["client"] == "READY"
    assert rep["archive"]["last_24h"] == 12


def test_report_service_down_and_wa_broken_flags_crit(monkeypatch):
    services = {u.replace(".service", ""): "active" for u in guardian._UNITS}
    services["wa-sheets-bot"] = "failed"
    _patch_collectors(monkeypatch, services=services,
                      wa={"client": "DISCONNECTED", "buffer": 0, "is_ready": False},
                      ci={"last_ci": "failure"})
    rep = guardian.build_guardian_report()
    assert rep["overall"] == "crit"
    assert "KRITIS" in rep["text"]
    assert "wa-sheets-bot=failed" in rep["text"]
    assert "DISCONNECTED" in rep["text"]


def test_report_warns_on_journal_noise_and_run_errors(monkeypatch):
    journals = {u.replace(".service", ""): {"red": 0, "noise": 0} for u in guardian._UNITS}
    journals["telegram-ai-bot"] = {"red": 15, "noise": 180}
    _patch_collectors(monkeypatch, journals=journals,
                      runs={"runs_today": 3, "steps": 9, "error_runs": 1})
    rep = guardian.build_guardian_report()
    assert rep["overall"] == "warn"
    assert "telegram-ai-bot: 15 baris" in rep["text"]
    assert "1 run ALFA gagal" in rep["text"]


def test_collectors_fail_soft(monkeypatch):
    """Kolektor run aktivitas gagal-lembut: DB error → dict dialihkan, bukan exception."""
    def _boom(**_kw):
        raise RuntimeError("boom")

    from alfa.core.db import run_trace as run_trace_mod

    monkeypatch.setattr(run_trace_mod, "list_runs_sync", _boom)
    result = guardian._collect_run_activity()
    assert isinstance(result, dict)
    assert result["runs_today"] == -1
    assert "detail" in result


def test_journal_collector_never_throws_and_separates_noise():
    counts = guardian._collect_journal_errors()
    assert isinstance(counts, dict)
    assert set(counts.keys()) == {
        u.replace(".service", "") for u in guardian._UNITS
    }
    for jc in counts.values():
        assert set(jc.keys()) == {"red", "noise"}
        assert jc["red"] >= 0 and jc["noise"] >= 0


def test_noise_is_not_counted_as_red(monkeypatch):
    """Guncangan net berulir httpx/NetworkError → noise, bukan red."""
    def fake_run_cmd(_args, timeout=10.0):  # noqa: ARG001
        return "\n".join(
            [
                "Traceback (most recent call last):",  # milik keluarga net → noise
                "ERROR httpx.NetworkError boom",  # noise (baris sendiri)
                "Exception: ConnectionReset saat membaca",  # noise
                "FATAL: antrean hang detik ke-99",  # red betulan
            ]
        )

    monkeypatch.setattr(guardian, "_run_cmd", fake_run_cmd)
    jc = guardian._collect_journal_errors()
    tg = jc["telegram-ai-bot"]
    assert tg["red"] == 1
    assert tg["noise"] == 3


# ── Watchdog WA: sekali cek (I/O dikikis) ───────────────────────────────────


class _FakeApp:
    def __init__(self):
        self.sent: list | None = []

    async def send(self, text: str) -> None:  # pragma: no cover
        pass


def test_watchdog_check_once_sends_once_then_silence(monkeypatch):
    sent: list = []

    async def fake_safe_send(app, chat_id, text, **_kw):
        sent.append((chat_id, text))

    import alfa.bot.helpers as helpers

    monkeypatch.setattr(helpers, "safe_send_message", fake_safe_send)
    monkeypatch.setenv("ALLOWED_USER_IDS", "424242")
    state = guardian.WaWatchState(threshold=2, cooldown_s=3600)
    bad = {"client": "DISCONNECTED", "buffer": 0, "is_ready": False}
    app = _FakeApp()
    # gagal #1: salah diam
    fired = asyncio.run(guardian.guardian_watch_check_once(app, state, snapshot=bad))
    assert fired is False and sent == []

    # gagal #2: bunamkan peringatan
    fired = asyncio.run(guardian.guardian_watch_check_once(app, state, snapshot=bad))
    assert fired is True
    assert len(sent) == 1
    chat, text = sent[0]
    assert chat == 424242
    assert "PERINGATAN WA" in text and "DISCONNECTED" in text

    # masih jelek tapi dalam cooldown → tidak dibunamkan ulang
    fired = asyncio.run(guardian.guardian_watch_check_once(app, state, snapshot=bad))
    assert fired is False
    assert len(sent) == 1

    # sembuh → memutikan streak
    good = {"client": "READY", "buffer": 2, "is_ready": True}
    fired = asyncio.run(guardian.guardian_watch_check_once(app, state, snapshot=good))
    assert fired is False


def test_wa_alert_text_mentions_restart_is_safe(monkeypatch):
    text = guardian.build_wa_alert_text({"client": "QR_READY"})
    assert "TIDAK menghapus sesi" in text


# ── Jadwal cron (I/O dikikis) ───────────────────────────────────────────────


def test_schedule_guardian_daily_creates_unique_job(monkeypatch):
    calls: list = []

    def fake_list(_uid):
        return calls and [{"id": 77, "title": guardian._GUARDIAN_TITLE}] or []

    deleted: list = []
    monkeypatch.setattr(cron_tasks, "list_cron_jobs_sync", fake_list)
    monkeypatch.setattr(
        cron_tasks, "delete_cron_job_sync",
        lambda uid, jid: deleted.append(jid) or True,
    )

    def fake_add(**kwargs):
        calls.append(kwargs)
        return 501

    monkeypatch.setattr(cron_tasks, "add_cron_job_sync", fake_add)

    res = guardian.schedule_guardian_daily(9, 9, enabled=True, interval_minutes=1440)
    assert res["status"] == "ok" and res["job_id"] == 501
    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["interval_minutes"] == 1440
    assert kwargs["kind"] == "single"
    assert "guardian_daily_report" in kwargs["prompt_instruction"]
    assert guardian._GUARDIAN_TITLE in kwargs["title"]


def test_schedule_guardian_daily_disable_removes_existing(monkeypatch):
    monkeypatch.setattr(
        cron_tasks, "list_cron_jobs_sync",
        lambda _uid: [{"id": 63, "title": guardian._GUARDIAN_TITLE}
                      for _ in range(2)],
    )
    deleted: list = []
    monkeypatch.setattr(cron_tasks, "delete_cron_job_sync",
                        lambda uid, jid: deleted.append(jid) or True)
    add_calls: list = []
    monkeypatch.setattr(cron_tasks, "add_cron_job_sync",
                        lambda **kw: add_calls.append(kw) or 1)
    res = guardian.schedule_guardian_daily(9, 9, enabled=False)
    assert res["status"] == "ok" and len(deleted) == 2
    assert add_calls == []


# ── Registrasi tool ────────────────────────────────────────────────────────


def test_guardian_tools_registered():
    import alfa.tools

    registry = getattr(alfa.tools, "TOOL_REGISTRY", {})
    for name in ("guardian_daily_report", "schedule_daily_guardian_task"):
        assert name in registry, f"{name} belum terdaftar"
