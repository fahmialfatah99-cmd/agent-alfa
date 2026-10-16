"""OAuth callback + status untuk konektor MCP remote."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


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
