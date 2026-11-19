"""Regression tests for Phase 4 quality & compliance (retensi, SBOM, a11y)."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "phase4_quality.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as conn

    conn.init_db_sync()
    return db_file


def _load_sbom_module():
    path = ROOT / "scripts" / "generate_sbom.py"
    spec = importlib.util.spec_from_file_location("alfa_generate_sbom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_retention_prunes_only_old_rows(isolated_db):
    from alfa.core import database as db
    from alfa.dashboard.routes.auth import prune_dashboard_sessions_sync

    now = datetime.now()
    old = (now - timedelta(days=50)).strftime("%Y-%m-%d %H:%M:%S")
    expired = (now - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    recent = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    future = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    conn = db.get_connection_pool().acquire()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                is_valid INTEGER DEFAULT 1
            )
            """
        )
        conn.execute("DELETE FROM dashboard_sessions")
        rows = [
            (1, "old-invalid", old, expired, 0),
            (1, "old-expired", old, expired, 1),
            (1, "recent-valid", recent, future, 1),
            (1, "recent-invalid", recent, future, 0),
        ]
        conn.executemany(
            """
            INSERT INTO dashboard_sessions
                (user_id, token_hash, created_at, expires_at, is_valid)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        db.get_connection_pool().release(conn)

    removed = prune_dashboard_sessions_sync(30)
    assert removed == 2

    conn = db.get_connection_pool().acquire()
    try:
        remaining = {
            row[0]
            for row in conn.execute(
                "SELECT token_hash FROM dashboard_sessions"
            ).fetchall()
        }
    finally:
        db.get_connection_pool().release(conn)
    assert remaining == {"recent-valid", "recent-invalid"}


def test_session_retention_zero_disables_pruning(isolated_db):
    from alfa.dashboard.routes.auth import prune_dashboard_sessions_sync

    assert prune_dashboard_sessions_sync(0) == 0


def test_sbom_parses_lockfile_and_normalizes_purl(tmp_path):
    module = _load_sbom_module()
    lockfile = tmp_path / "requirements-lock.txt"
    lockfile.write_text(
        "# komentar\n"
        "aiofiles==25.1.0\n"
        "Authlib==1.7.2  # hash diabaikan\n"
        "python-dotenv==1.2.1\n"
        "--extra-index-url https://example.invalid/simple\n",
        encoding="utf-8",
    )

    components = module.parse_requirements(lockfile)
    by_name = {item["name"]: item for item in components}

    assert [item["name"] for item in components] == [
        "aiofiles",
        "Authlib",
        "python-dotenv",
    ]
    assert by_name["Authlib"]["version"] == "1.7.2"
    assert by_name["Authlib"]["purl"] == "pkg:pypi/authlib@1.7.2"
    assert by_name["python-dotenv"]["purl"] == "pkg:pypi/python-dotenv@1.2.1"


def test_sbom_document_is_cyclonedx_1_5(tmp_path):
    module = _load_sbom_module()
    lockfile = tmp_path / "requirements-lock.txt"
    lockfile.write_text("requests==2.32.5\n", encoding="utf-8")

    document = module.build_sbom(module.parse_requirements(lockfile), "9.9.9")

    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    assert document["metadata"]["component"]["version"] == "9.9.9"
    assert document["components"][0]["name"] == "requests"


def test_dashboard_version_matches_package_version():
    import alfa
    from alfa.dashboard.app import app

    assert app.version == alfa.__version__


def test_dashboard_health_reports_package_version():
    from fastapi.testclient import TestClient

    from alfa import __version__
    from alfa.dashboard import app as pkg_app

    response = TestClient(pkg_app).get("/healthz")
    assert response.status_code == 200
    assert response.json()["version"] == __version__


def test_dashboard_accessibility_hooks_present():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "dashboard.css").read_text(encoding="utf-8")

    assert 'class="skip-link"' in html
    assert 'id="main-content"' in html
    assert 'aria-live="polite"' in html
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css


def test_compose_bot_uses_real_module_entrypoint():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'command: ["python3", "-m", "alfa.bot.telegram_bot"]' in compose
    assert 'command: ["python3", "bot.py"]' not in compose


def test_dockerfile_default_command_targets_existing_module():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["python3", "-m", "alfa.dashboard.app"]' in dockerfile
    assert "web_dashboard.py" not in dockerfile
