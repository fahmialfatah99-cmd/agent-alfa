"""ALFA Security: Vault encryption, permission gates, and sandboxing."""
import sys
from pathlib import Path
root_dir = str(Path(__file__).resolve().parents[2])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import vault_engine
    import permission_gate
    import security_auditor
except ImportError:
    pass
