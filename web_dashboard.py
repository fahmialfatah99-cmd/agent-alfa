"""Backward-compatibility shim for alfa.dashboard.

Used directly by systemd service alfa-dashboard.service.
"""

import os
import sys

import uvicorn

# Re-export all symbols from alfa.dashboard.app
from alfa.dashboard.app import (
    DASHBOARD_AUTH_TOKEN,
    REPO_ROOT,
    SESSION_DURATION_HOURS,
    SESSION_SECRET,
    STATIC_DIR,
    TEMPLATES_DIR,
    ConnectionManager,
    DashboardAuthMiddleware,
    _check_security_config,
    _create_session_token,
    _hash_password,
    _malloc_trim_loop,
    _parse_ai_sections,
    _pipeline_trigger_scheduler,
    _safe_workspace_path,
    _verify_password,
    _verify_session_token,
    _ws_real_path,
    app,
    authenticate_user,
    categorize_tool,
    create_app,
    create_user,
    delete_user,
    get_all_users,
    get_primary_user_id,
    init_auth_db,
    invalidate_session,
    lifespan,
    logger,
    safe_int,
    store_session,
    validate_session,
    ws_manager,
)

# Re-run security check on module reload (initial import is checked by create_app())
if getattr(sys.modules.get(__name__), "_initialized", False):
    _check_security_config()
_initialized = True

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    uvicorn.run("alfa.dashboard.app:app", host=host, port=port, reload=False)
