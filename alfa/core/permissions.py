"""PERMISSION GATE — human-in-the-loop untuk tool berbahaya (Enhanced v2.0).

Facade re-exporting from modular subpackage alfa.core.perm.
"""

from alfa.core.perm import *  # noqa: F401, F403
from alfa.core.perm import (
    APPROVAL_TIMEOUT,
    DB_PATH,
    DEFAULT_TIER,
    FAIL_MODE,
    PERMISSION_GATE_ENABLED,
    PROJECT_DIR,
    REPO_ROOT,
    SAFE_TOOLS,
    TOOL_CLASSIFICATION,
    TRUST_THRESHOLD,
    RiskTier,
    _connect,
    audit_local_host_security,
    audit_website_security,
    get_tool_tier,
    get_trust_score,
    handle_permission_callback,
    is_always_allowed,
    is_enabled,
    list_always_allowed,
    log_permission_decision,
    make_gate,
    request_approval,
    save_always_allow,
    should_auto_approve,
    update_trust_score,
    wrap_tool_for_afc,
)
