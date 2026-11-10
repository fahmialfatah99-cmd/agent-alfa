"""Transport HTTP streamable untuk ALFA MCP Server — selain stdio.

Stdio hanya nyaman untuk klien desktop lokal (Claude Desktop, Cursor).
Dengan streamable HTTP, klien remote (worker swarm, Antigravity, integrasi
pihak ketiga) dapat memakai server MCP ALFA melalui jaringan dengan token.

Keamanan fail-closed:
- Token WAJIB: ``ALFA_MCP_HTTP_TOKEN`` (atau argumen ``token``). Server
  menolak start tanpa token — pola sama dengan boot guard dashboard.
- Token juga harus MINIMAL 16 karakter: endpoint ini bisa mengeksekusi
  tools lokal, jadi token pendek = brute-force murahan.
- Auth dicek SEBELUM request menyentuh transport MCP; tools tidak pernah
  dieksekusi tanpa token valid (bandingkan konstanta-waktu via hmac).
- DNS rebinding protection AKTIF: Host header dipelintir dengan daftar
  izin (default localhost/127.0.0.1/[::1] dgn port apa saja). Ekspansi lewat
  ``ALFA_MCP_HTTP_HOSTS`` (contoh: ``"bot.example.com:*,10.0.0.5:*"``).
- ``allowed_origins`` ikut diturunkan dari allowlist Host — tanpa itu klien
  browser kena 403 "Invalid Origin header".
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

MIN_TOKEN_LENGTH = 16


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
    if len(resolved) < MIN_TOKEN_LENGTH:
        msg = (
            f"Token MCP terlalu pendek ({len(resolved)} karakter, minimal "
            f"{MIN_TOKEN_LENGTH}). Endpoint ini bisa mengeksekusi tools lokal "
            "jadi token pendek tidak aman — pakai token acak panjang."
        )
        raise RuntimeError(msg)
    return resolved


def _expand_host_patterns(hosts: list[str]) -> list[str]:
    """Lengkapi allowlist dengan bentuk tanpa port.

    SDK mencocokkan Host header sebagai string PERSIS, plus pola ``host:*``.
    Jadi allowlist ``bot.example.com:*`` saja akan menolak request ke
    ``Host: bot.example.com`` (port 80) dengan 421 Misdirected Request.
    """
    out: list[str] = []
    for h in hosts:
        h = h.strip()
        if not h:
            continue
        if h not in out:
            out.append(h)
        if h.endswith(":*"):
            base = h[:-2]
            if base and base not in out:
                out.append(base)
    return out


def _default_allowed_hosts() -> list[str]:
    raw = os.getenv("ALFA_MCP_HTTP_HOSTS", "").strip()
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    if not hosts:
        # [::1] wajib: banyak mesin lokal me-resolve "localhost" ke IPv6.
        hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    return _expand_host_patterns(hosts)


def _derive_allowed_origins(hosts: list[str]) -> list[str]:
    """Turunkan daftar Origin dari allowlist Host.

    Tanpa ``allowed_origins`` yang terisi, SDK menolak request ber-Origin
    (browser) dengan 403 "Invalid Origin header" — padahal Host-nya legal.
    """
    origins: list[str] = []
    for h in hosts:
        base = h[:-2] if h.endswith(":*") else h
        if not base:
            continue
        for scheme in ("http", "https"):
            for form in (base, f"{base}:*"):
                o = f"{scheme}://{form}"
                if o not in origins:
                    origins.append(o)
    return origins


def _transport_security_settings(allowed_hosts: list[str], allowed_origins: list[str]):
    """Buat TransportSecuritySettings (path import beda antara SDK v1 & v2)."""
    try:
        from mcp.server.transport_security import (  # SDK v2
            TransportSecuritySettings,
        )
    except ImportError:
        from mcp.server.streamable_http import (  # SDK v1
            TransportSecuritySettings,
        )

    try:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    except TypeError:  # pragma: no cover - SDK lama tanpa allowed_origins
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        )


def _build_manager(server: Any, allowed_hosts: list[str], allowed_origins: list[str] | None = None) -> Any:
    """StreamableHTTPSessionManager + rebinding protection eksplisit."""
    try:
        from mcp.server.streamable_http_manager import (
            StreamableHTTPSessionManager,
        )
    except ImportError:  # pragma: no cover - SDK v2 punya lokasi modul berbeda
        from mcp.server.streamable_http import (  # type: ignore[attr-defined, no-redef]
            StreamableHTTPSessionManager,
        )

    origins = allowed_origins if allowed_origins is not None else _derive_allowed_origins(allowed_hosts)
    return StreamableHTTPSessionManager(
        server,
        json_response=True,
        stateless=True,
        security_settings=_transport_security_settings(allowed_hosts, origins),
    )


def create_streamable_http_app(
    server_name: str = "alfa-sovereign-ai",
    *,
    token: str | None = None,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> Starlette:
    """ASGI app MCP-over-HTTP: guard token → transport streamable.

    ``allowed_hosts`` :)uggle eksplisit bila di-deploy di belakang domain
    lain (UJI: TestClient pakai Host "testserver" → lewat ``testserver`` bebas
    port di ``allowed_hosts``).
    """
    resolved = _resolve_token(token)
    server = create_mcp_server(server_name)
    hosts = allowed_hosts if allowed_hosts is not None else _default_allowed_hosts()
    hosts = _expand_host_patterns(hosts)
    manager = _build_manager(server, hosts, allowed_origins)

    @asynccontextmanager
    async def lifespan(_app) -> AsyncIterator[None]:
        async with manager.run():
            yield

    async def mcp_endpoint(scope, receive, send):
        if scope["type"] == "websocket":
            # Transport streamable HTTP tidak mendukung WebSocket.
            await send({"type": "websocket.close", "code": 1000})
            return
        if scope["type"] != "http":
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers") or []
        }
        authorization = headers.get("authorization", "")
        supplied = authorization[7:] if authorization[:7].lower() == "bearer " else ""
        if not supplied:
            supplied = headers.get("x-mcp-token", "")
        # Bandingkan sebagai BYTES: compare_digest menolak str non-ASCII
        # (TypeError -> 500), padahal token non-ASCII harusnya 401 biasa.
        if not hmac.compare_digest(supplied.encode("utf-8"), resolved.encode("utf-8")):
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


def _env_port() -> int:
    """Baca MCP_HTTP_PORT dengan pesan error yang jelas."""
    raw = (os.getenv("MCP_HTTP_PORT") or "8902").strip()
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(
            f"MCP_HTTP_PORT tidak valid: {raw!r} (harus angka, mis. 8902)"
        ) from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"MCP_HTTP_PORT di luar rentang: {port} (harus 1-65535)")
    return port


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
        default=_env_port(),
        help="Port HTTP (default: env MCP_HTTP_PORT atau 8902)",
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
