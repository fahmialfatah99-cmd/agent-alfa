"""Backward-compatibility shim for alfa.swarm.personas."""
import sys
from alfa.swarm import personas as _impl
from alfa.swarm.personas import *  # noqa: F403

sys.modules[__name__] = _impl
