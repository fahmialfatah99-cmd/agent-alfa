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

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def test_env():
    """Set up test environment variables."""
    original_env = os.environ.copy()

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
        os.environ[key] = value

    yield test_vars

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


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
            "properties": {
                "input": {"type": "string", "description": "Test input"}
            },
            "required": ["input"]
        },
        "enabled": True,
        "whitelisted": True
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
        "allow_delegation": False
    }


@pytest.fixture
def sample_vector_data():
    """Sample vector data for RAG testing."""
    return [
        {
            "id": "doc_1",
            "content": "Python is a programming language.",
            "metadata": {"source": "test", "type": "code"}
        },
        {
            "id": "doc_2",
            "content": "Machine learning is a subset of AI.",
            "metadata": {"source": "test", "type": "ml"}
        },
        {
            "id": "doc_3",
            "content": "FastAPI is a modern web framework.",
            "metadata": {"source": "test", "type": "web"}
        }
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
        {
            "id": "agent_1",
            "role": "researcher",
            "status": "idle",
            "tasks_completed": 0
        },
        {
            "id": "agent_2",
            "role": "writer",
            "status": "busy",
            "tasks_completed": 5
        },
        {
            "id": "agent_3",
            "role": "reviewer",
            "status": "idle",
            "tasks_completed": 3
        }
    ]


@pytest.fixture
def security_context():
    """Security context for testing permission gates."""
    return {
        "user_id": "123456789",
        "permissions": ["read", "write", "execute"],
        "whitelist_status": True,
        "sandbox_enabled": True,
        "audit_logging": True
    }


# Custom markers
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers",
        "security: marks tests related to security features"
    )
    config.addinivalue_line(
        "markers",
        "rag: marks tests related to RAG functionality"
    )
    config.addinivalue_line(
        "markers",
        "swarm: marks tests related to swarm intelligence"
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
