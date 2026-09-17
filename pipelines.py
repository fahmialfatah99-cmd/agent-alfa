"""Backward-compatibility shim for alfa.pipelines.engine."""

import sys

import alfa.pipelines.engine as _impl
from alfa.pipelines.engine import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
