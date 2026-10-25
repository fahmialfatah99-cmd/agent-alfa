"""
Reverse Engineering Tools for ALFA powered by REA (Reverse Engineer Anything).

Provides deep binary, Android APK, JavaScript/Electron application inspection,
decompilation, and non-intrusive forensic snapshot analysis.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
def rea_inspect_binary_or_wasm(file_path: str, operation: str = "file_headers") -> dict[str, Any]:
    """
    Inspeksi binary native (ELF, SO, DLL, Mach-O) atau artefak WebAssembly (.wasm) menggunakan objdump / WABT.

    Args:
        file_path: Jalur absolut atau relatif ke file binary atau .wasm target.
        operation: Jenis inspeksi objdump ('file_headers', 'section_headers', 'symbols', 'relocations', 'disassemble'). Default: 'file_headers'.
    """
    abs_file = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(abs_file):
        return {"status": "error", "message": f"Berkas binary tidak ditemukan: {abs_file}"}

    if abs_file.lower().endswith(".wasm"):
        return _run_rea_command(["inspect-wasm-artifact", abs_file])

    valid_ops = {"file_headers", "section_headers", "symbols", "relocations", "dwarf", "disassemble", "disassemble_all"}
    op = operation if operation in valid_ops else "file_headers"
    return _run_rea_command(["inspect-with-objdump", abs_file, op])


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


@register_tool(category="system")
def rea_android_device_control(
    action: str = "capture_screen",
    package_name: str = "",
    extra_arg: str = "",
) -> dict[str, Any]:
    """
    KONTROL PERANGKAT ANDROID JARAK JAUH VIA ADB & REA (FITUR SELEVEL OPENCLAW):
    Mengambil screenshot layar HP Android, meluncurkan atau menghentikan aplikasi Android,
    membaca logcat sistem, mengunduh file, atau mengecek daftar paket aplikasi yang terpasang.

    Args:
        action: Jenis aksi kontrol ('capture_screen', 'start_app', 'stop_app', 'read_logcat', 'list_packages', 'read_setting').
        package_name: Nama package aplikasi Android (misal: 'com.whatsapp', 'com.google.android.apps.maps').
        extra_arg: Parameter tambahan (misal: nama setting untuk 'read_setting', atau kata kunci untuk 'list_packages').

    Returns:
        Dict hasil eksekusi status, path file screenshot, atau teks respon dari perangkat.
    """
    act = action.strip().lower()
    try:
        if act == "capture_screen":
            res = _run_rea_command(["capture-adb-screen"])
            return res

        elif act == "start_app":
            if not package_name:
                return {"status": "error", "message": "Parameter 'package_name' wajib diisi untuk aksi 'start_app'."}
            return _run_rea_command(["start-adb-app", package_name])

        elif act == "stop_app":
            if not package_name:
                return {"status": "error", "message": "Parameter 'package_name' wajib diisi untuk aksi 'stop_app'."}
            return _run_rea_command(["stop-adb-app", package_name])

        elif act == "read_logcat":
            buffer_name = extra_arg or "main"
            return _run_rea_command(["read-adb-logcat", buffer_name])

        elif act == "list_packages":
            query = extra_arg or package_name
            return _run_rea_command(["resolve-adb-packages", query] if query else ["resolve-adb-packages", ""])

        elif act == "read_setting":
            setting_name = extra_arg or "airplane_mode_on"
            return _run_rea_command(["read-adb-setting", "system", setting_name])

        else:
            return {
                "status": "error",
                "message": f"Aksi '{action}' tidak dikenali. Gunakan: 'capture_screen', 'start_app', 'stop_app', 'read_logcat', 'list_packages', atau 'read_setting'.",
            }
    except Exception as e:
        logger.exception("Gagal eksekusi REA Android control: %s", e)
        return {"status": "error", "message": f"REA Android control error: {str(e)}"}


@register_tool(category="agent")
def rea_synthesize_skill_from_code(
    target_path: str,
    skill_topic: str = "",
    trigger_pattern: str = "",
) -> dict[str, Any]:
    """
    SINTESIS SKILL DARI REVERSE ENGINEERING KODE/APLIKASI LUAR (REA + HERMES LEARNING LOOP):
    Menganalisis bundle JavaScript, modul Python, atau artefak aplikasi lokal menggunakan REA,
    mengekstrak arsitektur, fungsi kunci, dan alur kerjanya, lalu secara otomatis mendaftarkannya
    menjadi Learned Skill di ALFA OS agar AI dapat menggunakannya di masa depan.

    Args:
        target_path: Jalur absolut/relatif ke file bundle JS, skrip Python, atau folder modul target.
        skill_topic: Topik atau nama kemampuan (misal: 'TELEGRAM_BOT_FLOW', 'EXCEL_EXPORT_ENGINE').
        trigger_pattern: Kata kunci pemicu aturan (misal: 'telegram bot export excel').

    Returns:
        Dict status sintesis, skill_id, dan rangkuman aturan yang dipelajari.
    """
    try:
        from alfa.core.brain.learning_loop import synthesize_skill_from_experience

        clean_path = os.path.abspath(os.path.expanduser(target_path))
        if not os.path.exists(clean_path):
            return {"status": "error", "message": f"Target path '{clean_path}' tidak ditemukan."}

        topic = (skill_topic or os.path.basename(clean_path)).strip().upper()
        topic = re.sub(r"[^A-Z0-9_]+", "_", topic).strip("_")

        # 1. Analisis menggunakan REA bila target adalah JavaScript / Bundle / SQLite
        analysis_summary = ""
        if clean_path.endswith((".js", ".asar", ".json")) or os.path.isdir(clean_path):
            rea_res = _run_rea_command(["analyze-javascript-application", clean_path])
            if rea_res.get("status") == "success":
                norm = rea_res.get("normalized", {})
                analysis_summary = f"REA Analysis: framework={norm.get('framework')}, exports={list(norm.get('exports', {}).keys())[:10]}"

        # 2. Ekstraksi kode atau dokumen teks langsung
        if not analysis_summary:
            if os.path.isfile(clean_path):
                try:
                    with open(clean_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = [line.strip() for line in f if line.strip() and not line.startswith(("#", "//"))]
                    analysis_summary = f"Source summary ({len(lines)} lines): " + " | ".join(lines[:10])
                except Exception as e:
                    analysis_summary = f"File inspection: {e}"
            else:
                analysis_summary = f"Directory target with {len(os.listdir(clean_path))} files."

        rule_text = (
            f"Aturan Rekonstruksi dari '{os.path.basename(clean_path)}': "
            f"{analysis_summary[:400]}. Gunakan pola ini saat menangani tugas terkait modul {topic}."
        )

        res = synthesize_skill_from_experience(
            topic=topic,
            learned_rule=rule_text,
            trigger_pattern=trigger_pattern or topic.lower().replace("_", " "),
        )

        return {
            "status": "success",
            "skill_id": res["skill_id"],
            "topic": res["topic"],
            "learned_rule": rule_text,
            "message": f"Skill '{res['topic']}' berhasil direverse-engineer dan disintesis ke memori permanen ALFA OS.",
        }
    except Exception as e:
        logger.exception("Gagal mensintesis skill dari kode: %s", e)
        return {"status": "error", "message": f"REA skill synthesis error: {str(e)}"}
