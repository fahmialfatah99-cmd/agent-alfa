"""ALFA Swarm: Autonomous multi-agent meeting orchestrator and checkpoint engine."""
import sys
from pathlib import Path
root_dir = str(Path(__file__).resolve().parents[2])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import swarm_engine
    import swarm_personas
    import swarm_checkpoint
except ImportError:
    pass
