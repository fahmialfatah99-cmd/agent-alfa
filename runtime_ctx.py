"""Backward-compatibility shim for alfa.core.runtime_ctx."""

import sys
from alfa.core import runtime_ctx as _impl
from alfa.core.runtime_ctx import *  # noqa: F403

sys.modules[__name__] = _impl
