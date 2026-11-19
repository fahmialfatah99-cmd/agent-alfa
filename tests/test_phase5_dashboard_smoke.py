"""Phase 5 coverage: dashboard route smoke tests with an isolated database.

Hermetic: DB SQLite sementara, registry situs/ pipeline diarahkan ke tmp,
dan systemctl di-mock. Tidak ada layanan produksi yang disentuh.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "dashboard_smoke.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return db_file


@pytest.fixture
def client(isolated_db, tmp_path, monkeypatch):
    from alfa.core import config
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.ratelimit import reset_rate_limits
    from alfa.dashboard.routes import auth as auth_mod
    from alfa.dashboard.routes.system import settings_admin, telemetry
    from alfa.integrations import google_sheets
    from alfa.pipelines import engine as pipelines
    from alfa.tools.system import sites

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    monkeypatch.setenv("ALLOWED_USER_IDS", "42")
    monkeypatch.delenv("ALFA_CHAT_RATE_LIMIT", raising=False)
    monkeypatch.delenv("ALFA_CHAT_RATE_WINDOW_SEC", raising=False)

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "no-secrets.env")
    monkeypatch.setattr(settings_admin, "REPO_ROOT", str(tmp_path / "repo"))
    monkeypatch.setattr(
        google_sheets, "WA_BOT_DIR", str(tmp_path / "wa")
    )
    monkeypatch.setattr(
        google_sheets, "WA_KEY_FILE", str(tmp_path / "wa" / "service-account.json")
    )
    monkeypatch.setattr(
        google_sheets, "GDRIVE_KEY_FILE", str(tmp_path / "gdrive_credentials.json")
    )

    state = tmp_path / ".alfa"
    outputs = tmp_path / "outputs"
    monkeypatch.setattr(sites, "STATE_DIR", str(state))
    monkeypatch.setattr(sites, "REGISTRY_FILE", str(state / "sites_registry.json"))
    monkeypatch.setattr(sites, "LOGS_DIR", str(state / "sites_logs"))
    monkeypatch.setattr(sites, "OUTPUTS_DIR", str(outputs))

    pipeline_dir = tmp_path / "pipelines"
    pipeline_dir.mkdir()
    monkeypatch.setattr(pipelines, "PIPELINE_DIR", str(pipeline_dir))

    monkeypatch.setattr(
        telemetry.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="active\n", stderr="", returncode=0),
    )
    reset_rate_limits()
    return TestClient(pkg_app)


# ── read-only GET routes ─────────────────────────────────────────────────────


def test_index_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_settings_route(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "main_brain" in payload
    assert "vault_keys" in payload
    assert "env" in payload


def test_pipelines_routes(client):
    response = client.get("/api/pipelines")
    assert response.status_code == 200
    assert response.json()["pipelines"] == []

    response = client.get("/api/pipelines/tidak-ada")
    assert response.status_code == 404


def test_memory_routes(client):
    assert client.get("/api/memory").status_code == 200
    assert client.get("/api/brain/export").status_code == 200

    bad = client.post("/api/memory/add", json={"type": "fact", "key_topic": "x"})
    assert bad.status_code == 400

    added = client.post(
        "/api/memory/add",
        json={
            "type": "fact",
            "key_topic": "proyek",
            "content": "ALFA OS",
            "category": "umum",
        },
    )
    assert added.status_code == 200

    relation = client.post(
        "/api/memory/add",
        json={
            "type": "relation",
            "entity": "ALFA",
            "relation": "memakai",
            "target_value": "SQLite",
            "category": "teknis",
        },
    )
    assert relation.status_code == 200

    memory = client.get("/api/memory").json()
    assert memory["total_memories"] >= 1
    assert memory["knowledge_graph"]
    exported = client.get("/api/brain/export").json()
    assert "ALFA SECOND BRAIN" in exported["markdown"]
    assert exported["json"]["memories"]


def test_tools_plugins_and_skills_routes(client):
    tools = client.get("/api/tools")
    assert tools.status_code == 200

    plugins = client.get("/api/plugins/list")
    assert plugins.status_code == 200
    assert plugins.json()["status"] == "success"

    skills = client.get("/api/skills/superpowers")
    assert skills.status_code == 200


def test_sites_and_budget_routes(client):
    sites = client.get("/api/sites")
    assert sites.status_code == 200
    assert sites.json()["total"] == 0

    budget = client.get("/api/budget/today")
    assert budget.status_code == 200


def test_telemetry_routes(client):
    home = client.get("/api/system/home-dir")
    assert home.status_code == 200
    assert home.json()["home_dir"]

    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert stats.json()["status"] == "success"

    services = client.get("/api/services")
    assert services.status_code == 200
    assert services.json()["status"] == "success"


def test_trust_and_trace_routes(client):
    trust = client.get("/api/v1/trust/summary")
    assert trust.status_code == 200
    assert trust.json()["status"] == "ok"

    capabilities = client.get("/api/v1/trust/capabilities")
    assert capabilities.status_code == 200

    runs = client.get("/api/v1/trace/runs")
    assert runs.status_code == 200

    missing = client.get("/api/v1/trace/runs/tidak-ada")
    assert missing.status_code == 404


def test_unknown_route_returns_404(client):
    assert client.get("/api/tidak-ada-sama-sekali").status_code == 404


def test_site_action_validates_slug(client):
    response = client.post("/api/sites/tidak-ada/start")
    assert response.status_code == 404
    bad = client.post("/api/sites/x/hapus")
    assert bad.status_code == 400


def test_pipeline_webhook_requires_existing_pipeline(client):
    response = client.post("/api/pipelines/tidak-ada/webhook", json={})
    assert response.status_code == 404


def test_pipeline_canvas_save_and_run(client, tmp_path):
    payload = {"steps": [{"id": "s1", "type": "noop"}]}
    saved = client.post("/api/pipelines/uji", json=payload)
    assert saved.status_code == 200
    assert saved.json()["file"] == "uji.json"
    stored = json.loads((tmp_path / "pipelines" / "uji.json").read_text())
    assert stored["id"] == "uji"

    invalid = client.post("/api/pipelines/uji", json={"steps": []})
    assert invalid.status_code == 400
