"""
ALFA Sovereign MCP (Model Context Protocol) Server.
Allows external AI clients (Claude Desktop, Cursor, Antigravity, etc.) to discover and call ALFA's 120+ sovereign tools over standard I/O (stdio).
"""

import asyncio
import inspect
import json
import logging
import os
from typing import Any

# Ensure tools are loaded
from alfa.tools.registry import TOOL_REGISTRY, get_tool

logger = logging.getLogger("alfa.mcp")

try:
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.lowlevel.helper_types import ReadResourceContents
    from mcp.server.stdio import stdio_server
except ImportError:
    Server = None
    stdio_server = None
    types = None
    ReadResourceContents = None


def create_mcp_server(server_name: str = "alfa-sovereign-ai") -> Any:
    """Create and configure the official ALFA MCP Server instance."""
    if Server is None:
        raise RuntimeError(
            "The 'mcp' package is required to run the ALFA MCP Server. "
            "Please install it using: pip install mcp"
        )

    server = Server(server_name)

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List all available tools registered in ALFA TOOL_REGISTRY."""
        tools_list: list[types.Tool] = []
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
        name: str, arguments: dict[str, Any] | None = None
    ) -> list[types.TextContent]:
        """Execute a requested tool and return the output formatted as TextContent."""
        fn = get_tool(name)
        if not fn:
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "error",
                            "message": f"Tool '{name}' not found in ALFA registry.",
                        },
                        ensure_ascii=False,
                    ),
                )
            ]

        args = arguments or {}
        try:
            from alfa.core.perm import gate as _perm_gate

            mcp_uid = int(os.getenv("ALFA_MCP_USER_ID", "0") or 0)
            denial = _perm_gate.check_headless_approval(
                mcp_uid, name, json.dumps(args, ensure_ascii=False, default=str)
            )
            if denial:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"status": "error", "message": denial},
                            ensure_ascii=False,
                        ),
                    )
                ]
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

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        """Expose ringkasan berkas-maklumat MCP (status & katalog tools)."""
        return [
            types.Resource(
                uri=types.AnyUrl("alfa://status"),
                name="ALFA status",
                description="Jumlah tools & identitas server ALFA",
                mimeType="application/json",
            ),
            types.Resource(
                uri=types.AnyUrl("alfa://tools/catalog"),
                name="Tool catalog",
                description="Daftar nama + deskripsi seluruh tools ALFA",
                mimeType="application/json",
            ),
        ]

    @server.read_resource()
    async def handle_read_resource(uri: Any) -> list[types.ReadResourceContents]:
        """Baca isi resource MCP ALFA (JSON). URI tak dikenal → KeyError dgn pesan."""
        text_uri = str(uri)
        if text_uri == "alfa://status":
            payload = {
                "server": server.name,
                "tools": len(TOOL_REGISTRY),
                "protocol": "mcp",
            }
        elif text_uri == "alfa://tools/catalog":
            payload = {
                tool: str(info.get("description", tool))[:200]
                for tool, info in TOOL_REGISTRY.items()
            }
        else:
            msg = (
                f"Resource {text_uri} tidak dikenal; gunakan "
                "alfa://status atau alfa://tools/catalog"
            )
            raise KeyError(msg)
        return [
            ReadResourceContents(
                content=json.dumps(payload, ensure_ascii=False, indent=2),
                mime_type="application/json",
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
