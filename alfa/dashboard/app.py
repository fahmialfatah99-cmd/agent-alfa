"""ALFA Sovereign Command Center - FastAPI Application Factory & Entrypoint.

Provides FastAPI app setup, middleware, static mounts, lifespans, router inclusion,
and backwards-compatible exports.
"""

import asyncio
import base64
import ctypes
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from alfa.dashboard.common import (
    DASHBOARD_AUTH_TOKEN,
    REPO_ROOT,
    SESSION_DURATION_HOURS,
    SESSION_SECRET,
    STATIC_DIR,
    TEMPLATES_DIR,
    _get_bot,
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
from alfa.dashboard.websocket import ConnectionManager, websocket_router, ws_manager

load_dotenv()


async def _pipeline_trigger_scheduler():
    """Background loop: eksekusi pipeline ber-trigger interval tiap 60 detik cek."""
    import pipelines as pl

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
                rss_mb = int(open("/proc/self/status").read().split("VmRSS:")[1].split()[0]) // 1024
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
    asyncio.create_task(_pipeline_trigger_scheduler())
    asyncio.create_task(_malloc_trim_loop())
    yield
    logger.info("ALFA Sovereign Command Center shutting down...")


def _check_security_config():
    """PRODUCTION SECURITY CHECK: Require DASHBOARD_AUTH_TOKEN di production."""
    token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
    if not token:
        dashboard_host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
        if dashboard_host in ("0.0.0.0", "::"):
            logger.critical(
                "⚠️ CRITICAL SECURITY WARNING ⚠️\n"
                "DASHBOARD_HOST terbuka ke jaringan (0.0.0.0/::) TANPA DASHBOARD_AUTH_TOKEN!\n"
                "Semua endpoint /api/* dapat diakses SIAPA PUN dari jaringan Anda.\n"
                "SOLUSI CEPAT: Set DASHBOARD_AUTH_TOKEN di .env atau ubah DASHBOARD_HOST=127.0.0.1"
            )
            raise RuntimeError(
                "Dashboard tidak boleh berjalan tanpa autentikasi saat binding ke 0.0.0.0/::. "
                "Set DASHBOARD_AUTH_TOKEN di environment atau gunakan DASHBOARD_HOST=127.0.0.1 untuk localhost-only."
            )
        else:
            logger.warning(
                "DASHBOARD_AUTH_TOKEN tidak diset - dashboard TANPA autentikasi. "
                "Aman HANYA jika DASHBOARD_HOST=127.0.0.1 (localhost). "
                "Untuk production, WAJIB set DASHBOARD_AUTH_TOKEN di .env!"
            )
    else:
        logger.info("Dashboard authentication enabled (Bearer token + Basic auth)")


def create_app() -> FastAPI:
    """FastAPI application factory."""
    _check_security_config()

    app_instance = FastAPI(
        title="ALFA Sovereign Command Center Pro-Max",
        version="2.5.0",
        lifespan=lifespan,
    )

    # Middleware registration
    app_instance.add_middleware(DashboardAuthMiddleware)

    _cors_env = os.getenv("ALLOWED_CORS_ORIGINS", "").strip()
    if _cors_env:
        allowed_cors_origins = [orig.strip() for orig in _cors_env.split(",") if orig.strip()]
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
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            user = getattr(request.state, "user", None)
            auth_token = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
            if not user and auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header == f"Bearer {auth_token}" or (
                    auth_header.startswith("Basic ")
                    and secrets.compare_digest(
                        auth_header.split()[-1] if len(auth_header.split()) > 1 else "",
                        base64.b64encode(f":{auth_token}".encode()).decode(),
                    )
                ):
                    user = {"username": "admin"}

            return HTMLResponse(
                content=html_content,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        return HTMLResponse("<h2>Dashboard template not found. Please create templates/index.html</h2>")

    # Include APIRouters
    app_instance.include_router(auth_router)
    app_instance.include_router(chat_router)
    app_instance.include_router(tools_router)
    app_instance.include_router(swarm_router)
    app_instance.include_router(system_router)
    app_instance.include_router(websocket_router)

    return app_instance


# Global FastAPI instance (create_app() runs _check_security_config())
app = create_app()

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
]
