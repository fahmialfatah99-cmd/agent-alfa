"""Regression tests for Phase 3 production platform (readiness, tracing, limits)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "phase3_production.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as conn

    conn.init_db_sync()
    return db_file


@pytest.fixture
def api_client(isolated_db, monkeypatch):
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.ratelimit import reset_rate_limits
    from alfa.dashboard.routes import auth as auth_mod

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    monkeypatch.setenv("ALLOWED_USER_IDS", "42")
    monkeypatch.delenv("ALFA_CHAT_RATE_LIMIT", raising=False)
    monkeypatch.delenv("ALFA_CHAT_RATE_WINDOW_SEC", raising=False)
    reset_rate_limits()
    return TestClient(pkg_app)


def test_readyz_reports_ready(api_client):
    for path in ("/readyz", "/api/readyz"):
        response = api_client.get(path)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["checks"]["database"]["ok"] is True
        assert payload["checks"]["disk"]["ok"] is True
        assert payload["version"]


def test_readiness_fails_closed_without_database(monkeypatch):
    from alfa.dashboard import health

    monkeypatch.setattr(
        health, "_check_database", lambda: {"ok": False, "error": "db down"}
    )
    snapshot = health.readiness_snapshot()
    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["database"]["ok"] is False


def test_request_id_is_echoed_when_safe(api_client):
    response = api_client.get(
        "/healthz", headers={"X-Request-ID": "req-12345678"}
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-12345678"


def test_request_id_is_regenerated_when_invalid(api_client):
    response = api_client.get(
        "/healthz", headers={"X-Request-ID": "bad id with spaces"}
    )
    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_chat_generation_is_rate_limited(api_client, monkeypatch):
    from alfa.dashboard.ratelimit import reset_rate_limits

    monkeypatch.setenv("ALFA_CHAT_RATE_LIMIT", "2")
    monkeypatch.setenv("ALFA_CHAT_RATE_WINDOW_SEC", "60")
    reset_rate_limits()

    first = api_client.post("/api/chat/stream", json={})
    second = api_client.post("/api/chat/stream", json={})
    third = api_client.post("/api/chat/stream", json={})

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429
    assert third.headers["retry-after"].isdigit()
    assert third.headers["x-ratelimit-remaining"] == "0"


def test_metrics_include_operational_snapshot(api_client):
    response = api_client.get("/api/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"]
    assert "operational" in payload
    assert "queue" in payload["operational"]
    assert "active_chat_turns" in payload["operational"]


def test_queue_stats_counts_status(tmp_path):
    from alfa.swarm.queue import enqueue, queue_stats

    db_path = str(tmp_path / "queue.db")
    enqueue("misi uji", db_path=db_path)
    stats = queue_stats(db_path)
    assert stats["queued"] == 1
    assert stats["total"] == 1
    assert stats["done"] == 0


def test_cancel_active_turns_clears_registry():
    from alfa.dashboard.routes import chat

    class FakeTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    first, second = FakeTask(), FakeTask()
    chat._ACTIVE_TURNS.clear()
    chat._ACTIVE_BY_CONVERSATION.clear()
    chat._ACTIVE_TURNS["r1"] = first  # type: ignore[assignment]
    chat._ACTIVE_TURNS["r2"] = second  # type: ignore[assignment]
    chat._ACTIVE_BY_CONVERSATION["c1"] = "r1"

    assert chat.active_turn_count() == 2
    assert chat.cancel_active_turns() == 2
    assert first.cancelled is True
    assert second.cancelled is True
    assert chat.active_turn_count() == 0
    assert chat._ACTIVE_BY_CONVERSATION == {}


def test_lifespan_shutdown_cancels_active_turns(isolated_db, monkeypatch):
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.routes import auth as auth_mod
    from alfa.dashboard.routes import chat

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")

    class FakeTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    task = FakeTask()
    chat._ACTIVE_TURNS.clear()
    with TestClient(pkg_app) as client:
        chat._ACTIVE_TURNS["shutdown-test"] = task  # type: ignore[assignment]
        assert client.get("/healthz").status_code == 200

    assert task.cancelled is True
    assert chat.active_turn_count() == 0
