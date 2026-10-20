"""ALFA Sovereign Command Center - FastAPI Application Factory & Entrypoint.

Provides FastAPI app setup, middleware, static mounts, lifespans, router inclusion,
and backwards-compatible exports.
"""

import asyncio
import base64
import ctypes
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

_START_TIME = time.time()


def _agent_snapshot() -> dict:
    """Snapshot metrik runtime agent (anti-throwing) untuk /api/metrics."""
    try:
        from alfa.core import metrics as _metrics

        return _metrics.snapshot()
    except Exception:
        return {}

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from alfa.core.config import ensure_env_loaded
from alfa.dashboard.common import (
    DASHBOARD_AUTH_TOKEN,
    REPO_ROOT,
    SESSION_DURATION_HOURS,
    SESSION_SECRET,
    STATIC_DIR,
    TEMPLATES_DIR,
    get_primary_user_id,
    logger,
    safe_int,
)
from alfa.dashboard.routes.auth import (
    DashboardAuthMiddleware,
    _create_session_token,
    _hash_password,
    _verify_password,
    _verify_session_token,
    auth_router,
    authenticate_user,
    create_user,
    delete_user,
    get_all_users,
    init_auth_db,
    invalidate_session,
    store_session,
    validate_session,
)
from alfa.dashboard.routes.chat import chat_router
from alfa.dashboard.routes.swarm import _parse_ai_sections, swarm_router
from alfa.dashboard.routes.system import (
    _safe_workspace_path,
    _ws_real_path,
    system_router,
)
from alfa.dashboard.routes.tools import categorize_tool, tools_router
from alfa.dashboard.routes.webauthn_auth import webauthn_router
from alfa.dashboard.routes.webhook import webhook_router
from alfa.dashboard.schemas import HealthCheckResponse, SystemMetricsResponse
from alfa.dashboard.websocket import ConnectionManager, websocket_router, ws_manager

ensure_env_loaded()

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = safe_int(
    os.getenv("DASHBOARD_PORT", "8080"), 8080, minimum=1, maximum=65535
)


async def _pipeline_trigger_scheduler():
    """Background loop: eksekusi pipeline ber-trigger interval tiap 60 detik cek."""
    from alfa.pipelines import engine as pl

    while True:
        try:
            await pl.scheduler_tick()
        except Exception as e:
            logger.debug(f"pipeline scheduler: {e}")
        await asyncio.sleep(60)


_TRIM_INTERVAL_SEC = int(os.getenv("DASHBOARD_MALLOC_TRIM_SEC", "900"))


async def _malloc_trim_loop():
    try:
        libc = ctypes.CDLL("libc.so.6")
    except OSError:
        return
    while True:
        await asyncio.sleep(_TRIM_INTERVAL_SEC)
        try:
            freed = libc.malloc_trim(0)
            if freed:
                rss_mb = (
                    int(open("/proc/self/status").read().split("VmRSS:")[1].split()[0])
                    // 1024
                )
                logger.debug(f"malloc_trim OK — RSS sekarang {rss_mb} MB")
        except Exception as e:
            logger.debug(f"malloc_trim gagal (abaikan): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    try:
        init_auth_db()
    except Exception as e:
        logger.error(f"Gagal inisialisasi auth database di lifespan startup: {e}")
    try:
        from alfa.integrations.gdrive import secret_store as _gs

        report = _gs.migrate_legacy_plaintext()
        if any(report.values()):
            logger.info(f"GDrive secret migrasi plaintext→vault: {report}")
    except Exception as e:
        logger.debug(f"GDrive secret migration dilewati: {e}")
    asyncio.create_task(_pipeline_trigger_scheduler())
    asyncio.create_task(_malloc_trim_loop())
    yield
    logger.info("ALFA Sovereign Command Center shutting down...")


_ERR_INSECURE_LOCAL_PUBLIC = (
    "ALFA_INSECURE_LOCAL=true tidak boleh dipakai saat DASHBOARD_HOST "
    "terbuka ke jaringan (0.0.0.0/::). Set DASHBOARD_HOST=127.0.0.1 "
    "atau matikan ALFA_INSECURE_LOCAL dan set DASHBOARD_AUTH_TOKEN."
)
_ERR_NO_TOKEN_PUBLIC_BIND = (
    "Dashboard tidak boleh berjalan tanpa autentikasi saat binding ke 0.0.0.0/::. "
    "Set DASHBOARD_AUTH_TOKEN di environment atau gunakan DASHBOARD_HOST=127.0.0.1 "
    "untuk localhost-only."
)


def _check_security_config():
    """PRODUCTION SECURITY CHECK: Require DASHBOARD_AUTH_TOKEN di production."""
    token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    insecure_local = os.getenv("ALFA_INSECURE_LOCAL", "false").strip().lower() == "true"
    dashboard_host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    if insecure_local and dashboard_host in ("0.0.0.0", "::"):  # nosec B104 - perbandingan string untuk guard, bukan bind
        if token:
            raise RuntimeError(_ERR_INSECURE_LOCAL_PUBLIC)
    if not token:
        if dashboard_host in ("0.0.0.0", "::"):  # nosec B104 - string comparison for guard check, not a bind
            logger.critical(
                "⚠️ CRITICAL SECURITY WARNING ⚠️\n"
                "DASHBOARD_HOST terbuka ke jaringan (0.0.0.0/::) TANPA DASHBOARD_AUTH_TOKEN!\n"
                "Semua endpoint /api/* dapat diakses SIAPA PUN dari jaringan Anda.\n"
                "SOLUSI CEPAT: Set DASHBOARD_AUTH_TOKEN di .env atau ubah DASHBOARD_HOST=127.0.0.1"
            )
            raise RuntimeError(_ERR_NO_TOKEN_PUBLIC_BIND)
        if insecure_local:
            logger.warning(
                "ALFA_INSECURE_LOCAL=true: endpoint /api/* dapat diakses tanpa autentikasi "
                "dari klien lokal (127.0.0.1). HANYA untuk development di localhost."
            )
        else:
            logger.warning(
                "DASHBOARD_AUTH_TOKEN tidak diset - endpoint /api/* WAJIB login "
                "(fail-closed). Gunakan akun admin yang dibuat lewat /api/auth/register, "
                "atau set ALFA_INSECURE_LOCAL=true untuk mode development localhost tanpa login."
            )
    else:
        logger.info("Dashboard authentication enabled (Bearer token + Basic auth)")

    # Guard kombinasi env berbahaya (unrestricted + bind publik, dll.)
    from alfa.core.security_boot_guard import check_runtime_security

    check_runtime_security("dashboard")


class CSPNonceMiddleware(BaseHTTPMiddleware):
    """Tambahkan Content-Security-Policy ketat + nonce untuk script inline.

    Tanpa CSP, stored XSS dari output LLM punya jalur eksekusi bebas:
    `<img src=x onerror=...>` di dalam HTML yang di-render akan berjalan.
    DOMPurify (P1) membersihkan HTML-nya, CSP adalah lapis kedua:policy ini
    memblokir script inline maupun handler event yang lolos sanitasi.

    Script inline di `templates/index.html` diberi nonce oleh route `/`.
    """

    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(18)
        request.state.csp_nonce = nonce
        csp = "; ".join(
            [
                "default-src 'self'",
                (
                    "script-src 'self' "
                    f"'nonce-{nonce}' "
                    "https://cdn.tailwindcss.com "
                    "https://unpkg.com "
                    "https://cdn.jsdelivr.net"
                ),
                # Mengizinkan event listener inline (onclick, onchange, dll.) di elemen UI
                "script-src-attr 'unsafe-inline'",
                # Tailwind Play CDN menyuntik <style> runtime + template memakai
                # atribut style inline, jadi 'unsafe-inline' diperlukan di style-src.
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://fonts.googleapis.com",
                "img-src 'self' data: blob: https:",
                "font-src 'self' data: https://fonts.gstatic.com",
                "connect-src 'self' ws: wss:",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
                "object-src 'none'",
            ]
        )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = csp
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


def create_app() -> FastAPI:
    """FastAPI application factory."""
    _check_security_config()

    app_instance = FastAPI(
        title="ALFA Sovereign Command Center Pro-Max",
        description=(
            "The Autonomous Sovereign AI Operating System & Command Center API.\n\n"
            "Features 173 native tools, Swarm Multi-Agent War Room, Dual Telegram/Web interface, "
            "and external webhook automation integration."
        ),
        version="2.6.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Middleware registration
    app_instance.add_middleware(DashboardAuthMiddleware)
    app_instance.add_middleware(CSPNonceMiddleware)

    _cors_env = os.getenv("ALLOWED_CORS_ORIGINS", "").strip()
    if _cors_env:
        allowed_cors_origins = [
            orig.strip() for orig in _cors_env.split(",") if orig.strip()
        ]
    else:
        allowed_cors_origins = [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    if os.path.exists(STATIC_DIR):
        app_instance.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Root route
    @app_instance.get("/", response_class=HTMLResponse)
    async def serve_index(request: Request):
        """Serve the single-page luxury glassmorphic dashboard."""
        index_path = os.path.join(TEMPLATES_DIR, "index.html")
        if os.path.exists(index_path):
            with open(index_path, encoding="utf-8") as f:
                html_content = f.read()

            # Sisipkan nonce pada script inline agar CSP bisa memakai
            # 'nonce-...' alih-alih 'unsafe-inline' untuk script.
            nonce = getattr(request.state, "csp_nonce", "")
            if nonce:
                html_content = html_content.replace(
                    "<script>", f'<script nonce="{nonce}">'
                )

            user = getattr(request.state, "user", None)
            auth_token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
            query_token = request.query_params.get("token") or request.query_params.get(
                "auth"
            )
            if not user and auth_token:
                auth_header = request.headers.get("Authorization", "")
                if (
                    auth_header == f"Bearer {auth_token}"
                    or (
                        auth_header.startswith("Basic ")
                        and secrets.compare_digest(
                            auth_header.split()[-1]
                            if len(auth_header.split()) > 1
                            else "",
                            base64.b64encode(f":{auth_token}".encode()).decode(),
                        )
                    )
                    or (query_token and secrets.compare_digest(query_token, auth_token))
                ):
                    user = {"username": "admin"}

            response = HTMLResponse(
                content=html_content,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

            # If accessing locally or authenticated and DASHBOARD_AUTH_TOKEN is configured, auto-provision session cookie
            is_local = not request.client or request.client.host in (
                "127.0.0.1",
                "::1",
                "localhost",
                "testclient",
            )
            existing_session = request.cookies.get("session_token")
            insecure_local = (
                os.getenv("ALFA_INSECURE_LOCAL", "false").strip().lower() == "true"
            )
            if (
                (is_local or user)
                and (auth_token or (insecure_local and is_local))
                and not (existing_session and validate_session(existing_session))
            ):
                try:
                    s_token = _create_session_token(
                        0, "admin_local" if is_local else "admin"
                    )
                    store_session(0, s_token)
                    response.set_cookie(
                        key="session_token",
                        value=s_token,
                        max_age=SESSION_DURATION_HOURS * 3600,
                        httponly=False,
                        samesite="lax",
                    )
                except Exception as e:
                    logger.debug(f"Failed to auto-provision local session: {e}")

            return response
        return HTMLResponse(
            "<h2>Dashboard template not found. Please create templates/index.html</h2>"
        )

    # Health check & metrics endpoints
    @app_instance.get(
        "/health",
        tags=["Monitoring"],
        response_model=HealthCheckResponse,
        summary="Kubernetes / Docker Liveness Check",
    )
    @app_instance.get(
        "/healthz",
        tags=["Monitoring"],
        response_model=HealthCheckResponse,
        include_in_schema=False,
    )
    @app_instance.get(
        "/api/health",
        tags=["Monitoring"],
        response_model=HealthCheckResponse,
        summary="Service & Database Health Status",
    )
    @app_instance.get(
        "/api/healthz",
        tags=["Monitoring"],
        response_model=HealthCheckResponse,
        include_in_schema=False,
    )
    async def health_check():
        """Health check endpoint for Docker, Kubernetes, and uptime monitoring."""
        db_status = "unknown"
        table_count = 0
        try:
            from alfa.core import database as db

            conn = db.get_connection_pool().acquire()
            try:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                )
                row = cursor.fetchone()
                table_count = int(row[0]) if row else 0
                db_status = "connected"
            finally:
                db.get_connection_pool().release(conn)
        except Exception as e:
            db_status = f"degraded: {e}"

        import psutil

        process = psutil.Process()
        memory_info = process.memory_info()

        return HealthCheckResponse(
            status="healthy" if db_status == "connected" else "degraded",
            service="alfa-sovereign-ai",
            version="2.6.0",
            database=db_status,
            database_tables=table_count,
            uptime_seconds=round(time.time() - _START_TIME, 2),
            memory_rss_mb=round(memory_info.rss / (1024 * 1024), 2),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @app_instance.get(
        "/api/metrics",
        tags=["Monitoring"],
        response_model=SystemMetricsResponse,
        summary="Telemetry & Resource Metrics",
    )
    async def system_metrics():
        """System performance and resource telemetry metrics."""
        import psutil

        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        proc = psutil.Process()

        db_pool_stats = {}
        try:
            from alfa.core import database as db

            db_pool_stats = db.get_connection_pool().stats
        except Exception:
            pass

        return SystemMetricsResponse(
            service="alfa-sovereign-ai",
            version="2.6.0",
            timestamp=datetime.now(timezone.utc).isoformat(),
            system={
                "cpu_percent": cpu_pct,
                "memory_total_mb": round(mem.total / (1024 * 1024), 2),
                "memory_used_mb": round(mem.used / (1024 * 1024), 2),
                "memory_percent": mem.percent,
                "disk_percent": disk.percent,
            },
            process={
                "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 2),
                "threads": proc.num_threads(),
                "uptime_seconds": round(time.time() - _START_TIME, 2),
            },
            database_pool=db_pool_stats,
            agent=_agent_snapshot(),
        )

    # Include APIRouters
    app_instance.include_router(auth_router)
    app_instance.include_router(webauthn_router)
    app_instance.include_router(chat_router)
    app_instance.include_router(tools_router)
    app_instance.include_router(swarm_router)
    app_instance.include_router(system_router)
    app_instance.include_router(webhook_router)
    app_instance.include_router(websocket_router)

    return app_instance


# Global FastAPI instance (create_app() runs _check_security_config())
app = create_app()


def _serve() -> None:
    """Entry subprocess `python -m alfa.dashboard.app` (pengganti web_dashboard.py)."""
    import uvicorn

    uvicorn.run(
        "alfa.dashboard.app:app",
        host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.getenv("DASHBOARD_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    _serve()

__all__ = [
    "app",
    "create_app",
    "_check_security_config",
    "lifespan",
    "_pipeline_trigger_scheduler",
    "_malloc_trim_loop",
    "DashboardAuthMiddleware",
    "init_auth_db",
    "create_user",
    "authenticate_user",
    "store_session",
    "validate_session",
    "invalidate_session",
    "get_all_users",
    "delete_user",
    "_hash_password",
    "_verify_password",
    "_create_session_token",
    "_verify_session_token",
    "get_primary_user_id",
    "safe_int",
    "categorize_tool",
    "_parse_ai_sections",
    "_ws_real_path",
    "_safe_workspace_path",
    "logger",
    "TEMPLATES_DIR",
    "STATIC_DIR",
    "REPO_ROOT",
    "DASHBOARD_AUTH_TOKEN",
    "SESSION_SECRET",
    "SESSION_DURATION_HOURS",
    "ws_manager",
    "ConnectionManager",
    "webhook_router",
]
