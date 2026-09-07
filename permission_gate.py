"""Backward-compatibility shim for alfa.core.permissions."""

import sys
from alfa.core import permissions as _impl
from alfa.core.permissions import *  # noqa: F403

sys.modules[__name__] = _impl
