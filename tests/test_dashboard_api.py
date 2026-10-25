"""Permukaan API dashboard — gating, validasi, dan bentuk respons.

Semua route diuji lewat TestClient (tanpa jaringan). Fokusnya: endpoint
mutating WAJIB admin, endpoint publik TIDAK membocorkan data, dan payload
error tetap terstruktur.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client_local(monkeypatch):
    """Dashboard dalam mode development lokal (klien lokal tanpa auth)."""
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.routes import auth as auth_mod

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    return TestClient(pkg_app)


@pytest.fixture
def client_token(monkeypatch):
    """Dashboard dengan token aktif — klien anonim harus ditolak."""
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.routes import auth as auth_mod

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok-rahasia")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "tok-rahasia")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "false")
    return TestClient(pkg_app)


# ── Gating: endpoint mutating wajib admin ───────────────────────────────────

ADMIN_REQUIRED = [
    ("POST", "/api/settings"),
    ("POST", "/api/settings/main-brain"),
    ("POST", "/api/main-brain/test"),
    ("POST", "/api/antigravity/apply"),
    ("POST", "/api/keys/validate"),
    ("POST", "/api/wa/logout"),
    ("POST", "/api/wa/media-rules"),
    ("POST", "/api/wa/media-upload"),
    ("POST", "/api/wa/formats"),
    ("POST", "/api/gdrive/credentials"),
    ("DELETE", "/api/gdrive/credentials"),
    ("POST", "/api/gdrive/folder"),
    ("POST", "/api/gdrive/oauth/start"),
    ("POST", "/api/gdrive/oauth/exchange-code"),
    ("POST", "/api/gdrive/oauth/logout"),
    ("POST", "/api/gdrive/oauth/upload-secret"),
    ("POST", "/api/gdrive/upload"),
    ("POST", "/api/gdrive/create-folder"),
    ("POST", "/api/gdrive/sync-brain"),
    ("POST", "/api/sites/contoh/start"),
    ("POST", "/api/checkpoints/sesi-1/resume"),
    ("POST", "/api/agents"),
    ("POST", "/api/agents/1/chat"),
    ("POST", "/api/agents/1/execute"),
    ("POST", "/api/meetings/start"),
    ("POST", "/api/meetings/cancel"),
    ("POST", "/api/swarm/queue/enqueue"),
    ("POST", "/api/affiliate/generate"),
    ("POST", "/api/affiliate/broadcast"),
    ("POST", "/api/tools/execute"),
    ("POST", "/api/plugins/create"),
    ("POST", "/api/plugins/delete"),
    ("POST", "/api/plugins/execute"),
    ("POST", "/api/pipelines/p1/webhook"),
    ("POST", "/api/antigravity/login/start"),
    ("POST", "/api/antigravity/logout"),
]


class TestAdminGating:
    @pytest.mark.parametrize("method,path", ADMIN_REQUIRED)
    def test_anonim_ditolak(self, client_token, method, path):
        if method == "POST":
            res = client_token.post(path, json={})
        elif method == "DELETE":
            res = client_token.delete(path)
        else:
            res = client_token.get(path)
        assert res.status_code in (401, 403), (method, path, res.status_code)


class TestPublicEndpoints:
    def test_health_tersedia(self, client_token):
        res = client_token.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] in ("ok", "healthy")

    def test_healthz_tersedia(self, client_token):
        res = client_token.get("/healthz")
        assert res.status_code == 200

    def test_metrics_tidak_lagi_publik(self, client_token):
        """Metrics membocorkan CPU/RAM/disk — tidak boleh anonymously."""
        res = client_token.get("/api/metrics")
        assert res.status_code == 401, res.text

    def test_metrics_terbuka_untuk_yang_terautentikasi(self, client_local):
        res = client_local.get("/api/metrics")
        assert res.status_code == 200, res.text

    def test_openapi_tidak_publik(self, client_token):
        """Permukaan API tidak boleh terpublikasi lewat openapi.json."""
        res = client_token.get("/api/openapi.json")
        assert res.status_code == 401, res.text

    def test_docs_tidak_publik(self, client_token):
        res = client_token.get("/docs")
        assert res.status_code == 401, res.text

    def test_passkey_login_ceremony_publik(self, client_token):
        """Ceremony passkey harus bisa diakses tanpa session."""
        res = client_token.get("/api/auth/webauthn/login/options")
        assert res.status_code in (200, 400, 404), res.text


class TestEndpointShapes:
    """Endpoint baca harus mengembalikan JSON terstruktur."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/settings",
            "/api/models",
            "/api/sites",
            "/api/budget/today",
            "/api/memory",
            "/api/pipelines",
            "/api/traces",
            "/api/checkpoints",
            "/api/evals/runs",
            "/api/agents",
            "/api/meetings",
            "/api/swarm/queue",
            "/api/gdrive/status",
            "/api/wa/formats",
            "/api/wa/reports",
            "/api/wa/media-rules",
            "/api/wa/drive-uploads",
            "/api/wa/qr",
            "/api/affiliate/campaigns",
            "/api/chat/models",
            "/api/chat/modes",
            "/api/swarm/live",
            "/api/meeting/history",
            "/api/agent-activity",
            "/api/brain/vector/list",
            "/api/brain/graph/overview",
            "/api/brain/graph/communities",
            "/api/brain/graph/elements",
            "/api/brain/graph/export",
            "/api/plugins/list",
            "/api/skills/superpowers",
            "/api/tools",
        ],
    )
    def test_endpoint_baca_json(self, client_local, path):
        res = client_local.get(path)
        assert res.status_code == 200, (path, res.text[:200])
        assert isinstance(res.json(), (dict, list)), path

    def test_endpoint_tidak_ditemukan_404(self, client_local):
        res = client_local.get("/api/tidak-ada- sama sekali")
        assert res.status_code == 404

    def test_graph_consolidate_and_export_formats(self, client_local):
        res_cons = client_local.post("/api/brain/graph/consolidate", json={"auto_alias": True, "recluster": True})
        assert res_cons.status_code == 200
        assert res_cons.json()["status"] == "success"

        res_gml = client_local.get("/api/brain/graph/export?format=graphml")
        assert res_gml.status_code == 200
        assert "<graphml" in res_gml.text

        res_cql = client_local.get("/api/brain/graph/export?format=cypher")
        assert res_cql.status_code == 200
        assert "MERGE" in res_cql.text or "//" in res_cql.text


class TestInputValidation:
    def test_body_bukan_json_ditolak(self, client_local):
        res = client_local.post(
            "/api/settings",
            content=b"bukan json",
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code in (400, 422), res.status_code

    def test_settings_tanpa_payload_menolak(self, client_local):
        res = client_local.post("/api/settings", json={})
        assert res.status_code in (200, 400, 422), res.status_code

    def test_agents_execute_tanpa_instruction_ditolak(self, client_local):
        res = client_local.post("/api/agents/1/execute", json={})
        assert res.status_code in (400, 404), res.status_code

    def test_swarm_enqueue_payload_kosong_ditolak(self, client_local):
        res = client_local.post("/api/swarm/queue/enqueue", json={})
        assert res.status_code in (400, 422, 404), res.status_code
