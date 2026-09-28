"""Shared browser engine state (singleton page, locks, constants)."""

from __future__ import annotations

import threading
from typing import Any

_INTERACTIVE_SEL = (
    "a[href], button, input, textarea, select, "
    "[role=button], [role=link], [role=tab], [role=menuitem], [onclick]"
)
_MAX_REFS = 60
_LOCK = threading.RLock()
_STATE: dict[str, Any] = {"ctx": None, "page": None, "elements": []}
_AT_EXIT_DONE = False
