"""Backward-compatibility shim for alfa.core.brain."""

import sys
from alfa.core import brain as _impl
from alfa.core.brain import *  # noqa: F403

sys.modules[__name__] = _impl
