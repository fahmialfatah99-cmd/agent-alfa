"""
ALFA Model Context Protocol (MCP) Server.
Exposes ALFA's sovereign tool catalog to any MCP-compliant client (Cursor, Claude Desktop, Antigravity, etc.).
"""

from alfa.mcp.server import create_mcp_server, run_stdio_server

__all__ = ["create_mcp_server", "run_stdio_server"]
