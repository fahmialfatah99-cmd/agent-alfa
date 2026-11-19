"""Rate limit ringan untuk endpoint generasi chat (aditif).

Endpooint auth sudah punya rate limit sendiri. Middleware ini melindungi
endpoint LLM yang mahal dari loop klien/bug frontend, dengan default longgar
(20 permintaan / 60 detik per IP) dan bisa dimatikan lewat env. Streaming yang
sedang berjalan tidak diputus; hanya permintaan baru yang ditolak 429.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from alfa.dashboard.common import logger

_GENERATION_PATHS = {
    "/api/chat",
    "/api/chat/stream",
    "/api/chat/regenerate",
    "/api/chat/edit",
}
_DEFAULT_LIMIT = 20
_DEFAULT_WINDOW_SEC = 60
_MAX_BUCKETS = 4096

_buckets: dict[str, list[float]] = {}
_lock = threading.Lock()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _settings() -> tuple[int, int]:
    limit = _env_int("ALFA_CHAT_RATE_LIMIT", _DEFAULT_LIMIT)
    window = _env_int("ALFA_CHAT_RATE_WINDOW_SEC", _DEFAULT_WINDOW_SEC)
    return max(0, limit), max(1, window)


def reset_rate_limits() -> None:
    """Kosongkan bucket (dipakai test; tidak diekspos ke HTTP)."""
    with _lock:
        _buckets.clear()


def _consume(key: str, limit: int, window: int) -> tuple[bool, int, int]:
    """Return (allowed, retry_after, remaining)."""
    now = time.monotonic()
    with _lock:
        if len(_buckets) >= _MAX_BUCKETS and key not in _buckets:
            # Buang bucket yang sudah kedaluwarsa; bila masih penuh, tolak
            # key baru agar memori tidak tumbuh tanpa batas.
            stale = [
                k
                for k, stamps in _buckets.items()
                if not stamps or now - stamps[-1] >= window
            ]
            for k in stale[: max(1, _MAX_BUCKETS // 4)]:
                _buckets.pop(k, None)
            if len(_buckets) >= _MAX_BUCKETS:
                return False, window, 0
        stamps = [t for t in _buckets.get(key, []) if now - t < window]
        if len(stamps) >= limit:
            retry = max(1, int(window - (now - stamps[0])) + 1)
            _buckets[key] = stamps
            return False, retry, 0
        stamps.append(now)
        _buckets[key] = stamps
        return True, 0, max(0, limit - len(stamps))


def _client_ip(request: Any) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", None) or "unknown")


class ChatRateLimitMiddleware(BaseHTTPMiddleware):
    """Batasi POST generasi chat per IP dengan sliding window."""

    async def dispatch(self, request, call_next):
        limit, window = _settings()
        if (
            limit <= 0
            or request.method != "POST"
            or request.url.path not in _GENERATION_PATHS
        ):
            return await call_next(request)

        key = f"chat:{_client_ip(request)}"
        allowed, retry_after, remaining = _consume(key, limit, window)
        if not allowed:
            logger.warning(
                "[RATE] chat limit tercapai untuk %s (limit=%s/%ss)",
                _client_ip(request),
                limit,
                window,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Terlalu banyak permintaan chat. "
                        f"Coba lagi dalam {retry_after} detik."
                    )
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


__all__ = ["ChatRateLimitMiddleware", "reset_rate_limits"]
