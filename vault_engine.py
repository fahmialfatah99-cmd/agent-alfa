"""Backward-compatibility shim for alfa.security.vault."""

import sys

import alfa.security.vault as _impl
from alfa.security.vault import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
