"""Backward-compatibility shim for alfa.tools.registry."""

import sys

import alfa.tools.registry as _impl
from alfa.tools.registry import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
