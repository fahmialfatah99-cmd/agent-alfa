"""Middleware observability: request-id + access log terstruktur (aditif).

Tidak mengubah kontrak endpoint. Setiap response mendapat ``X-Request-ID``
(divalidasi agar tidak bisa dipakai untuk log injection), dan satu baris log
memuat method, path tanpa query string, status, serta durasi. Header
``Authorization``/cookie tidak pernah dicatat.
"""

from __future__ import annotations

import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from alfa.dashboard.common import logger

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = {"/health", "/healthz", "/api/health", "/api/healthz", "/readyz", "/api/readyz"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Tambahkan request-id yang aman dan log akses tanpa data sensitif."""

    async def dispatch(self, request, call_next):
        incoming = (request.headers.get("X-Request-ID") or "").strip()
        request_id = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            path = request.url.path
            if not (path == "/static" or path.startswith("/static/")):
                if path in _QUIET_PATHS and status_code < 400:
                    logger.debug(
                        "HTTP %s %s -> %s %.1fms request_id=%s",
                        request.method,
                        path,
                        status_code,
                        duration_ms,
                        request_id,
                    )
                else:
                    logger.info(
                        "HTTP %s %s -> %s %.1fms request_id=%s",
                        request.method,
                        path,
                        status_code,
                        duration_ms,
                        request_id,
                    )


__all__ = ["RequestContextMiddleware"]
