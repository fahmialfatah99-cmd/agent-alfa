"""Autonomous ReAct agent runner (multi-turn tool loop)."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from alfa.core.cli.agent_engine.parsing import ToolCallParserMixin
from alfa.core.cli.agent_engine.permissions import DEFAULT_ASK_TOOLS, PermissionStore
from alfa.core.cli.agent_engine.prompts import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
    PLAN_MODE_ADDENDUM,
)
from alfa.core.cli.agent_engine.repomap import RepomapGenerator
from alfa.core.cli.agent_engine.reporting import RunReporterMixin
from alfa.core.cli.agent_engine.tool_registry import LocalToolRegistry


class AutonomousAgentRunner(ToolCallParserMixin, RunReporterMixin):
    """Orchestrates multi-turn ReAct agent loops with tools, real-time live display, and self-correction."""

    def __init__(
        self,
        direct_ai: Any,
        workspace_root: Path | None = None,
        console: Console | None = None,
    ):
        self.direct_ai = direct_ai
        self.root = workspace_root or Path.cwd()
        self.tools = LocalToolRegistry(self.root)
        self.repomap_gen = RepomapGenerator(self.root)
        self.console = console or Console()
        self.max_turns = self._resolve_max_turns()
        self.auto_approve = False
        self.plan_mode = False
        self.perm_store = PermissionStore()
        # Auto-continue budget when todos remain unfinished at loop end.
        self.max_continuations = 2
        self._continuations_used = 0

    @staticmethod
    def _resolve_max_turns(default: int = 20) -> int:
        import os

        try:
            return max(1, int(os.getenv("ALFA_MAX_TURNS", str(default))))
        except (TypeError, ValueError):
            return default

    def _pending_todos(self) -> list[dict[str, Any]]:
        try:
            todos = self.tools.todos.list()
        except Exception:
            return []
        return [t for t in todos if isinstance(t, dict) and not t.get("done")]

    # Tools that mutate files or execute commands — confirm by default.
    # Single source of truth lives in permissions.DEFAULT_ASK_TOOLS.
    MUTATING_TOOLS = DEFAULT_ASK_TOOLS


    @staticmethod
    def _read_memory_file(path: Path, limit: int = 4000) -> str:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")[:limit]
        except OSError:
            pass
        return ""

    def _load_project_memory(self) -> str:
        """Load ALFA.md project memory (workspace + global) for agent context."""
        parts = []
        local = self._read_memory_file(Path(self.root) / "ALFA.md")
        if local:
            parts.append(f"[Proyek {self.root.name}]\n{local}")
        glob = self._read_memory_file(Path.home() / ".alfa" / "ALFA.md")
        if glob:
            parts.append(f"[Global]\n{glob}")
        return "\n\n".join(parts)


    # Aliases for tool names commonly hallucinated by LLMs.
    TOOL_ALIASES = {
        "run_shell_command": "run_command",
        "run_shell": "run_command",
        "shell": "run_command",
        "bash": "run_command",
        "execute_command": "run_command",
        "execute_shell": "run_command",
        "list_files": "list_directory",
        "ls": "list_directory",
        "read": "read_file",
        "write": "write_file",
        "edit_file": "edit_file_precise",
        "edit": "edit_file_precise",
        "apply_patch": "apply_unified_diff",
        "apply_diff": "apply_unified_diff",
        "grep": "grep_workspace",
        "code_search": "search_code",
        "semantic_search": "search_codebase",
        "find_definition": "lsp_find_symbol_definition",
        "find_references": "lsp_find_symbol_references",
        "find_symbol": "lsp_find_symbol_definition",
        "git": "git_operations",
        "git_status": "git_operations",
        "add_todo": "todo_add",
        "new_todo": "todo_add",
        "complete_todo": "todo_done",
        "finish_todo": "todo_done",
    }

    def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute the appropriate registry tool or ecosystem tool."""
        tool_name = self.TOOL_ALIASES.get(tool_name, tool_name)
        if self.plan_mode and tool_name in self.MUTATING_TOOLS:
            return (
                f"Blocked: tool '{tool_name}' menonaktifkan diri dalam PLAN MODE "
                f"(read-only). Lanjutkan eksplorasi dengan tool baca dan susun "
                f"rencana akhir — JANGAN mengeksekusi."
            )
        # 1. Local Developer Tools
        if tool_name == "search_code":
            return self.tools.search_code(args.get("query", ""), args.get("path", "."))
        elif tool_name == "find_files":
            return self.tools.find_files(
                args.get("pattern", "*"), args.get("path", ".")
            )
        elif tool_name == "read_file":
            return self.tools.read_file(
                args.get("path", ""),
                int(args.get("start_line", 1)),
                int(args.get("end_line", 200)),
            )
        elif tool_name == "write_file":
            return self.tools.write_file(args.get("path", ""), args.get("content", ""))
        elif tool_name == "patch_file":
            return self.tools.patch_file(
                args.get("path", ""),
                args.get("target_content", ""),
                args.get("replacement_content", ""),
            )
        elif tool_name == "run_command":
            return self.tools.run_command(args.get("command", ""))
        elif tool_name == "list_directory":
            return self.tools.list_directory(args.get("path", "."))
        elif tool_name == "todo_add":
            return self.tools.todo_add(args.get("task", ""))
        elif tool_name == "todo_list":
            return self.tools.todo_list()
        elif tool_name == "todo_done":
            return self.tools.todo_done(args.get("todo_id", 0))

        # 2. Web & Ecosystem Tools (alfa.tools)
        try:
            from alfa import tools as alfa_ecosystem_tools

            if hasattr(alfa_ecosystem_tools, tool_name):
                fn = getattr(alfa_ecosystem_tools, tool_name)
                import asyncio
                import inspect

                sig = inspect.signature(fn)
                valid_args = {}
                for param_name, _param in sig.parameters.items():
                    if param_name in args:
                        valid_args[param_name] = args[param_name]

                # Fallback if function accepts arbitrary kwargs
                if any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                ):
                    valid_args = args

                if inspect.iscoroutinefunction(fn):
                    res = asyncio.run(fn(**valid_args))
                else:
                    res = fn(**valid_args)

                if isinstance(res, (dict, list)):
                    return json.dumps(res, indent=2, ensure_ascii=False)
                return str(res)
        except Exception as eco_err:
            return f"Error eksekusi ecosystem tool '{tool_name}': {eco_err}"

        return f"Error: Tool '{tool_name}' tidak dikenal."

    @staticmethod
    def _compress_conversation_history(
        history: list[dict[str, str]], keep_recent_messages: int = 4
    ) -> list[dict[str, str]]:
        """Compress older observations to save tokens while keeping recent turns at full resolution."""
        if len(history) <= keep_recent_messages + 1:
            return history

        compressed: list[dict[str, str]] = []
        # Message 0 is the root prompt & context -> always preserve completely
        compressed.append(history[0])

        cutoff = len(history) - keep_recent_messages
        for msg in history[1:cutoff]:
            content = msg.get("content", "")
            role = msg.get("role", "user")
            # If older user observation is very long, summarize it
            if (
                role == "user"
                and content.startswith("Observation from ")
                and len(content) > 500
            ):
                header = content.split("\n", 1)[0]
                lines = content.splitlines()
                first_part = "\n".join(lines[1:4])
                last_part = "\n".join(lines[-2:]) if len(lines) > 6 else ""
                summary_tag = (
                    f"\n[... {len(lines) - 6} baris / {len(content)} karakter diringkas untuk efisiensi token ...]\n"
                    if len(lines) > 6
                    else "\n"
                )
                pruned_content = f"{header}\n{first_part}{summary_tag}{last_part}"
                compressed.append({"role": role, "content": pruned_content})
            else:
                compressed.append(msg)

        # Append the recent messages at 100% full resolution
        compressed.extend(history[cutoff:])
        return compressed

    def run(self, user_prompt: str, plan_mode: bool = False) -> str:
        """Run the full Autonomous ReAct Loop with real-time live display.

        plan_mode=True: read-only exploration producing an execution plan
        (mutating tools are blocked, plan instructions appended to prompt).
        """
        prev_plan_mode = self.plan_mode
        self.plan_mode = plan_mode
        self._continuations_used = 0
        self._exec_log = []
        self._turns_used = 0
        self.last_run = {"task": user_prompt, "turns": 0, "finished": False}
        try:
            result = self._run_loop(user_prompt)
            self.last_run["finished"] = True
            return result
        finally:
            self.plan_mode = prev_plan_mode

    def _run_loop(self, user_prompt: str) -> str:
        """ReAct loop body (plan_mode read from self.plan_mode)."""
        # 1. Build repomap
        with self.console.status(
            "[bold cyan]🔍 Memindai arsitektur dan repomap proyek...[/bold cyan]"
        ):
            repomap = self.repomap_gen.generate_repomap()

        system_instruction = AGENT_SYSTEM_PROMPT_TEMPLATE.format(
            repomap=repomap,
            root_name=self.root.name,
            root_path=str(self.root),
        )
        memory = self._load_project_memory()
        if memory:
            system_instruction += "\n=== MEMORI PROYEK (ALFA.md) ===\n" + memory
        if self.plan_mode:
            system_instruction += "\n" + PLAN_MODE_ADDENDUM
        orig_sys_prompt = self.direct_ai.system_prompt
        self.direct_ai.system_prompt = system_instruction

        conversation_history = [
            {"role": "user", "content": f"User Request: {user_prompt}"}
        ]

        self.console.print(
            Panel(
                f"[bold green]🤖 ALFA Autonomous Agent Mode Aktif[/bold green]\n"
                f"[dim]Provider: {self.direct_ai.provider.upper()} | Model: {self.direct_ai.model} | Root: {self.root.name}[/dim]",
                border_style="green",
            )
        )

        # Proactive Local Directory & Key File Context Injection (AGY-grade Deep Inspection)
        user_lower = user_prompt.lower()
        folder_check_kws = [
            "cek folder",
            "lihat folder",
            "isi folder",
            "periksa folder",
            "struktur folder",
            "cek direktori",
            "list directory",
            "baca folder",
            "folder ini",
            "direktori ini",
            "ada file apa",
        ]
        if any(w in user_lower for w in folder_check_kws):
            dir_listing = self.tools.list_directory(".")
            self.console.print(
                f"[bold blue]📁 [REAL-TIME PERIKSA FOLDER][/bold blue] Memeriksa direktori root: [yellow]{self.root.name}[/yellow]"
            )
            self.console.print(
                Panel(
                    dir_listing,
                    title=f"📁 Isi Direktori ({self.root.name})",
                    border_style="blue",
                    padding=(0, 1),
                )
            )

            # Deep inspection: Read key files automatically (up to 3 files under 50KB)
            file_previews = []
            try:
                root_files = [
                    p
                    for p in sorted(self.root.iterdir())
                    if p.is_file()
                    and not p.name.startswith(".")
                    and p.name not in RepomapGenerator.IGNORE_DIRS
                ]
                for f in root_files[:3]:
                    if f.stat().st_size <= 50000:
                        content_snip = self.tools.read_file(f.name, 1, 150)
                        self.console.print(
                            f"[bold cyan]📖 [REAL-TIME INSPEKSI KONTEN][/bold cyan] Membaca berkas: [yellow]{f.name}[/yellow] ({f.stat().st_size} bytes)"
                        )
                        file_previews.append(
                            f"--- BERKAS: {f.name} ({f.stat().st_size} bytes) ---\n{content_snip}"
                        )
            except Exception:
                pass

            proactive_info = (
                f"[Sistem Lokal: Output real-time list_directory('.')]:\n{dir_listing}"
            )
            if file_previews:
                proactive_info += (
                    "\n\n[Sistem Lokal: Isi Berkas Penting yang Ditemukan]:\n"
                    + "\n\n".join(file_previews)
                )

            conversation_history[0]["content"] += (
                f"\n\n{proactive_info}\n\n"
                "Instruksi Wajib: Berikan laporan analisis arsitektur proyek dan isi berkas secara sangat mendalam, terstruktur, dan komprehensif ala Google Antigravity / Cursor, "
                "mencakup ringkasan eksekutif, struktur & pemetaan berkas, bedah mendalam arsitektur isi berkas, evaluasi teknis, dan rekomendasi langkah selanjutnya."
            )

        final_answer = ""
        executed_calls_history: set[tuple[str, str]] = set()

        try:
            for turn in range(1, self.max_turns + 1):
                self._turns_used = getattr(self, "_turns_used", 0) + 1
                # Smart context pruning for token efficiency
                pruned_history = self._compress_conversation_history(
                    conversation_history, keep_recent_messages=4
                )
                prompt_text = ""
                for msg in pruned_history:
                    role_prefix = "User" if msg["role"] == "user" else "Assistant"
                    prompt_text += f"{role_prefix}: {msg['content']}\n\n"

                with self.console.status(
                    f"[bold yellow]🧠 Turn #{turn}: AI sedang menganalisis & merencanakan tindakan...[/bold yellow]"
                ):
                    response = self.direct_ai.generate(prompt_text, stream=False)

                # Anti-Refusal Intervention:
                # If LLM hallucinates refusal regarding local access, intercept and feed directory
                refusal_phrases = [
                    "tidak memiliki akses langsung",
                    "tidak memiliki akses ke sistem file",
                    "tidak dapat mengakses sistem file",
                    "silakan jalankan salah satu perintah berikut",
                    "salin dan tempel",
                ]
                if any(rp in response.lower() for rp in refusal_phrases):
                    dir_info = self.tools.list_directory(".")
                    self.console.print(
                        "[bold yellow]⚡ [REAL-TIME AUTO-OBSERVE][/bold yellow] Menginspeksi direktori lokal..."
                    )
                    self.console.print(
                        Panel(
                            dir_info,
                            title="📁 [REAL-TIME] Isi Folder Lokal",
                            border_style="blue",
                            padding=(0, 1),
                        )
                    )
                    conversation_history.append(
                        {
                            "role": "assistant",
                            "content": "Saya akan memeriksa isi folder lokal.",
                        }
                    )
                    conversation_history.append(
                        {
                            "role": "user",
                            "content": f"Anda memiliki akses lokal penuh di komputer ini. Berikut adalah isi folder proyek saat ini:\n{dir_info}\nSilakan langsung analisis folder ini dan berikan Final Answer secara lengkap.",
                        }
                    )
                    continue

                # Check for tool calls
                tool_calls = self._extract_tool_calls(response)

                if "Final Answer:" in response and not tool_calls:
                    final_part = response.split("Final Answer:", 1)[1].strip()
                    final_answer = final_part or response
                    break

                # Self-heal: model attempted a tool call but it is malformed
                # (unclosed fence / broken JSON). Ask for a clean re-emit
                # instead of printing raw protocol text as the final answer.
                if not tool_calls and (
                    "```tool_call" in response or "<tool_call>" in response
                ):
                    self.console.print(
                        "   [dim]Blok tool_call tidak valid — meminta model mengirim ulang...[/dim]"
                    )
                    conversation_history.append(
                        {"role": "assistant", "content": response}
                    )
                    conversation_history.append(
                        {
                            "role": "user",
                            "content": (
                                "Blok tool_call Anda tidak lengkap/valid (pagar kode "
                                "tidak ditutup atau JSON rusak) sehingga tidak bisa "
                                "dieksekusi. Kirim ULANG hanya SATU blok "
                                "```tool_call berisi SATU objek JSON valid "
                                '{"tool": "<nama>", "args": {...}}, tanpa teks lain.'
                            ),
                        }
                    )
                    continue

                # Filter out redundant tool calls that were already executed with exact same arguments
                filtered_calls = []
                for call in tool_calls:
                    call_sig = (
                        call.get("tool", ""),
                        json.dumps(call.get("args", {}), sort_keys=True),
                    )
                    if call_sig in executed_calls_history:
                        continue
                    executed_calls_history.add(call_sig)
                    filtered_calls.append(call)

                if not filtered_calls:
                    # No new tool calls needed, treat response as final completion
                    if "Final Answer:" in response:
                        final_answer = response.split("Final Answer:", 1)[1].strip()
                    else:
                        final_answer = response
                    break

                tool_calls = filtered_calls

                # Execute discovered tool calls with real-time visual output
                for call in tool_calls:
                    tool_name = call.get("tool", "")
                    args = call.get("args", {})
                    # Normalize aliases BEFORE approval checks so hallucinated
                    # names (e.g. run_shell_command) get the same safety barrier.
                    tool_name = self.TOOL_ALIASES.get(tool_name, tool_name)
                    args_str = json.dumps(args)

                    # Approval policy: deny > auto-approve/allow > manual confirm.
                    # Rules persist via /permit (opencode-style allow/ask/deny).
                    rule = self.perm_store.get(tool_name)
                    if rule == "deny":
                        tool_result = (
                            f"Ditolak: tool '{tool_name}' diblokir oleh aturan "
                            f"permission. Ubah dengan /permit {tool_name} allow."
                        )
                        self.console.print(f"   [dim]{tool_result}[/dim]")
                    elif self.auto_approve or rule == "allow":
                        with self.console.status(
                            f"[cyan]Menjalankan {tool_name}...[/cyan]"
                        ):
                            tool_result = self._execute_tool(tool_name, args)
                    else:
                        ans = (
                            input(
                                f"\n   [Konfirmasi] Eksekusi {tool_name}({args_str[:80]}...)? "
                                f"[Y/n/a(ll)=auto sesi ini]: "
                            )
                            .strip()
                            .lower()
                        )
                        if ans in ("n", "no"):
                            tool_result = "Eksekusi dibatalkan oleh pengguna."
                            self.console.print("   [dim]Dibatalkan oleh user.[/dim]")
                        else:
                            if ans in ("a", "all", "always"):
                                self.auto_approve = True
                                self.console.print(
                                    "   [dim]Auto-approve AKTIF untuk sesi ini.[/dim]"
                                )
                            with self.console.status(
                                f"[cyan]Menjalankan {tool_name}...[/cyan]"
                            ):
                                tool_result = self._execute_tool(tool_name, args)

                    # Log every execution for honest end-of-run reporting.
                    self._log_execution(tool_name, args, tool_result)

                    # Real-time live display based on tool type:
                    if tool_name == "read_file":
                        file_p = args.get("path", "")
                        st = args.get("start_line", 1)
                        en = args.get("end_line", 200)
                        self.console.print(
                            f"\n[bold cyan]📖 [REAL-TIME BACA FILE][/bold cyan] Membaca: [yellow]{file_p}[/yellow] (Baris {st}-{en})"
                        )
                        lines = tool_result.splitlines()
                        display_text = "\n".join(lines[:35]) + (
                            f"\n... [{len(lines) - 35} baris lainnya]"
                            if len(lines) > 35
                            else ""
                        )
                        self.console.print(
                            Panel(
                                display_text,
                                title=f"📄 {file_p}",
                                border_style="cyan",
                                padding=(0, 1),
                            )
                        )

                    elif tool_name == "write_file":
                        file_p = args.get("path", "")
                        self.console.print(
                            f"\n[bold green]✍️ [REAL-TIME TULIS FILE][/bold green] Menulis: [yellow]{file_p}[/yellow]"
                        )
                        content = args.get("content", "")
                        ext = Path(file_p).suffix.lstrip(".")
                        lang = (
                            "python"
                            if ext in ("py", "pyw")
                            else "javascript"
                            if ext in ("js", "ts", "jsx", "tsx")
                            else ext or "text"
                        )
                        syntax = Syntax(
                            content[:1500], lang, theme="monokai", line_numbers=True
                        )
                        self.console.print(
                            Panel(
                                syntax,
                                title=f"✨ {file_p}",
                                border_style="green",
                                padding=(0, 1),
                            )
                        )

                    elif tool_name == "patch_file":
                        file_p = args.get("path", "")
                        self.console.print(
                            f"\n[bold yellow]📝 [REAL-TIME PATCH FILE][/bold yellow] Menerapkan patch pada: [yellow]{file_p}[/yellow]"
                        )
                        target_c = args.get("target_content", "")
                        repl_c = args.get("replacement_content", "")
                        diff = difflib.unified_diff(
                            target_c.splitlines(keepends=True),
                            repl_c.splitlines(keepends=True),
                            fromfile="sebelum",
                            tofile="sesudah",
                        )
                        diff_text = "".join(diff)
                        if diff_text:
                            syntax = Syntax(diff_text, "diff", theme="monokai")
                            self.console.print(
                                Panel(
                                    syntax,
                                    title=f"📝 Diff Patch: {file_p}",
                                    border_style="yellow",
                                    padding=(0, 1),
                                )
                            )

                    elif tool_name == "list_directory":
                        dir_p = args.get("path", ".")
                        self.console.print(
                            f"\n[bold blue]📁 [REAL-TIME PERIKSA FOLDER][/bold blue] Memindai: [yellow]{dir_p}[/yellow]"
                        )
                        self.console.print(
                            Panel(
                                tool_result,
                                title=f"📁 Isi Direktori ({dir_p})",
                                border_style="blue",
                                padding=(0, 1),
                            )
                        )

                    elif tool_name in ("search_code", "find_files"):
                        q = args.get("query") or args.get("pattern", "")
                        self.console.print(
                            f"\n[bold magenta]🔍 [REAL-TIME PENCARIAN][/bold magenta] Query: [yellow]'{q}'[/yellow]"
                        )
                        self.console.print(
                            Panel(
                                tool_result[:1500],
                                title=f"🔍 Hasil Temuan ({q})",
                                border_style="magenta",
                                padding=(0, 1),
                            )
                        )

                    elif tool_name == "run_command":
                        cmd_p = args.get("command", "")
                        self.console.print(
                            f"\n[bold red]⚡ [REAL-TIME TERMINAL SHELL][/bold red] `$ {cmd_p}`"
                        )
                        self.console.print(
                            Panel(
                                tool_result[:2000],
                                title="⚡ Output Shell",
                                border_style="red",
                                padding=(0, 1),
                            )
                        )

                    else:
                        preview = tool_result.strip()[:400]
                        self.console.print(
                            Panel(
                                preview,
                                title=f"📋 Observation ({tool_name})",
                                border_style="dim",
                            )
                        )

                    conversation_history.append(
                        {"role": "assistant", "content": response}
                    )
                    conversation_history.append(
                        {
                            "role": "user",
                            "content": f"Observation from {tool_name}:\n{tool_result}\n\nLanjutkan analisis mendalam atau berikan Final Answer jika tugas selesai.",
                        }
                    )

            if not final_answer:
                # 1. Recover last substantial assistant message
                for msg in reversed(conversation_history):
                    content = msg.get("content", "").strip()
                    if (
                        msg.get("role") == "assistant"
                        and len(content) > 100
                        and "```tool_call" not in content
                    ):
                        if "Final Answer:" in content:
                            final_answer = content.split("Final Answer:", 1)[1].strip()
                        else:
                            final_answer = content
                        break

            if not final_answer:
                if self._exec_log:
                    # 2a. Honest execution report: tools DID run but no Final
                    # Answer was produced (e.g. turn budget exhausted).
                    final_answer = self._build_execution_report()
                else:
                    # 2b. Nothing executed at all: generic directory overview.
                    dir_summary = self.tools.list_directory(".")
                    final_answer = (
                        f"## 📋 Laporan Analisis Direktori: `{self.root.name}`\n\n"
                        f"### 📁 Struktur Berkas & Komponen\n```text\n{dir_summary}\n```\n\n"
                        f"> [!NOTE]\n"
                        f"> Direktori kerja saat ini berada di `{self.root}`. Seluruh berkas di atas telah berhasil dipindai dan siap untuk diinspeksi atau dimodifikasi.\n\n"
                        f"### 💡 Rekomendasi Tindakan Selanjutnya\n"
                        f"- Ketik perintah untuk membaca berkas secara mendalam (contoh: `baca file <nama_berkas>`).\n"
                        f"- Minta saya menambahkan kode, fitur baru, atau menjalankan unit test."
                    )

            # Auto-continue: never go silent while todos remain unfinished.
            # (plan_mode runs are one-shot by design and never continue.)
            pending = self._pending_todos()
            if pending and not self.plan_mode and self._continuations_used < self.max_continuations:
                self._continuations_used += 1
                remaining = ", ".join(
                    f"#{t.get('id')} {t.get('task', '')}" for t in pending
                )
                self.console.print(
                    f"\n[bold yellow]🔁 Melanjutkan otomatis "
                    f"({self._continuations_used}/{self.max_continuations}): "
                    f"{len(pending)} todo belum selesai...[/bold yellow]"
                )
                return self._run_loop(
                    f"Lanjutkan tugas multi-langkah yang BELUM SELESAI. "
                    f"Jangan ulangi yang sudah beres; fokus menuntaskan sisa ini. "
                    f"Todo tersisa: {remaining}\n\n"
                    f"Hasil terakhir sejauh ini:\n{final_answer[:2000]}"
                )

            if isinstance(getattr(self, "last_run", None), dict):
                try:
                    pending_left = self._pending_todos()
                except Exception:
                    pending_left = []
                exec_log = getattr(self, "_exec_log", []) or []
                self.last_run.update(
                    {
                        "turns": getattr(self, "_turns_used", 0),
                        "tools": [e["tool"] for e in exec_log],
                        "files": sorted(
                            {f for e in exec_log for f in e["files"]}
                        ),
                        "todos_pending": len(pending_left),
                        "finished": not pending_left,
                    }
                )
            return final_answer

        finally:
            # Restore normal system prompt
            self.direct_ai.system_prompt = orig_sys_prompt
