"""HTTP client internal untuk bot WhatsApp (wa-sheets-bot)."""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("AgentTools.Integrations")

WA_BOT_URL = os.getenv("WA_BOT_URL", "http://127.0.0.1:3000")


def _wa_api(
    method: str,
    path: str,
    params: dict | None = None,
    body: dict | None = None,
) -> dict[str, Any]:
    """Panggil HTTP API wa-sheets-bot lokal. Return dict JSON (status success/error)."""
    try:
        url = WA_BOT_URL.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 - localhost only
            res_data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            return res_data
    except urllib.error.HTTPError as e:
        # HTTP error membawa body JSON dari bot WA (pesan kesalahan nyata).
        try:
            parsed = json.loads(e.read().decode("utf-8"))
            if isinstance(parsed, dict) and parsed.get("message"):
                return {"status": "error", "message": parsed["message"], "code": parsed.get("code", "")}
        except (ValueError, TypeError, OSError, UnicodeError) as exc:
            logger.debug("Body error WA tidak bisa dibaca: %s", exc)
        return {"status": "error", "message": f"WA API error: {e.code} {str(e)[:150]}"}
    except (OSError, ValueError, TypeError, RuntimeError, ArithmeticError, UnicodeError) as e:
        return {"status": "error", "message": f"WA API tak terjangkau: {type(e).__name__}: {str(e)[:150]}"}
