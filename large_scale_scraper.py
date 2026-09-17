"""Backward-compatibility shim for alfa.scrapers.large_scale."""

import sys

import alfa.scrapers.large_scale as _impl
from alfa.scrapers.large_scale import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
