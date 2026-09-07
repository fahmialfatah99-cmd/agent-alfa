"""Backward-compatibility shim for alfa.swarm.engine."""
import sys
from alfa.swarm import engine as _impl
from alfa.swarm.engine import *  # noqa: F403

sys.modules[__name__] = _impl
