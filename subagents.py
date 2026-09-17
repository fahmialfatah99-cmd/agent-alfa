"""Backward-compatibility shim for alfa.swarm.subagents."""

import sys

import alfa.swarm.subagents as _impl
from alfa.swarm.subagents import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
