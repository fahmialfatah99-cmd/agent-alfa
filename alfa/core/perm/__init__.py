"""Permission gate package: risk classifications, store, human-in-the-loop gate, and auditor."""

from alfa.core.perm.constants import (
    APPROVAL_TIMEOUT,
    DB_PATH,
    DEFAULT_TIER,
    FAIL_MODE,
    PERMISSION_GATE_ENABLED,
    PROJECT_DIR,
    REPO_ROOT,
    RiskTier,
    SAFE_TOOLS,
    TOOL_CLASSIFICATION,
    TRUST_THRESHOLD,
)
from alfa.core.perm.store import (
    _connect,
    get_trust_score,
    is_always_allowed,
    list_always_allowed,
    log_permission_decision,
    save_always_allow,
    update_trust_score,
)
from alfa.core.perm.gate import (
    get_tool_tier,
    is_enabled,
    make_gate,
    request_approval,
    should_auto_approve,
    wrap_tool_for_afc,
)
from alfa.core.perm.auditor import (
    audit_local_host_security,
    audit_website_security,
)

__all__ = [
    "APPROVAL_TIMEOUT",
    "DB_PATH",
    "DEFAULT_TIER",
    "FAIL_MODE",
    "PERMISSION_GATE_ENABLED",
    "PROJECT_DIR",
    "REPO_ROOT",
    "RiskTier",
    "SAFE_TOOLS",
    "TOOL_CLASSIFICATION",
    "TRUST_THRESHOLD",
    "_connect",
    "get_trust_score",
    "is_always_allowed",
    "list_always_allowed",
    "log_permission_decision",
    "save_always_allow",
    "update_trust_score",
    "get_tool_tier",
    "is_enabled",
    "make_gate",
    "request_approval",
    "should_auto_approve",
    "wrap_tool_for_afc",
    "audit_local_host_security",
    "audit_website_security",
]
