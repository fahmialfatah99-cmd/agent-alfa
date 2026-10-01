"""Workspace file-context menu helpers."""

import os
from pathlib import Path
from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from alfa.core.cli.constants import print_status


def get_workspace_files(max_files: int = 100) -> list[str]:
    """Scan workspace files excluding heavy/system directories."""
    ignore_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        "venv",
        ".alfa_worktrees",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".alfa_backups",
        "dist",
        "build",
    }
    results = []
    root = Path.cwd()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for f in filenames:
            full = Path(dirpath) / f
            try:
                rel = str(full.relative_to(root))
                results.append(rel)
                if len(results) >= max_files:
                    return sorted(results)
            except Exception:
                pass
    return sorted(results)


def menu_manage_context_files(cli: Any) -> None:
    """Interactive checkbox file selector for prompt context."""
    files = get_workspace_files()
    if not files:
        print_status(
            "Tidak ada file yang terdeteksi di direktori proyek saat ini.", "warning"
        )
        return

    currently_attached = set(getattr(cli, "attached_files", []))

    choices = []
    for f in files:
        is_checked = f in currently_attached
        size_str = f"({os.path.getsize(f)} B)" if os.path.exists(f) else ""
        choices.append(Choice(f, f"{f:<40} {size_str}", enabled=is_checked))

    selected_files = inquirer.checkbox(
        message="Pilih file untuk konteks AI (Spasi untuk pilih/batal, Enter untuk konfirmasi):",
        choices=choices,
        instruction="(Tekan Spasi untuk Toggle, Enter untuk Simpan)",
    ).execute()

    cli.attached_files = list(selected_files)
    print_status(
        f"Konteks file diperbarui ({len(cli.attached_files)} file terpilih): {', '.join(cli.attached_files) if cli.attached_files else 'Kosong'}",
        "success",
    )
