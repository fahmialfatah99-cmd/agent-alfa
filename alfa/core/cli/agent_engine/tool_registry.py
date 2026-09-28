"""Local developer tool registry (search, files, patch, shell)."""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

from alfa.core.cli.agent_engine.patch_history import PatchHistoryManager
from alfa.core.cli.agent_engine.repomap import RepomapGenerator

# ==========================================
# 3. LOCAL DEVELOPER TOOL REGISTRY
# ==========================================


class LocalToolRegistry:
    """Provides fast, secure, local development tools for the autonomous agent."""

    def __init__(self, workspace_root: Path | None = None):
        self.root = workspace_root or Path.cwd()
        self.patch_manager = PatchHistoryManager(self.root)

    def _resolve(self, path_str: str) -> Path:
        p = Path(path_str.strip())
        if not p.is_absolute():
            p = self.root / p
        return p

    def search_code(self, query: str, path: str = ".") -> str:
        """Search text/regex across codebase using ripgrep if available, or python fallback."""
        target_dir = self._resolve(path)
        if not target_dir.exists():
            return f"Error: Path '{path}' tidak ditemukan."

        # 1. Try ripgrep (rg)
        rg_bin = shutil.which("rg") or os.path.expanduser("~/.cargo/bin/rg")
        if os.path.exists(rg_bin) if not shutil.which("rg") else True:
            try:
                cmd = [
                    rg_bin if not shutil.which("rg") else "rg",
                    "-n",
                    "--max-count",
                    "30",
                    "--color",
                    "never",
                    "--no-heading",
                    "--glob",
                    "!node_modules",
                    "--glob",
                    "!venv",
                    "--glob",
                    "!*.pyc",
                    query,
                    str(target_dir),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                output = res.stdout.strip()
                if output:
                    # Clean up paths relative to root
                    cleaned = []
                    for line in output.splitlines()[:40]:
                        try:
                            if str(self.root) in line:
                                line = line.replace(str(self.root) + "/", "")
                            cleaned.append(line)
                        except Exception:
                            cleaned.append(line)
                    return "\n".join(cleaned)
                return f"Tidak ditemukan kecocokan untuk: '{query}'"
            except Exception:
                pass

        # 2. Python fallback search
        results = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
            for dirpath, dirnames, filenames in os.walk(target_dir):
                dirnames[:] = [
                    d for d in dirnames if d not in RepomapGenerator.IGNORE_DIRS
                ]
                for f in filenames:
                    fp = Path(dirpath) / f
                    if fp.suffix.lower() in RepomapGenerator.IGNORE_EXTS:
                        continue
                    try:
                        rel = fp.relative_to(self.root)
                        lines = fp.read_text(
                            encoding="utf-8", errors="ignore"
                        ).splitlines()
                        for i, line in enumerate(lines, 1):
                            if pattern.search(line):
                                results.append(f"{rel}:{i}: {line.strip()[:150]}")
                                if len(results) >= 30:
                                    return "\n".join(results)
                    except Exception:
                        pass
        except Exception as e:
            return f"Error pencarian: {e}"

        return (
            "\n".join(results)
            if results
            else f"Tidak ditemukan kecocokan untuk: '{query}'"
        )

    def find_files(self, pattern: str, path: str = ".") -> str:
        """Find files matching name glob pattern using fd or os.walk."""
        target_dir = self._resolve(path)
        if not target_dir.exists():
            return f"Error: Path '{path}' tidak ditemukan."

        # Try fd
        fd_bin = (
            shutil.which("fd")
            or shutil.which("fdfind")
            or os.path.expanduser("~/.cargo/bin/fd")
        )
        if (
            os.path.exists(fd_bin)
            if not (shutil.which("fd") or shutil.which("fdfind"))
            else True
        ):
            try:
                cmd = [
                    fd_bin if not shutil.which("fd") else "fd",
                    "--type",
                    "f",
                    "--exclude",
                    "node_modules",
                    "--exclude",
                    "venv",
                    pattern,
                    str(target_dir),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                if res.stdout.strip():
                    lines = [
                        line.replace(str(self.root) + "/", "")
                        for line in res.stdout.strip().splitlines()[:50]
                    ]
                    return "\n".join(lines)
            except Exception:
                pass

        # Python fallback

        matches = []
        for dirpath, dirnames, filenames in os.walk(target_dir):
            dirnames[:] = [d for d in dirnames if d not in RepomapGenerator.IGNORE_DIRS]
            for f in filenames:
                if fnmatch.fnmatch(f, pattern):
                    rel = (Path(dirpath) / f).relative_to(self.root)
                    matches.append(str(rel))
                    if len(matches) >= 50:
                        break
        return (
            "\n".join(matches)
            if matches
            else f"Tidak ada file yang cocok dengan '{pattern}'"
        )

    def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        """Read content of a file with line numbers."""
        p = self._resolve(path)
        if not p.exists():
            return f"Error: File '{path}' tidak ditemukan."
        if not p.is_file():
            return f"Error: '{path}' bukan file reguler."

        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            start = max(1, start_line)
            end = min(total, end_line)

            selected = lines[start - 1 : end]
            numbered = [
                f"{i:>4} │ {line}" for i, line in enumerate(selected, start=start)
            ]
            header = f"--- {path} (Baris {start}-{end} dari {total}) ---"
            return f"{header}\n" + "\n".join(numbered)
        except Exception as e:
            return f"Error membaca '{path}': {e}"

    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a file with automatic backup."""
        p = self._resolve(path)
        old_content = ""
        if p.exists() and p.is_file():
            try:
                old_content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            record = self.patch_manager.record_patch(path, old_content, content)
            return f"Sukses: File '{path}' berhasil ditulis (Backup ID: #{record.id})."
        except Exception as e:
            return f"Error menulis file '{path}': {e}"

    @staticmethod
    def _apply_resilient_patch(
        old_content: str, target_content: str, replacement_content: str
    ) -> tuple[bool, str, str]:
        """Apply patch using a 3-layer progressive strategy:
        1. Exact substring matching (fastest, 100% preservation).
        2. Line-by-line normalized whitespace matching (handles \r\n vs \n, trailing spaces, indentation tweaks).
        3. Block similarity matching via SequenceMatcher (handles minor comment/spacing differences, threshold >= 0.82).
        """
        # --- Strategy 1: Exact match ---
        if target_content in old_content:
            new_content = old_content.replace(target_content, replacement_content, 1)
            return True, new_content, "exact"

        # --- Strategy 2: Line-by-line whitespace-normalized matching ---
        target_lines = target_content.splitlines()
        if not target_lines:
            return False, old_content, "Blok target kosong."

        old_lines_raw = old_content.splitlines(keepends=True)
        old_lines_stripped = [line.strip() for line in old_lines_raw]
        target_stripped = [line.strip() for line in target_lines]

        target_len = len(target_stripped)
        matched_idx = -1

        for i in range(len(old_lines_stripped) - target_len + 1):
            if old_lines_stripped[i : i + target_len] == target_stripped:
                matched_idx = i
                break

        if matched_idx != -1:
            prefix = "".join(old_lines_raw[:matched_idx])
            newline_char = "\r\n" if "\r\n" in old_content else "\n"
            repl = replacement_content
            if not repl.endswith("\n") and not repl.endswith("\r\n"):
                repl += newline_char
            suffix = "".join(old_lines_raw[matched_idx + target_len :])
            new_content = prefix + repl + suffix
            return True, new_content, "whitespace-normalized"

        # --- Strategy 3: Block similarity matching (difflib SequenceMatcher) ---
        if target_len >= 2 and len(old_lines_raw) >= target_len:
            best_ratio = 0.0
            best_idx = -1
            best_span = target_len

            for span in range(
                max(1, target_len - 1), min(len(old_lines_raw), target_len + 2)
            ):
                for i in range(len(old_lines_raw) - span + 1):
                    window_text = "".join(old_lines_raw[i : i + span])
                    ratio = difflib.SequenceMatcher(
                        None, target_content, window_text
                    ).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_idx = i
                        best_span = span

            if best_ratio >= 0.82 and best_idx != -1:
                prefix = "".join(old_lines_raw[:best_idx])
                newline_char = "\r\n" if "\r\n" in old_content else "\n"
                repl = replacement_content
                if not repl.endswith("\n") and not repl.endswith("\r\n"):
                    repl += newline_char
                suffix = "".join(old_lines_raw[best_idx + best_span :])
                new_content = prefix + repl + suffix
                return (
                    True,
                    new_content,
                    f"fuzzy-matched ({int(best_ratio * 100)}% similarity)",
                )

        return (
            False,
            old_content,
            "Blok target tidak cocok secara exact, normalized, maupun fuzzy.",
        )

    def patch_file(
        self, path: str, target_content: str, replacement_content: str
    ) -> str:
        """Replace a specific substring / block of code in a file with resilient 3-layer matching."""
        p = self._resolve(path)
        if not p.exists():
            return f"Error: File '{path}' tidak ditemukan."

        try:
            old_content = p.read_text(encoding="utf-8", errors="replace")
            ok, new_content, strategy = self._apply_resilient_patch(
                old_content, target_content, replacement_content
            )
            if not ok:
                return (
                    f"Error: Blok kode target tidak ditemukan di '{path}' ({strategy}). "
                    "Pastikan karakter target sesuai dengan isi file asli."
                )

            p.write_text(new_content, encoding="utf-8")
            record = self.patch_manager.record_patch(path, old_content, new_content)
            return (
                f"Sukses: Patch berhasil diterapkan ke '{path}' "
                f"menggunakan strategi '{strategy}' (Backup ID: #{record.id})."
            )
        except Exception as e:
            return f"Error patching '{path}': {e}"

    def run_command(self, command: str, timeout: int | None = None) -> str:
        """Execute a shell command in project directory with dynamic timeout & non-interactive flags."""
        # Safety barrier: prevent destructive system operations
        dangerous_patterns = [
            r"\brm\s+-rf\s+/(?:\s|$)",
            r"\bmkfs\b",
            r"\bdd\s+if=",
            r"\b:(){ :|:& };:\b",
        ]
        for pat in dangerous_patterns:
            if re.search(pat, command):
                return f"Ditolak: Perintah terdeteksi berbahaya dan diblokir demi keamanan: '{command}'"

        # Determine dynamic timeout if not explicitly specified
        effective_timeout = timeout
        if effective_timeout is None:
            cmd_lower = command.lower()
            heavy_keywords = [
                "npm install",
                "npm i",
                "yarn",
                "pnpm",
                "pip install",
                "poetry install",
                "cargo build",
                "cargo test",
                "go build",
                "pytest",
                "gradle",
                "mvn",
                "flutter pub",
                "docker build",
            ]
            if any(k in cmd_lower for k in heavy_keywords):
                effective_timeout = 180
            else:
                effective_timeout = 45

        # Environment flags to prevent interactive hangs (e.g. CI, git, debconf)
        env = os.environ.copy()
        env["CI"] = "1"
        env["DEBIAN_FRONTEND"] = "noninteractive"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["PYTHONUNBUFFERED"] = "1"

        try:
            res = subprocess.run(
                command,
                shell=True,  # nosec B602 - agent runner executes approved operator tasks with timeout; see permission gate
                cwd=str(self.root),
                text=True,
                capture_output=True,
                timeout=effective_timeout,
                env=env,
            )
            out = res.stdout.strip()
            err = res.stderr.strip()
            code = res.returncode

            resp_lines = [f"[Exit Code: {code}]"]
            if out:
                resp_lines.append(f"STDOUT:\n{out[:3000]}")
            if err:
                resp_lines.append(f"STDERR:\n{err[:2000]}")
            if not out and not err:
                resp_lines.append("(Tidak ada output teks)")

            return "\n\n".join(resp_lines)
        except subprocess.TimeoutExpired:
            return f"Error: Perintah melampaui batas waktu ({effective_timeout} detik)."
        except Exception as e:
            return f"Error eksekusi: {e}"

    def list_directory(self, path: str = ".") -> str:
        """List files and folders in specified directory."""
        p = self._resolve(path)
        if not p.exists():
            return f"Error: Path '{path}' tidak ditemukan."
        if not p.is_dir():
            return f"Error: '{path}' bukan direktori."

        items = []
        try:
            for item in sorted(p.iterdir()):
                if (
                    item.name.startswith(".")
                    or item.name in RepomapGenerator.IGNORE_DIRS
                ):
                    continue
                type_mark = "📁 DIR " if item.is_dir() else "📄 FILE"
                size = f"({item.stat().st_size} B)" if item.is_file() else ""
                items.append(f"{type_mark} {item.name:<30} {size}")
            return "\n".join(items) if items else "(Direktori kosong)"
        except Exception as e:
            return f"Error membaca direktori: {e}"
