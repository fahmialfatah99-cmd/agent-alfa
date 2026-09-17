"""Backward-compatibility shim for alfa.scrapers.universal."""

import sys
from alfa.scrapers import universal as _impl
from alfa.scrapers.universal import *  # noqa: F403

sys.modules[__name__] = _impl
