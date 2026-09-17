"""Backward-compatibility shim for alfa.memory.reflection."""

import sys

import alfa.memory.reflection as _impl
from alfa.memory.reflection import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
