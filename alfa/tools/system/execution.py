"""Execution tools for Bash and Python sandboxes."""

import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from alfa.tools.registry import register_tool
from alfa.tools.system.constants import (
    SANDBOX_DIR,
    _SANDBOX_IMAGE,
    _bash_blocked_reason,
    _check_docker_available,
    _clean_code_snippet,
    _ensure_sandbox_image,
    generate_self_heal_hint,
)

logger = logging.getLogger("AgentTools.System")


def _get_subprocess():
    mod = sys.modules.get("alfa.tools.system_tools")
    if mod and hasattr(mod, "subprocess"):
        return mod.subprocess
    return subprocess


@register_tool(category="system")
def execute_bash_command(command: str, working_dir: str = "", backend: str = "") -> Dict[str, Any]:
    """
    Execute a Linux shell command SAFELY inside an isolated Docker sandbox by
    default (resource-limited, no privileges). Falls back to a direct host run
    ONLY when Docker is unavailable, or when backend='host' is requested
    explicitly. Destructive command patterns are always rejected first.
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

    pref = (backend or os.getenv("ALFA_BASH_BACKEND", "auto")).lower().strip()
    use_docker = (
        pref in ("auto", "docker")
        and _check_docker_available()
        and _ensure_sandbox_image()
    )

    script_path = None
    try:
        if use_docker:
            stamp = f"{os.getpid()}_{int(time.time()*1000)%10**9}"
            script_name = f"sandbox_sh_{stamp}.sh"
            script_path = os.path.join(SANDBOX_DIR, script_name)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write("#!/bin/bash\nset -o pipefail\n" + (command or "").strip() + "\n")

            wd_abs = os.path.realpath(os.path.expanduser(working_dir)) if working_dir else ""
            cmd = [
                "docker", "run", "--rm",
                "--name", f"alfa_sbx_{stamp}",
                "-v", f"{SANDBOX_DIR}:/sandbox",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                *(["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []),
                "-e", "HOME=/tmp",
                "--memory", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--memory-swap", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--cpus", os.getenv("SANDBOX_CPUS", "1.0"),
                "--pids-limit", "128",
            ]
            if wd_abs and os.path.isdir(wd_abs):
                cmd += ["-v", f"{wd_abs}:/workspace", "-w", "/workspace"]
                cmd += ["-v", f"{wd_abs}:{wd_abs}"]
            else:
                cmd += ["-w", "/sandbox"]

            tf = os.getenv("ALFA_TARGET_FOLDER", "").strip()
            if tf and os.path.isdir(tf) and tf != wd_abs:
                cmd += ["-v", f"{tf}:{tf}"]

            user_home = os.path.expanduser("~")
            project_dirs = [
                os.path.join(user_home, "alfa_projects"),
                os.path.join(user_home, "ALFA_WORKSPACE"),
                os.path.join(user_home, "Dokumen", "ALFA_SWARM_OUTPUTS"),
                os.path.join(user_home, "output"),
            ]
            for pdir in project_dirs:
                if os.path.isdir(pdir) and pdir != wd_abs and pdir != tf:
                    cmd += ["-v", f"{pdir}:{pdir}"]

            cmd += [_SANDBOX_IMAGE, "bash", f"/sandbox/{script_name}"]
            timeout_secs = int(os.getenv("SANDBOX_BASH_TIMEOUT", "55"))
            isolation = "docker"
        else:
            allow_host = os.getenv("ALFA_ALLOW_HOST_EXEC", "false").strip().lower() == "true"
            if not allow_host:
                logger.warning("[SECURITY] Host execution blocked: Docker unavailable and ALFA_ALLOW_HOST_EXEC != true.")
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
                logger.warning("[SECURITY] Docker tidak tersedia — eksekusi bash dialihkan ke HOST (ALFA_ALLOW_HOST_EXEC=true). Pastikan ALLOWED_USER_IDS terkonfigurasi ketat.")
            target_dir = os.path.expanduser(working_dir) if working_dir else os.path.expanduser("~")
            if not os.path.exists(target_dir):
                target_dir = os.path.expanduser("~")
            if os.name == "nt":
                git_bash = r"C:\Program Files\Git\bin\bash.exe"
                if os.path.exists(git_bash):
                    cmd = [git_bash, "-lc", command]
                else:
                    cmd = ["powershell", "-NoProfile", "-Command", command]
            else:
                cmd = ["bash", "-c", command]
            timeout_secs, isolation = 45, "none"

        logger.info(f"Executing bash ({isolation}): {command[:150]}")
        try:
            # If sub has a fake or patched run without real subprocess, test compatibility:
            if hasattr(sub, "run") and sub.run is not subprocess.run:
                res = sub.run(cmd, capture_output=True, text=True, timeout=timeout_secs)
                result = res
            else:
                popen_kwargs: Dict[str, Any] = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "cwd": target_dir if isolation == "none" else None,
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    popen_kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **popen_kwargs)
                try:
                    out, errout = proc.communicate(timeout=timeout_secs)
                    result = subprocess.CompletedProcess(cmd, proc.returncode or 0, out, errout)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                           capture_output=True, timeout=10)
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

        stdout = result.stdout.strip() if hasattr(result, "stdout") and result.stdout else ""
        stderr = result.stderr.strip() if hasattr(result, "stderr") and result.stderr else ""
        if len(stdout) > 3500:
            stdout = stdout[:3500] + "\n...[Output terpotong karena terlalu panjang]"
        if len(stderr) > 1200:
            stderr = stderr[:1200] + "\n...[Stderr terpotong]"

        warn = "" if isolation == "docker" else " [PERINGATAN: dieksekusi di HOST tanpa isolasi]"
        returncode = result.returncode if hasattr(result, "returncode") else 0
        hint = generate_self_heal_hint("execute_bash_command", "", stdout, stderr) if returncode != 0 else None
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
        return {"status": "error", "message": f"Command execution timed out ({timeout_secs}s).", "isolation": isolation}
    except Exception as e:
        return {"status": "error", "message": str(e), "isolation": "none"}


@register_tool(category="system")
def execute_python_sandbox(code: str) -> Dict[str, Any]:
    """
    Execute a Python script in an ISOLATED Docker container (default) with
    resource limits and no privileges. Falls back to a local subprocess only
    when Docker is unavailable or SANDBOX_BACKEND=none.
    """
    sub = _get_subprocess()
    cleaned = _clean_code_snippet(code)
    if not cleaned:
        return {"status": "error", "exit_code": -1, "stdout": "", "stderr": "Kode kosong untuk dieksekusi.", "has_plot": False, "isolation": "none"}
    try:
        compile(cleaned, "<sandbox>", "exec")
    except SyntaxError as syn_err:
        return {
            "status": "error", "exit_code": -1, "stdout": "",
            "stderr": f"Syntax error di baris {syn_err.lineno}: {syn_err.msg}",
            "has_plot": False, "isolation": "none",
        }

    backend_pref = os.getenv("SANDBOX_BACKEND", "auto").lower().strip()
    use_docker = (
        backend_pref in ("auto", "docker")
        and _check_docker_available()
        and _ensure_sandbox_image()
    )

    stamp = f"{os.getpid()}_{int(time.time()*1000)%10**9}"
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
            cmd = [
                "docker", "run", "--rm",
                "--name", f"alfa_sbx_{stamp}",
                "-v", f"{SANDBOX_DIR}:/sandbox",
                "-w", "/sandbox",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                *(["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []),
                "-e", "HOME=/tmp",
                "--memory", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--memory-swap", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--cpus", os.getenv("SANDBOX_CPUS", "1.0"),
                "--pids-limit", "128",
            ]
            user_home = os.path.expanduser("~")
            project_dirs = [
                os.path.join(user_home, "alfa_projects"),
                os.path.join(user_home, "ALFA_WORKSPACE"),
                os.path.join(user_home, "Dokumen", "ALFA_SWARM_OUTPUTS"),
                os.path.join(user_home, "output"),
            ]
            for pdir in project_dirs:
                if os.path.isdir(pdir):
                    cmd += ["-v", f"{pdir}:{pdir}"]

            cmd += [_SANDBOX_IMAGE, "python", f"/sandbox/{script_name}"]
            timeout_secs = 45
            isolation = "docker"
        else:
            cmd = [sys.executable, script_path]
            timeout_secs = 30
            isolation = "none"
            if backend_pref in ("auto", "docker"):
                logger.warning("Docker sandbox unavailable - falling back to DIRECT execution (no isolation).")

        try:
            res = sub.run(cmd, capture_output=True, text=True, timeout=timeout_secs)
        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

        stdout = res.stdout.strip() if hasattr(res, "stdout") and res.stdout else ""
        stderr = res.stderr.strip() if hasattr(res, "stderr") and res.stderr else ""
        returncode = res.returncode if hasattr(res, "returncode") else 0
        has_plot = os.path.exists(plot_path) and os.path.getsize(plot_path) > 0
        hint = generate_self_heal_hint("execute_python_sandbox", "", stdout, stderr) if returncode != 0 else None

        return {
            "status": "success" if returncode == 0 else "error",
            "exit_code": returncode,
            "stdout": stdout or "(tidak ada print output)",
            "stderr": stderr or None,
            "generated_chart_photo": has_plot,
            "isolation": isolation,
            "message": ("Grafik visual berhasil dibuat dan akan dikirim ke Telegram!" if has_plot else "Eksekusi kode selesai.")
                        + ("" if isolation == "docker" else " [PERINGATAN: tanpa isolasi]"),
            "self_heal_hint": hint,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Eksekusi Python melebihi batas waktu ({timeout_secs} detik).", "isolation": isolation}
    except Exception as e:
        return {"status": "error", "message": f"Python runner error: {str(e)}", "isolation": "none"}
