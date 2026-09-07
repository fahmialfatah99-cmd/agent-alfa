"""Backward-compatibility shim for alfa.core.database."""

import sys
from alfa.core import database as _impl
from alfa.core.database import *  # noqa: F403

sys.modules[__name__] = _impl
