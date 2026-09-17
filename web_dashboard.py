"""Backward-compatibility shim for alfa.dashboard.

Used directly by systemd service alfa-dashboard.service.
"""
import os
import sys
import uvicorn

# Re-export all symbols from alfa.dashboard.app
from alfa.dashboard.app import (
    app,
    create_app,
    lifespan,
    _check_security_config,
    _pipeline_trigger_scheduler,
    _malloc_trim_loop,
    DashboardAuthMiddleware,
    init_auth_db,
    create_user,
    authenticate_user,
    store_session,
    validate_session,
    invalidate_session,
    get_all_users,
    delete_user,
    _hash_password,
    _verify_password,
    _create_session_token,
    _verify_session_token,
    get_primary_user_id,
    safe_int,
    categorize_tool,
    _parse_ai_sections,
    _ws_real_path,
    _safe_workspace_path,
    logger,
    TEMPLATES_DIR,
    STATIC_DIR,
    REPO_ROOT,
    DASHBOARD_AUTH_TOKEN,
    SESSION_SECRET,
    SESSION_DURATION_HOURS,
    ws_manager,
    ConnectionManager,
)

# Re-run security check on module reload (initial import is checked by create_app())
if getattr(sys.modules.get(__name__), "_initialized", False):
    _check_security_config()
_initialized = True

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    uvicorn.run("alfa.dashboard.app:app", host=host, port=port, reload=False)
