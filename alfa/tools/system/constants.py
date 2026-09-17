"""Constants, safety guards, and sandboxing checks for system tools."""

import logging
import os
import re
import subprocess
import sys
from typing import Optional

logger = logging.getLogger("AgentTools.System")

if os.name == "nt":
    _drive = os.path.splitdrive(os.path.abspath("."))[0] or "C:"
    _sandbox_base = os.path.join(_drive + os.sep, "dev", "shm", "alfa_sandbox")
else:
    _sandbox_base = "/dev/shm/alfa_sandbox"
SANDBOX_DIR = _sandbox_base
os.makedirs(SANDBOX_DIR, exist_ok=True)

_BASH_BLOCK_PATTERNS = [
    (r":\s*\(\s*\)\s*\{.*\}\s*;", "fork bomb"),
    (r"\bdd\s+[^\n]*of=/dev/(sd|hd|vd|nvme|mmcblk)", "tulis mentah ke disk fisik"),
    (r"\bmkfs(\.\w+)?\b", "format filesystem"),
    (r"chmod\s+-R\s+777\s+/", "chmod 777 rekursif pada root"),
    (r"chown\s+-R\b[^\n]*(\s/|\s~|\s\$HOME)(\s|$)", "chown rekursif pada root/home"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "mematikan/menyalakan ulang sistem"),
    (
        r"(history\s+-c\b|>\s*~/\.bash_history|shred\s+[^;\n]*history|unset\s+HISTFILE)",
        "menghapus jejak riwayat shell",
    ),
    (
        r"(curl|wget|fetch)[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
        "pipe skrip internet langsung ke shell",
    ),
    (
        r"base64\s+[^;\n|&]*(?:-d\b|--decode)[^;\n|&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
        "pipe payload base64 ke shell",
    ),
    (r"/(dev/tcp/|proc/sysrq-trigger)", "teknik reverse-shell/kernel trigger"),
    (
        r"\.(ssh/id_(rsa|ed25519|ecdsa)|aws/credentials|gnupg)",
        "akses berkas kredensial privat",
    ),
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
    ".py",
    ".sh",
    ".bash",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".sql",
    ".c",
    ".cpp",
    ".h",
    ".go",
    ".rs",
}


def _docker_available() -> bool:
    """Check (and cache) whether the Docker daemon is usable by this user."""
    global _DOCKER_AVAILABLE_CACHE
    if _DOCKER_AVAILABLE_CACHE is None:
        try:
            probe = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            _DOCKER_AVAILABLE_CACHE = probe.returncode == 0
        except Exception:
            _DOCKER_AVAILABLE_CACHE = False
    return _DOCKER_AVAILABLE_CACHE


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
        if q.startswith("/dev/shm"):
            drive = os.path.splitdrive(os.path.abspath("."))[0] or "C:"
            q = drive + q
        elif q[1:3] not in (":/", ":\\"):
            pass
    return os.path.normpath(q) if os.name == "nt" else p


def _bash_blocked_reason(command: str) -> Optional[str]:
    """Kembalikan alasan pemblokiran bila perintah cocok pola berbahaya."""
    cmd = command or ""

    for pat, reason in _BASH_BLOCK_PATTERNS:
        if re.search(pat, cmd):
            return reason

    m = re.search(r"\brm\b([^#;\n]*)", cmd)
    if m:
        seg = m.group(1)
        has_recursive = bool(
            re.search(
                r"(?:^|\s)(-{1,2}[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(?:\s|$)", seg
            )
        )
        has_danger_target = bool(
            re.search(r"(?:^|\s)(\"|')?" + _RM_DANGER_TARGETS, seg)
        )
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


def generate_self_heal_hint(
    tool_name: str, error_msg: str, stdout: str = "", stderr: str = ""
) -> Optional[str]:
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


def is_internal_sandbox_artifact(fname: str) -> bool:
    """True bila file adalah artefak infrastruktur sandbox."""
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
    """True bila file adalah kode sumber."""
    return os.path.splitext(fname or "")[1].lower() in _SOURCE_CODE_EXTS


def _ensure_sandbox_image() -> bool:
    """Ensure the alfa-sandbox image exists; auto-build it on first use."""
    try:
        chk = subprocess.run(
            ["docker", "images", "-q", _SANDBOX_IMAGE],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if chk.returncode == 0 and chk.stdout.strip():
            return True

        logger.info(
            "Building sandbox image '%s' (first use, ~2-5 min)...", _SANDBOX_IMAGE
        )
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
            capture_output=True,
            text=True,
            timeout=600,
        )
        if build.returncode == 0:
            logger.info("Sandbox image built successfully.")
            return True
        logger.error("Sandbox image build failed: %s", build.stderr[-400:])
        return False
    except Exception as img_err:
        logger.error("ensure_sandbox_image error: %s", img_err)
        return False
