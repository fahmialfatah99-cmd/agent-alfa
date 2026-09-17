"""
Backward-compatibility facade for web_dashboard.
Directs all imports to the modular alfa.dashboard subpackage.
"""

import sys
import uvicorn

# Re-export all symbols from alfa.dashboard.app (using 'as X' for explicit re-export)
from alfa.dashboard.app import (
    DASHBOARD_AUTH_TOKEN as DASHBOARD_AUTH_TOKEN,
    REPO_ROOT as REPO_ROOT,
    SESSION_DURATION_HOURS as SESSION_DURATION_HOURS,
    SESSION_SECRET as SESSION_SECRET,
    STATIC_DIR as STATIC_DIR,
    TEMPLATES_DIR as TEMPLATES_DIR,
    ConnectionManager as ConnectionManager,
    DashboardAuthMiddleware as DashboardAuthMiddleware,
    _check_security_config as _check_security_config,
    _create_session_token as _create_session_token,
    _hash_password as _hash_password,
    _malloc_trim_loop as _malloc_trim_loop,
    _parse_ai_sections as _parse_ai_sections,
    _pipeline_trigger_scheduler as _pipeline_trigger_scheduler,
    _safe_workspace_path as _safe_workspace_path,
    _verify_password as _verify_password,
    _verify_session_token as _verify_session_token,
    _ws_real_path as _ws_real_path,
    app as app,
    authenticate_user as authenticate_user,
    categorize_tool as categorize_tool,
    create_app as create_app,
    create_user as create_user,
    delete_user as delete_user,
    get_all_users as get_all_users,
    get_primary_user_id as get_primary_user_id,
    init_auth_db as init_auth_db,
    invalidate_session as invalidate_session,
    lifespan as lifespan,
    logger as logger,
    safe_int as safe_int,
    store_session as store_session,
    validate_session as validate_session,
    ws_manager as ws_manager,
)

# Re-run security check on module reload (initial import is checked by create_app())
_check_security_config()

if __name__ == "__main__":
    from alfa.dashboard.app import DASHBOARD_HOST, DASHBOARD_PORT

    uvicorn.run(
        "alfa.dashboard.app:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=False,
    )
