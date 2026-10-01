"""Named conversation-session persistence for the CLI (opencode-style).

Sessions live in ~/.alfa/sessions/<name>.json and capture chat history,
the last approved plan, and agent mode flags — so closing the terminal
never loses work. Use /session save|list|load|delete.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SESSIONS_DIR = Path.home() / ".alfa" / "sessions"
LAST_SESSION_NAME = "last"
MAX_MESSAGES = 100
MAX_CHARS_PER_MESSAGE = 4000


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "sesi"


class SessionStore:
    """Save/load/list/delete named CLI sessions."""

    def __init__(self, base_dir: Path | None = None):
        self.base = base_dir or SESSIONS_DIR
        try:
            self.base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _path(self, name: str) -> Path:
        return self.base / f"{_slug(name)}.json"

    def save(
        self,
        name: str,
        chat_history: list[dict[str, Any]],
        last_plan: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        slug = _slug(name)
        trimmed = []
        for m in chat_history[-MAX_MESSAGES:]:
            content = str(m.get("content", ""))[:MAX_CHARS_PER_MESSAGE]
            trimmed.append({"role": m.get("role", "user"), "content": content})
        payload = {
            "name": slug,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "workspace": str(Path.cwd()),
            "chat_history": trimmed,
            "last_plan": last_plan,
            "extra": extra or {},
        }
        self._path(slug).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return slug

    def load(self, name: str) -> dict[str, Any] | None:
        try:
            path = self._path(name)
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def delete(self, name: str) -> bool:
        try:
            path = self._path(name)
            if path.exists():
                path.unlink()
                return True
        except OSError:
            pass
        return False

    def list(self) -> list[dict[str, Any]]:
        out = []
        try:
            files = sorted(self.base.glob("*.json"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return out
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                history = data.get("chat_history", [])
                out.append(
                    {
                        "name": path.stem,
                        "saved_at": data.get("saved_at", "-"),
                        "workspace": data.get("workspace", "-"),
                        "messages": len(history) if isinstance(history, list) else 0,
                        "has_plan": bool(data.get("last_plan")),
                    }
                )
            except (OSError, ValueError):
                continue
        return out
