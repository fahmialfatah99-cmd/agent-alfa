"""ALFA Sovereign AI - Cursor/Claude Code-Style Terminal Interface & Agentic File Patcher.

Provides an advanced, minimalist yet powerful terminal UI with:
- Prompt Toolkit session with auto-suggestions and floating completion popups.
- Dynamic bottom toolbar displaying Provider, Model, Git Branch, and Context Files.
- @file autocompletion for project files.
- Agentic File Patcher: automatically detects proposed code changes, shows colored diffs,
  and prompts to apply them directly to disk.
- Git integration (/diff, /commit, /undo).
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from alfa.core.cli.constants import (
    HISTORY_FILE,
    RICH_AVAILABLE,
    VERSION,
    Colors,
    print_status,
)


def get_git_branch() -> str:
    """Get the current git branch name if inside a git repository."""
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return ""


class AlfaCursorCompleter(Completer):
    """Provides dropdown popup completions for /slash commands and @files in the project."""

    def __init__(self, cli_instance: Any):
        self.cli = cli_instance
        self._cached_files: list[str] = []
        self._cache_mtime: float = 0.0

    def _get_project_files(self) -> list[str]:
        """Scan workspace files excluding heavy/system folders."""
        ignore_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            "venv",
            ".alfa_worktrees",
            ".pytest_cache",
            ".ruff_cache",
            ".superpowers",
            "dist",
            "build",
        }
        results = []
        root = Path.cwd()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
            for f in filenames:
                full = Path(dirpath) / f
                try:
                    rel = str(full.relative_to(root))
                    results.append(rel)
                    if len(results) >= 200:
                        return results
                except Exception:
                    pass
        return results

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text_before_cursor = document.text_before_cursor
        word_before_cursor = document.get_word_before_cursor(WORD=True)

        # 1. Complete @file mentions
        if "@" in word_before_cursor:
            prefix = word_before_cursor.split("@")[-1]
            files = self._get_project_files()
            for f in files:
                if prefix.lower() in f.lower():
                    # Replace after the @ symbol
                    display_meta = f"{os.path.getsize(f)} B" if os.path.exists(f) else "file"
                    yield Completion(
                        f,
                        start_position=-len(prefix),
                        display=f"@{f}",
                        display_meta=display_meta,
                    )
            return

        # 2. Complete /slash commands
        if text_before_cursor.strip().startswith("/"):
            query = text_before_cursor.strip()
            commands = [
                ("/menu", "Buka menu interaktif / Command Palette (Arrow keys)"),
                ("/agent", "Toggle Autonomous ReAct Agent mode [on|off]"),
                ("/repomap", "Tampilkan hierarki arsitektur & simbol proyek"),
                ("/tools", "Lihat daftar tools developer untuk agent"),
                ("/undo", "Rollback perubahan file dari riwayat patch transaksional"),
                ("/help", "Tampilkan bantuan perintah"),
                ("/add", "Tambah file ke konteks kode"),
                ("/drop", "Hapus file dari konteks"),
                ("/files", "Lihat daftar file konteks aktif"),
                ("/diff", "Lihat perubahan git diff lokal"),
                ("/commit", "Commit perubahan ke git"),
                ("/provider", "Ganti AI Provider (google, nvidia, openai, etc)"),
                ("/models", "Lihat katalog model yang didukung"),
                ("/switch", "Ganti preset (coding, fast, smart, creative)"),
                ("/mode", "Beralih mode: auto | server | standalone"),
                ("/clear", "Bersihkan riwayat percakapan"),
                ("/exit", "Keluar dari sesi ALFA CLI"),
            ]
            for cmd, desc in commands:
                if cmd.startswith(query):
                    yield Completion(
                        cmd,
                        start_position=-len(query),
                        display=cmd,
                        display_meta=desc,
                    )


class FilePatcher:
    """Detects proposed code edits from AI output and interactively applies diffs to disk."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.backup_dir = Path.cwd() / ".alfa_backups"

    def extract_modifications(self, text: str) -> list[tuple[str, str]]:
        """Extract target file paths and their contents from Markdown code blocks."""
        modifications: list[tuple[str, str]] = []

        # Pattern 1: ```lang:path/to/file.ext or ```path/to/file.ext
        pat1 = r"```(?:[a-zA-Z0-9_\-]+:)?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9_\-]+)\n(.*?)(\n```|\Z)"
        for m in re.finditer(pat1, text, re.DOTALL):
            filepath = m.group(1).strip()
            content = m.group(2)
            # Filter out non-file languages like ```json or ```python without extension
            if "/" in filepath or "." in filepath:
                modifications.append((filepath, content))

        # Pattern 2: File: `path/to/file.ext` followed by codeblock
        pat2 = r"(?:###\s*File:\s*`?|File:\s*`?)([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9_\-]+)`?\n+```(?:[a-zA-Z0-9_\-]+)?\n(.*?)(\n```|\Z)"
        for m in re.finditer(pat2, text, re.DOTALL):
            filepath = m.group(1).strip()
            content = m.group(2)
            if (filepath, content) not in modifications:
                modifications.append((filepath, content))

        return modifications

    def process_and_prompt(self, response_text: str) -> None:
        """Scan AI response for file changes and ask user to apply them."""
        mods = self.extract_modifications(response_text)
        if not mods:
            return

        for filepath_str, new_content in mods:
            target_path = Path(filepath_str)
            if not target_path.is_absolute():
                target_path = Path.cwd() / target_path

            file_exists = target_path.exists() and target_path.is_file()

            if file_exists:
                try:
                    old_content = target_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    old_content = ""

                # Compute diff
                old_lines = old_content.splitlines(keepends=True)
                new_lines = new_content.splitlines(keepends=True)
                diff = list(
                    difflib.unified_diff(
                        old_lines,
                        new_lines,
                        fromfile=f"a/{filepath_str}",
                        tofile=f"b/{filepath_str}",
                    )
                )

                if not diff:
                    continue  # Identical content

                diff_text = "".join(diff)

                # Render preview panel
                if RICH_AVAILABLE and self.console:
                    syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=False)
                    self.console.print(
                        Panel(
                            syntax,
                            title=f"📝 [bold cyan]Usulan Perubahan File: {filepath_str}[/bold cyan]",
                            border_style="cyan",
                            subtitle="[dim]Cursor Agentic Patcher[/dim]",
                        )
                    )
                else:
                    print(f"\n--- Usulan Perubahan File: {filepath_str} ---")
                    print(diff_text)

                ans = input(
                    f"\n{Colors.BOLD}{Colors.CYAN}⚡ Terapkan perubahan ke '{filepath_str}'? [y/N]: {Colors.ENDC}"
                ).strip().lower()

                if ans in ["y", "yes"]:
                    self._apply_write(target_path, old_content, new_content, filepath_str)
                else:
                    print_status(f"Perubahan pada '{filepath_str}' dilewati.", "info")

            else:
                # New file creation
                if RICH_AVAILABLE and self.console:
                    syntax = Syntax(new_content[:500], "python", theme="monokai", line_numbers=True)
                    self.console.print(
                        Panel(
                            syntax,
                            title=f"✨ [bold green]Buat File Baru: {filepath_str}[/bold green]",
                            border_style="green",
                        )
                    )

                ans = input(
                    f"\n{Colors.BOLD}{Colors.GREEN}✨ Buat file baru '{filepath_str}'? [y/N]: {Colors.ENDC}"
                ).strip().lower()

                if ans in ["y", "yes"]:
                    self._apply_write(target_path, None, new_content, filepath_str)
                else:
                    print_status(f"Pembuatan file '{filepath_str}' dibatalkan.", "info")

    def _apply_write(
        self,
        target_path: Path,
        old_content: str | None,
        new_content: str,
        display_name: str,
    ) -> None:
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Create backup if old content exists
            if old_content is not None:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                backup_file = self.backup_dir / f"{target_path.name}.bak"
                backup_file.write_text(old_content, encoding="utf-8")

            target_path.write_text(new_content, encoding="utf-8")
            print_status(f"Berhasil menerapkan perubahan ke '{display_name}'! (Backup tersimpan di .alfa_backups/)", "success")
        except Exception as e:
            print_status(f"Gagal menulis ke '{display_name}': {e}", "error")


def render_cursor_banner(cli: Any) -> None:
    """Print a clean, modern Cursor-style header."""
    direct = cli.direct_ai
    branch = get_git_branch()
    branch_info = f"  🌱 [dim]git:({branch})[/dim]" if branch else ""
    prov_info = f"[bold cyan]{direct.provider.upper()}[/bold cyan] ([green]{direct.model}[/green])"

    if RICH_AVAILABLE and cli.console:
        panel_content = (
            f"[bold white]ALFA AI Code Assistant[/bold white] [dim]v{VERSION}[/dim]\n"
            f"⚡ Provider: {prov_info}{branch_info}  │  Mode: [bold magenta]{cli.mode.upper()}[/bold magenta]\n"
            f"[dim]Ketik [bold cyan]/menu[/bold cyan] untuk menu interaktif, [cyan]@[/cyan] untuk file, atau langsung tanya/coding.[/dim]"
        )
        cli.console.print(Panel(panel_content, border_style="cyan", padding=(0, 2)))
    else:
        print(f"\n--- ALFA AI Code Assistant v{VERSION} [{direct.provider}/{direct.model}] ---")
        print("Ketik /menu untuk menu interaktif, @file untuk konteks.\n")


def run_cursor_loop(cli: Any) -> None:
    """Launch the modern Prompt Toolkit Cursor-style REPL loop."""
    render_cursor_banner(cli)
    patcher = FilePatcher(cli.console)
    completer = AlfaCursorCompleter(cli)

    # Prompt Toolkit styling
    style = Style.from_dict(
        {
            "prompt-name": "#38bdf8 bold",
            "prompt-arrow": "#22c55e bold",
            "bottom-toolbar": "bg:#0f172a #94a3b8",
            "toolbar-brand": "#38bdf8 bold",
            "toolbar-model": "#f8fafc bold",
            "toolbar-git": "#4ade80",
            "toolbar-ctx": "#fbbf24",
            "toolbar-tip": "#94a3b8 italic",
        }
    )

    history = FileHistory(str(HISTORY_FILE))
    session: PromptSession = PromptSession(
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        complete_while_typing=True,
        style=style,
    )

    def bottom_toolbar():
        direct = cli.direct_ai
        branch = get_git_branch() or "local"
        ctx_count = len(getattr(cli, "attached_files", []))
        agent_active = getattr(cli, "agent_mode", True)
        agent_style = "class:toolbar-git" if agent_active else "class:toolbar-ctx"
        agent_label = "🤖 AGENT:ON " if agent_active else "💬 CHAT:ON "
        return [
            ("class:toolbar-brand", " 🤖 ALFA "),
            ("class:toolbar-model", f"{direct.provider}:{direct.model} "),
            ("", "│ "),
            (agent_style, agent_label),
            ("", "│ "),
            ("class:toolbar-git", f"🌱 git:{branch} "),
            ("", "│ "),
            ("class:toolbar-ctx", f"📁 Context:{ctx_count} "),
            ("", "│ "),
            ("", f"🧭 Mode:{cli.mode} "),
            ("", "│ "),
            ("class:toolbar-tip", "TAB: @files & /commands "),
        ]

    prompt_fragments = [
        ("class:prompt-name", "alfa "),
        ("class:prompt-arrow", "❯ "),
    ]

    while True:
        try:
            line = session.prompt(
                prompt_fragments,
                bottom_toolbar=bottom_toolbar,
            ).strip()

            if not line:
                continue

            # Handle exit commands
            if line.lower() in ["exit", "quit", "/exit", "/quit"]:
                print_status("Sampai jumpa!", "success")
                break

            # Handle interactive menu palette
            if line.lower() in ["/menu", "menu", "/m", "m", "/palette"]:
                from alfa.core.cli.interactive_menu import open_interactive_menu
                open_interactive_menu(cli)
                continue

            # Handle git shortcuts directly
            if line.startswith("/diff"):
                res = subprocess.run(["git", "diff"], capture_output=True, text=True)
                if res.stdout:
                    if RICH_AVAILABLE and cli.console:
                        syntax = Syntax(res.stdout, "diff", theme="monokai")
                        cli.console.print(Panel(syntax, title="Git Diff", border_style="yellow"))
                    else:
                        print(res.stdout)
                else:
                    print_status("Tidak ada perubahan git yang belum di-commit.", "info")
                continue

            if line.startswith("/commit"):
                parts = line.split(maxsplit=1)
                msg = parts[1] if len(parts) > 1 else "Updates via ALFA CLI"
                res = subprocess.run(["git", "commit", "-am", msg], capture_output=True, text=True)
                print(res.stdout if res.stdout else res.stderr)
                continue

            if line.startswith("/undo"):
                parts = line.split(maxsplit=1)
                target = parts[1].strip() if len(parts) > 1 else ""
                cli.do_slash_undo(target)
                continue

            if line.startswith("/add"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    cli.do_slash_file(f"add {parts[1]}")
                else:
                    print_status("Gunakan: /add <filepath>", "warning")
                continue

            if line.startswith("/drop"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    cli.do_slash_file(f"remove {parts[1]}")
                else:
                    print_status("Gunakan: /drop <filepath>", "warning")
                continue

            if line.startswith("/files") or line.startswith("/context"):
                cli.do_slash_file("list")
                continue

            # Run regular command or chat
            cli.default(line)

            # Check if last response contained file changes, and offer agentic patching!
            if cli.chat_history:
                last_turn = cli.chat_history[-1]
                if last_turn.get("role") == "assistant":
                    patcher.process_and_prompt(last_turn.get("content", ""))

        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print("\n")
            print_status("Keluar dari ALFA CLI...", "info")
            break
        except Exception as e:
            print_status(f"Error: {e}", "error")
