"""Tes read-only Trust/Evidence API di dashboard."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_turn_ctx():
    from alfa.core.runtime_ctx import reset_turn_context

    reset_turn_context()
    yield
    reset_turn_context()


@pytest.fixture()
def trust_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALFA_DB_PATH", str(tmp_path / "trust_api.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALFA_EVIDENCE_LEDGER", "on")
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "shadow")
    monkeypatch.setenv("ALFA_DURABLE_TASKS", "shadow")
    monkeypatch.setenv("ALFA_SKILL_COMPILER", "shadow")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.routes import auth as auth_mod

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    return TestClient(pkg_app)


def _seed(tmp_path):
    from alfa.core.db import evidence
    from alfa.core.runtime_ctx import begin_turn, reset_turn_context

    reset_turn_context()
    turn_id = begin_turn()
    path = tmp_path / "rekap.xlsx"
    path.write_bytes(b"bukti")
    evidence.record_tool_evidence(
        "update_excel_sheet",
        arguments=json.dumps({"file_path": str(path)}),
        output=json.dumps({"status": "success", "file_path": str(path)}),
    )
    return turn_id, str(path)


def test_trust_summary_shape(trust_client, tmp_path):
    _seed(tmp_path)

    response = trust_client.get("/api/v1/trust/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["evidence_mode"] == "on"
    assert data["evidence"]["total"] >= 1
    assert "context_governor" in data


def test_trust_evidence_list_and_turn_detail(trust_client, tmp_path):
    turn_id, path = _seed(tmp_path)

    listed = trust_client.get("/api/v1/trust/evidence", params={"limit": 10})
    detail = trust_client.get(f"/api/v1/trust/evidence/{turn_id}")

    assert listed.status_code == 200
    assert listed.json()["count"] >= 1
    assert listed.json()["evidence"][0]["path"] == path
    assert detail.status_code == 200
    assert detail.json()["turn_id"] == turn_id
    assert detail.json()["count"] >= 1


def test_trust_evidence_filter_by_path(trust_client, tmp_path):
    _, path = _seed(tmp_path)

    response = trust_client.get(
        "/api/v1/trust/evidence", params={"path": path}
    )

    assert response.status_code == 200
    assert all(item["path"] == path for item in response.json()["evidence"])


def test_trust_context_endpoint(trust_client):
    response = trust_client.get("/api/v1/trust/context")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "context_governor" in data
    assert "limits" in data["context_governor"]


def test_trust_capabilities_endpoint(trust_client):
    from alfa.core.perm.capabilities import grant_capability_sync

    granted = grant_capability_sync(
        4242, "execute_bash_command", user_id=4242, ttl_minutes=30
    )
    assert granted is not None

    response = trust_client.get(
        "/api/v1/trust/capabilities", params={"chat_id": 4242}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "shadow"
    assert data["count"] == 1
    assert data["capabilities"][0]["grant_id"] == granted["grant_id"]


def test_trust_tasks_endpoint(trust_client):
    from alfa.core.db.durable_tasks import create_task_sync

    created = create_task_sync("task-trust-api", user_id=1, prompt="uji trust")
    assert created is not None

    response = trust_client.get("/api/v1/trust/tasks")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "shadow"
    assert data["count"] >= 1
    assert any(item["task_id"] == "task-trust-api" for item in data["tasks"])


def test_trust_skills_endpoint(trust_client):
    from alfa.core.brain.learning_loop import record_trajectory
    from alfa.core.brain.skill_compiler import compile_skills_sync

    for idx in range(2):
        record_trajectory(
            user_prompt="rekap material lahat",
            tool_calls=[
                {"tool": "read_local_file"},
                {"tool": "update_excel_sheet"},
            ],
            success=True,
            turn_id=f"skill-api-{idx}",
        )
    compiled = compile_skills_sync(min_support=2)
    assert compiled["compiled"] == 1

    response = trust_client.get("/api/v1/trust/skills")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "shadow"
    assert data["count"] == 1
    assert data["skills"][0]["active"] == 0


def test_spa_contains_trust_center_panel(trust_client):
    html = trust_client.get("/").text

    assert 'id="trust-center-panel"' in html
    assert 'id="trust-hours"' in html
    assert 'id="trust-evidence-body"' in html
    assert 'id="trust-capability-body"' in html
    assert 'id="trust-task-body"' in html
    assert 'id="trust-skill-body"' in html
    # Tidak boleh menambah <button> baru (menjaga snapshot Playwright).
    assert "fetchTrustCenter(); return false;" in html
