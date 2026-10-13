"""Persistent per-tool permission rules for the CLI agent (opencode-style).

Rules: `allow` (never ask), `ask` (confirm each time), `deny` (always block).
Stored in ~/.alfa_cli_permissions.json. Default: ask for mutating tools,
allow for read-only tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PERMISSIONS_FILE = Path.home() / ".alfa_cli_permissions.json"

ASK = "ask"
ALLOW = "allow"
DENY = "deny"
VALID_RULES = (ALLOW, ASK, DENY)

# Tools that mutate files or execute commands — default rule is `ask`.
DEFAULT_ASK_TOOLS = frozenset(
    {
        "write_file",
        "patch_file",
        "edit_file_precise",
        "apply_unified_diff",
        "write_local_file",
        "run_command",
    }
)


class PermissionStore:
    """Load/save per-tool permission rules."""

    def __init__(self, path: Path | None = None):
        self.path = path or PERMISSIONS_FILE
        self.rules: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.rules = {
                        str(k): v for k, v in data.items() if v in VALID_RULES
                    }
        except (OSError, ValueError):
            self.rules = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.rules, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass

    def get(self, tool: str) -> str:
        """Return rule for tool: stored rule, else ask-if-mutating else allow."""
        if tool in self.rules:
            return self.rules[tool]
        return ASK if tool in DEFAULT_ASK_TOOLS else ALLOW

    def set(self, tool: str, rule: str) -> bool:
        if rule not in VALID_RULES:
            return False
        self.rules[tool] = rule
        self.save()
        return True

    def reset(self, tool: str) -> bool:
        if tool in self.rules:
            del self.rules[tool]
            self.save()
            return True
        return False

    def as_dict(self) -> dict[str, Any]:
        return dict(self.rules)
