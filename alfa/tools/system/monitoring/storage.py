"""Storage cleanup tool."""

import logging
import os
import subprocess
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system.constants import SANDBOX_DIR

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def clean_system_storage(dry_run: bool = True) -> dict[str, Any]:
    """
    GOD MODE: Smart Linux Storage Cleaner & Optimizer.
    """
    try:
        cleanup_targets = [
            ("Thumbnail Cache", os.path.expanduser("~/.cache/thumbnails")),
            ("Sandbox Temp Files", SANDBOX_DIR),
            ("Python Cache", os.path.expanduser("~/.cache/pip")),
        ]

        report = []
        total_freed_mb = 0.0

        for name, path in cleanup_targets:
            if os.path.exists(path):
                size_b = sum(
                    os.path.getsize(os.path.join(dirpath, f))
                    for dirpath, _, filenames in os.walk(path)
                    for f in filenames
                    if not os.path.islink(os.path.join(dirpath, f))
                )
                size_mb = round(size_b / (1024 * 1024), 2)
                report.append({"target": name, "path": path, "size_mb": size_mb})
                total_freed_mb += size_mb

                if not dry_run and size_mb > 0:
                    subprocess.run(f'rm -rf "{path}"/*', shell=True, timeout=10)  # nosec B602 - path from fixed internal target list

        if not dry_run:
            subprocess.run(
                "journalctl --user --vacuum-time=2d 2>/dev/null",
                shell=True,
                timeout=10,  # nosec B602 - fixed string
            )

        action_msg = "ANALISIS (Dry Run)" if dry_run else "PEMBERSIHAN SELESAI"
        return {
            "status": "success",
            "mode": action_msg,
            "total_space_mb": round(total_freed_mb, 2),
            "details": report,
            "message": (
                f"{action_msg}: Potensi ruang dibersihkan: {round(total_freed_mb, 2)} MB. Jalankan dengan dry_run=False untuk eksekusi pembersihan nyata."
                if dry_run
                else f"Pembersihan berhasil! {round(total_freed_mb, 2)} MB ruang disk berhasil dikembalikan."
            ),
        }
    except Exception as e:
        return {"status": "error", "message": f"Storage cleanup error: {str(e)}"}
