"""Backward-compatibility shim for alfa.swarm.checkpoint."""
import sys
from alfa.swarm import checkpoint as _impl
from alfa.swarm.checkpoint import *  # noqa: F403

sys.modules[__name__] = _impl
