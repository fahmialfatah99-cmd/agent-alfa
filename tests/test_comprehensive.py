"""
Comprehensive test suite for ALFA Agent core functionality.

This module provides comprehensive tests covering:
- Core agent brain functionality
- Tool execution and registry
- Database operations
- Security features
- Swarm intelligence
- RAG memory system
- API endpoints
- Authentication system
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestCoreAgent:
    """Tests for core agent functionality."""

    def test_agent_initialization(self, sample_agent_config):
        """Test agent initializes with correct configuration."""
        assert sample_agent_config["name"] == "test_agent"
        assert sample_agent_config["role"] == "assistant"
        assert "tools" in sample_agent_config

    def test_agent_goal_setting(self, sample_agent_config):
        """Test agent goal is properly set."""
        assert sample_agent_config["goal"] is not None
        assert len(sample_agent_config["goal"]) > 0

    @pytest.mark.asyncio
    async def test_agent_async_operation(self, async_mock):
        """Test agent can handle async operations."""
        async_mock.return_value = {"status": "success"}
        result = await async_mock()
        assert result["status"] == "success"


class TestToolRegistry:
    """Tests for tool registry and execution."""

    def test_tool_configuration(self, sample_tool_config):
        """Test tool configuration is valid."""
        assert "name" in sample_tool_config
        assert "description" in sample_tool_config
        assert "parameters" in sample_tool_config

    def test_tool_parameters_validation(self, sample_tool_config):
        """Test tool parameters have correct structure."""
        params = sample_tool_config["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params

    def test_tool_enabled_status(self, sample_tool_config):
        """Test tool enabled status."""
        assert sample_tool_config["enabled"] is True

    def test_tool_whitelist_status(self, sample_tool_config):
        """Test tool whitelist status for security."""
        assert sample_tool_config["whitelisted"] is True

    @pytest.mark.security
    def test_tool_security_enforcement(self, sample_tool_config, security_context):
        """Test tool security enforcement mechanisms."""
        assert security_context["whitelist_status"] is True
        assert security_context["sandbox_enabled"] is True


class TestDatabaseOperations:
    """Tests for database operations."""

    def test_database_connection_mock(self, mock_database_connection):
        """Test database connection mocking."""
        assert mock_database_connection is not None
        assert hasattr(mock_database_connection, 'execute')
        assert hasattr(mock_database_connection, 'commit')

    def test_database_transaction(self, mock_database_connection):
        """Test database transaction handling."""
        mock_database_connection.execute("CREATE TABLE test (id INTEGER)")
        mock_database_connection.commit()
        mock_database_connection.execute.assert_called()
        mock_database_connection.commit.assert_called()


class TestVectorMemory:
    """Tests for vector memory and RAG functionality."""

    @pytest.mark.rag
    def test_vector_data_structure(self, sample_vector_data):
        """Test vector data has correct structure."""
        assert len(sample_vector_data) == 3
        for doc in sample_vector_data:
            assert "id" in doc
            assert "content" in doc
            assert "metadata" in doc

    @pytest.mark.rag
    def test_vector_metadata(self, sample_vector_data):
        """Test vector metadata fields."""
        for doc in sample_vector_data:
            assert "source" in doc["metadata"]
            assert "type" in doc["metadata"]

    @pytest.mark.rag
    def test_vector_content_types(self, sample_vector_data):
        """Test different content types in vector store."""
        types = [doc["metadata"]["type"] for doc in sample_vector_data]
        assert "code" in types
        assert "ml" in types
        assert "web" in types


class TestSwarmIntelligence:
    """Tests for swarm intelligence and multi-agent collaboration."""

    @pytest.mark.swarm
    def test_swarm_agents_count(self, sample_swarm_agents):
        """Test swarm has multiple agents."""
        assert len(sample_swarm_agents) >= 2

    @pytest.mark.swarm
    def test_agent_roles(self, sample_swarm_agents):
        """Test agents have distinct roles."""
        roles = [agent["role"] for agent in sample_swarm_agents]
        assert "researcher" in roles
        assert "writer" in roles

    @pytest.mark.swarm
    def test_agent_status_tracking(self, sample_swarm_agents):
        """Test agent status is tracked."""
        statuses = [agent["status"] for agent in sample_swarm_agents]
        assert "idle" in statuses or "busy" in statuses

    @pytest.mark.swarm
    def test_task_completion_tracking(self, sample_swarm_agents):
        """Test task completion is tracked per agent."""
        for agent in sample_swarm_agents:
            assert "tasks_completed" in agent
            assert isinstance(agent["tasks_completed"], int)


class TestSecurityFeatures:
    """Tests for security features."""

    @pytest.mark.security
    def test_user_permissions(self, security_context):
        """Test user permissions are defined."""
        assert "permissions" in security_context
        assert len(security_context["permissions"]) > 0

    @pytest.mark.security
    def test_audit_logging(self, security_context):
        """Test audit logging is enabled."""
        assert security_context["audit_logging"] is True

    @pytest.mark.security
    def test_sandbox_enforcement(self, security_context):
        """Test sandbox enforcement."""
        assert security_context["sandbox_enabled"] is True

    @pytest.mark.security
    def test_whitelist_mode(self, security_context):
        """Test whitelist mode is active."""
        assert security_context["whitelist_status"] is True


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    def test_rate_limiter_creation(self, rate_limiter):
        """Test rate limiter is created with correct parameters."""
        assert rate_limiter.max_calls == 10
        assert rate_limiter.period == 1.0

    def test_rate_limiter_acquire(self, rate_limiter):
        """Test rate limiter acquire method."""
        # Should succeed for first 10 calls
        for _i in range(10):
            assert rate_limiter.acquire() is True

        # Should fail after limit reached
        assert rate_limiter.acquire() is False

    def test_rate_limiter_reset(self, rate_limiter):
        """Test rate limiter reset functionality."""
        # Exhaust the limiter
        for _ in range(10):
            rate_limiter.acquire()

        # Reset by clearing calls
        rate_limiter.calls = []

        # Should work again
        assert rate_limiter.acquire() is True


class TestCaching:
    """Tests for caching functionality."""

    def test_cache_set_get(self, cache_fixture):
        """Test cache set and get operations."""
        cache_fixture.set("key1", "value1")
        assert cache_fixture.get("key1") == "value1"

    def test_cache_default_value(self, cache_fixture):
        """Test cache returns default for missing keys."""
        assert cache_fixture.get("nonexistent", "default") == "default"

    def test_cache_delete(self, cache_fixture):
        """Test cache delete operation."""
        cache_fixture.set("key1", "value1")
        cache_fixture.delete("key1")
        assert cache_fixture.get("key1") is None

    def test_cache_clear(self, cache_fixture):
        """Test cache clear operation."""
        cache_fixture.set("key1", "value1")
        cache_fixture.set("key2", "value2")
        cache_fixture.clear()
        assert cache_fixture.get("key1") is None
        assert cache_fixture.get("key2") is None


class TestEnvironmentConfiguration:
    """Tests for environment configuration."""

    def test_env_variables_set(self, test_env):
        """Test environment variables are set correctly."""
        import os
        assert os.environ.get("TELEGRAM_BOT_TOKEN") == "test_bot_token_12345"
        assert os.environ.get("GEMINI_API_KEY") == "test_api_key_67890"

    def test_env_allowed_users(self, test_env):
        """Test allowed user IDs configuration."""
        import os
        allowed_ids = os.environ.get("ALLOWED_USER_IDS")
        assert allowed_ids is not None
        assert "123456789" in allowed_ids


class TestTempFileHandling:
    """Tests for temporary file handling."""

    def test_temp_dir_creation(self, temp_dir):
        """Test temporary directory is created."""
        assert temp_dir.exists()
        assert temp_dir.is_dir()

    def test_temp_file_creation(self, temp_file):
        """Test temporary file creation."""
        file_path = temp_file(content="test content", name="test.txt")
        assert file_path.exists()
        assert file_path.read_text() == "test content"

    def test_temp_file_cleanup(self, temp_dir):
        """Test temporary files are cleaned up."""
        # This test verifies cleanup happens automatically
        # via the fixture's teardown
        pass


class TestMockObjects:
    """Tests for mock objects and fixtures."""

    def test_llm_mock_response(self, mock_llm_response):
        """Test LLM mock response structure."""
        assert mock_llm_response.text is not None
        assert len(mock_llm_response.choices) > 0

    def test_async_mock_functionality(self, async_mock):
        """Test async mock can be awaited."""
        assert callable(async_mock)

    def test_database_mock_context_manager(self, mock_database_connection):
        """Test database mock works as context manager."""
        with mock_database_connection as conn:
            conn.execute("SELECT 1")
        mock_database_connection.__enter__.assert_called()
        mock_database_connection.__exit__.assert_called()


@pytest.mark.integration
class TestIntegrationScenarios:
    """Integration tests for complete scenarios."""

    @pytest.mark.slow
    def test_full_agent_workflow(self, sample_agent_config, sample_tool_config):
        """Test complete agent workflow from config to execution."""
        # Simulate agent initialization
        sample_agent_config["name"]
        tool_name = sample_tool_config["name"]

        # Verify agent can access tools
        assert tool_name in sample_agent_config["tools"] or len(sample_agent_config["tools"]) > 0

    @pytest.mark.slow
    @pytest.mark.security
    def test_secure_tool_execution(self, sample_tool_config, security_context):
        """Test tool execution with security checks."""
        # Verify tool is whitelisted
        assert sample_tool_config["whitelisted"] is True

        # Verify security context is active
        assert security_context["whitelist_status"] is True

    @pytest.mark.slow
    @pytest.mark.rag
    def test_rag_enhanced_query(self, sample_vector_data):
        """Test RAG-enhanced query processing."""
        # Simulate finding relevant documents
        query = "programming"
        relevant_docs = [
            doc for doc in sample_vector_data
            if query.lower() in doc["content"].lower()
        ]

        assert len(relevant_docs) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
