"""Backward-compatibility shim for alfa.tools.rag."""

import sys

import alfa.tools.rag as _impl
from alfa.tools.rag import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
