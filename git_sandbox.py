"""Backward-compatibility shim for alfa.tools.filesystem.git_sandbox."""

import sys

import alfa.tools.filesystem.git_sandbox as _impl
from alfa.tools.filesystem.git_sandbox import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
