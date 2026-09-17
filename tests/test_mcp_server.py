"""
Unit tests for ALFA Model Context Protocol (MCP) Server.
Verifies MCP server initialization, tool exposure, schema integrity, and execution.
"""

import pytest

try:
    from mcp.server import Server
    import mcp.types as types
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from alfa.mcp.server import create_mcp_server


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
class TestAlfaMCPServer:
    """Test suite for ALFA MCP Server."""

    def test_create_mcp_server(self):
        """Verify MCP server instance creation."""
        server = create_mcp_server("test-alfa-mcp")
        assert server is not None
        assert server.name == "test-alfa-mcp"
        assert types.ListToolsRequest in server.request_handlers
        assert types.CallToolRequest in server.request_handlers

    @pytest.mark.asyncio
    async def test_list_tools_returns_all_registered_tools(self):
        """Verify list_tools exposes all tools with valid JSON input schemas."""
        server = create_mcp_server("test-alfa-mcp")
        handler = server.request_handlers[types.ListToolsRequest]
        res = await handler(None)
        tools = res.root.tools
        assert len(tools) >= 100

        tool_names = {t.name for t in tools}
        assert "deep_research_topic" in tool_names
        assert "generate_secure_password" in tool_names
        assert "get_system_stats" in tool_names

        # Check inputSchema validity
        for t in tools:
            assert isinstance(t.inputSchema, dict)
            assert t.inputSchema.get("type") == "object"
            assert "properties" in t.inputSchema

    @pytest.mark.asyncio
    async def test_call_tool_executes_successfully(self):
        """Verify tool execution via MCP CallToolRequest."""
        server = create_mcp_server("test-alfa-mcp")
        call_handler = server.request_handlers[types.CallToolRequest]
        call_req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="generate_secure_password",
                arguments={"length": 12, "count": 1},
            ),
        )
        res = await call_handler(call_req)
        assert len(res.root.content) == 1
        text = res.root.content[0].text
        assert "success" in text

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool_returns_error(self):
        """Verify calling an unknown tool returns an error payload gracefully."""
        server = create_mcp_server("test-alfa-mcp")
        call_handler = server.request_handlers[types.CallToolRequest]
        call_req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="nonexistent_tool_xyz_123",
                arguments={},
            ),
        )
        res = await call_handler(call_req)
        text = res.root.content[0].text
        assert "error" in text
        assert "not found" in text
