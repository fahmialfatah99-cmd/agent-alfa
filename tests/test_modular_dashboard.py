import sys
from pathlib import Path

from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_dashboard_package_import():
    """Verify alfa.dashboard imports and exposes FastAPI app."""
    from alfa.dashboard import app as app_from_pkg
    from alfa.dashboard import create_app, get_app
    from alfa.dashboard.app import app as app_from_mod

    assert isinstance(app_from_pkg, FastAPI)
    assert app_from_pkg.title == "ALFA Sovereign Command Center Pro-Max"
    assert app_from_mod is app_from_pkg
    assert get_app() is app_from_pkg
    assert callable(create_app)


def test_web_dashboard_shim_parity():
    """Verify antarmuka dashboard setara (jejak history: dulu membandingkan
    facade web_dashboard.py — facade kini dihapus, pernyataan langsung ke modul)."""
    import importlib as _imp
    web_dashboard = _imp.import_module("alfa.dashboard.app")

    from alfa.dashboard import app as pkg_app

    assert web_dashboard.app is pkg_app
    assert hasattr(web_dashboard, "_parse_ai_sections")
    assert hasattr(web_dashboard, "create_user")
    assert hasattr(web_dashboard, "authenticate_user")
    assert hasattr(web_dashboard, "validate_session")
    assert hasattr(web_dashboard, "_ws_real_path")
    assert hasattr(web_dashboard, "ws_manager")
    assert hasattr(web_dashboard, "ConnectionManager")


def test_dashboard_routes_parity():
    """Verify essential routes across all decomposed routers are present."""
    from alfa.dashboard.app import app

    routes = {r.path for r in app.routes if hasattr(r, "path")}
    for r in app.routes:
        if hasattr(r, "original_router"):
            routes.update(
                sub_r.path
                for sub_r in r.original_router.routes
                if hasattr(sub_r, "path")
            )

    expected_routes = [
        "/",
        "/health",
        "/healthz",
        "/api/metrics",
        "/api/stats",
        "/api/chat",
        "/api/chat/stream",
        "/api/tools",
        "/api/tools/execute",
        "/api/auth/login",
        "/api/auth/register",
        "/api/swarm/live",
        "/api/workspace/tree",
        "/ws/terminal",
        "/ws/logs",
        "/ws/broadcast",
    ]

    for expected in expected_routes:
        assert expected in routes, f"Missing route: {expected}"


def test_health_and_metrics_endpoints():
    """Verify /health, /healthz and /api/metrics respond with 200 OK and valid telemetry."""
    from fastapi.testclient import TestClient

    from alfa.dashboard.app import app

    client = TestClient(app)

    r_health = client.get("/health")
    assert r_health.status_code == 200
    data = r_health.json()
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert "database" in data

    r_healthz = client.get("/healthz")
    assert r_healthz.status_code == 200

    r_metrics = client.get("/api/metrics")
    assert r_metrics.status_code == 200
    mdata = r_metrics.json()
    assert "system" in mdata
    assert "process" in mdata


class TestRequireAdmin:
    def _req(self, user=None):
        class _State:
            pass

        class _Req:
            pass

        r = _Req()
        r.state = _State()
        r.state.user = user
        return r

    def test_lokal_tanpa_auth_diloloskan(self, monkeypatch):
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
        out = auth_mod.require_admin(self._req(None))
        assert out["is_admin"] is True

    def test_tanpa_user_ditolak_bila_auth_aktif(self, monkeypatch):
        from fastapi import HTTPException

        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok")
        try:
            auth_mod.require_admin(self._req(None))
            raise AssertionError("harus 401")
        except HTTPException as e:
            assert e.status_code == 401

    def test_non_admin_ditolak(self, monkeypatch):
        from fastapi import HTTPException

        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok")
        try:
            auth_mod.require_admin(self._req({"is_admin": False}))
            raise AssertionError("harus 403")
        except HTTPException as e:
            assert e.status_code == 403

    def test_admin_lolos(self, monkeypatch):
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok")
        out = auth_mod.require_admin(self._req({"is_admin": True}))
        assert out["is_admin"] is True

    def test_endpoint_sensitif_tolak_member(self, monkeypatch):
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok")
        monkeypatch.setattr(
            auth_mod,
            "validate_session",
            lambda token: {"user_id": 2, "username": "member", "is_admin": False},
        )
        client = TestClient(pkg_app)
        for method, path, body in [
            ("POST", "/api/settings", {"x": "1"}),
            ("POST", "/api/system/cli-exec", {"cmd": "id"}),
            ("POST", "/api/vault/reveal", {"id": "x"}),
            ("DELETE", "/api/keys/1", None),
        ]:
            if method == "POST":
                resp = client.post(
                    path, json=body, cookies={"session_token": "member-sess"}
                )
            else:
                resp = client.delete(path, cookies={"session_token": "member-sess"})
            assert resp.status_code == 403, (path, resp.status_code)
