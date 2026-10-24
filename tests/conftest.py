"""
Pytest configuration and fixtures for ALFA Agent test suite.

This module provides shared fixtures, markers, and configuration
for all tests in the ALFA Agent project.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Hermetic tests: never inherit developer-local secrets from shell or `.env`
# (`load_dotenv()` runs at import time in alfa.dashboard.*). In particular an
# operator-set DASHBOARD_AUTH_TOKEN would switch the dashboard to auth mode and
# break unauthenticated TestClient calls, while CI (no .env) stays green.
os.environ["DASHBOARD_AUTH_TOKEN"] = ""
# Dashboard API sekarang fail-CLOSED: tanpa DASHBOARD_AUTH_TOKEN, /api/* wajib
# login (tidak lagi terbuka untuk semua orang). Test suite dashboard memakai
# TestClient (host "testclient") yang diperlakukan sebagai klien lokal, jadi
# mode development lokal eksplisit diaktifkan agar endpoint tetap bisa diuji.
# Perilaku fail-closed-nya sendiri diuji terpisah di test_security_hardening.
os.environ["ALFA_INSECURE_LOCAL"] = "true"
# Operator-local ALFA_UNRESTRICTED=true would disable every safety guard the
# security tests assert on; force the safe default for the test session.
os.environ["ALFA_UNRESTRICTED"] = "false"
# Test suite verifies strict per-tier trust calculation by default unless overridden
os.environ["PERMISSION_GATE_DANGEROUS_ONLY"] = "false"
# Same hermetic reason: an operator .env with DASHBOARD_HOST=0.0.0.0 would fire
# the fatal boot guard (_check_security_config) at import time of
# alfa.dashboard.* because token above is forced empty in tests. Force the
# localhost default; tests exercising the guard set their own env per-test.
os.environ["DASHBOARD_HOST"] = "127.0.0.1"

# ---------------------------------------------------------------------------
# PROTEKSI DATA PRODUKSI (insiden 2026-10-23):
# Test `wa_clear_history(target="all")` pernah berjalan terhadap agent_data.db
# produksi dan API wa-sheets-bot live, sehingga arsip WA asli terhapus.
# Dua lapis pengaman berikut membuat test suite TIDAK MUNGKIN menyentuh data asli:
#   1. Setiap sqlite3.connect() ke file DB produksi dialihkan ke DB test sementara
#      (precedence ALFA_DB_PATH / DATABASE_URL / patch DB_PATH milik test tetap utuh).
#   2. WA_BOT_URL diarahkan ke port mati + urlopen ke port wa-sheets-bot diblokir.
# ---------------------------------------------------------------------------
import sqlite3 as _sqlite3  # noqa: E402
import urllib.request as _urllib_request  # noqa: E402

_TEST_DB_DIR = tempfile.mkdtemp(prefix="alfa_testdb_")
_TEST_DB_PATH = os.path.join(_TEST_DB_DIR, "agent_data_test.db")
_PROTECTED_DB_PATHS = {
    os.path.realpath(p)
    for p in (
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_data.db"),
        os.path.expanduser("~/.alfa/alfa.db"),
        os.path.expanduser("~/telegram-ai-bot/agent_data.db"),
    )
}
_real_sqlite_connect = _sqlite3.connect


def _guarded_sqlite_connect(database, *args, **kwargs):
    try:
        raw = os.fspath(database)
    except TypeError:
        raw = None
    if isinstance(raw, str) and raw and raw != ":memory:" and not raw.startswith("file:"):
        if os.path.realpath(raw) in _PROTECTED_DB_PATHS:
            database = _TEST_DB_PATH
    return _real_sqlite_connect(database, *args, **kwargs)


_sqlite3.connect = _guarded_sqlite_connect

# Lindungi recent_incoming.json produksi dari direct file write di tests
_TEST_INCOMING_FILE = os.path.join(_TEST_DB_DIR, "recent_incoming_test.json")
with open(_TEST_INCOMING_FILE, "w", encoding="utf-8") as _f:
    _f.write("[]")
os.environ["WA_BOT_INCOMING_FILE"] = _TEST_INCOMING_FILE

os.environ["WA_BOT_URL"] = "http://127.0.0.1:9"  # discard port: selalu gagal konek
_PROTECTED_WA_PORTS = (":3000",)
_real_urlopen = _urllib_request.urlopen


def _guarded_urlopen(req, *args, **kwargs):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if any(f"127.0.0.1{p}" in url or f"localhost{p}" in url for p in _PROTECTED_WA_PORTS):
        raise ConnectionRefusedError(f"[test-guard] akses ke wa-sheets-bot live diblokir: {url}")
    return _real_urlopen(req, *args, **kwargs)


_urllib_request.urlopen = _guarded_urlopen

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Auto-detect local venv site-packages so running pytest directly outside venv still resolves dependencies
venv_sp = list(project_root.glob("venv/lib/python*/site-packages"))
if venv_sp and str(venv_sp[0]) not in sys.path:
    sys.path.insert(1, str(venv_sp[0]))


@pytest.fixture
def test_env(monkeypatch):
    """Set up test environment variables (function-scoped, auto-restored).

    NOTE: must NOT be session-scoped — leaked DATABASE_URL would silently
    redirect every DB layer to ./test_alfa.db for the rest of the session.
    """
    test_vars = {
        "TELEGRAM_BOT_TOKEN": "test_bot_token_12345",
        "GEMINI_API_KEY": "test_api_key_67890",
        "ALLOWED_USER_IDS": "123456789,987654321",
        "OWNER_NAME": "Test Owner",
        "DATABASE_URL": "sqlite:///./test_alfa.db",
        "ENCRYPTION_KEY": "test_encryption_key_32chars!!",
        "WHITELIST_MODE": "true",
        "SANDBOX_ENABLED": "true",
    }

    for key, value in test_vars.items():
        monkeypatch.setenv(key, value)

    yield test_vars


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    tmpdir = tempfile.mkdtemp(prefix="alfa_test_")
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def temp_file(temp_dir):
    """Create a temporary file with optional content."""

    def _create_file(content="", name="test_file.txt"):
        file_path = temp_dir / name
        file_path.write_text(content)
        return file_path

    return _create_file


@pytest.fixture
def mock_llm_response():
    """Mock LLM response object."""
    mock = MagicMock()
    mock.text = "This is a mock LLM response."
    mock.choices = [MagicMock(message=MagicMock(content="Mock response content"))]
    return mock


@pytest.fixture
def async_mock():
    """Create an async mock for testing."""
    return AsyncMock()


@pytest.fixture
def sample_tool_config():
    """Sample tool configuration for testing."""
    return {
        "name": "test_tool",
        "description": "A test tool for unit testing",
        "parameters": {
            "type": "object",
            "properties": {"input": {"type": "string", "description": "Test input"}},
            "required": ["input"],
        },
        "enabled": True,
        "whitelisted": True,
    }


@pytest.fixture
def sample_agent_config():
    """Sample agent configuration for testing."""
    return {
        "name": "test_agent",
        "role": "assistant",
        "goal": "Test agent for unit testing",
        "backstory": "A test agent created for testing purposes",
        "tools": ["test_tool"],
        "verbose": False,
        "allow_delegation": False,
    }


@pytest.fixture
def sample_vector_data():
    """Sample vector data for RAG testing."""
    return [
        {
            "id": "doc_1",
            "content": "Python is a programming language.",
            "metadata": {"source": "test", "type": "code"},
        },
        {
            "id": "doc_2",
            "content": "Machine learning is a subset of AI.",
            "metadata": {"source": "test", "type": "ml"},
        },
        {
            "id": "doc_3",
            "content": "FastAPI is a modern web framework.",
            "metadata": {"source": "test", "type": "web"},
        },
    ]


@pytest.fixture
def mock_database_connection():
    """Mock database connection for testing."""
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock()
    mock_conn.commit = MagicMock()
    mock_conn.close = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


@pytest.fixture
def sample_swarm_agents():
    """Sample swarm agents configuration."""
    return [
        {"id": "agent_1", "role": "researcher", "status": "idle", "tasks_completed": 0},
        {"id": "agent_2", "role": "writer", "status": "busy", "tasks_completed": 5},
        {"id": "agent_3", "role": "reviewer", "status": "idle", "tasks_completed": 3},
    ]


@pytest.fixture
def security_context():
    """Security context for testing permission gates."""
    return {
        "user_id": "123456789",
        "permissions": ["read", "write", "execute"],
        "whitelist_status": True,
        "sandbox_enabled": True,
        "audit_logging": True,
    }


# Custom markers
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line(
        "markers", "security: marks tests related to security features"
    )
    config.addinivalue_line("markers", "rag: marks tests related to RAG functionality")
    config.addinivalue_line(
        "markers", "swarm: marks tests related to swarm intelligence"
    )


@pytest.fixture
def rate_limiter():
    """Rate limiter fixture for API testing."""

    class RateLimiter:
        def __init__(self, max_calls=10, period=1.0):
            self.max_calls = max_calls
            self.period = period
            self.calls = []

        def acquire(self):
            if len(self.calls) >= self.max_calls:
                return False
            self.calls.append(True)
            return True

    return RateLimiter()


@pytest.fixture
def cache_fixture():
    """Simple cache fixture for testing."""
    cache = {}

    class Cache:
        def get(self, key, default=None):
            return cache.get(key, default)

        def set(self, key, value, ttl=None):
            cache[key] = value

        def delete(self, key):
            cache.pop(key, None)

        def clear(self):
            cache.clear()

    return Cache()


@pytest.fixture(autouse=True)
def _ensure_single_telegram_mode():
    yield
    try:
        from alfa.bot.mode_commands import set_telegram_mode_sync
        set_telegram_mode_sync("single")
    except Exception:
        pass

