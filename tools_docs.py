"""Backward-compatibility shim for alfa.tools.docs."""

import sys

import alfa.tools.docs as _impl
from alfa.tools.docs import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
