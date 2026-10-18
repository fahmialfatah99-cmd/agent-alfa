"""OAuth callback + status untuk konektor MCP remote."""

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def _require_admin(request: Request) -> None:
    """Gate admin untuk status infra MCP (jangan bocorkan ke non-admin)."""
    user = getattr(request.state, "user", None)
    if user and user.get("is_admin"):
        return
    from alfa.dashboard.routes.auth import require_admin

    require_admin(request)


@router.get("/api/mcp/status")
async def mcp_status(request: Request):
    """Status ekosistem MCP: transport lokal + konektor remote (admin-gated)."""
    _require_admin(request)

    from alfa.mcp import client as _mc

    http_token_dihidupkan = bool(os.getenv("ALFA_MCP_HTTP_TOKEN", "").strip())
    try:
        remote = _mc.connection_status()
    except Exception as exc:  # noqa: BLE001 — status jangan meledak
        remote = {"servers": [], "error": str(exc)}

    return {
        "http_transport": {
            "tersedia": True,
            "token_dihidupkan": http_token_dihidupkan,
            "host_default": os.getenv("MCP_HTTP_HOST", "127.0.0.1"),
            "port_default": int(os.getenv("MCP_HTTP_PORT", "8902") or 8902),
            "perintah": (
                "python -m alfa.mcp.http_server"
                + ("" if http_token_dihidupkan else "  # butuh ALFA_MCP_HTTP_TOKEN")
            ),
        },
        "stdio_transport": {
            "tersedia": True,
            "perintah": "python -m alfa.mcp.server",
        },
        "remote_connectors": remote,
    }


@router.get("/api/mcp/oauth/callback")
async def mcp_oauth_callback(code: str = "", state: str = "") -> HTMLResponse:
    from alfa.mcp import client as _mc

    if not code:
        return HTMLResponse("<h3>Otorisasi dibatalkan (tanpa code).</h3>", status_code=400)
    res = _mc.finish_connect(code, state)
    if res.get("status") == "success":
        return HTMLResponse(
            f"<h3>✅ MCP '{res.get('server')}' terhubung!</h3>"
            "<p>Kembali ke Telegram — agent kini bisa memanggil tool-nya.</p>"
        )
    return HTMLResponse(f"<h3>❌ Gagal: {res.get('message')}</h3>", status_code=400)
