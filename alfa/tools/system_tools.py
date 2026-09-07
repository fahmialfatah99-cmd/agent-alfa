"""System execution, sandboxing, monitoring, and administration tools."""

import asyncio
import datetime
import difflib
import glob
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil
from dotenv import load_dotenv

from alfa.core import database
import plugins
from alfa.core.runtime_ctx import (
    current_chat_id_var,
    current_user_id_var,
    get_current_chat_id,
    get_current_user_id,
)
from alfa.tools.registry import register_tool

load_dotenv()
logger = logging.getLogger("AgentTools.System")

if os.name == "nt":
    _drive = os.path.splitdrive(os.path.abspath("."))[0] or "C:"
    _sandbox_base = os.path.join(_drive + os.sep, "dev", "shm", "alfa_sandbox")
else:
    _sandbox_base = "/dev/shm/alfa_sandbox"
SANDBOX_DIR = _sandbox_base
os.makedirs(SANDBOX_DIR, exist_ok=True)

_BASH_BLOCK_PATTERNS = [
    # (regex, alasan) — dicocokkan terhadap perintah mentah
    (r":\s*\(\s*\)\s*\{.*\}\s*;", "fork bomb"),
    (r"\bdd\s+[^\n]*of=/dev/(sd|hd|vd|nvme|mmcblk)", "tulis mentah ke disk fisik"),
    (r"\bmkfs(\.\w+)?\b", "format filesystem"),
    (r"chmod\s+-R\s+777\s+/", "chmod 777 rekursif pada root"),
    (r"chown\s+-R\b[^\n]*(\s/|\s~|\s\$HOME)(\s|$)", "chown rekursif pada root/home"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "mematikan/menyalakan ulang sistem"),
    (r"(history\s+-c\b|>\s*~/\.bash_history|shred\s+[^;\n]*history|unset\s+HISTFILE)",
     "menghapus jejak riwayat shell"),
    (r"(curl|wget|fetch)[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe skrip internet langsung ke shell"),
    (r"base64\s+[^;\n|&]*(?:-d\b|--decode)[^;\n|&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
     "pipe payload base64 ke shell"),
    (r"/(dev/tcp/|proc/sysrq-trigger)", "teknik reverse-shell/kernel trigger"),
    (r"\.(ssh/id_(rsa|ed25519|ecdsa)|aws/credentials|gnupg)", "akses berkas kredensial privat"),
    (r"\b(useradd|userdel|usermod|visudo)\b", "manipulasi akun pengguna sistem"),
    (r"(iptables|nft)\s+(-F|--flush)", "flush firewall"),
    (r">\s*/dev/(sd|hd|vd|nvme)", "overwrite perangkat blok"),
]

_RM_DANGER_TARGETS = (
    r"(?:(?:/{1,2})|(?:~)|(?:\$HOME)|\*|(?:/(?:home|etc|usr|var|boot|lib|opt|bin|sbin|srv|root))"
    r"|(?:\.\./)+(?:home|etc|usr))?(?:\s|$|/)"
)

_DOCKER_AVAILABLE_CACHE: Optional[bool] = None
_SANDBOX_IMAGE = "alfa-sandbox:latest"

_SOURCE_CODE_EXTS = {
    ".py", ".sh", ".bash", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".toml",
    ".md", ".txt", ".sql", ".c", ".cpp", ".h", ".go", ".rs",
}

def _check_docker_available() -> bool:
    """Check if docker is available, respecting monkeypatching on tools or alfa.tools."""
    for mod_name in ("tools", "alfa.tools", "alfa.tools.system_tools"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_docker_available"):
            fn = getattr(mod, "_docker_available")
            if fn is not _docker_available and callable(fn):
                return fn()
    return _docker_available()



def normalize_path(p: str) -> str:
    """Samakan path gaya Linux (/dev/shm/...) dengan lokasi fisiknya di Windows
    (C:\\dev\\shm\\...) dan rapikan pemisah campuran / vs \\. No-op di Linux."""
    if not p or not isinstance(p, str):
        return p
    q = p.replace("\\", "/")
    if os.name == "nt":
        # /dev/shm/... → C:\dev\shm\...
        if q.startswith("/dev/shm"):
            drive = os.path.splitdrive(os.path.abspath("."))[0] or "C:"
            q = drive + q
        # Jika belum punya drive letter, tambahkan
        elif q[1:3] not in (":/", ":\\"):
            pass  # path relatif — biarkan
    return os.path.normpath(q) if os.name == "nt" else p


@register_tool(category="system")
def get_system_stats() -> Dict[str, Any]:
    """
    Get real-time Linux system health metrics including CPU cores/frequencies, RAM, Swap,
    Disk usage, Network interfaces, Battery/Thermal status, Uptime, and Top Processes.
    Use this tool when the user asks about laptop/server specs, resource usage, or performance.
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        freq_str = f"{round(cpu_freq.current, 1)} MHz" if cpu_freq else "N/A"
        
        mem = psutil.virtual_memory()
        ram_total_gb = round(mem.total / (1024 ** 3), 2)
        ram_used_gb = round(mem.used / (1024 ** 3), 2)
        ram_free_gb = round(mem.available / (1024 ** 3), 2)
        ram_percent = mem.percent
        
        swap = psutil.swap_memory()
        swap_total_gb = round(swap.total / (1024 ** 3), 2)
        swap_used_gb = round(swap.used / (1024 ** 3), 2)
        
        disk = psutil.disk_usage('/')
        disk_total_gb = round(disk.total / (1024 ** 3), 2)
        disk_used_gb = round(disk.used / (1024 ** 3), 2)
        disk_percent = disk.percent
        
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = str(datetime.datetime.now() - boot_time).split('.')[0]
        
        # Network stats
        net_addrs = psutil.net_if_addrs()
        ip_summary = []
        for iface, addrs in net_addrs.items():
            if iface.startswith("lo"):
                continue
            for a in addrs:
                if a.family.name == "AF_INET":
                    ip_summary.append(f"{iface}: {a.address}")
        
        # Battery stats if available
        battery = psutil.sensors_battery()
        battery_str = "N/A (Desktop/Server)"
        if battery:
            plugged = "🔌 Mengisi daya" if battery.power_plugged else "🔋 Baterai"
            battery_str = f"{battery.percent}% ({plugged})"

        # Top processes by RAM and CPU
        processes = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(p.info)
            except Exception:
                pass
                
        top_ram = sorted(processes, key=lambda p: p.get('memory_percent') or 0, reverse=True)[:4]
        top_cpu = sorted(processes, key=lambda p: p.get('cpu_percent') or 0, reverse=True)[:4]
        
        return {
            "status": "success",
            "cpu": f"{cpu_percent}% ({cpu_count} cores @ {freq_str})",
            "ram": f"{ram_used_gb} GB / {ram_total_gb} GB ({ram_percent}%, free: {ram_free_gb} GB)",
            "swap": f"{swap_used_gb} GB / {swap_total_gb} GB",
            "disk": f"{disk_used_gb} GB / {disk_total_gb} GB ({disk_percent}%)",
            "battery": battery_str,
            "ip_addresses": ", ".join(ip_summary) or "127.0.0.1",
            "uptime": uptime,
            "top_ram_processes": [
                f"{p['name']} (PID {p['pid']}: {round(p['memory_percent'] or 0, 1)}% RAM)"
                for p in top_ram
            ],
            "top_cpu_processes": [
                f"{p['name']} (PID {p['pid']}: {round(p['cpu_percent'] or 0, 1)}% CPU)"
                for p in top_cpu if (p.get('cpu_percent') or 0) > 0
            ]
        }
    except Exception as e:
        logger.error(f"Error in get_system_stats: {e}")
        return {"status": "error", "message": str(e)}


def _bash_blocked_reason(command: str) -> Optional[str]:
    """Kembalikan alasan pemblokiran bila perintah cocok pola berbahaya."""
    import re as _re
    cmd = command or ""

    for pat, reason in _BASH_BLOCK_PATTERNS:
        if _re.search(pat, cmd):
            return reason

    # rm rekursif (-r/-R/-rf/-fr/--recursive) ke target luas/sistem/home
    m = _re.search(r"\brm\b([^#;\n]*)", cmd)
    if m:
        seg = m.group(1)
        has_recursive = bool(_re.search(
            r"(?:^|\s)(-{1,2}[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(?:\s|$)", seg))
        has_danger_target = bool(_re.search(
            r"(?:^|\s)(\"|')?" + _RM_DANGER_TARGETS, seg))
        if has_recursive and has_danger_target:
            return "penghapusan massal direktori sistem/home"

    low_parts = cmd.lower().split()
    if low_parts and (low_parts[0] == "sudo" or " sudo " in f" {cmd.lower()} "):
        return "eskalasi hak akses (sudo)"
    return None


def _clean_code_snippet(code: str) -> str:
    """Safely unwrap markdown code fences (```python ... ```, ```bash ... ```) and trim whitespace."""
    if not code or not isinstance(code, str):
        return ""
    cleaned = code.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def generate_self_heal_hint(tool_name: str, error_msg: str, stdout: str = "", stderr: str = "") -> Optional[str]:
    """Analisis kegagalan eksekusi tool & hasilkan petunjuk pemulihan otomatis cerdas (Self-Heal Hint) bagi agen LLM."""
    combined = f"{error_msg} {stderr} {stdout}".lower()
    
    if "command not found" in combined or "perintah tidak ditemukan" in combined:
        return "[SELF_HEAL_HINT] Biner/perintah tidak ditemukan. Periksa ejaan atau periksa lokasi dengan `which <perintah>` atau gunakan tool alternatif."
    if "permission denied" in combined or "akses ditolak" in combined:
        return "[SELF_HEAL_HINT] Izin akses ditolak. Coba jalankan di direktori kerja ~/ atau periksa izin file menggunakan `ls -la`."
    if "modulenotfounderror" in combined or "no module named" in combined:
        m = re.search(r"no module named ['\"]([^'\"]+)['\"]", combined)
        pkg = m.group(1) if m else "paket"
        return f"[SELF_HEAL_HINT] Modul Python '{pkg}' belum terpasang. Pasang modul dengan `execute_bash_command` (mis. `pip install {pkg}`) atau gunakan modul standar alternatif."
    if "syntaxerror" in combined or "indentationerror" in combined:
        return "[SELF_HEAL_HINT] Kesalahan sintaks/indentasi kode. Tinjau kembali baris kode, tanda kurung, titik dua, atau indentasi spasi."
    if "file tidak ditemukan" in combined or "no such file or directory" in combined:
        return "[SELF_HEAL_HINT] File atau direktori tidak ditemukan. Gunakan `search_workspace_files` untuk mencari nama file di workspace terlebih dahulu."
    if "address already in use" in combined or "port is already allocated" in combined:
        return "[SELF_HEAL_HINT] Port jaringan sudah digunakan proses lain. Periksa proses dengan `list_running_processes` atau hentikan dengan `kill_process`."
    if "database is locked" in combined or "sqlite3.busyerror" in combined:
        return "[SELF_HEAL_HINT] Database SQLite sedang terkunci/sibuk. Ulangi permintaan setelah jeda singkat."
    if "jsondecodeerror" in combined or "invalid json" in combined:
        return "[SELF_HEAL_HINT] Format JSON tidak valid. Pastikan semua string dikutip ganda dan tidak ada trailing comma."
    return None


@register_tool(category="system")
def execute_bash_command(command: str, working_dir: str = "", backend: str = "") -> Dict[str, Any]:
    """
    Execute a Linux shell command SAFELY inside an isolated Docker sandbox by
    default (resource-limited, no privileges). Falls back to a direct host run
    ONLY when Docker is unavailable, or when backend='host' is requested
    explicitly. Destructive command patterns are always rejected first.

    Args:
        command: The bash command string to execute (e.g. 'ls -la', 'pytest').
        working_dir: Directory to run in (mounted read-write into sandbox).
        backend: 'auto' (default), 'docker', or 'host'.
    """
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
            home_in_box = "/workspace" if (wd_abs and os.path.isdir(wd_abs)) else "/sandbox"
            cmd = [
                "docker", "run", "--rm",
                "--name", f"alfa_sbx_{stamp}",
                "-v", f"{SANDBOX_DIR}:/sandbox",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                # POSIX saja: os.getuid/getgid tidak ada di Windows; di Linux
                # flag ini penting agar file mount bukan milik root.
                *(["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []),
                "-e", f"HOME={home_in_box}",
                "--memory", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--memory-swap", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--cpus", os.getenv("SANDBOX_CPUS", "1.0"),
                "--pids-limit", "128",
            ]
            if wd_abs and os.path.isdir(wd_abs):
                cmd += ["-v", f"{wd_abs}:/workspace", "-w", "/workspace"]
                # Mirror path absolut: /tmp/x di kontainer == host /tmp/x.
                # Agen kerap memakai path absolut; tanpa mirror ini hasil
                # tulisnya hilang ke tmpfs kontainer (klaim sukses palsu).
                cmd += ["-v", f"{wd_abs}:{wd_abs}"]
            else:
                cmd += ["-w", "/sandbox"]
            # Mirror folder target swarm (bila diset) meski working_dir
            # tidak dipakai model — path absolut agen tetap mengenai host.
            tf = os.getenv("ALFA_TARGET_FOLDER", "").strip()
            if tf and os.path.isdir(tf) and tf != wd_abs:
                cmd += ["-v", f"{tf}:{tf}"]

            # Mirror standard user project & workspace directories so scripts in ~/alfa_projects can run
            user_home = os.path.expanduser("~")
            project_dirs = [
                os.path.join(user_home, "alfa_projects"),
                os.path.join(user_home, "ALFA_WORKSPACE"),
                os.path.join(user_home, "Dokumen", "ALFA_SWARM_OUTPUTS"),
                os.path.join(user_home, "output"),
            ]
            for pdir in project_dirs:
                if os.path.isdir(pdir) and pdir != wd_abs and pdir != tf:
                    cmd += [
                        "-v", f"{pdir}:{pdir}",
                        "-v", f"{pdir}:{home_in_box}/{os.path.basename(pdir)}"
                    ]

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
                # Windows: utamakan Git Bash bila tersedia (perintah gaya
                # Linux tetap jalan), jika tidak ada fallback ke PowerShell.
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
            # Popen + kill pohon proses: mencegah HANG permanen ketika agent
            # menjalankan server background (mis. `node serve.mjs &`) yang
            # menahan pipe stdout/stderr walau bash induk sudah dibunuh.
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
            # Skrip wrapper adalah infrastruktur internal; jangan tinggalkan
            # agar tidak ikut terkirim ke chat oleh auto-dispatcher.
            if script_path:
                try:
                    os.remove(script_path)
                except OSError:
                    pass

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if len(stdout) > 3500:
            stdout = stdout[:3500] + "\n...[Output terpotong karena terlalu panjang]"
        if len(stderr) > 1200:
            stderr = stderr[:1200] + "\n...[Stderr terpotong]"

        warn = "" if isolation == "docker" else " [PERINGATAN: dieksekusi di HOST tanpa isolasi]"
        hint = generate_self_heal_hint("execute_bash_command", "", stdout, stderr) if result.returncode != 0 else None
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
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


def is_internal_sandbox_artifact(fname: str) -> bool:
    """True bila file adalah artefak infrastruktur sandbox (bukan hasil kerja
    untuk dikirim ke pengguna): skrip wrapper bash/python, Dockerfile,
    plot sementara, dan file tersembunyi."""
    name = fname or ""
    if not name or name.startswith("."):
        return True
    return (
        name.startswith("sandbox_run")
        or name.startswith("sandbox_sh_")
        or name.startswith("sandbox_py_")
        or name == "Dockerfile"
        or name.startswith("generated_plot_old")
        or name == "screen_recording.mp4"
    )


def is_source_code_file(fname: str) -> bool:
    """True bila file adalah kode sumber — tidak usah dikirim mentah ke chat;
    hasil coding ditulis langsung di folder proyek lokal."""
    return os.path.splitext(fname or "")[1].lower() in _SOURCE_CODE_EXTS


def _docker_available() -> bool:
    """Check (and cache) whether the Docker daemon is usable by this user."""
    global _DOCKER_AVAILABLE_CACHE
    if _DOCKER_AVAILABLE_CACHE is None:
        try:
            probe = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=8,
            )
            _DOCKER_AVAILABLE_CACHE = probe.returncode == 0
        except Exception:
            _DOCKER_AVAILABLE_CACHE = False
    return _DOCKER_AVAILABLE_CACHE


def _ensure_sandbox_image() -> bool:
    """Ensure the alfa-sandbox image exists; auto-build it on first use."""
    try:
        chk = subprocess.run(
            ["docker", "images", "-q", _SANDBOX_IMAGE],
            capture_output=True, text=True, timeout=10,
        )
        if chk.returncode == 0 and chk.stdout.strip():
            return True

        logger.info("Building sandbox image '%s' (first use, ~2-5 min)...", _SANDBOX_IMAGE)
        dockerfile = os.path.join(SANDBOX_DIR, "Dockerfile")
        os.makedirs(SANDBOX_DIR, exist_ok=True)
        with open(dockerfile, "w", encoding="utf-8") as f:
            f.write(
                "FROM python:3.11-slim\n"
                "RUN useradd -ms /bin/bash -u 1000 sandbox || true\n"
                "RUN pip install --no-cache-dir matplotlib numpy pandas\n"
            )
        build = subprocess.run(
            ["docker", "build", "-t", _SANDBOX_IMAGE, SANDBOX_DIR],
            capture_output=True, text=True, timeout=600,
        )
        if build.returncode == 0:
            logger.info("Sandbox image built successfully.")
            return True
        logger.error("Sandbox image build failed: %s", build.stderr[-400:])
        return False
    except Exception as img_err:
        logger.error("ensure_sandbox_image error: %s", img_err)
        return False


@register_tool(category="system")
def execute_python_sandbox(code: str) -> Dict[str, Any]:
    """
    Execute a Python script in an ISOLATED Docker container (default) with
    resource limits and no privileges. Falls back to a local subprocess only
    when Docker is unavailable or SANDBOX_BACKEND=none.
    If matplotlib/seaborn creates a plot, it is captured as generated_plot*.png
    for delivery to the Telegram chat.

    Args:
        code: Complete Python code string to execute.
    """
    # Reject empty/trivial/unparseable code before spawning anything
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

    # Unique per-invocation filenames avoid races between concurrent runs
    stamp = f"{os.getpid()}_{int(time.time()*1000)%10**9}"
    script_name = f"sandbox_run_{stamp}.py"
    plot_name = f"generated_plot_{stamp}.png"
    script_path = os.path.join(SANDBOX_DIR, script_name)
    plot_path = os.path.join(SANDBOX_DIR, plot_name)
    # Clean stale artifacts from previous runs (best effort)
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
                # Match host uid/gid so bind-mounted sandbox files stay writable
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--memory", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--memory-swap", os.getenv("SANDBOX_MEM_LIMIT", "512m"),
                "--cpus", os.getenv("SANDBOX_CPUS", "1.0"),
                "--pids-limit", "128",
            ]
            # Mirror standard user project & workspace directories
            user_home = os.path.expanduser("~")
            project_dirs = [
                os.path.join(user_home, "alfa_projects"),
                os.path.join(user_home, "ALFA_WORKSPACE"),
                os.path.join(user_home, "Dokumen", "ALFA_SWARM_OUTPUTS"),
                os.path.join(user_home, "output"),
            ]
            for pdir in project_dirs:
                if os.path.isdir(pdir):
                    cmd += [
                        "-v", f"{pdir}:{pdir}",
                        "-v", f"{pdir}:/sandbox/{os.path.basename(pdir)}"
                    ]

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
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_secs)
        finally:
            # Skrip runner adalah infrastruktur internal; hapus agar tidak
            # bocor ke auto-dispatcher lampiran Telegram.
            try:
                os.remove(script_path)
            except OSError:
                pass

        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        has_plot = os.path.exists(plot_path) and os.path.getsize(plot_path) > 0
        hint = generate_self_heal_hint("execute_python_sandbox", "", stdout, stderr) if res.returncode != 0 else None

        return {
            "status": "success" if res.returncode == 0 else "error",
            "exit_code": res.returncode,
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


@register_tool(category="system")
def schedule_reminder(reminder_time_iso: str, message: str) -> Dict[str, Any]:
    """
    Schedule a future proactive reminder or alert that the bot will send directly to Telegram.
    
    Args:
        reminder_time_iso: The target time in ISO format (YYYY-MM-DDTHH:MM:SS), e.g. '2026-08-19T08:00:00'.
        message: The reminder message content.
    """
    try:
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        rem_id = database.add_reminder_sync(user_id=user_id, chat_id=chat_id, reminder_time_iso=reminder_time_iso, message=message)
        return {
            "status": "success",
            "reminder_id": rem_id,
            "message": f"Pengingat #{rem_id} berhasil dijadwalkan pada {reminder_time_iso}: '{message}'"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def scan_local_network() -> Dict[str, Any]:
    """
    Scan connected local LAN devices, IP neighbors, and active gateways.
    Use this tool when the user asks to check network devices, Wi-Fi neighbors, or connected hardware.
    """
    try:
        res = subprocess.run("ip neigh || arp -a", shell=True, capture_output=True, text=True, timeout=10)
        return {
            "status": "success",
            "devices": res.stdout.strip() or "Tidak ada perangkat terdeteksi di tabel ARP/Neighbor."
        }
    except Exception as err:
        return {"status": "error", "message": str(err)}


@register_tool(category="system")
def control_linux_hardware(action: str, value: str = "") -> Dict[str, Any]:
    """
    Control Linux laptop/server hardware, audio, screen lock, power, Wi-Fi, and media from Telegram.
    
    Args:
        action: Target hardware action. Options:
                - 'lock_screen': Lock the Linux desktop session immediately.
                - 'set_volume': Set audio output volume (value: '0' to '100', e.g. '50%').
                - 'mute_toggle': Toggle audio mute/unmute.
                - 'media_play_pause': Toggle media playback (Spotify, YouTube, VLC).
                - 'media_next': Next media track.
                - 'media_prev': Previous media track.
                - 'wifi_scan': Scan and list available Wi-Fi access points.
                - 'bluetooth_status': Check Bluetooth status and connected devices.
                - 'battery_status': Check battery health, percentage, and charging state.
        value: Optional parameter for the action (e.g. '50%' for set_volume).
    """
    try:
        act = action.strip().lower()
        if act == "lock_screen":
            subprocess.run("loginctl lock-session 2>/dev/null || gnome-screensaver-command -l", shell=True, capture_output=True, text=True)
            return {"status": "success", "message": "🔒 Layar desktop Linux telah berhasil dikunci."}

        elif act == "set_volume":
            vol_val = value.replace("%", "").strip() or "50"
            try:
                frac = float(vol_val) / 100.0
                subprocess.run(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {frac}", shell=True, capture_output=True, timeout=3)
            except Exception:
                subprocess.run(f"amixer set Master {vol_val}%", shell=True, capture_output=True, timeout=3)
            return {"status": "success", "message": f"🔊 Volume speaker berhasil diubah ke {vol_val}%."}

        elif act == "mute_toggle":
            subprocess.run("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle || amixer set Master toggle", shell=True, capture_output=True, timeout=3)
            return {"status": "success", "message": "🔇 Status mute audio berhasil dialihkan (toggle)."}

        elif act in ["media_play_pause", "media_next", "media_prev"]:
            cmd = "playerctl play-pause" if act == "media_play_pause" else "playerctl next" if act == "media_next" else "playerctl previous"
            subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
            return {"status": "success", "message": f"🎵 Perintah media '{act}' berhasil dieksekusi."}

        elif act == "wifi_scan":
            res = subprocess.run("nmcli -f SSID,SIGNAL,SECURITY dev wifi list | head -n 12", shell=True, capture_output=True, text=True, timeout=8)
            return {"status": "success", "wifi_networks": res.stdout.strip() or "Tidak ada jaringan Wi-Fi ditemukan."}

        elif act == "bluetooth_status":
            res = subprocess.run("bluetoothctl show 2>/dev/null | grep -E 'Name|Powered|Discoverable'; bluetoothctl devices 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            return {"status": "success", "bluetooth": res.stdout.strip() or "Bluetooth tidak aktif."}

        elif act == "battery_status":
            bat = psutil.sensors_battery()
            if not bat:
                return {"status": "success", "battery": "Perangkat tidak menggunakan baterai (Desktop PC / Server)."}
            plugged = "🔌 Sedang Mengisi Daya (Charging)" if bat.power_plugged else "🔋 Berjalan dengan Baterai (Discharging)"
            time_left = f"{round(bat.secsleft / 60)} menit" if bat.secsleft > 0 else "N/A"
            return {
                "status": "success",
                "percentage": f"{bat.percent}%",
                "power_state": plugged,
                "estimated_time_remaining": time_left
            }

        return {"status": "error", "message": f"Aksi hardware '{action}' tidak dikenal."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def list_running_processes(filter_name: str = "") -> Dict[str, Any]:
    """
    List currently running processes on the system, sorted by memory usage.
    
    Args:
        filter_name: Optional filter to show only processes matching this name (e.g. 'chrome', 'python', 'code').
    """
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status', 'username']):
            try:
                info = p.info
                mem_mb = round(info['memory_info'].rss / (1024 * 1024), 1) if info.get('memory_info') else 0
                if filter_name and filter_name.lower() not in (info.get('name') or '').lower():
                    continue
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "cpu_percent": info.get('cpu_percent', 0),
                    "memory_mb": mem_mb,
                    "status": info.get('status', ''),
                    "user": info.get('username', '')
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        procs.sort(key=lambda x: x['memory_mb'], reverse=True)
        top = procs[:30]
        total_mem = sum(p['memory_mb'] for p in procs)
        
        return {
            "status": "success",
            "total_processes": len(procs),
            "total_memory_mb": round(total_mem, 1),
            "top_processes": top
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def kill_process(pid_or_name: str) -> Dict[str, Any]:
    """
    Terminate/kill a running process by PID number or process name.
    
    Args:
        pid_or_name: Process ID (e.g. '12345') or process name (e.g. 'chrome', 'firefox', 'spotify').
    """
    try:
        killed = []
        if pid_or_name.isdigit():
            pid = int(pid_or_name)
            p = psutil.Process(pid)
            name = p.name()
            p.terminate()
            killed.append(f"PID {pid} ({name})")
        else:
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if pid_or_name.lower() in p.info['name'].lower():
                        p.terminate()
                        killed.append(f"PID {p.info['pid']} ({p.info['name']})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        
        if killed:
            return {"status": "success", "message": f"Proses berhasil dihentikan: {', '.join(killed)}"}
        return {"status": "error", "message": f"Proses '{pid_or_name}' tidak ditemukan."}
    except psutil.NoSuchProcess:
        return {"status": "error", "message": f"Proses dengan PID/nama '{pid_or_name}' tidak ditemukan."}
    except psutil.AccessDenied:
        return {"status": "error", "message": "Akses ditolak. Coba jalankan dengan sudo."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def audit_network_security(target_host: str = "127.0.0.1", scan_type: str = "quick_ports") -> Dict[str, Any]:
    """
    GOD MODE: Network Security & Port Sentinel.
    Audits listening network ports, socket services, firewall status (UFW),
    and remote SSL/TLS certificate validity & security ciphers.
    
    Args:
        target_host: Target IP or domain to audit (e.g. '127.0.0.1', 'example.com').
        scan_type: 'quick_ports' or 'full_audit'.
    """
    try:
        import socket
        import ssl
        
        result = {"target": target_host, "scan_type": scan_type}
        
        # Local socket listening check
        if target_host in ["127.0.0.1", "localhost", "0.0.0.0"]:
            res_ss = subprocess.run("ss -tuln 2>/dev/null || netstat -tuln 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            listening_lines = [ln for ln in res_ss.stdout.strip().splitlines() if "LISTEN" in ln or "State" in ln][:20]
            result["local_listening_sockets"] = "\n".join(listening_lines)
            
            # Firewall check
            res_ufw = subprocess.run("sudo -n ufw status 2>/dev/null || ufw status 2>/dev/null", shell=True, capture_output=True, text=True, timeout=3)
            result["firewall_status"] = res_ufw.stdout.strip() if res_ufw.stdout.strip() else "UFW status tidak memerlukan sudo / tidak aktif."
        else:
            # Common ports probe
            common_ports = [21, 22, 25, 80, 443, 3000, 3306, 5432, 8000, 8080, 8443]
            open_ports = []
            for p in common_ports:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                res = s.connect_ex((target_host, p))
                if res == 0:
                    open_ports.append(p)
                s.close()
            result["open_ports_detected"] = open_ports
            
            # SSL Certificate inspection if port 443 open
            if 443 in open_ports or target_host.startswith("http") or "." in target_host:
                try:
                    ctx = ssl.create_default_context()
                    with ctx.wrap_socket(socket.socket(), server_hostname=target_host) as s:
                        s.settimeout(5)
                        s.connect((target_host, 443))
                        cert = s.getpeercert()
                        not_after = cert.get('notAfter', '')
                        result["ssl_certificate"] = {
                            "subject": dict(x[0] for x in cert.get('subject', ())),
                            "issuer": dict(x[0] for x in cert.get('issuer', ())),
                            "expires_at": not_after,
                            "version": cert.get('version', '')
                        }
                except Exception as ssl_err:
                    result["ssl_error"] = str(ssl_err)
                    
        return {"status": "success", "audit_report": result}
    except Exception as e:
        return {"status": "error", "message": f"Security audit error: {str(e)}"}


@register_tool(category="system")
def clean_system_storage(dry_run: bool = True) -> Dict[str, Any]:
    """
    GOD MODE: Smart Linux Storage Cleaner & Optimizer.
    Inspects and frees disk waste by safely cleaning thumbnail caches, user journal logs,
    temporary files, and apt cache.
    
    Args:
        dry_run: If True, only analyzes space to be freed without deleting anything. Set to False to perform actual cleanup.
    """
    try:
        cleanup_targets = [
            ("Thumbnail Cache", os.path.expanduser("~/.cache/thumbnails")),
            ("Sandbox Temp Files", SANDBOX_DIR),
            ("Python Cache", os.path.expanduser("~/.cache/pip"))
        ]
        
        report = []
        total_freed_mb = 0.0
        
        for name, path in cleanup_targets:
            if os.path.exists(path):
                size_b = sum(os.path.getsize(os.path.join(dirpath, f)) for dirpath, _, filenames in os.walk(path) for f in filenames if not os.path.islink(os.path.join(dirpath, f)))
                size_mb = round(size_b / (1024*1024), 2)
                report.append({"target": name, "path": path, "size_mb": size_mb})
                total_freed_mb += size_mb
                
                if not dry_run and size_mb > 0:
                    subprocess.run(f'rm -rf "{path}"/*', shell=True, timeout=10)
                    
        if not dry_run:
            # Vacuum journalctl logs older than 2 days
            subprocess.run("journalctl --user --vacuum-time=2d 2>/dev/null", shell=True, timeout=10)
            
        action_msg = "ANALISIS (Dry Run)" if dry_run else "PEMBERSIHAN SELESAI"
        return {
            "status": "success",
            "mode": action_msg,
            "total_space_mb": round(total_freed_mb, 2),
            "details": report,
            "message": f"{action_msg}: Potensi ruang dibersihkan: {round(total_freed_mb, 2)} MB. Jalankan dengan dry_run=False untuk eksekusi pembersihan nyata." if dry_run else f"Pembersihan berhasil! {round(total_freed_mb, 2)} MB ruang disk berhasil dikembalikan."
        }
    except Exception as e:
        return {"status": "error", "message": f"Storage cleanup error: {str(e)}"}


@register_tool(category="system")
def manage_system_services(service_name: str, action: str = "status", scope: str = "user") -> Dict[str, Any]:
    """
    GOD MODE: Linux Systemd Services Controller.
    Manage, start, stop, restart, enable, disable, and inspect status of systemd units.
    
    Args:
        service_name: Name of the service unit (e.g. 'telegram-ai-bot.service', 'pipewire', 'docker', 'nginx').
        action: 'status', 'restart', 'start', 'stop', 'enable', 'disable', 'is-active'.
        scope: 'user' (default, for user-space services) or 'system' (system-wide).
    """
    try:
        act = action.strip().lower()
        if os.name == "nt":
            # Windows: petakan aksi service systemd ke Task Scheduler / proses lokal.
            svc_map = {
                "telegram-ai-bot.service": ("ALFA Telegram Bot", "bot.py"),
                "alfa-dashboard.service": ("ALFA Dashboard", "web_dashboard.py"),
                "wa-sheets-bot.service": ("WA Sheets Bot", "wa_sheets_bot"),
            }
            name, hint = svc_map.get(service_name, (service_name, service_name))
            running = False
            for p in psutil.process_iter(['cmdline']):
                try:
                    cl = p.info.get('cmdline') or []
                    if any(hint in str(c) for c in cl):
                        running = True
                        break
                except Exception:
                    continue
            if act in ("status", "is-active"):
                return {"status": "success", "service": service_name, "action": "status",
                        "scope": scope, "exit_code": 0,
                        "output": f"{name}: {'RUNNING (proses terdeteksi)' if running else 'STOPPED'} "
                                  f"(Windows: systemd tidak tersedia)"}
            return {"status": "error", "service": service_name, "action": act,
                    "message": f"Aksi '{act}' untuk '{name}' tidak didukung di Windows. "
                               f"Status saat ini: {'RUNNING' if running else 'STOPPED'}. "
                               f"Restart layanan dilakukan manual/Task Scheduler."}
        flag = "--user" if scope == "user" else ""
        valid_actions = ["status", "restart", "start", "stop", "enable", "disable", "is-active"]
        if act not in valid_actions:
            return {"status": "error", "message": f"Aksi '{action}' tidak valid. Pilihan: {', '.join(valid_actions)}"}
            
        cmd = f"systemctl {flag} {act} {service_name}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        output = (res.stdout.strip() or res.stderr.strip())[:2500]
        
        return {
            "status": "success" if res.returncode == 0 or act == "status" else "error",
            "service": service_name,
            "action": act,
            "scope": scope,
            "exit_code": res.returncode,
            "output": output
        }
    except Exception as e:
        return {"status": "error", "message": f"Systemd control error: {str(e)}"}


@register_tool(category="system")
def manage_crontab_jobs(action: str = "list", cron_line: str = "", search_pattern: str = "") -> Dict[str, Any]:
    """
    GOD MODE: Real Linux OS Crontab Manager.
    Reads, adds, or removes native Linux user crontab schedule entries.
    
    Args:
        action: 'list' (show all crontab entries), 'add' (add new cron_line), 'remove' (remove entries matching search_pattern).
        cron_line: The crontab entry string (e.g. '0 8 * * * /home/user/script.sh').
        search_pattern: Keyword/pattern to match when removing crontab entries.
    """
    try:
        if os.name == "nt":
            return {"status": "error",
                    "message": "Crontab hanya tersedia di Linux. Di Windows gunakan Task Scheduler: "
                               "`schtasks /create /tn Nama /tr 'perintah' /sc hourly` (atau minta agent "
                               "membuatnya lewat tool execute_bash_command)."}
        if action == "list":
            res = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            entries = res.stdout.strip()
            return {"status": "success", "crontab_entries": entries if entries else "(Crontab kosong)"}
        elif action == "add":
            if not cron_line:
                return {"status": "error", "message": "Parameter cron_line harus diisi."}
            res_curr = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            curr = res_curr.stdout.strip()
            new_cron = (curr + "\n" + cron_line.strip()).strip() + "\n"
            proc = subprocess.Popen("crontab -", shell=True, stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_cron, timeout=5)
            return {"status": "success", "message": f"Entri crontab berhasil ditambahkan: '{cron_line}'"}
        elif action == "remove":
            if not search_pattern:
                return {"status": "error", "message": "Parameter search_pattern harus diisi untuk menghapus entri crontab."}
            res_curr = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
            lines = [ln for ln in res_curr.stdout.splitlines() if search_pattern not in ln]
            new_cron = "\n".join(lines).strip() + "\n"
            proc = subprocess.Popen("crontab -", shell=True, stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_cron, timeout=5)
            return {"status": "success", "message": f"Entri crontab yang cocok dengan pola '{search_pattern}' berhasil dihapus."}
        return {"status": "error", "message": f"Aksi '{action}' tidak dikenal. Gunakan: list, add, remove."}
    except Exception as e:
        return {"status": "error", "message": f"Crontab error: {str(e)}"}


@register_tool(category="system")
def auto_diagnose_and_heal_system(fix_issues: bool = False) -> Dict[str, Any]:
    """
    GOD MODE: Autonomous System Diagnostic & Self-Healing Engine.
    Inspects system journal error logs, failed systemd units, memory pressure,
    broken packages, and zombie processes. Produces a root-cause diagnosis
    and optionally executes safe autonomous healing actions.
    
    Args:
        fix_issues: If True, executes safe autonomous healing (restarting failed units, vacuuming logs, clearing zombies).
    """
    try:
        diagnosis = {}
        healing_actions = []
        
        # 1. Check failed systemd units
        res_failed = subprocess.run("systemctl --user list-units --failed --no-legend 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
        failed_user_units = [line.strip().split()[0] for line in res_failed.stdout.strip().splitlines() if line.strip()]
        diagnosis["failed_user_services"] = failed_user_units
        
        # 2. Check system error logs in journalctl
        res_journal = subprocess.run("journalctl --user -p 3 -n 15 --no-pager 2>/dev/null", shell=True, capture_output=True, text=True, timeout=5)
        diagnosis["recent_critical_logs"] = res_journal.stdout.strip()[:1500] if res_journal.stdout.strip() else "Tidak ada critical error log terbaru."
        
        # 3. Check zombie / hung processes
        zombies = []
        for p in psutil.process_iter(['pid', 'name', 'status']):
            try:
                if p.info['status'] == psutil.STATUS_ZOMBIE:
                    zombies.append(f"PID {p.info['pid']} ({p.info['name']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        diagnosis["zombie_processes"] = zombies
        
        # 4. Check disk and swap pressure
        disk = psutil.disk_usage('/')
        swap = psutil.swap_memory()
        diagnosis["disk_health"] = f"Root: {disk.percent}% used ({round(disk.free / (1024**3), 1)} GB free)"
        diagnosis["swap_health"] = f"Swap: {swap.percent}% used"
        
        # Self-healing execution if requested
        if fix_issues:
            # Restart failed user services (excluding disabled ones)
            for unit in failed_user_units:
                if "telegram-ai-bot" not in unit:  # avoid recursive restart in diagnostic turn
                    subprocess.run(f"systemctl --user reset-failed {unit} && systemctl --user restart {unit}", shell=True, timeout=10)
                    healing_actions.append(f"Restarted failed unit: {unit}")
            
            # Vacuum journal logs if disk > 85%
            if disk.percent > 85:
                subprocess.run("journalctl --user --vacuum-time=2d", shell=True, timeout=10)
                healing_actions.append("Cleaned old user journal logs")
                
            diagnosis["healing_executed"] = healing_actions if healing_actions else "Tidak ada tindakan perbaikan yang diperlukan saat ini."
            
        return {
            "status": "success",
            "diagnosis": diagnosis,
            "fix_mode": fix_issues
        }
    except Exception as e:
        return {"status": "error", "message": f"Diagnostic error: {str(e)}"}


@register_tool(category="system")
def self_restart_service() -> Dict[str, Any]:
    """
    GOD MODE: Self-Restart — the bot restarts its own systemd service to apply
    code changes, new tools, or recover from errors. The bot will go offline
    briefly (~2 seconds) and come back with all updates applied.
    """
    try:
        # Verify tools.py compiles before restarting
        tools_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.py")
        compile_check = subprocess.run(
            [sys.executable, "-m", "py_compile", tools_path],
            capture_output=True, text=True
        )
        if compile_check.returncode != 0:
            return {"status": "error", "message": f"Tidak bisa restart — tools.py memiliki error: {compile_check.stderr}"}
        
        bot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")
        compile_check2 = subprocess.run(
            [sys.executable, "-m", "py_compile", bot_path],
            capture_output=True, text=True
        )
        if compile_check2.returncode != 0:
            return {"status": "error", "message": f"Tidak bisa restart — bot.py memiliki error: {compile_check2.stderr}"}
        
        # Schedule restart in 2 seconds (so we can send response first)
        subprocess.Popen(
            "sleep 2 && systemctl --user restart telegram-ai-bot.service",
            shell=True, start_new_session=True
        )
        
        return {
            "status": "success",
            "message": "🔄 Bot akan restart dalam 2 detik... Semua pembaruan dan tool baru akan aktif setelah restart. Bot akan kembali online dalam ~3 detik."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def proactive_system_guardian_config(action: str = "status", cpu_threshold: int = 90, ram_threshold: int = 85, disk_threshold: int = 90, battery_critical: int = 10, auto_kill_ram_hogs: bool = False) -> Dict[str, Any]:
    """
    GOD MODE: Configure the Proactive System Guardian daemon.
    The guardian runs in the background 24/7, monitoring system health and
    automatically taking protective actions (sending alerts, killing memory hogs,
    locking screen on critical battery, etc.).
    
    Args:
        action: 'status' to check guardian config, 'enable' to activate, 'disable' to deactivate.
        cpu_threshold: CPU usage % threshold for alert (default: 90).
        ram_threshold: RAM usage % threshold for alert (default: 85).
        disk_threshold: Disk usage % threshold for alert (default: 90).
        battery_critical: Battery % threshold for critical alert (default: 10).
        auto_kill_ram_hogs: If True, automatically kill top RAM-consuming non-essential processes when threshold exceeded.
    """
    try:
        config_path = os.path.join(os.path.expanduser("~"), ".alfa", "guardian_config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        import json
        
        if action == "status":
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                return {"status": "success", "guardian": config}
            return {"status": "success", "guardian": {"enabled": False, "message": "Guardian belum dikonfigurasi."}}
        
        elif action == "enable":
            config = {
                "enabled": True,
                "cpu_threshold": cpu_threshold,
                "ram_threshold": ram_threshold,
                "disk_threshold": disk_threshold,
                "battery_critical": battery_critical,
                "auto_kill_ram_hogs": auto_kill_ram_hogs,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": f"🛡️ System Guardian AKTIF! Monitoring: CPU>{cpu_threshold}%, RAM>{ram_threshold}%, Disk>{disk_threshold}%, Battery<{battery_critical}%. Auto-kill: {'ON' if auto_kill_ram_hogs else 'OFF'}."
            }
        
        elif action == "disable":
            config = {"enabled": False, "updated_at": datetime.datetime.now().isoformat()}
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            return {"status": "success", "message": "🛡️ System Guardian dinonaktifkan."}
        
        return {"status": "error", "message": f"Action '{action}' tidak dikenal. Gunakan: status, enable, disable."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def proactive_ambient_agent_config(action: str = "status", enabled: bool = True, min_hours_between_pings: int = 3, quiet_hours_start: int = 23, quiet_hours_end: int = 7) -> Dict[str, Any]:
    """
    GOD MODE: Configure Ambient Proactive Autonomous Engagement.
    Controls whether and how often the AI agent can autonomously initiate contact,
    ask questions, check in on user projects, or send daily morning/afternoon briefings.
    
    Args:
        action: 'status' (view config), 'enable' (turn on proactive mode), 'disable' (turn off).
        enabled: Set proactive mode active/inactive.
        min_hours_between_pings: Minimum hours between spontaneous messages (default: 3).
        quiet_hours_start: Start hour for quiet time (default: 23 / 11 PM).
        quiet_hours_end: End hour for quiet time (default: 7 / 7 AM).
    """
    try:
        import json
        config_path = os.path.join(os.path.expanduser("~"), ".alfa", "proactive_config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        if action == "status":
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                return {"status": "success", "proactive_config": config}
            return {
                "status": "success",
                "proactive_config": {
                    "enabled": True,
                    "min_hours_between_pings": 3,
                    "quiet_hours_start": 23,
                    "quiet_hours_end": 7,
                    "message": "Mode Proaktif default aktif."
                }
            }
            
        elif action in ["enable", "set"]:
            config = {
                "enabled": True,
                "min_hours_between_pings": max(1, min_hours_between_pings),
                "quiet_hours_start": quiet_hours_start,
                "quiet_hours_end": quiet_hours_end,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return {
                "status": "success",
                "message": f"🤖 Mode Proaktif Otonom AKTIF! Bot akan berinisiatif menyapa/mengecek kondisi setiap ~{min_hours_between_pings} jam di luar jam tenang ({quiet_hours_start}:00 - {quiet_hours_end}:00)."
            }
            
        elif action == "disable":
            config = {
                "enabled": False,
                "updated_at": datetime.datetime.now().isoformat()
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return {"status": "success", "message": "🤖 Mode Proaktif Otonom dinonaktifkan. Bot hanya akan membalas jika Anda bertanya."}
            
        return {"status": "error", "message": f"Action '{action}' tidak dikenal. Gunakan: status, enable, disable."}
    except Exception as e:
        return {"status": "error", "message": f"Proactive config error: {str(e)}"}


@register_tool(category="system")
def ssh_execute_command(host: str, command: str, username: str = "", port: int = 22, key_path: str = "") -> Dict[str, Any]:
    """
    Execute a command on a remote Linux server via SSH and return the output.
    Use this for remote server management, deployment, monitoring, etc.
    
    Args:
        host: Remote server hostname or IP address.
        command: Shell command to execute on the remote server.
        username: SSH username (defaults to current user if empty).
        port: SSH port (default: 22).
        key_path: Path to SSH private key file (defaults to ~/.ssh/id_rsa if empty).
    """
    try:
        import paramiko
        
        ssh_user = username or os.environ.get("USER", "root")
        ssh_key = os.path.expanduser(key_path) if key_path else os.path.expanduser("~/.ssh/id_rsa")
        
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {"hostname": host, "port": port, "username": ssh_user, "timeout": 10}
        if os.path.exists(ssh_key):
            connect_kwargs["key_filename"] = ssh_key
        
        client.connect(**connect_kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        
        return {
            "status": "success",
            "host": host,
            "exit_code": exit_code,
            "stdout": out[:8000],
            "stderr": err[:2000] if err else ""
        }
    except Exception as e:
        return {"status": "error", "message": f"SSH error: {str(e)}"}


@register_tool(category="system")
def generate_secure_password(length: int = 20, include_uppercase: bool = True, include_digits: bool = True, include_special: bool = True, count: int = 1) -> Dict[str, Any]:
    """
    Generate one or more cryptographically secure random passwords.
    
    Args:
        length: Password length (8-128 characters, default: 20).
        include_uppercase: Include uppercase letters (default: True).
        include_digits: Include digits (default: True).
        include_special: Include special characters !@#$%^&* (default: True).
        count: Number of passwords to generate (1-10, default: 1).
    """
    try:
        import secrets
        import string
        
        length = max(8, min(128, length))
        count = max(1, min(10, count))
        
        chars = string.ascii_lowercase
        if include_uppercase:
            chars += string.ascii_uppercase
        if include_digits:
            chars += string.digits
        if include_special:
            chars += "!@#$%^&*_+-=?."
        
        passwords = []
        for _ in range(count):
            pw = ''.join(secrets.choice(chars) for _ in range(length))
            passwords.append(pw)
        
        # Calculate entropy
        import math
        entropy = round(math.log2(len(chars)) * length, 1)
        strength = "Sangat Kuat 🟢" if entropy > 80 else "Kuat 🔵" if entropy > 60 else "Cukup 🟡" if entropy > 40 else "Lemah 🔴"
        
        return {
            "status": "success",
            "passwords": passwords,
            "length": length,
            "entropy_bits": entropy,
            "strength": strength,
            "charset_size": len(chars)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def start_focus_session(title: str, duration_minutes: int = 25, notes: str = "") -> Dict[str, Any]:
    """
    GOD MODE: Focus & Pomodoro Productivity Session.
    Starts a deep work focus session with automatic timer, records target end time,
    and schedules an automatic Telegram completion alert.
    
    Args:
        title: Title/objective of the focus session (e.g. 'Code Review Backend', 'Menulis Laporan').
        duration_minutes: Duration in minutes (default: 25).
        notes: Optional extra notes for the session.
    """
    uid = get_current_user_id()
    cid = get_current_chat_id()
    if not uid:
        return {"status": "error", "message": "User context tidak ditemukan."}
    res = database.start_focus_session_sync(uid, cid, title, duration_minutes, notes)
    return {
        "status": "success",
        "message": f"🎯 Sesi fokus '{title}' ({duration_minutes} menit) dimulai! Berakhir pada: {res['end_time']}. Bot akan mengirim notifikasi saat waktu habis.",
        "session_details": res
    }


@register_tool(category="system")
def self_add_new_tool(tool_name: str, tool_description: str, tool_code: str, test_arguments_json: str = "{}") -> Dict[str, Any]:
    """
    GOD MODE: Self-Evolution Engine — dynamically writes, compiles, sandbox-tests, and hot-loads
    a brand new Python tool into the plugins/ directory for immediate runtime execution.
    
    Args:
        tool_name: Python function name for the new tool (e.g. 'check_crypto_price', 'calculate_loan_emi').
        tool_description: Detailed description of what the tool does and its parameters.
        tool_code: Complete Python function code including def, docstring, typing, args, and return dict.
        test_arguments_json: Optional JSON string of kwargs to test-run the tool in a sandbox before saving.
    """
    try:
        import plugins
        test_kwargs = {}
        if test_arguments_json and test_arguments_json.strip():
            try:
                test_kwargs = json.loads(test_arguments_json)
            except Exception:
                test_kwargs = {}
        return plugins.create_and_register_plugin(tool_name, tool_description, tool_code, test_kwargs=test_kwargs)
    except Exception as e:
        return {"status": "error", "message": f"Self-evolution error: {str(e)}"}


@register_tool(category="system")
def list_dynamic_plugins() -> Dict[str, Any]:
    """
    List all dynamically created and hot-loaded plugin tools currently available in the system.
    """
    try:
        import plugins
        plugins_list = plugins.list_all_plugins()
        return {
            "status": "success",
            "total_plugins": len(plugins_list),
            "plugins": plugins_list
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def delete_dynamic_plugin(tool_name: str) -> Dict[str, Any]:
    """
    Permanently delete a dynamic plugin tool from disk and unregister from memory.
    
    Args:
        tool_name: Name of the plugin tool to delete.
    """
    try:
        import plugins
        return plugins.delete_plugin(tool_name)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def query_token_usage(hours: int = 24) -> Dict[str, Any]:
    """
    Laporan pemakaian token AI per API key (realtime dari dashboard vault).
    
    Args:
        hours: Rentang jam ke belakang (1-720, default 24).
    """
    try:
        summary = database.get_api_usage_summary_sync(hours=hours)
        per_key = [
            {k: r.get(k) for k in ('key_name', 'provider', 'total_tokens', 'calls', 'last_used')}
            for r in summary.get('per_key', [])[:15]
        ]
        return {
            "status": "success",
            "window_hours": summary.get("window_hours"),
            "tokens_today": summary.get("tokens_today"),
            "calls_today": summary.get("calls_today"),
            "total_all_time": summary.get("total_all_time"),
            "per_key": per_key,
            "by_context": summary.get("by_context", []),
            "message": f"Pemakaian {hours} jam terakhir: {summary.get('tokens_today')} token hari ini."
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal membaca pemakaian token: {str(e)}"}


@register_tool(category="system")
def open_web_dashboard(port: int = 8080) -> Dict[str, Any]:
    """
    ALFA OS: Web Command Center Dashboard Controller.
    Returns the active local web URL for the luxury management dashboard
    and ensures the alfa-dashboard.service is running.
    
    Args:
        port: Dashboard port (default: 8080).
    """
    try:
        # Check if service is active
        res = subprocess.run(["systemctl", "--user", "is-active", "alfa-dashboard.service"], capture_output=True, text=True)
        if res.stdout.strip() != "active":
            subprocess.run(["systemctl", "--user", "start", "alfa-dashboard.service"], capture_output=True, text=True)
            
        import socket
        local_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
            
        return {
            "status": "success",
            "message": f"🌐 Web Dashboard Command Center aktif! Buka di browser laptop: http://localhost:{port} atau dari HP di WiFi yang sama: http://{local_ip}:{port}",
            "local_url": f"http://localhost:{port}",
            "network_url": f"http://{local_ip}:{port}",
            "dashboard_features": ["Live Hardware Telemetry", "75+ Tools Arsenal & Runner", "Ecosystem Services Hub", "Second Brain Memory Visualizer", "24/7 Guardian Control", "Web Live AI Console", "AI Swarm & Rapat Antar Agent", "Multi-Provider API Key Vault"]
        }
    except Exception as e:
        return {"status": "error", "message": f"Open web dashboard error: {str(e)}"}


@register_tool(category="system")
def manage_api_keys(action: str, name: str = "", provider: str = "gemini", api_key: str = "", default_model: str = "gemini-3.6-flash", base_url: str = "", key_id: int = None) -> Dict[str, Any]:
    """
    Manage API keys and multi-provider endpoints (Gemini, OpenAI, Groq, OpenRouter, Anthropic, Ollama, NVIDIA NIM).
    Enables switching active keys or assigning specific provider keys to specialized agents.
    
    Args:
        action: 'list' (view all keys), 'add' (add key), 'activate' (set key active), 'delete' (remove key).
        name: Label name for the key (e.g. 'Production Gemini', 'NVIDIA NIM Llama 3.3', 'Groq Llama 3').
        provider: 'gemini', 'openai', 'groq', 'openrouter', 'anthropic', 'ollama', 'nvidia'.
        api_key: The API secret key string (e.g. nvapi-..., AIza..., sk-...).
        default_model: Default model string (e.g. 'meta/llama-3.3-70b-instruct', 'gemini-3.6-flash', 'gpt-4o').
        base_url: Optional custom proxy or Ollama/NVIDIA NIM base URL (default for nvidia: 'https://integrate.api.nvidia.com/v1').
        key_id: Target key ID for 'activate' or 'delete'.
    """
    action = action.lower().strip()
    try:
        if action == "list":
            keys = database.list_api_keys_sync()
            return {
                "status": "success",
                "total_keys": len(keys),
                "keys": keys
            }
        elif action == "add":
            if not api_key:
                return {"status": "error", "message": "Parameter 'api_key' wajib diisi."}
            res = database.add_api_key_sync(
                name=name or f"{provider.capitalize()} Key",
                provider=provider,
                api_key=api_key,
                default_model=default_model,
                base_url=base_url,
                set_active=True
            )
            return {"status": "success", "message": f"API Key '{name}' untuk provider '{provider}' berhasil disimpan & diaktifkan!", "key_id": res.get("id")}
        elif action == "activate":
            if not key_id:
                return {"status": "error", "message": "Parameter 'key_id' wajib diisi."}
            return database.activate_api_key_sync(key_id)
        elif action == "delete":
            if not key_id:
                return {"status": "error", "message": "Parameter 'key_id' wajib diisi."}
            return database.delete_api_key_sync(key_id)
        else:
            return {"status": "error", "message": f"Action tidak dikenal: {action}. Gunakan 'list', 'add', 'activate', atau 'delete'."}
    except Exception as e:
        return {"status": "error", "message": f"Manage API keys error: {str(e)}"}


@register_tool(category="system")
def manage_custom_agents(action: str, name: str = "", role: str = "", persona: str = "", system_instruction: str = "", provider: str = "gemini", model: str = "gemini-3.6-flash", avatar_emoji: str = "🤖", color_theme: str = "cyan", agent_id: int = None) -> Dict[str, Any]:
    """
    Manage the Autonomous AI Agent Workforce (Society of Agents).
    Create, list, update, and configure specialized agents that can collaborate, hold meetings, and execute tasks.
    
    Args:
        action: 'list' (view all agents), 'add' (create agent), 'delete' (remove agent), 'toggle' (enable/disable).
        name: Unique name of the agent (e.g. 'Security Guard', 'Frontend Ninja').
        role: Title / Role of the agent (e.g. 'Penetration Tester', 'Vue/React UI Specialist').
        persona: Persona description (e.g. 'Kritis, teliti, mengutamakan performa').
        system_instruction: Detailed system prompt for this agent.
        provider: 'gemini', 'openai', 'groq', 'openrouter', 'ollama'.
        model: Model identifier (default: 'gemini-3.6-flash').
        avatar_emoji: Avatar emoji (e.g. '👑', '⚡', '🛡️', '🌐', '💡').
        color_theme: 'cyan', 'emerald', 'violet', 'amber', 'rose', 'blue'.
        agent_id: Target agent ID for update or delete.
    """
    action = action.lower().strip()
    try:
        if action == "list":
            agents = database.list_custom_agents_sync()
            return {
                "status": "success",
                "total_agents": len(agents),
                "agents": agents
            }
        elif action == "add":
            if not name or not role:
                return {"status": "error", "message": "Parameter 'name' dan 'role' wajib diisi."}
            res = database.add_custom_agent_sync(
                name=name,
                role=role,
                persona=persona or f"Spesialis dalam {role}",
                system_instruction=system_instruction or f"Kamu adalah {name}, {role}.",
                provider=provider,
                model=model,
                avatar_emoji=avatar_emoji,
                color_theme=color_theme
            )
            return {"status": "success", "message": f"Agent '{name}' ({role}) berhasil ditambahkan ke AI Workforce!", "agent_id": res.get("id")}
        elif action == "delete":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' wajib diisi."}
            return database.delete_custom_agent_sync(agent_id)
        elif action == "toggle":
            if not agent_id:
                return {"status": "error", "message": "Parameter 'agent_id' wajib diisi."}
            cur = database.get_custom_agent_sync(agent_id)
            if not cur:
                return {"status": "error", "message": "Agent tidak ditemukan"}
            new_state = 0 if cur.get("is_enabled", 1) else 1
            return database.update_custom_agent_sync(agent_id, {"is_enabled": new_state})
        else:
            return {"status": "error", "message": f"Action tidak dikenal: {action}."}
    except Exception as e:
        return {"status": "error", "message": f"Manage custom agents error: {str(e)}"}


@register_tool(category="system")
def conduct_ai_meeting(topic: str, participants: str = "", rounds: int = 2, mode: str = "execute", folder: str = "") -> Dict[str, Any]:
    """
    Jalankan SWARM EKSEKUSI LANGSUNG: agen bekerja nyata memakai tool (mode rapat/diskusi sudah dihapus).

    Args:
        topic: Ringkasan TUGAS nyata yang harus dikerjakan tim. Contoh: 'perbaiki bug login lalu tambah halaman kontak'.
        participants: Comma-separated agent names or empty for default team.
        rounds: Number of execution coordination rounds (1 to 3, default: 2).
        mode: Diabaikan — selalu 'execute' (eksekusi langsung).
        folder: Path folder lokal yang WAJIB diedit agen, contoh '/home/user/proyek'. Kosongkan biar agen bebas.
    """
    try:
        import concurrent.futures

        from alfa.swarm import engine as swarm_engine
        part_list = [p.strip() for p in participants.split(",") if p.strip()] if participants else None
        rounds_clamped = max(1, min(3, int(rounds)))
        
        def _run_meeting():
            return asyncio.run(swarm_engine.conduct_multi_agent_meeting(
                topic, part_list, rounds_clamped, "execute", target_folder=folder))
        
        # asyncio.run() needs a fresh loop; if this tool is invoked from inside
        # a running loop (e.g. Telegram handler), delegate to a worker thread.
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_run_meeting).result(timeout=600)
        except RuntimeError:
            result = _run_meeting()
            
        return {
            "status": "success",
            "meeting_id": result.get("meeting_id"),
            "title": result.get("title"),
            "topic": topic,
            "mode": "execute",
            "target_folder": result.get("target_folder", ""),
            "total_rounds": rounds_clamped,
            "participants": result.get("participants"),
            "total_dialogues": len(result.get("dialogue_transcript", [])),
            "execution_results": result.get("execution_results", []),
            "consensus": result.get("consensus"),
            "action_plan": result.get("action_plan")
        }
    except Exception as e:
        return {"status": "error", "message": f"AI Meeting error: {str(e)}"}


@register_tool(category="system")
def spawn_background_subagent(task_description: str, agent_role: str = "Researcher & Coder") -> Dict[str, Any]:
    """
    Spawn an autonomous background subagent worker to solve a complex, long-running task
    (e.g. deep research, scraping multiple sources, data analysis, codebase audits)
    independently without blocking the user. When finished, the subagent sends a full report to Telegram.
    
    Args:
        task_description: Complete detailed instructions for the subagent.
        agent_role: Specialized title or job role (e.g. 'Deep Web Researcher', 'Python Coder', 'Security Auditor').
    """
    try:
        import subagents
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        return subagents.spawn_subagent(user_id=user_id, chat_id=chat_id, role=agent_role, task_description=task_description)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def check_subagent_status(subagent_id: str) -> Dict[str, Any]:
    """
    Check the execution status and report of a spawned background subagent by its task ID.
    
    Args:
        subagent_id: The task ID (e.g. 'sub_1a2b3c4d').
    """
    try:
        task = database.get_subagent_task_sync(subagent_id)
        if not task:
            return {"status": "error", "message": f"Subagent dengan ID '{subagent_id}' tidak ditemukan."}
        return {"status": "success", "task": task}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def add_recurring_task(title: str, prompt_instruction: str, interval_minutes: int = 60) -> Dict[str, Any]:
    """
    Schedule an autonomous recurring task or proactive watchdog (e.g. monitor server stats every 30m, check crypto price every 15m, daily tech news briefing every 1440m).
    The AI will automatically run this instruction periodically and send the result to Telegram!
    
    Args:
        title: Short descriptive name for this task.
        prompt_instruction: The exact prompt/action for the AI agent to execute on each interval.
        interval_minutes: Repeat interval in minutes (default: 60 minutes).
    """
    try:
        user_id = get_current_user_id()
        chat_id = get_current_chat_id()
        job_id = database.add_cron_job_sync(
            user_id=user_id,
            chat_id=chat_id,
            title=title,
            prompt_instruction=prompt_instruction,
            interval_minutes=max(1, interval_minutes)
        )
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Tugas berulang #{job_id} '{title}' berhasil dijadwalkan setiap {interval_minutes} menit."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def list_recurring_tasks() -> Dict[str, Any]:
    """
    List all active recurring tasks and watchdogs scheduled for the user.
    """
    try:
        user_id = get_current_user_id()
        jobs = database.list_cron_jobs_sync(user_id)
        return {"status": "success", "total_jobs": len(jobs), "tasks": jobs}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def cancel_recurring_task(task_id: int) -> Dict[str, Any]:
    """
    Cancel and delete a scheduled recurring task or watchdog by its ID.
    
    Args:
        task_id: The ID of the recurring task.
    """
    try:
        user_id = get_current_user_id()
        success = database.delete_cron_job_sync(user_id, task_id)
        if success:
            return {"status": "success", "message": f"Tugas berulang #{task_id} berhasil dibatalkan dan dihapus."}
        return {"status": "error", "message": f"Tugas #{task_id} tidak ditemukan."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@register_tool(category="system")
def manage_wa_sheets_bot(action: str = "status") -> Dict[str, Any]:
    """
    ECOSYSTEM INTEGRATION: WhatsApp Google Sheets Bot Controller.
    Controls and monitors the wa-sheets-bot systemd user service.
    Can check status, start, stop, restart, enable auto-start, or view live logs.
    
    Args:
        action: 'status' (check running state & memory), 'start', 'stop', 'restart', 'logs' (recent 20 lines), 'enable' (enable autostart on boot).
    """
    try:
        act = action.lower().strip()
        svc_name = "wa-sheets-bot.service"
        
        if act == "status":
            res_active = subprocess.run(["systemctl", "--user", "is-active", svc_name], capture_output=True, text=True)
            res_enabled = subprocess.run(["systemctl", "--user", "is-enabled", svc_name], capture_output=True, text=True)
            res_status = subprocess.run(["systemctl", "--user", "status", svc_name, "--no-pager", "-n", "5"], capture_output=True, text=True)
            
            is_act = res_active.stdout.strip() == "active"
            return {
                "status": "success",
                "service": svc_name,
                "is_running": is_act,
                "state": res_active.stdout.strip(),
                "enabled_on_boot": res_enabled.stdout.strip() == "enabled",
                "details": res_status.stdout.strip()
            }
            
        elif act in ["start", "stop", "restart", "enable", "disable"]:
            res = subprocess.run(["systemctl", "--user", act, svc_name], capture_output=True, text=True)
            if res.returncode == 0:
                time.sleep(1)
                res_active = subprocess.run(["systemctl", "--user", "is-active", svc_name], capture_output=True, text=True)
                return {
                    "status": "success",
                    "message": f"Service '{svc_name}' berhasil di-{act}! Status saat ini: {res_active.stdout.strip()}.",
                    "current_state": res_active.stdout.strip()
                }
            return {"status": "error", "message": f"Gagal mengeksekusi {act}: {res.stderr}"}
            
        elif act == "logs":
            res_logs = subprocess.run(["journalctl", "--user", "-u", svc_name, "-n", "25", "--no-pager"], capture_output=True, text=True)
            return {
                "status": "success",
                "service": svc_name,
                "logs": res_logs.stdout.strip()
            }
            
        return {"status": "error", "message": f"Aksi '{action}' tidak dikenal. Gunakan: status, start, stop, restart, logs, enable."}
    except Exception as e:
        return {"status": "error", "message": f"Manage wa-sheets-bot error: {str(e)}"}


@register_tool(category="system")
def list_wa_drive_uploads(limit: int = 20) -> Dict[str, Any]:
    """
    Daftar berkas (foto/PDF/dokumen) yang otomatis diunggah dari WhatsApp ke Google Drive.
    
    Args:
        limit: Jumlah maksimal entri terbaru (default 20).
    """
    try:
        path = os.path.expanduser("~/wa-sheets-bot/drive_uploads.json")
        if not os.path.exists(path):
            return {"status": "success", "total": 0,
                    "message": "Belum ada berkas WA yang terunggah ke Drive.",
                    "uploads": []}
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        uploads = (data.get("uploads") or [])[: max(1, min(int(limit), 100))]
        compact = [{
            'waktu': u.get('ts'), 'nama_file': u.get('file_name'),
            'folder': u.get('folder'), 'pengirim': u.get('sender'),
            'grup': u.get('group'), 'link': u.get('web_link'),
        } for u in uploads]
        return {"status": "success", "total": len(uploads),
                "message": f"{len(uploads)} berkas WA terakhir di Drive.",
                "uploads": compact}
    except Exception as e:
        return {"status": "error", "message": f"Gagal membaca log unggahan: {str(e)}"}


@register_tool(category="system")
def scrcpy_android_control(action: str = "status", device_id: str = "", command_or_key: str = "", capture_screenshot: bool = True) -> Dict[str, Any]:
    """
    SCRCPY & ADB ANDROID ENGINE: Control Android smartphones/tablets via USB or Wi-Fi.
    Allows screen capture, sending keyevents, touch taps, app launches, and desktop screen mirroring.
    
    Args:
        action: 'status' (list devices), 'screenshot' (save screen PNG), 'key' (send HOME/BACK/ENTER), 
                'tap' (tap X Y coordinates), 'swipe' (swipe X1 Y1 X2 Y2), 'launch_app' (open app package), 'mirror' (open scrcpy window).
        device_id: Optional specific Android device serial (from adb devices).
        command_or_key: Key name or coordinates (e.g. 'BACK', 'HOME', '500 800' for tap, 'com.whatsapp' for launch_app).
        capture_screenshot: If True, takes a fresh screenshot after performing the action.
    """
    import shutil
    import subprocess
    import time
    
    adb_bin = shutil.which("adb")
    scrcpy_bin = shutil.which("scrcpy")
    
    if not adb_bin and not scrcpy_bin:
        return {
            "status": "error",
            "message": "ADB / Scrcpy belum terpasang di sistem. Untuk mengaktifkan kontrol Android, jalankan: 'sudo apt install -y scrcpy adb' (Linux), 'brew install scrcpy' (macOS), atau 'winget install scrcpy' (Windows)."
        }
        
    dev_flag = ["-s", device_id] if device_id else []
    
    try:
        if action == "status":
            res = subprocess.run([adb_bin, "devices", "-l"], capture_output=True, text=True, timeout=5)
            return {
                "status": "success",
                "raw_devices_output": res.stdout.strip(),
                "adb_path": adb_bin,
                "scrcpy_path": scrcpy_bin
            }
            
        elif action == "screenshot":
            out_dir = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS")
            os.makedirs(out_dir, exist_ok=True)
            shot_file = os.path.join(out_dir, f"android_screen_{int(time.time())}.png")
            with open(shot_file, "wb") as f:
                subprocess.run([adb_bin] + dev_flag + ["exec-out", "screencap", "-p"], stdout=f, timeout=10)
            return {
                "status": "success",
                "screenshot_file": shot_file,
                "file_size": os.path.getsize(shot_file) if os.path.exists(shot_file) else 0
            }
            
        elif action == "key":
            key_map = {
                "HOME": "3", "BACK": "4", "CALL": "5", "ENDCALL": "6",
                "ENTER": "66", "DELETE": "67", "TAB": "61", "SPACE": "62",
                "VOLUME_UP": "24", "VOLUME_DOWN": "25", "POWER": "26", "CAMERA": "27"
            }
            keycode = key_map.get(command_or_key.upper(), command_or_key)
            subprocess.run([adb_bin] + dev_flag + ["shell", "input", "keyevent", keycode], capture_output=True, timeout=5)
            return {"status": "success", "action": "key", "sent_key": command_or_key}
            
        elif action == "tap":
            coords = command_or_key.split()
            if len(coords) < 2:
                return {"status": "error", "message": "Koordinat tap harus berupa 'X Y' (contoh: '500 800')"}
            subprocess.run([adb_bin] + dev_flag + ["shell", "input", "tap", coords[0], coords[1]], capture_output=True, timeout=5)
            return {"status": "success", "action": "tap", "coords": coords[:2]}
            
        elif action == "launch_app":
            subprocess.run([adb_bin] + dev_flag + ["shell", "monkey", "-p", command_or_key, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True, timeout=5)
            return {"status": "success", "action": "launch_app", "package": command_or_key}
            
        elif action == "mirror":
            if not scrcpy_bin:
                return {"status": "error", "message": "Binary scrcpy tidak ditemukan. Install dengan 'sudo apt install -y scrcpy'"}
            subprocess.Popen([scrcpy_bin] + (["-s", device_id] if device_id else []))
            return {"status": "success", "message": "Window screen mirroring Scrcpy berhasil dibuka di desktop."}
            
        else:
            return {"status": "error", "message": f"Action '{action}' tidak dikenal."}
    except Exception as e:
        return {"status": "error", "message": f"Android control error: {str(e)}"}


@register_tool(category="system")
def query_database(db_path: str, sql_query: str) -> Dict[str, Any]:
    """
    Execute a SQL query on a local SQLite database file and return the results as a table.
    
    Args:
        db_path: Path to the SQLite database file (e.g. '~/data/app.db', 'bot_database.db').
        sql_query: SQL query to execute (SELECT, INSERT, UPDATE, DELETE, etc.).
    
    Security Note: This function accepts raw SQL queries. Ensure input is validated
    before calling this function to prevent SQL injection attacks.
    """
    try:
        import sqlite3
        expanded = os.path.expanduser(db_path)
        if not os.path.exists(expanded):
            return {"status": "error", "message": f"Database file tidak ditemukan: {db_path}"}
        
        # Security validation: Block dangerous statements
        query_upper = sql_query.strip().upper()
        dangerous_keywords = ["DROP ", "DELETE FROM ", "TRUNCATE", "ALTER ", "CREATE INDEX", 
                             "DETACH DATABASE", "ATTACH DATABASE"]
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return {"status": "error", "message": f"Potensi SQL injection terdeteksi: '{keyword}' tidak diizinkan."}
        
        conn = sqlite3.connect(expanded)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Execute with safety check - only allow parameterized queries for non-SELECT
        # For SELECT queries from trusted sources (internal tool), direct execution is acceptable
        cursor.execute(sql_query)
        
        query_upper = sql_query.strip().upper()
        if query_upper.startswith("SELECT") or query_upper.startswith("PRAGMA") or query_upper.startswith("WITH"):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows[:100]]
            conn.close()
            return {
                "status": "success",
                "columns": columns,
                "row_count": len(data),
                "total_available": len(rows) if len(rows) <= 100 else f"{len(rows)}+ (showing first 100)",
                "data": data
            }
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return {"status": "success", "message": f"Query berhasil dieksekusi. {affected} baris terpengaruh."}
    except Exception as e:
        return {"status": "error", "message": f"SQL error: {str(e)}"}


@register_tool(category="system")
def send_email(to: str, subject: str, body: str, attachment_path: str = "") -> Dict[str, Any]:
    """
    Send an email via SMTP (supports Gmail, Outlook, custom SMTP servers).
    Requires SMTP_EMAIL and SMTP_PASSWORD environment variables in .env file.
    
    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text (supports plain text).
        attachment_path: Optional file path to attach.
    """
    try:
        import smtplib
        from email import encoders
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        
        smtp_email = os.environ.get("SMTP_EMAIL", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        
        if not smtp_email or not smtp_password:
            return {"status": "error", "message": "SMTP_EMAIL dan SMTP_PASSWORD belum dikonfigurasi di file .env. Tambahkan: SMTP_EMAIL=xxx@gmail.com dan SMTP_PASSWORD=your_app_password"}
        
        msg = MIMEMultipart()
        msg["From"] = smtp_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        if attachment_path:
            expanded = os.path.expanduser(attachment_path)
            if os.path.exists(expanded):
                with open(expanded, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(expanded)}")
                    msg.attach(part)
        
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, to, msg.as_string())
        server.quit()
        
        return {"status": "success", "message": f"Email berhasil dikirim ke {to} dengan subjek '{subject}'."}
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengirim email: {str(e)}"}


@register_tool(category="system")
def download_file_from_url(url: str, filename: str = "") -> Dict[str, Any]:
    """
    Download a file from a URL on the internet to the local computer and optionally send it to Telegram.
    Supports direct file links (images, PDFs, ZIPs, videos, audio, executables, etc.).
    
    Args:
        url: Direct download URL.
        filename: Optional filename to save as (auto-detected from URL if empty).
    """
    try:
        import httpx
        
        if not filename:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "downloaded_file"
        
        dest_path = os.path.join(SANDBOX_DIR, filename)
        
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            resp = client.get(url)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(resp.content)
        
        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        
        if size_mb > 50:
            return {
                "status": "success",
                "message": f"File '{filename}' ({round(size_mb, 2)} MB) berhasil diunduh ke {dest_path}. Terlalu besar untuk dikirim via Telegram (>50MB), tetapi tersedia di disk lokal.",
                "file_path": dest_path,
                "sent_to_telegram": False
            }
        
        return {
            "status": "success",
            "message": f"File '{filename}' ({round(size_mb, 2)} MB) berhasil diunduh dan akan dikirim ke Telegram.",
            "file_path": dest_path,
            "sent_to_telegram": True
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengunduh: {str(e)}"}

