"""
ALFA Model Context Protocol (MCP) Server.
Exposes ALFA's sovereign tool catalog to any MCP-compliant client (Cursor, Claude Desktop, Antigravity, etc.).
"""

from alfa.mcp.http_server import create_streamable_http_app, run_http_server
from alfa.mcp.server import create_mcp_server, run_stdio_server

__all__ = [
    "create_mcp_server",
    "create_streamable_http_app",
    "run_http_server",
    "run_stdio_server",
]
