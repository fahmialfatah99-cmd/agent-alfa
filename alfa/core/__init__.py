"""ALFA Core: Reasoning loop, Tool RAG, and Main Brain routing."""
import sys
from pathlib import Path
root_dir = str(Path(__file__).resolve().parents[2])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import main_brain
    import tool_rag
    import vector_memory
except ImportError:
    pass
