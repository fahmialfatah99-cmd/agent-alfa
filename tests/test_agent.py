import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import AVAILABLE_TOOLS, get_system_stats


def test_agent_tools_and_stats():
    print("Verifying tools and client...")
    print("Tools loaded:", len(AVAILABLE_TOOLS))
    assert len(AVAILABLE_TOOLS) > 0
    stats = get_system_stats()
    print("System stats sample:", stats)
    assert stats is not None


if __name__ == "__main__":
    test_agent_tools_and_stats()
