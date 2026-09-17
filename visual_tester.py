"""Backward-compatibility shim for alfa.tools.web.visual_tester."""

import sys

import alfa.tools.web.visual_tester as _impl
from alfa.tools.web.visual_tester import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
