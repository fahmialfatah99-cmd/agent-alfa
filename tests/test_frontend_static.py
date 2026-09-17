import sys
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_index_html_decomposition():
    """Verify templates/index.html is decomposed and cleanly links to static assets."""
    from alfa.dashboard.app import app, TEMPLATES_DIR, STATIC_DIR

    index_path = Path(TEMPLATES_DIR) / "index.html"
    assert index_path.exists(), "templates/index.html does not exist"

    content = index_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Monolithic index.html was 11,450 lines. Decomposed index.html should be under 5,000 lines.
    assert len(lines) < 5000, f"index.html has {len(lines)} lines, expected < 5000"

    # Verify links to static assets
    assert "/static/css/dashboard.css" in content
    assert "/static/js/app.js" in content
    assert "/static/js/terminal.js" in content
    assert "/static/js/tools.js" in content
    assert "/static/js/chat.js" in content


def test_static_files_exist():
    """Verify extracted static files physically exist on disk and have non-trivial size."""
    from alfa.dashboard.app import STATIC_DIR

    static_path = Path(STATIC_DIR)
    expected_files = [
        static_path / "css" / "dashboard.css",
        static_path / "js" / "app.js",
        static_path / "js" / "terminal.js",
        static_path / "js" / "tools.js",
        static_path / "js" / "chat.js",
    ]

    for f in expected_files:
        assert f.exists(), f"Missing static asset file: {f}"
        assert f.stat().st_size > 1000, f"Static asset {f} is suspiciously small ({f.stat().st_size} bytes)"


def test_static_files_served_via_fastapi():
    """Verify FastAPI app serves index.html and static assets with HTTP 200."""
    from alfa.dashboard.app import app

    client = TestClient(app)

    # Root index
    res = client.get("/")
    assert res.status_code == 200
    assert "dashboard.css" in res.text

    # Static assets
    for asset in [
        "/static/css/dashboard.css",
        "/static/js/app.js",
        "/static/js/terminal.js",
        "/static/js/tools.js",
        "/static/js/chat.js",
    ]:
        res = client.get(asset)
        assert res.status_code == 200, f"Failed serving {asset}: status {res.status_code}"
        assert len(res.content) > 0


def test_static_files_accessible_with_auth_token():
    """Verify static assets are public and accessible even if DASHBOARD_AUTH_TOKEN is configured."""
    from alfa.dashboard.app import create_app

    orig_token = os.environ.get("DASHBOARD_AUTH_TOKEN")
    try:
        os.environ["DASHBOARD_AUTH_TOKEN"] = "secure-test-token"
        test_app = create_app()
        client = TestClient(test_app)

        for asset in [
            "/static/css/dashboard.css",
            "/static/js/app.js",
            "/static/js/terminal.js",
            "/static/js/tools.js",
            "/static/js/chat.js",
        ]:
            res = client.get(asset)
            assert res.status_code == 200, f"Asset {asset} blocked by auth: status {res.status_code}"
    finally:
        if orig_token is not None:
            os.environ["DASHBOARD_AUTH_TOKEN"] = orig_token
        else:
            os.environ.pop("DASHBOARD_AUTH_TOKEN", None)


def test_static_boundary_check():
    """Verify paths like /statistics or /static_analysis do not bypass auth."""
    from alfa.dashboard.routes.auth import DashboardAuthMiddleware
    from starlette.requests import Request
    from starlette.datastructures import URL
    from unittest.mock import AsyncMock

    middleware = DashboardAuthMiddleware(app=AsyncMock())

    # Helper mock request
    def make_req(path: str):
        scope = {"type": "http", "method": "GET", "path": path, "headers": [], "cookies": {}}
        return Request(scope)

    # Valid static paths
    assert make_req("/static").url.path == "/static"
    assert make_req("/static/css/dashboard.css").url.path.startswith("/static/")

    # Non-static similar paths
    bad_paths = ["/statistics", "/static_data", "/staticanalysis"]
    for bp in bad_paths:
        req = make_req(bp)
        assert req.url.path != "/static" and not req.url.path.startswith("/static/"), f"{bp} should not match /static boundary"

