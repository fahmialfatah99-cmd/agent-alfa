"""Execution tools for Bash and Python sandboxes."""

import logging
import os
import re
import subprocess
import sys
import time
from typing import Any

from alfa.core.tuning import host_exec_timeout, truncate_middle
from alfa.tools.registry import register_tool
from alfa.tools.system.constants import (
    _SANDBOX_IMAGE,
    SANDBOX_DIR,
    _bash_blocked_reason,
    _check_docker_available,
    _clean_code_snippet,
    _ensure_sandbox_image,
    _is_within,
    _sandbox_network,
    generate_self_heal_hint,
    is_unrestricted,
    resolve_sandbox_working_dir,
    sandbox_allowed_roots,
)

logger = logging.getLogger("AgentTools.System")


def _get_subprocess():
    mod = sys.modules.get("alfa.tools.system_tools")
    if mod and hasattr(mod, "subprocess"):
        return mod.subprocess
    return subprocess


def _docker_common_args(stamp: str) -> list[str]:
    """Basis argumen `docker run` yang di-hardening untuk semua sandbox.

    Termasuk pemutusan jaringan (`--network none` default), drop capabilitas,
    no-new-privileges, dan limit memori/CPU/PID. Mount spesifik tugas
    ditambahkan oleh pemanggil.
    """
    return [
        "run",
        "--rm",
        "--name",
        f"alfa_sbx_{stamp}",
        "--network",
        _sandbox_network(),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        *(
            ["--user", f"{os.getuid()}:{os.getgid()}"]
            if hasattr(os, "getuid")
            else []
        ),
        "-e",
        "HOME=/tmp",
        "--memory",
        os.getenv("SANDBOX_MEM_LIMIT", "512m"),
        "--memory-swap",
        os.getenv("SANDBOX_MEM_LIMIT", "512m"),
        "--cpus",
        os.getenv("SANDBOX_CPUS", "1.0"),
        "--pids-limit",
        "128",
    ]


@register_tool(category="system")
def execute_bash_command(
    command: str, working_dir: str = "", backend: str = ""
) -> dict[str, Any]:
    """
    Execute a Linux shell command. When unrestricted mode (ALFA_UNRESTRICTED) is active,
    executes directly on the host Linux system with full root/user privileges and no command blocks.
    In standard mode, runs inside an isolated Docker container with fallback to host.
    """
    sub = _get_subprocess()
    clean_cmd = _clean_code_snippet(command)
    if not clean_cmd:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": "Perintah bash kosong untuk dieksekusi.",
            "isolation": "none",
        }

    blocked = _bash_blocked_reason(clean_cmd)
    if blocked:
        logger.warning(f"Bash command BLOCKED ({blocked}): {clean_cmd[:200]}")
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"[KEAMANAN] Perintah diblokir: {blocked}.",
            "isolation": "rejected",
        }

    unrestricted = is_unrestricted()
    pref = (
        backend
        or os.getenv("ALFA_BASH_BACKEND", "host" if unrestricted else "auto")
    ).lower().strip()
    use_docker = (
        pref in ("auto", "docker")
        and _check_docker_available()
        and _ensure_sandbox_image()
    )

    script_path = None
    try:
        if use_docker:
            stamp = f"{os.getpid()}_{int(time.time() * 1000) % 10**9}"
            script_name = f"sandbox_sh_{stamp}.sh"
            script_path = os.path.join(SANDBOX_DIR, script_name)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(
                    "#!/bin/bash\nset -o pipefail\n" + clean_cmd + "\n"
                )

            wd_abs, wd_err = resolve_sandbox_working_dir(working_dir)
            if wd_err:
                logger.warning(f"[SECURITY] working_dir ditolak: {wd_err}")
                return {
                    "status": "error",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"[KEAMANAN] {wd_err}",
                    "isolation": "rejected",
                }
            cmd = ["docker", *_docker_common_args(stamp)]
            cmd += ["-v", f"{SANDBOX_DIR}:/sandbox"]
            if wd_abs:
                # Hanya working dir yang sudah lolos containment check yang
                # di-mount. TIDAK ada lagi mount `host:host` (yang membuat
                # container bisa mencapai path host di luar workspace).
                cmd += ["-v", f"{wd_abs}:/workspace", "-w", "/workspace"]
                cmd += ["-v", f"{wd_abs}:{wd_abs}"]
            else:
                cmd += ["-w", "/sandbox"]

            # Root lain yang diizinkan di-mount pada path sisi-container
            # (/alfa/rootN) supaya model tetap bisa menjangkau folder kerja
            # ALFA tanpa membuka path host secara bebas.
            for idx, root in enumerate(sandbox_allowed_roots()):
                if not os.path.isdir(root):
                    continue
                if wd_abs and _is_within(root, wd_abs):
                    continue  # sudah ter-mount lewat /workspace
                cmd += ["-v", f"{root}:/alfa/root{idx}"]
                cmd += ["-e", f"ALFA_SANDBOX_ROOT_{idx}={root}"]

            cmd += [_SANDBOX_IMAGE, "bash", f"/sandbox/{script_name}"]
            timeout_secs = int(os.getenv("SANDBOX_BASH_TIMEOUT", "55"))
            isolation = "docker"
        else:
            allow_host = unrestricted or (
                os.getenv("ALFA_ALLOW_HOST_EXEC", "false").strip().lower() == "true"
            )
            if not allow_host:
                logger.warning(
                    "[SECURITY] Host execution blocked: Docker unavailable and ALFA_ALLOW_HOST_EXEC != true."
                )
                return {
                    "status": "error",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": (
                        "[SECURITY] Eksekusi bash di host diblokir karena Docker tidak tersedia. "
                        "Set ALFA_ALLOW_HOST_EXEC=true di .env untuk mengizinkan eksekusi langsung di host. "
                        "PERINGATAN: Ini memungkinkan kode AI berjalan dengan hak akses penuh mesin ini."
                    ),
                    "isolation": "blocked",
                }
            if pref in ("auto", "docker"):
                logger.warning(
                    "[SECURITY] Docker tidak tersedia — eksekusi bash dialihkan ke HOST (ALFA_ALLOW_HOST_EXEC=true). Pastikan ALLOWED_USER_IDS terkonfigurasi ketat."
                )
            if unrestricted:
                # Mode unrestricted: bebaskan working_dir ke host mana pun tanpa batasan root sandbox
                if working_dir and str(working_dir).strip():
                    wd_cand = os.path.realpath(os.path.expanduser(str(working_dir).strip()))
                    target_dir = wd_cand if os.path.isdir(wd_cand) else os.path.realpath(os.path.expanduser("~"))
                else:
                    target_dir = os.path.realpath(os.path.expanduser("~"))
            else:
                # Containment check berlaku untuk eksekusi di host biasa: working_dir
                # tetap harus berada di dalam root yang diizinkan.
                wd_abs, wd_err = resolve_sandbox_working_dir(working_dir)
                if wd_err:
                    logger.warning(f"[SECURITY] working_dir ditolak: {wd_err}")
                    return {
                        "status": "error",
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": f"[KEAMANAN] {wd_err}",
                        "isolation": "rejected",
                    }
                target_dir = (
                    wd_abs
                    if wd_abs
                    else os.path.realpath(os.path.expanduser("~"))
                )
            if not os.path.exists(target_dir):
                target_dir = os.path.realpath(os.path.expanduser("~"))
            # Proteksi: cegah find merambah ke remote cloud mounts (rclone FUSE di /mnt/.remotes dan ~/GDrive)
            if re.search(r"\bfind\s+", clean_cmd) and "-xdev" not in clean_cmd:
                clean_cmd = re.sub(r"(\bfind\s+)([~/][^\s\-]*|\$HOME[^\s\-]*)(\s+)", r"\1\2 -xdev\3", clean_cmd)

            if os.name == "nt":
                git_bash = r"C:\Program Files\Git\bin\bash.exe"
                if os.path.exists(git_bash):
                    cmd = [git_bash, "-lc", clean_cmd]
                else:
                    cmd = ["powershell", "-NoProfile", "-Command", clean_cmd]
            else:
                cmd = ["bash", "-c", clean_cmd]
            timeout_secs = host_exec_timeout(unrestricted, default_restricted=45)
            isolation = "none"

        logger.info(f"Executing bash ({isolation}): {command[:150]}")
        try:
            # If sub has a fake or patched run without real subprocess, test compatibility:
            if hasattr(sub, "run") and sub.run is not subprocess.run:
                res = sub.run(cmd, capture_output=True, text=True, timeout=timeout_secs)
                result = res
            else:
                popen_kwargs: dict[str, Any] = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "cwd": target_dir if isolation == "none" else None,
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = getattr(
                        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                    )
                else:
                    popen_kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **popen_kwargs)
                try:
                    out, errout = proc.communicate(timeout=timeout_secs)
                    result = subprocess.CompletedProcess(
                        cmd, proc.returncode or 0, out, errout
                    )
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                capture_output=True,
                                timeout=10,
                            )
                        else:
                            import signal as _sig

                            try:
                                pgid = os.getpgid(proc.pid)
                                if pgid != os.getpgrp():
                                    os.killpg(pgid, _sig.SIGKILL)
                                else:
                                    proc.kill()
                            except Exception:
                                proc.kill()
                    except Exception:
                        pass
                    try:
                        out, errout = proc.communicate(timeout=5)
                    except Exception:
                        out, errout = "", ""
                    return {
                        "status": "error",
                        "exit_code": -1,
                        "stdout": (out or "")[:3500],
                        "stderr": f"[TIMEOUT] Perintah melebihi {timeout_secs}s — pohon proses dihentikan paksa.",
                        "isolation": isolation,
                    }
        finally:
            if script_path:
                try:
                    os.remove(script_path)
                except OSError:
                    pass

        stdout = truncate_middle(
            result.stdout.strip() if hasattr(result, "stdout") and result.stdout else "",
            3500,
        )
        stderr = truncate_middle(
            result.stderr.strip() if hasattr(result, "stderr") and result.stderr else "",
            1200,
        )

        warn = (
            ""
            if isolation == "docker"
            else " [PERINGATAN: dieksekusi di HOST tanpa isolasi]"
        )
        returncode = result.returncode if hasattr(result, "returncode") else 0
        hint = (
            generate_self_heal_hint("execute_bash_command", "", stdout, stderr)
            if returncode != 0
            else None
        )
        return {
            "status": "success" if returncode == 0 else "failed",
            "exit_code": returncode,
            "stdout": stdout or "(tidak ada output standar)",
            "stderr": (stderr or None),
            "isolation": isolation,
            "message": "Perintah selesai." + warn,
            "self_heal_hint": hint,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Command execution timed out ({timeout_secs}s).",
            "isolation": isolation,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "isolation": "none"}


@register_tool(category="system")
def execute_python_sandbox(code: str) -> dict[str, Any]:
    """
    Execute a Python script. When unrestricted mode (ALFA_UNRESTRICTED) is active,
    executes directly on the host Linux OS with full access to host files, packages, and hardware.
    In standard mode, runs in an isolated Docker container with resource limits.
    """
    sub = _get_subprocess()
    cleaned = _clean_code_snippet(code)
    if not cleaned:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": "Kode kosong untuk dieksekusi.",
            "has_plot": False,
            "isolation": "none",
        }
    try:
        compile(cleaned, "<sandbox>", "exec")
    except SyntaxError as syn_err:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Syntax error di baris {syn_err.lineno}: {syn_err.msg}",
            "has_plot": False,
            "isolation": "none",
        }

    unrestricted = is_unrestricted()
    backend_pref = (
        os.getenv("SANDBOX_BACKEND", "none" if unrestricted else "auto").lower().strip()
    )
    use_docker = (
        backend_pref in ("auto", "docker")
        and _check_docker_available()
        and _ensure_sandbox_image()
    )

    # Fail-CLOSED: tanpa Docker, Python TIDAK boleh jatuh ke host kecuali
    # operator opting-in eksplisit (ALFA_ALLOW_HOST_EXEC=true). Sebelumnya
    # jalur ini diam-diam berjalan di host tanpa izin — hanya beda
    # perlakuan dengan execute_bash_command. Dicek SEBELUM file script
    # ditulis supaya tidak ada sisa kode di disk.
    allow_host = unrestricted or (
        os.getenv("ALFA_ALLOW_HOST_EXEC", "false").strip().lower() == "true"
    )
    if not use_docker and not allow_host:
        logger.warning(
            "[SECURITY] Host execution blocked (Python): Docker unavailable "
            "and ALFA_ALLOW_HOST_EXEC != true."
        )
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": (
                "[SECURITY] Eksekusi Python di host diblokir karena Docker "
                "tidak tersedia. Set ALFA_ALLOW_HOST_EXEC=true di .env untuk "
                "mengizinkan eksekusi langsung di host. PERINGATAN: Ini "
                "memungkinkan kode AI berjalan dengan hak akses penuh mesin ini."
            ),
            "isolation": "blocked",
            "has_plot": False,
        }

    stamp = f"{os.getpid()}_{int(time.time() * 1000) % 10**9}"
    script_name = f"sandbox_run_{stamp}.py"
    plot_name = f"generated_plot_{stamp}.png"
    script_path = os.path.join(SANDBOX_DIR, script_name)
    plot_path = os.path.join(SANDBOX_DIR, plot_name)
    for old in ("sandbox_run.py", "generated_plot.png"):
        old_p = os.path.join(SANDBOX_DIR, old)
        if os.path.exists(old_p):
            try:
                os.remove(old_p)
            except OSError:
                pass

    try:
        plot_target = f"/sandbox/{plot_name}" if use_docker else plot_path
        preamble = (
            "import os\n"
            "try:\n"
            "    import matplotlib\n"
            "    matplotlib.use('Agg')\n"
            "    import matplotlib.pyplot as plt\n"
            f"    _plot_target = '{plot_target}'\n"
            "    def _auto_save():\n"
            "        if plt.get_fignums():\n"
            "            plt.savefig(_plot_target, bbox_inches='tight', dpi=150)\n"
            "            plt.close('all')\n"
            "    import atexit\n"
            "    atexit.register(_auto_save)\n"
            "except ImportError:\n"
            "    pass\n\n"
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(preamble + cleaned)

        if use_docker:
            cmd = ["docker", *_docker_common_args(stamp)]
            cmd += ["-v", f"{SANDBOX_DIR}:/sandbox", "-w", "/sandbox"]
            # Root yang diizinkan di-mount pada path sisi-container saja —
            # TIDAK ada mount `host:host` yang membuka path host di dalam
            # container.
            for idx, root in enumerate(sandbox_allowed_roots()):
                if not os.path.isdir(root):
                    continue
                if _is_within(root, SANDBOX_DIR):
                    continue  # sudah ter-mount lewat /sandbox
                cmd += ["-v", f"{root}:/alfa/root{idx}"]
                cmd += ["-e", f"ALFA_SANDBOX_ROOT_{idx}={root}"]

            cmd += [_SANDBOX_IMAGE, "python", f"/sandbox/{script_name}"]
            timeout_secs = 45
            isolation = "docker"
        else:
            cmd = [sys.executable, script_path]
            timeout_secs = host_exec_timeout(unrestricted, default_restricted=30)
            isolation = "none"
            logger.warning(
                "[SECURITY] Docker sandbox unavailable - menjalankan Python "
                "di HOST (ALFA_ALLOW_HOST_EXEC=true). Tidak ada isolasi."
            )

        try:
            if hasattr(sub, "run") and sub.run is not subprocess.run:
                res = sub.run(cmd, capture_output=True, text=True, timeout=timeout_secs)
            else:
                popen_kwargs: dict[str, Any] = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "cwd": None,
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = getattr(
                        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                    )
                else:
                    popen_kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **popen_kwargs)
                try:
                    out, errout = proc.communicate(timeout=timeout_secs)
                    res = subprocess.CompletedProcess(
                        cmd, proc.returncode if proc.returncode is not None else 0, out, errout
                    )
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                capture_output=True,
                                timeout=10,
                            )
                        else:
                            import signal as _sig

                            try:
                                pgid = os.getpgid(proc.pid)
                                if pgid != os.getpgrp():
                                    os.killpg(pgid, _sig.SIGKILL)
                                else:
                                    proc.kill()
                            except Exception:
                                proc.kill()
                    except Exception:
                        pass
                    try:
                        out, errout = proc.communicate(timeout=5)
                    except Exception:
                        out, errout = "", ""
                    return {
                        "status": "error",
                        "exit_code": -1,
                        "stdout": truncate_middle(out or "", 3500),
                        "stderr": f"[TIMEOUT] Eksekusi Python melebihi {timeout_secs}s — pohon proses dihentikan paksa.",
                        "has_plot": False,
                        "isolation": isolation,
                    }
        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

        stdout = truncate_middle(
            res.stdout.strip() if hasattr(res, "stdout") and res.stdout else "",
            3500,
        )
        stderr = truncate_middle(
            res.stderr.strip() if hasattr(res, "stderr") and res.stderr else "",
            1200,
        )
        returncode = res.returncode if hasattr(res, "returncode") else 0
        has_plot = os.path.exists(plot_path) and os.path.getsize(plot_path) > 0
        hint = (
            generate_self_heal_hint("execute_python_sandbox", "", stdout, stderr)
            if returncode != 0
            else None
        )

        return {
            "status": "success" if returncode == 0 else "error",
            "exit_code": returncode,
            "stdout": stdout or "(tidak ada print output)",
            "stderr": stderr or None,
            "generated_chart_photo": has_plot,
            "isolation": isolation,
            "message": (
                "Grafik visual berhasil dibuat dan akan dikirim ke Telegram!"
                if has_plot
                else "Eksekusi kode selesai."
            )
            + ("" if isolation == "docker" else " [PERINGATAN: tanpa isolasi]"),
            "self_heal_hint": hint,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Eksekusi Python melebihi batas waktu ({timeout_secs} detik).",
            "isolation": isolation,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Python runner error: {str(e)}",
            "isolation": "none",
        }
