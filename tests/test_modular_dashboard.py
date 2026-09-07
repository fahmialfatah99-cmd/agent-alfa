import sys
from pathlib import Path
import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_dashboard_package_import():
    """Verify alfa.dashboard imports and exposes FastAPI app."""
    import alfa.dashboard
    from alfa.dashboard import app as app_from_pkg, get_app, create_app
    from alfa.dashboard.app import app as app_from_mod

    assert isinstance(app_from_pkg, FastAPI)
    assert app_from_pkg.title == "ALFA Sovereign Command Center Pro-Max"
    assert app_from_mod is app_from_pkg
    assert get_app() is app_from_pkg
    assert callable(create_app)


def test_web_dashboard_shim_parity():
    """Verify root web_dashboard.py acts as transparent shim for alfa.dashboard."""
    import web_dashboard
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
            routes.update(sub_r.path for sub_r in r.original_router.routes if hasattr(sub_r, "path"))

    expected_routes = [
        "/",
        "/health",
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
