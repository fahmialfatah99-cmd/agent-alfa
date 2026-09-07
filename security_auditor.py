"""Backward-compatibility shim for alfa.core.permissions (security auditing)."""
import sys
import alfa.core.permissions as _impl
from alfa.core.permissions import *  # noqa: F401, F403

sys.modules[__name__] = _impl
