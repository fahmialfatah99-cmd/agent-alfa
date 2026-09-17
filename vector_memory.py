"""Backward-compatibility shim for alfa.memory.vector."""

import sys

import alfa.memory.vector as _impl
from alfa.memory.vector import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
