"""Backward-compatibility shim for alfa.integrations.gdrive."""

import sys
from alfa.integrations import gdrive as _impl
from alfa.integrations.gdrive import *  # noqa: F403

sys.modules[__name__] = _impl
