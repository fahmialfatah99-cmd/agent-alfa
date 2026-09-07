"""ALFA Swarm: Autonomous multi-agent meeting orchestrator and checkpoint engine."""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from alfa.swarm import checkpoint, engine, personas
from alfa.swarm.checkpoint import SwarmCheckpoint
from alfa.swarm.engine import *  # noqa: F401, F403
from alfa.swarm.personas import AGENTS, DNA, build_prompts
