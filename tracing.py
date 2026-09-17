"""Backward-compatibility shim for alfa.core.tracing."""

import sys

import alfa.core.tracing as _impl
from alfa.core.tracing import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
