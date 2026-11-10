"""
ALFA Model Context Protocol (MCP) Server.
Exposes ALFA's sovereign tool catalog to any MCP-compliant client (Cursor, Claude Desktop, Antigravity, etc.).

Import bersifat LAZY: paket ``alfa.mcp`` tidak menarik ``starlette``/``uvicorn``
saat diimpor. Tanpa ini, mode stdio (``python -m alfa.mcp.server``) ikut gagal
start di mesin yang tidak memasang dependensi web — padahal stdio tak butuh
sama sekali.
"""

from typing import Any

__all__ = [
    "create_mcp_server",
    "create_streamable_http_app",
    "run_http_server",
    "run_stdio_server",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "create_mcp_server": ("alfa.mcp.server", "create_mcp_server"),
    "run_stdio_server": ("alfa.mcp.server", "run_stdio_server"),
    "create_streamable_http_app": ("alfa.mcp.http_server", "create_streamable_http_app"),
    "run_http_server": ("alfa.mcp.http_server", "run_http_server"),
}


def __getattr__(name: str) -> Any:
    """Impor sesuai kebutuhan (PEP 562) — ``alfa.mcp`` tetap ringan."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(target[0])
    value = getattr(module, target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
