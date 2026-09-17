"""Backward-compatibility shim for alfa.core.fast_path_executor."""

import sys

import alfa.core.fast_path_executor as _impl
from alfa.core.fast_path_executor import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
