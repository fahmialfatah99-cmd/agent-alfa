"""Transport HTTP streamable untuk ALFA MCP Server — selain stdio.

Stdio hanya nyaman untuk klien desktop lokal (Claude Desktop, Cursor).
Dengan streamable HTTP, klien remote (worker swarm, Antigravity, integrasi
pihak ketiga) dapat memakai server MCP ALFA melalui jaringan dengan token.

Keamanan fail-closed:
- Token WAJIB: ``ALFA_MCP_HTTP_TOKEN`` (atau argumen ``token``). Server
  menolak start tanpa token — pola sama dengan boot guard dashboard.
- Auth dicek SEBELUM request menyentuh transport MCP; tools tidak pernah
  dieksekusi tanpa token valid (bandingkan konstanta-waktu via hmac).
- DNS rebinding protection AKTIF: Host header dipelintir dengan daftar
  izin (default localhost/127.0.0.1 dgn port apa saja). Ekspansi lewat
  ``ALFA_MCP_HTTP_HOSTS`` (contoh: ``"bot.example.com:*,10.0.0.5:*"``).
- RBAC tools tetap diproses perm-gate di handler ``call_tool`` (server.py).

Pemakaian:

    ALFA_MCP_HTTP_TOKEN=<token> python -m alfa.mcp.http_server --port 8902
"""

from __future__ import annotations

import hmac
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.routing import Route as _Route  # noqa: F401 — dokumentasi tipe

from alfa.mcp.server import create_mcp_server

logger = logging.getLogger("alfa.mcp.http")


def _resolve_token(token: str | None) -> str:
    """Token wajib; batal-kan start bila tidak ada (fail-closed)."""
    resolved = (token or os.getenv("ALFA_MCP_HTTP_TOKEN") or "").strip()
    if not resolved:
        msg = (
            "MCP HTTP butuh token: set env ALFA_MCP_HTTP_TOKEN atau argumen "
            "token=. Tanpa token server MENOLAK start (fail-closed) karena "
            "endpoint ini bisa mengeksekusi tools lokal."
        )
        raise RuntimeError(msg)
    return resolved


def _default_allowed_hosts() -> list[str]:
    raw = os.getenv("ALFA_MCP_HTTP_HOSTS", "").strip()
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    if not hosts:
        hosts = ["localhost:*", "127.0.0.1:*"]
    return hosts


def _build_manager(server: Any, allowed_hosts: list[str]) -> Any:
    """StreamableHTTPSessionManager + rebinding protection eksplisit."""
    from mcp.server.streamable_http import TransportSecuritySettings
    from mcp.server.streamable_http_manager import (
        StreamableHTTPSessionManager,
    )

    return StreamableHTTPSessionManager(
        server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        ),
    )


def create_streamable_http_app(
    server_name: str = "alfa-sovereign-ai",
    *,
    token: str | None = None,
    allowed_hosts: list[str] | None = None,
) -> Starlette:
    """ASGI app MCP-over-HTTP: guard token → transport streamable.

    ``allowed_hosts`` :) punggil eksplisit bila di-deploy di belakang domain
    lain (UJI: TestClient pakai Host "testserver" → lewat ``testserver`` bebas
    port di ``allowed_hosts``).
    """
    resolved = _resolve_token(token)
    server = create_mcp_server(server_name)
    manager = _build_manager(server, allowed_hosts or _default_allowed_hosts())

    @asynccontextmanager
    async def lifespan(_app) -> AsyncIterator[None]:
        async with manager.run():
            yield

    async def mcp_endpoint(scope, receive, send):
        if scope["type"] != "http":  # pragma: no cover — lifespan tak lewat sini
            await manager.handle_request(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers") or []
        }
        authorization = headers.get("authorization", "")
        supplied = authorization[7:] if authorization[:7].lower() == "bearer " else ""
        if not supplied:
            supplied = headers.get("x-mcp-token", "")
        if not hmac.compare_digest(supplied, resolved):
            logger.warning("MCP HTTP: token tidak valid ditolak")
            response = JSONResponse(
                {"error": "unauthorized", "detail": "Token MCP tidak valid"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer realm=alfa-mcp"},
            )
            await response(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)

    return Starlette(
        lifespan=lifespan,
        routes=[Mount("/", app=mcp_endpoint)],
    )


async def run_http_server(
    host: str = "127.0.0.1",
    port: int = 8902,
    server_name: str = "alfa-sovereign-ai",
    token: str | None = None,
    allowed_hosts: list[str] | None = None,
):
    """Serve MCP streamable HTTP via uvicorn (token wajib — fail-closed)."""
    app = create_streamable_http_app(
        server_name, token=token, allowed_hosts=allowed_hosts
    )
    logger.info("MCP HTTP listening di http://%s:%s (token diaktifkan)", host, port)
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover — uvicorn sudah dependency utama
        msg = "uvicorn wajib untuk run_http_server"
        raise RuntimeError(msg) from exc

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main():
    """CLI: python -m alfa.mcp.http_server [--host] [--port]."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="ALFA MCP HTTP transport")
    parser.add_argument("--host", default=os.getenv("MCP_HTTP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_HTTP_PORT", "8902") or 8902),
    )
    parser.add_argument("--name", default="alfa-sovereign-ai")
    parser.add_argument(
        "--token",
        default=os.getenv("ALFA_MCP_HTTP_TOKEN", ""),
        help="Token klien (default: env ALFA_MCP_HTTP_TOKEN)",
    )
    parser.add_argument(
        "--allow-hosts",
        default=os.getenv("ALFA_MCP_HTTP_HOSTS", ""),
        help="Daftar host:port yang diizinkan (koma)",
    )
    args = parser.parse_args()

    try:
        import uvicorn  # noqa: F401 — gagal cepat bila tidak ada

        asyncio.run(
            run_http_server(
                args.host,
                args.port,
                args.name,
                token=args.token,
                allowed_hosts=(
                    [h.strip() for h in args.allow_hosts.split(",") if h.strip()]
                    or None
                ),
            )
        )
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    sys.exit(main())
