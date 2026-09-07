"""Backward-compatibility shim for alfa.core.cli."""

import sys
from alfa.core import cli as _impl
from alfa.core.cli import *  # noqa: F403
from alfa.core.cli import main

sys.modules[__name__] = _impl

if __name__ == "__main__":
    main()
