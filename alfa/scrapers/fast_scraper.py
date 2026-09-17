"""Backward-compatibility shim for alfa.scrapers.fast."""

import sys
from alfa.scrapers import fast as _impl
from alfa.scrapers.fast import *  # noqa: F403

sys.modules[__name__] = _impl
