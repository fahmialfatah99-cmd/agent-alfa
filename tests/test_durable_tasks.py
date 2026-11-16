"""Tes P1 Durable Task Runtime: checkpoint, recovery, resume claim, retensi."""

from __future__ import annotations

import sqlite3

import pytest

from alfa.core.db import durable_tasks
from alfa.core.db.connection import get_sync_db, init_db_sync


@pytest.fixture()
def isolated_durable_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "durable_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALFA_DURABLE_TASKS", "shadow")
    init_db_sync()
    return db_file


def _delete_all() -> None:
    with get_sync_db() as conn:
        try:
            conn.execute("DELETE FROM durable_tasks")
            conn.commit()
        except sqlite3.Error:
            pass


def test_create_checkpoint_finish_and_list(isolated_durable_db):
    _delete_all()
    created = durable_tasks.create_task_sync(
        "task-1",
        turn_id="turn-1",
        user_id=7,
        chat_id=9,
        prompt="Rekap material bulan ini",
        model="gemini-test",
        max_attempts=2,
    )
    assert created is not None
    assert created["status"] == "running"
    assert created["prompt"].startswith("Rekap material")

    assert durable_tasks.checkpoint_task_sync(
        "task-1", step_index=3, payload={"last_tools": ["a", "b"]}
    )
    current = durable_tasks.get_task_sync("task-1")
    assert current is not None
    assert current["step_index"] == 3
    assert current["payload"]["last_tools"] == ["a", "b"]

    assert durable_tasks.finish_task_sync(
        "task-1", status="completed", payload={"tokens": 12}
    )
    done = durable_tasks.get_task_sync("task-1")
    assert done is not None
    assert done["status"] == "completed"
    assert done["payload"]["tokens"] == 12
    assert done["finished_at"]

    listed = durable_tasks.list_tasks_sync(user_id=7)
    assert [row["task_id"] for row in listed] == ["task-1"]


def test_off_mode_does_not_write(isolated_durable_db, monkeypatch):
    _delete_all()
    monkeypatch.setenv("ALFA_DURABLE_TASKS", "off")
    assert durable_tasks.create_task_sync("task-off", prompt="x") is None
    assert durable_tasks.get_task_sync("task-off") is None
    assert durable_tasks.task_count_sync() == 0


def test_shadow_mode_disallows_resume_claim(isolated_durable_db):
    _delete_all()
    durable_tasks.create_task_sync("task-shadow", user_id=1, prompt="x")
    durable_tasks.finish_task_sync("task-shadow", status="interrupted")
    assert durable_tasks.claim_task_for_resume_sync("task-shadow", user_id=1) is None


def test_on_mode_claims_with_attempt_budget(isolated_durable_db, monkeypatch):
    _delete_all()
    monkeypatch.setenv("ALFA_DURABLE_TASKS", "on")
    durable_tasks.create_task_sync(
        "task-on", user_id=1, chat_id=2, prompt="lanjut", max_attempts=2
    )
    durable_tasks.finish_task_sync("task-on", status="failed", error="putus")

    first = durable_tasks.claim_task_for_resume_sync("task-on", user_id=1)
    assert first is not None
    assert first["status"] == "running"
    assert first["attempts"] == 1

    durable_tasks.finish_task_sync("task-on", status="failed", error="putus lagi")
    second = durable_tasks.claim_task_for_resume_sync("task-on", user_id=1)
    assert second is not None
    assert second["attempts"] == 2

    durable_tasks.finish_task_sync("task-on", status="failed", error="habis")
    assert durable_tasks.claim_task_for_resume_sync("task-on", user_id=1) is None


def test_claim_rejects_other_user(isolated_durable_db, monkeypatch):
    _delete_all()
    monkeypatch.setenv("ALFA_DURABLE_TASKS", "on")
    durable_tasks.create_task_sync("task-owner", user_id=1, prompt="x")
    durable_tasks.finish_task_sync("task-owner", status="interrupted")
    assert durable_tasks.claim_task_for_resume_sync("task-owner", user_id=2) is None


def test_recover_stale_marks_interrupted(isolated_durable_db):
    _delete_all()
    durable_tasks.create_task_sync("task-stale", user_id=1, prompt="x")
    with get_sync_db() as conn:
        conn.execute(
            "UPDATE durable_tasks SET updated_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", "task-stale"),
        )
        conn.commit()

    recovered = durable_tasks.recover_stale_tasks_sync(stale_minutes=30)
    assert recovered == 1
    row = durable_tasks.get_task_sync("task-stale")
    assert row is not None
    assert row["status"] == "interrupted"
    assert "startup recovery" in row["error"]

    listed = durable_tasks.list_resumable_tasks_sync(user_id=1)
    assert [item["task_id"] for item in listed] == ["task-stale"]


def test_prune_respects_retention_and_row_cap(isolated_durable_db):
    _delete_all()
    durable_tasks.create_task_sync("task-old", prompt="old")
    with get_sync_db() as conn:
        conn.execute(
            "UPDATE durable_tasks SET created_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", "task-old"),
        )
        conn.commit()
    durable_tasks.create_task_sync("task-new", prompt="new")

    pruned = durable_tasks.prune_tasks_sync(days=30, max_rows=0)
    assert pruned["status"] == "ok"
    assert pruned["deleted_old"] == 1
    assert durable_tasks.get_task_sync("task-old") is None
    assert durable_tasks.get_task_sync("task-new") is not None

    for idx in range(3):
        durable_tasks.create_task_sync(f"task-extra-{idx}", prompt="x")
    pruned = durable_tasks.prune_tasks_sync(days=0, max_rows=1)
    assert pruned["deleted_excess"] >= 1
    assert durable_tasks.task_count_sync() == 1


def test_fail_soft_on_missing_task(isolated_durable_db):
    assert durable_tasks.checkpoint_task_sync("missing", step_index=1) is False
    assert durable_tasks.finish_task_sync("missing") is False
    assert durable_tasks.claim_task_for_resume_sync("missing") is None
    assert durable_tasks.get_task_sync("") is None
