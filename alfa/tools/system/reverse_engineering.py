"""
Reverse Engineering Tools for ALFA powered by REA (Reverse Engineer Anything).

Provides deep binary, Android APK, JavaScript/Electron application inspection,
decompilation, and non-intrusive forensic snapshot analysis.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.ReverseEngineering")

_REA_EXECUTABLE = shutil.which("rea") or "rea"
_REA_TIMEOUT_SECONDS = 60


def _run_rea_command(args: list[str], timeout: int = _REA_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Execute REA CLI command with JSON formatting and structured error handling."""
    cmd = [_REA_EXECUTABLE, *args, "--format", "json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": "error",
            "message": "Executable 'rea' tidak ditemukan. Pastikan 'rea-agents' terinstal via npm (npm install -g rea-agents).",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Eksekusi REA melebihi batas waktu ({timeout} detik).",
        }
    except OSError as e:
        return {
            "status": "error",
            "message": f"Gagal mengeksekusi perintah REA: {e}",
        }

    stdout_str = (proc.stdout or "").strip()
    stderr_str = (proc.stderr or "").strip()

    if proc.returncode != 0:
        return {
            "status": "error",
            "returncode": proc.returncode,
            "error": stderr_str or stdout_str or "Eksekusi REA gagal tanpa output pesan error.",
        }

    try:
        data = json.loads(stdout_str)
        return {
            "status": "success",
            "operation": data.get("operation") or (args[0] if args else "unknown"),
            "confidence": data.get("confidence", "observed"),
            "normalized": data.get("normalized_result") or {},
            "raw": data.get("raw_result"),
            "limitations": data.get("limitations") or [],
        }
    except json.JSONDecodeError:
        return {
            "status": "success",
            "output_text": stdout_str,
            "note": "Output bukan format JSON murni.",
        }


@register_tool(category="system")
def rea_inspect_android_package(apk_path: str) -> dict[str, Any]:
    """
    Inspeksi berkas aplikasi Android APK tanpa menjalankannya menggunakan REA.

    Mengekstrak metadata paket, versi SDK, izin (permissions), exported activities,
    layanan (services), receiver, dan arsitektur deklarasi aplikasi.

    Args:
        apk_path: Jalur absolut atau relatif ke berkas .apk target.
    """
    abs_path = os.path.abspath(os.path.expanduser(apk_path))
    if not os.path.exists(abs_path):
        return {"status": "error", "message": f"Berkas APK tidak ditemukan: {abs_path}"}

    return _run_rea_command(["inspect-android-package", abs_path])


@register_tool(category="system")
def rea_inspect_js_app(target_path: str) -> dict[str, Any]:
    """
    Rekonstruksi dan analisis statis aplikasi JavaScript / Electron (ASAR atau direktori proyek) menggunakan REA.

    Args:
        target_path: Jalur absolut atau relatif ke file .asar atau folder root aplikasi JavaScript.
    """
    abs_path = os.path.abspath(os.path.expanduser(target_path))
    if not os.path.exists(abs_path):
        return {"status": "error", "message": f"Target JavaScript/Electron tidak ditemukan: {abs_path}"}

    return _run_rea_command(["analyze-javascript-application", abs_path])


@register_tool(category="system")
def rea_recover_js_sources(bundle_path: str, output_dir: str = "") -> dict[str, Any]:
    """
    Memulihkan kode sumber JavaScript yang terbundel/terminifikasi menjadi modul-modul modular yang mudah dibaca.

    Args:
        bundle_path: Jalur ke berkas JavaScript (.js) input.
        output_dir: Folder tujuan penyimpanan modul terurai (dibuat otomatis jika kosong).
    """
    abs_bundle = os.path.abspath(os.path.expanduser(bundle_path))
    if not os.path.exists(abs_bundle):
        return {"status": "error", "message": f"Berkas bundle tidak ditemukan: {abs_bundle}"}

    if not output_dir:
        base_name = os.path.splitext(os.path.basename(abs_bundle))[0]
        output_dir = os.path.join(os.path.dirname(abs_bundle), f"recovered_{base_name}")

    abs_out = os.path.abspath(os.path.expanduser(output_dir))
    if os.path.exists(abs_out):
        shutil.rmtree(abs_out, ignore_errors=True)

    return _run_rea_command(["recover-javascript-sources", abs_bundle, abs_out])


@register_tool(category="system")
def rea_inspect_sqlite_database(db_path: str, table: str = "", row_limit: int = 20) -> dict[str, Any]:
    """
    Inspeksi skema database SQLite, indeks, views, dan contoh baris data secara non-intrusif & aman dari snapshot lokal.

    Args:
        db_path: Jalur absolut atau relatif ke file database SQLite (.db, .sqlite).
        table: (Opsional) Nama tabel spesifik jika ingin melihat baris data.
        row_limit: Batas jumlah sampel baris yang ditampilkan (default: 20).
    """
    abs_db = os.path.abspath(os.path.expanduser(db_path))
    if not os.path.exists(abs_db):
        return {"status": "error", "message": f"Berkas database tidak ditemukan: {abs_db}"}

    args = ["inspect-sqlite-database", abs_db]
    if table:
        args.extend(["--table", table, "--row-limit", str(max(1, min(row_limit, 100)))])
    else:
        args.extend(["--schema-scope", "inventory"])

    return _run_rea_command(args)


@register_tool(category="system")
def rea_inspect_binary_or_wasm(file_path: str) -> dict[str, Any]:
    """
    Inspeksi binary native (ELF, SO, DLL, Mach-O) atau artefak WebAssembly (.wasm) menggunakan objdump / WABT.

    Args:
        file_path: Jalur absolut atau relatif ke file binary atau .wasm target.
    """
    abs_file = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(abs_file):
        return {"status": "error", "message": f"Berkas binary tidak ditemukan: {abs_file}"}

    if abs_file.lower().endswith(".wasm"):
        return _run_rea_command(["inspect-wasm-artifact", abs_file])
    return _run_rea_command(["inspect-with-objdump", abs_file])


@register_tool(category="system")
def rea_run_command(subcommand: str, args_json: str = "[]") -> dict[str, Any]:
    """
    Eksekusi perintah arbitrer REA (Reverse Engineer Anything) untuk tugas forensik & analisis software khusus.

    Args:
        subcommand: Nama subcommand REA (misal: 'search-android-classes', 'decode-android-resources', 'inspect-web-network-capture', 'instructions').
        args_json: Argumen tambahan dalam format JSON string array, misal: '["arg1", "--flag"]'.
    """
    subcmd = subcommand.strip()
    if not subcmd or subcmd.startswith("-"):
        return {"status": "error", "message": "Nama subcommand REA wajib diisi dan valid."}

    extra_args: list[str] = []
    if args_json and args_json.strip():
        try:
            parsed = json.loads(args_json)
            if isinstance(parsed, list):
                extra_args = [str(x) for x in parsed]
            elif isinstance(parsed, str):
                extra_args = [parsed]
        except json.JSONDecodeError:
            extra_args = [args_json.strip()]

    return _run_rea_command([subcmd, *extra_args])
