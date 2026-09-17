"""Backward-compatibility shim for alfa.swarm.apply_personas."""

import sys

import alfa.swarm.apply_personas as _impl
from alfa.swarm.apply_personas import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
