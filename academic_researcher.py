"""Backward-compatibility shim for alfa.tools.academic_researcher."""

import sys

import alfa.tools.academic_researcher as _impl
from alfa.tools.academic_researcher import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
