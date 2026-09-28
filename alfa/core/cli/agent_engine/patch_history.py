"""Patch history journal and rollback manager."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# ==========================================
# 1. PATCH HISTORY & ROLLBACK MANAGER
# ==========================================


@dataclass
class PatchRecord:
    id: int
    timestamp: str
    filepath: str
    backup_path: str
    summary: str


class PatchHistoryManager:
    """Manages transactional file backups and rollback operations."""

    def __init__(self, workspace_root: Path | None = None):
        self.workspace_root = workspace_root or Path.cwd()
        self.backup_dir = self.workspace_root / ".alfa_backups"
        self.journal_file = self.backup_dir / "patch_journal.json"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if not self.journal_file.exists():
            try:
                self.journal_file.write_text("[]", encoding="utf-8")
            except Exception:
                pass

    def _load_journal(self) -> list[dict[str, Any]]:
        try:
            if self.journal_file.exists():
                data = json.loads(self.journal_file.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
        except Exception:
            pass
        return []

    def _save_journal(self, entries: list[dict[str, Any]]) -> None:
        try:
            self.journal_file.write_text(
                json.dumps(entries, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def record_patch(
        self,
        filepath: str,
        old_content: str,
        new_content: str,
    ) -> PatchRecord:
        """Create timestamped backup and record in patch journal."""
        self._ensure_dirs()
        journal = self._load_journal()
        patch_id = len(journal) + 1
        ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_fname = Path(filepath).name
        backup_filename = f"{patch_id}_{ts_slug}_{safe_fname}.bak"
        backup_path = self.backup_dir / backup_filename

        try:
            backup_path.write_text(old_content, encoding="utf-8", errors="replace")
        except Exception:
            pass

        # Calculate line diff summary
        old_lines = len(old_content.splitlines())
        new_lines = len(new_content.splitlines())
        diff_lines = new_lines - old_lines
        summary = f"{'+' if diff_lines >= 0 else ''}{diff_lines} baris ({old_lines} -> {new_lines})"

        record = PatchRecord(
            id=patch_id,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            filepath=filepath,
            backup_path=str(backup_path),
            summary=summary,
        )

        journal.append(asdict(record))
        self._save_journal(journal)
        return record

    def list_patches(self) -> list[PatchRecord]:
        """Return list of all recorded patches."""
        journal = self._load_journal()
        return [PatchRecord(**e) for e in journal]

    def rollback_patch(self, patch_id: int) -> tuple[bool, str]:
        """Restore specific file from backup by patch ID."""
        journal = self._load_journal()
        target = next((e for e in journal if e["id"] == patch_id), None)
        if not target:
            return False, f"Patch #{patch_id} tidak ditemukan di jurnal."

        backup_file = Path(target["backup_path"])
        if not backup_file.exists():
            return False, f"File backup '{target['backup_path']}' tidak ditemukan."

        dest_file = self.workspace_root / target["filepath"]
        try:
            shutil.copy2(backup_file, dest_file)
            return (
                True,
                f"File '{target['filepath']}' berhasil di-rollback ke versi Patch #{patch_id}.",
            )
        except Exception as e:
            return False, f"Error saat rollback: {e}"

    def rollback_latest(self) -> tuple[bool, str]:
        """Rollback the most recent patch."""
        journal = self._load_journal()
        if not journal:
            return False, "Belum ada riwayat patch untuk dibatalkan."
        latest_id = journal[-1]["id"]
        return self.rollback_patch(latest_id)
