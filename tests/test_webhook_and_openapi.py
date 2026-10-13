"""Unit and integration tests for OpenAPI, Healthcheck, and Webhook endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from alfa.dashboard.app import app


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    return TestClient(app)


class TestHealthAndOpenAPI:
    def test_health_check_endpoints(self, client):
        """Verify /health, /healthz, /api/health, and /api/healthz return consistent schema."""
        for path in ("/health", "/healthz", "/api/health", "/api/healthz"):
            resp = client.get(path)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("healthy", "degraded")
            assert data["service"] == "alfa-sovereign-ai"
            assert data["version"] == "2.6.0"
            assert "uptime_seconds" in data
            assert "memory_rss_mb" in data

    def test_metrics_endpoint(self, client):
        """Verify /api/metrics endpoint returns system and process metrics."""
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "system" in data
        assert "process" in data
        assert "database_pool" in data

    def test_openapi_docs_endpoint(self, client):
        """Verify OpenAPI JSON schema and interactive docs."""
        resp = client.get("/api/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "ALFA Sovereign Command Center Pro-Max"
        assert schema["info"]["version"] == "2.6.0"
        assert "/api/v1/webhook/trigger" in schema["paths"]
        assert "/api/health" in schema["paths"]


class TestWebhookEndpoints:
    def test_webhook_status(self, client):
        """Verify webhook status probe returns ready state."""
        resp = client.get("/api/v1/webhook/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["endpoint"] == "/api/v1/webhook/trigger"

    def test_webhook_trigger_auth_denied(self, client, monkeypatch):
        """Verify unauthenticated request is rejected when secret is configured."""
        monkeypatch.setattr(
            "alfa.dashboard.routes.webhook.WEBHOOK_SECRET", "super_secret_123"
        )
        monkeypatch.setattr(
            "alfa.dashboard.routes.webhook.DASHBOARD_AUTH_TOKEN", "super_secret_123"
        )

        payload = {
            "event": "test_alert",
            "prompt": "Test instruction",
            "source": "n8n",
        }
        # Simulate non-localhost request without secret header
        resp = client.post(
            "/api/v1/webhook/trigger",
            json=payload,
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        assert resp.status_code == 401

    @patch("alfa.bot.turn_executor.run_agent_turn", new_callable=AsyncMock)
    def test_webhook_trigger_success(self, mock_turn, client, monkeypatch):
        """Verify authenticated webhook executes agent turn and returns response."""
        monkeypatch.setattr(
            "alfa.dashboard.routes.webhook.WEBHOOK_SECRET", "test_key_xyz"
        )
        monkeypatch.setattr(
            "alfa.dashboard.routes.webhook.DASHBOARD_AUTH_TOKEN", "test_key_xyz"
        )
        mock_turn.return_value = "✅ Tugas webhook berhasil diproses."

        payload = {
            "event": "cron_alert",
            "prompt": "Cek server disk",
            "source": "monitoring_system",
            "dispatch_telegram": False,
        }
        resp = client.post(
            "/api/v1/webhook/trigger",
            json=payload,
            headers={"X-Webhook-Secret": "test_key_xyz"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["event"] == "cron_alert"
        assert data["response"] == "✅ Tugas webhook berhasil diproses."
        assert data["duration_ms"] >= 0

    def test_github_webhook(self, client):
        """Verify GitHub webhook endpoint receives event payload."""
        payload = {
            "repository": {"full_name": "fahmial/agent-alfa"},
            "sender": {"login": "fahmial"},
        }
        resp = client.post(
            "/api/v1/webhook/github",
            json=payload,
            headers={"X-GitHub-Event": "push"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["event"] == "push"
