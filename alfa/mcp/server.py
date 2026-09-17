"""
ALFA Sovereign MCP (Model Context Protocol) Server.
Allows external AI clients (Claude Desktop, Cursor, Antigravity, etc.) to discover and call ALFA's 120+ sovereign tools over standard I/O (stdio).
"""

import asyncio
import inspect
import json
import logging
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger("alfa.mcp")

# Ensure tools are loaded
import alfa.tools
from alfa.tools.registry import TOOL_REGISTRY, get_tool

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types
except ImportError:
    Server = None
    stdio_server = None
    types = None


def create_mcp_server(server_name: str = "alfa-sovereign-ai") -> Any:
    """Create and configure the official ALFA MCP Server instance."""
    if Server is None:
        raise RuntimeError(
            "The 'mcp' package is required to run the ALFA MCP Server. "
            "Please install it using: pip install mcp"
        )

    server = Server(server_name)

    @server.list_tools()
    async def handle_list_tools() -> List[types.Tool]:
        """List all available tools registered in ALFA TOOL_REGISTRY."""
        tools_list: List[types.Tool] = []
        for name, info in TOOL_REGISTRY.items():
            schema = info.get("schema", {})
            openai_fn = schema.get("openai_spec", {}).get("function", {})
            desc = openai_fn.get("description", info.get("description", name))
            params = openai_fn.get(
                "parameters",
                {"type": "object", "properties": {}, "required": []},
            )
            # Ensure proper schema structure
            if not isinstance(params, dict):
                params = {"type": "object", "properties": {}}
            if "type" not in params:
                params["type"] = "object"
            if "properties" not in params:
                params["properties"] = {}

            tools_list.append(
                types.Tool(
                    name=name,
                    description=desc[:1024] if desc else f"ALFA tool: {name}",
                    inputSchema=params,
                )
            )
        return tools_list

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> List[types.TextContent]:
        """Execute a requested tool and return the output formatted as TextContent."""
        fn = get_tool(name)
        if not fn:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {"status": "error", "message": f"Tool '{name}' not found in ALFA registry."},
                        ensure_ascii=False,
                    ),
                )
            ]

        args = arguments or {}
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                # Run sync functions in threadpool to avoid blocking async event loop
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: fn(**args))

            if isinstance(result, (dict, list)):
                out_str = json.dumps(result, ensure_ascii=False, indent=2)
            else:
                out_str = str(result)

            return [types.TextContent(type="text", text=out_str)]
        except Exception as err:
            logger.exception(f"Error executing tool '{name}': {err}")
            err_payload = {
                "status": "error",
                "tool": name,
                "error_type": type(err).__name__,
                "message": str(err),
            }
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(err_payload, ensure_ascii=False, indent=2),
                )
            ]

    return server


async def run_stdio_server(server_name: str = "alfa-sovereign-ai"):
    """Run the MCP server over standard input and output streams."""
    server = create_mcp_server(server_name)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


def main():
    """CLI entrypoint for running the ALFA MCP Server."""
    import argparse

    parser = argparse.ArgumentParser(description="ALFA Sovereign AI - MCP Server")
    parser.add_argument(
        "--name",
        default="alfa-sovereign-ai",
        help="Name of the MCP server (default: alfa-sovereign-ai)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_stdio_server(args.name))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
