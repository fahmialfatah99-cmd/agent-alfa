"""ArtCraft Suite Integration: Headless CLI automation and GUI launcher for Storyteller Craft apps."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.ArtCraft")

# Peta aplikasi ArtCraft yang didukung
ARTCRAFT_APPS: dict[str, dict[str, Any]] = {
    "photocraft": {
        "app_id": "ai.storyteller.photocraft",
        "cli_command": "photocraft-cli",
        "name": "PhotoCraft",
        "description": "Image editor with layers, masks, filters, and PSD/PSB support (Photoshop alternative).",
        "formats_read": [".psd", ".psb", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".ora", ".kra", ".exr", ".avif"],
        "formats_write": [".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".exr", ".psd"],
        "cli_subcommands": ["convert", "info", "run", "batch", "droplet", "commands", "mcp", "serve"],
    },
    "cadcraft": {
        "app_id": "ai.storyteller.cadcraft",
        "cli_command": "cadcraft-cli",
        "name": "CADCraft",
        "description": "2D/3D Computer-Aided Design and drafting for engineering/architecture (AutoCAD alternative).",
        "formats_read": [".dxf", ".dwg"],
        "formats_write": [".dxf", ".dwg", ".svg", ".png", ".pdf"],
        "cli_subcommands": ["info", "convert", "run", "commands", "sample", "mcp"],
    },
    "gridcraft": {
        "app_id": "ai.storyteller.gridcraft",
        "cli_command": "gridcraft-cli",
        "name": "GridCraft",
        "description": "High-performance spreadsheet application with formula evaluator and charts (Excel alternative).",
        "formats_read": [".xlsx", ".xlsb", ".ods", ".csv", ".tsv"],
        "formats_write": [".xlsx", ".csv", ".tsv", ".json", ".html", ".pdf"],
        "cli_subcommands": ["info", "convert", "eval", "cat", "check", "run", "commands", "functions", "mcp", "send"],
    },
    "lightcraft": {
        "app_id": "ai.storyteller.lightcraft",
        "cli_command": "lightcraft-cli",
        "name": "LightCraft",
        "description": "Photo library and non-destructive RAW photo development with AI denoise (Lightroom alternative).",
        "formats_read": [".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".heic", ".heif", ".jpg", ".jpeg", ".png", ".tif"],
        "formats_write": [".jpg", ".png", ".tif", ".webp", ".avif", ".jxl", ".psd", ".dng"],
        "cli_subcommands": ["run", "render", "snapshot", "merge", "commands", "controls", "mcp", "denoise-serve"],
    },
    "pdfcraft": {
        "app_id": "ai.storyteller.pdfcraft",
        "cli_command": "pdfcraft-cli",
        "name": "PdfCraft",
        "description": "PDF reader, merger, splitter, page organizer, and form editor (Acrobat alternative).",
        "formats_read": [".pdf"],
        "formats_write": [".pdf", ".png", ".jpg", ".tif"],
        "cli_subcommands": ["info", "render", "text", "edit", "combine", "extract", "split", "check", "audit", "batch", "tools", "run", "mcp", "ui"],
    },
    "designcraft": {
        "app_id": "ai.storyteller.designcraft",
        "cli_command": "designcraft-cli",
        "name": "DesignCraft",
        "description": "Page layout, typesetting, and print desktop publishing for books/magazines (InDesign alternative).",
        "formats_read": [".idml", ".designcraft"],
        "formats_write": [".pdf", ".png", ".designcraft"],
        "cli_subcommands": ["run", "commands", "describe", "script", "app", "mcp"],
    },
}


def _resolve_app_key(app_name: str) -> str | None:
    """Normalisasi nama aplikasi (misal: 'PhotoCraft', 'ai.storyteller.cadcraft' -> 'cadcraft')."""
    low = (app_name or "").strip().lower()
    for key, meta in ARTCRAFT_APPS.items():
        if low == key or low == meta["app_id"].lower() or low == meta["name"].lower():
            return key
        if key in low:
            return key
    return None


@register_tool(category="media")
def artcraft_get_capabilities() -> dict[str, Any]:
    """Petakan seluruh aplikasi ArtCraft Suite yang terpasang di sistem dan kemampuannya.

    Mengembalikan daftar lengkap aplikasi (PhotoCraft, CADCraft, GridCraft, LightCraft,
    PdfCraft, DesignCraft), versi terpasang, format berkas yang didukung, serta subperintah
    CLI yang siap dieksekusi secara otonom.
    """
    mapped_apps: dict[str, Any] = {}
    try:
        # Cek versi terpasang via flatpak
        res = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application,version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        installed_versions: dict[str, str] = {}
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    installed_versions[parts[0]] = parts[1]

        for key, meta in ARTCRAFT_APPS.items():
            app_id = meta["app_id"]
            ver = installed_versions.get(app_id, "uninstalled")
            mapped_apps[key] = {
                "name": meta["name"],
                "app_id": app_id,
                "installed": ver != "uninstalled",
                "version": ver,
                "description": meta["description"],
                "formats_read": meta["formats_read"],
                "formats_write": meta["formats_write"],
                "cli_subcommands": meta["cli_subcommands"],
            }
    except (OSError, subprocess.SubprocessError) as err:
        logger.warning(f"Gagal memeriksa kemampuan ArtCraft: {err}")

    # Tambahkan launcher
    launcher_path = shutil.which("artcraft-launcher") or os.path.expanduser("~/.local/bin/artcraft-launcher")
    launcher_installed = os.path.exists(launcher_path)
    mapped_apps["artcraft_launcher"] = {
        "name": "ArtCraft Launcher",
        "installed": launcher_installed,
        "path": launcher_path,
        "description": "Centralized ArtCraft Suite manager and updater.",
    }

    return {
        "status": "success",
        "total_apps": len(ARTCRAFT_APPS),
        "apps": mapped_apps,
    }


@register_tool(category="media")
def artcraft_run_cli(
    app_name: str,
    subcommand: str,
    args: list[str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Jalankan perintah headless CLI dari salah satu aplikasi ArtCraft Suite.

    Mengeksekusi engine ArtCraft secara cepat di latar belakang tanpa butuh layar visual GUI.
    Contoh:
    - photocraft-cli convert input.psd output.png
    - photocraft-cli info photo.jpg
    - gridcraft-cli convert report.xlsx output.csv
    - gridcraft-cli eval '=SUM(A1:A10)' --in data.xlsx
    - cadcraft-cli convert floorplan.dxf preview.svg
    - pdfcraft-cli info document.pdf
    - pdfcraft-cli render document.pdf --page 1 --out page1.png
    - lightcraft-cli render raw_photo.arw -o output.jpg

    Args:
        app_name: Nama aplikasi ('photocraft', 'cadcraft', 'gridcraft', 'lightcraft', 'pdfcraft', 'designcraft').
        subcommand: Subperintah CLI (misal: 'info', 'convert', 'eval', 'cat', 'run', 'render', 'combine', 'split').
        args: Daftar argumen tambahan (flag, input file, output file).
        timeout_seconds: Batas waktu eksekusi (default: 60 detik).
    """
    key = _resolve_app_key(app_name)
    if not key:
        return {
            "status": "error",
            "message": f"Aplikasi '{app_name}' tidak dikenal dalam katalog ArtCraft Suite.",
        }

    meta = ARTCRAFT_APPS[key]
    app_id = meta["app_id"]
    cli_bin = meta["cli_command"]

    cmd = [
        "flatpak",
        "run",
        f"--command={cli_bin}",
        app_id,
        subcommand.strip(),
    ]
    if args:
        # Kembangkan path file lokal jika ada
        for a in args:
            if a.startswith("~"):
                cmd.append(os.path.expanduser(a))
            else:
                cmd.append(a)

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "status": "success" if res.returncode == 0 else "error",
            "app": meta["name"],
            "command": " ".join(cmd),
            "returncode": res.returncode,
            "stdout": (res.stdout or "").strip()[:8000],
            "stderr": (res.stderr or "").strip()[:2000],
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Eksekusi CLI {cli_bin} melebihi batas waktu {timeout_seconds}s.",
        }
    except (OSError, subprocess.SubprocessError) as err:
        return {
            "status": "error",
            "message": f"Gagal mengeksekusi CLI {cli_bin}: {err}",
        }


@register_tool(category="media")
def artcraft_launch_gui(
    app_name: str,
    file_path: str | None = None,
    control_port: int | None = None,
) -> dict[str, Any]:
    """Luncurkan aplikasi desktop GUI ArtCraft ke layar monitor pengguna.

    Dapat membuka berkas proyek secara langsung dan opsional membuka port kendali automasi (--control).

    Args:
        app_name: Nama aplikasi ('photocraft', 'cadcraft', 'gridcraft', 'lightcraft', 'pdfcraft', 'designcraft', atau 'launcher').
        file_path: Path berkas proyek yang ingin dibuka (opsional).
        control_port: Nomor port untuk kontrol JSON-lines latar belakang (opsional).
    """
    if "launcher" in app_name.lower():
        launcher_bin = shutil.which("artcraft-launcher") or os.path.expanduser("~/.local/bin/artcraft-launcher")
        if not os.path.exists(launcher_bin):
            return {"status": "error", "message": "ArtCraft Launcher tidak terpasang di sistem."}
        try:
            subprocess.Popen([launcher_bin], start_new_session=True)
        except OSError as err:
            return {"status": "error", "message": f"Gagal membuka ArtCraft Launcher: {err}"}
        else:
            return {
                "status": "success",
                "message": "ArtCraft Launcher berhasil dibuka di layar.",
            }

    key = _resolve_app_key(app_name)
    if not key:
        return {
            "status": "error",
            "message": f"Aplikasi '{app_name}' tidak dikenal dalam katalog ArtCraft Suite.",
        }

    meta = ARTCRAFT_APPS[key]
    app_id = meta["app_id"]
    binary_name = key

    cmd = ["flatpak", "run", f"--command={binary_name}", app_id]
    if control_port:
        cmd.extend(["--control", str(control_port)])

    if file_path:
        expanded = os.path.expanduser(file_path.strip())
        if not Path(expanded).exists():
            return {
                "status": "error",
                "message": f"Berkas yang diminta '{file_path}' tidak ditemukan di sistem.",
            }
        cmd.append(expanded)

    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
        return {
            "status": "success",
            "message": f"Aplikasi {meta['name']} berhasil diluncurkan ke layar monitor.",
            "app": meta["name"],
            "pid": proc.pid,
            "opened_file": file_path,
            "control_port": control_port,
        }
    except (OSError, subprocess.SubprocessError) as err:
        return {
            "status": "error",
            "message": f"Gagal meluncurkan {meta['name']}: {err}",
        }
