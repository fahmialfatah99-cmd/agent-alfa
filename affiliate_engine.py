"""Backward-compatibility shim for alfa.tools.web.affiliate_engine."""

import sys

import alfa.tools.web.affiliate_engine as _impl
from alfa.tools.web.affiliate_engine import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
