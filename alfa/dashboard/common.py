"""ALFA Sovereign Command Center - Dashboard Common Utilities & Constants."""

import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Request

load_dotenv()

# Setup logging
logger = logging.getLogger("Dashboard")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = str(REPO_ROOT / "templates")
STATIC_DIR = str(REPO_ROOT / "static")

DASHBOARD_AUTH_TOKEN = os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
SESSION_DURATION_HOURS = int(os.getenv("SESSION_DURATION_HOURS", "24"))

# Lazy bot module reference
bot = None
try:
    from alfa.bot import telegram_bot as _initial_bot
    bot = _initial_bot
except Exception:
    bot = None


def _get_bot():
    """Lazily load or retrieve bot module."""
    global bot
    if bot is None:
        from alfa.bot import telegram_bot as _bot_mod
        bot = _bot_mod
    return bot


def get_primary_user_id(request: Optional[Request] = None) -> int:
    """Safely get target telegram user id from request headers/params or ALLOWED_USER_IDS env var."""
    if request is not None:
        req_uid = request.headers.get("X-User-Id") or request.query_params.get("user_id")
        if req_uid and str(req_uid).strip().isdigit():
            return int(str(req_uid).strip())
    allowed_env = os.getenv("ALLOWED_USER_IDS", "").strip()
    if allowed_env:
        for uid_str in allowed_env.split(","):
            uid_clean = uid_str.strip()
            if uid_clean.isdigit():
                return int(uid_clean)
    return 0


def safe_int(value, default: int, minimum: int = None, maximum: int = None) -> int:
    """Convert payload value to int with fallback and optional bounds."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result
