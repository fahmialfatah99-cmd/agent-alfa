"""Unit test antrean misi swarm durable (hermetic, tanpa LLM)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.swarm import queue as swarm_queue


def _db(tmp_path):
    return str(tmp_path / "queue_test.db")


def test_enqueue_list_get(tmp_path):
    db = _db(tmp_path)
    m = swarm_queue.enqueue("Tugas A", mode="plan", db_path=db)
    assert m["id"] > 0
    assert m["status"] == "queued"
    assert m["topic"] == "Tugas A"
    assert swarm_queue.get_mission(m["id"], db_path=db)["topic"] == "Tugas A"
    assert len(swarm_queue.list_missions(db_path=db)) == 1


def test_enqueue_tanpa_topik_ditolak(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        swarm_queue.enqueue("   ", db_path=_db(tmp_path))


def test_claim_atomik_dan_complete(tmp_path):
    db = _db(tmp_path)
    m1 = swarm_queue.enqueue("Satu", db_path=db)
    m2 = swarm_queue.enqueue("Dua", db_path=db)
    c1 = swarm_queue.claim_next(db_path=db)
    assert c1["id"] == m1["id"]
    assert c1["status"] == "running"
    assert c1["attempts"] == 1
    assert swarm_queue.claim_next(db_path=db)["id"] == m2["id"]
    assert swarm_queue.claim_next(db_path=db) is None
    assert swarm_queue.complete_mission(m1["id"], {"ok": True}, db) is True
    assert swarm_queue.get_mission(m1["id"], db_path=db)["status"] == "done"


def test_fail_retry_lalu_failed(tmp_path):
    db = _db(tmp_path)
    m = swarm_queue.enqueue("Gagal", max_attempts=2, db_path=db)
    c = swarm_queue.claim_next(db_path=db)
    r1 = swarm_queue.fail_mission(c["id"], "boom", db)
    assert r1["status"] == "queued"  # retry tersisa
    c2 = swarm_queue.claim_next(db_path=db)
    assert c2 is None  # backoff menunda
    # Paksa siap jalan lagi
    import sqlite3
    import time

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE swarm_missions SET run_after = ? WHERE id = ?",
        (time.time() - 1, m["id"]),
    )
    conn.commit()
    conn.close()
    c3 = swarm_queue.claim_next(db_path=db)
    assert c3["id"] == m["id"]
    r2 = swarm_queue.fail_mission(c3["id"], "boom2", db)
    assert r2["status"] == "failed"


def test_cancel(tmp_path):
    db = _db(tmp_path)
    m = swarm_queue.enqueue("Batal", db_path=db)
    assert swarm_queue.cancel_mission(m["id"], db) is True
    assert swarm_queue.get_mission(m["id"], db_path=db)["status"] == "cancelled"
    assert swarm_queue.cancel_mission(999999, db) is False


def test_worker_eksekusi_dan_selesai(tmp_path, monkeypatch):
    from alfa.swarm import engine as swarm_engine

    db = _db(tmp_path)
    swarm_queue.enqueue("Misi W", db_path=db)

    async def _fake_conduct(**kwargs):
        assert kwargs["topic"] == "Misi W"
        return {"status": "success"}

    monkeypatch.setattr(swarm_engine, "conduct_multi_agent_meeting", _fake_conduct)
    out = asyncio.run(swarm_queue.run_queue_worker(stop_after=1, poll_interval=1, db_path=db))
    assert out == {"done": 1, "failed": 0}
    assert swarm_queue.list_missions(db_path=db)[0]["status"] == "done"


class TestQueueEndpoints:
    def test_enqueue_list_cancel(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from alfa.dashboard.app import app

        monkeypatch.setenv("ALFA_QUEUE_DB", str(tmp_path / "q.db"))
        client = TestClient(app)
        r = client.post(
            "/api/swarm/queue/enqueue", json={"topic": "Misi D", "mode": "plan"}
        )
        assert r.status_code == 200
        mid = r.json()["mission"]["id"]
        r2 = client.get("/api/swarm/queue")
        assert r2.status_code == 200
        assert r2.json()["total"] == 1
        r3 = client.post(f"/api/swarm/queue/{mid}/cancel")
        assert r3.status_code == 200
        r4 = client.get(f"/api/swarm/queue/{mid}")
        assert r4.json()["mission"]["status"] == "cancelled"
