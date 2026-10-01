"""Workspace-scoped todo tracking for multi-step coding tasks (Claude-style).

Persisted to <workspace>/.alfa_backups/todos.json so plans survive restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TodoManager:
    """Add/list/complete/clear todos for the active workspace."""

    def __init__(self, workspace_root: Path | None = None):
        self.root = workspace_root or Path.cwd()
        self.path = self.root / ".alfa_backups" / "todos.json"
        self.todos: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.todos = [t for t in data if isinstance(t, dict)]
        except (OSError, ValueError):
            self.todos = []

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.todos, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def add(self, task: str) -> dict[str, Any]:
        item = {
            "id": (max((t.get("id", 0) for t in self.todos), default=0) + 1),
            "task": task.strip(),
            "done": False,
        }
        self.todos.append(item)
        self.save()
        return item

    def list(self) -> list[dict[str, Any]]:
        return list(self.todos)

    def done(self, todo_id: int) -> bool:
        for t in self.todos:
            if t.get("id") == todo_id:
                t["done"] = True
                self.save()
                return True
        return False

    def clear(self, done_only: bool = True) -> int:
        before = len(self.todos)
        if done_only:
            self.todos = [t for t in self.todos if not t.get("done")]
        else:
            self.todos = []
        self.save()
        return before - len(self.todos)

    def summary(self) -> str:
        if not self.todos:
            return "Belum ada todo. Tambah dengan /todo add <tugas>."
        lines = []
        for t in self.todos:
            mark = "✅" if t.get("done") else "⬜"
            lines.append(f"{mark} #{t.get('id')} {t.get('task')}")
        return "\n".join(lines)
