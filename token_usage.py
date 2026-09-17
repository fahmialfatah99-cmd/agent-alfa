"""Backward-compatibility shim for alfa.core.token_usage."""

import sys

import alfa.core.token_usage as _impl
from alfa.core.token_usage import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
