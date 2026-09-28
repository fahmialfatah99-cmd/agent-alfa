"""Autonomous ReAct agent runner (multi-turn tool loop)."""

from __future__ import annotations

import ast
import difflib
import json
import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from alfa.core.cli.agent_engine.prompts import AGENT_SYSTEM_PROMPT_TEMPLATE
from alfa.core.cli.agent_engine.repomap import RepomapGenerator
from alfa.core.cli.agent_engine.tool_registry import LocalToolRegistry


class AutonomousAgentRunner:
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
        self.max_turns = 10
        self.auto_approve = False

    @staticmethod
    def _parse_relaxed_json(raw: str) -> dict[str, Any] | None:
        """Parse JSON with error tolerance for single quotes, trailing commas, and unescaped newlines."""
        cleaned = raw.strip()
        try:
            val = json.loads(cleaned)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Cleanup trailing commas
        cleaned_no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            val = json.loads(cleaned_no_trailing)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Try ast.literal_eval for Python dictionary literals with single quotes
        try:
            val = ast.literal_eval(cleaned)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # Convert single quotes around keys and values
        try:
            sq_fixed = re.sub(r"(?<=[{,\s])'([^']+)'(?=\s*:)", r'"\1"', cleaned_no_trailing)
            sq_fixed = re.sub(r":\s*'([^']*)'(?=[,}\s])", r': "\1"', sq_fixed)
            val = json.loads(sq_fixed)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        return None

    @staticmethod
    def _find_balanced_json_blocks(text: str) -> list[str]:
        """Find all top-level balanced JSON { ... } blocks in text, properly respecting strings."""
        blocks: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if text[i] == "{":
                start = i
                depth = 0
                in_str = False
                str_char = ""
                escape = False
                while i < n:
                    c = text[i]
                    if in_str:
                        if escape:
                            escape = False
                        elif c == "\\":
                            escape = True
                        elif c == str_char:
                            in_str = False
                    else:
                        if c in ('"', "'"):
                            in_str = True
                            str_char = c
                        elif c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                blocks.append(text[start : i + 1])
                                break
                    i += 1
            i += 1
        return blocks

    def _extract_tool_calls(self, text: str) -> list[dict[str, Any]]:
        """Extract tool call requests from LLM text with resilient balanced-braces & relaxed parsing."""
        calls: list[dict[str, Any]] = []

        # If LLM provided Final Answer, only parse tool calls before the final answer text
        search_text = text
        if "Final Answer:" in text:
            search_text = text.split("Final Answer:", 1)[0]
            if not search_text.strip():
                return []

        # 1. Search in code blocks ```tool_call ... ```, ```json ... ```, or <tool_call> ... </tool_call>
        code_block_patterns = [
            r"```(?:tool_call|json)?\s*([\s\S]*?)\s*```",
            r"<tool_call>\s*([\s\S]*?)\s*</tool_call>",
        ]
        for pat in code_block_patterns:
            for m in re.finditer(pat, search_text, re.DOTALL):
                block_text = m.group(1).strip()
                for json_candidate in self._find_balanced_json_blocks(block_text):
                    parsed = self._parse_relaxed_json(json_candidate)
                    if parsed and "tool" in parsed:
                        if not any(
                            c.get("tool") == parsed.get("tool") and c.get("args") == parsed.get("args")
                            for c in calls
                        ):
                            calls.append(parsed)

        # 2. Raw balanced JSON blocks anywhere in search_text
        if not calls:
            for json_candidate in self._find_balanced_json_blocks(search_text):
                parsed = self._parse_relaxed_json(json_candidate)
                if parsed and "tool" in parsed:
                    if not any(
                        c.get("tool") == parsed.get("tool") and c.get("args") == parsed.get("args")
                        for c in calls
                    ):
                        calls.append(parsed)

        # 3. Function call syntax: tool_name(arg1=val1, ...) or tool_name("arg1")
        if not calls:
            fn_pat = r"\b([a-zA-Z0-9_]+)\s*\(([\s\S]*?)\)"
            known_simple = {
                "list_directory", "read_file", "find_files", "search_code",
                "write_file", "patch_file", "run_command", "web_search",
                "fetch_web_page_content", "universal_deep_scraper",
                "audit_website_security", "get_system_stats",
                "vault_get_secret", "vault_store_secret", "vault_list_secrets",
            }
            for m in re.finditer(fn_pat, search_text):
                t_name = m.group(1)
                if t_name not in known_simple:
                    continue
                raw_args = m.group(2).strip()

                parsed_args: dict[str, Any] = {}
                kw_matches = re.findall(
                    r'([a-zA-Z0-9_]+)\s*=\s*([^\s,]+|"[^"]*"|\'[^\']*\')', raw_args
                )
                if kw_matches:
                    for k, v in kw_matches:
                        clean_v = v.strip().strip("'\"")
                        if clean_v.isdigit():
                            parsed_args[k] = int(clean_v)
                        else:
                            parsed_args[k] = clean_v
                else:
                    clean_single = raw_args.strip().strip("'\"")
                    if t_name == "list_directory":
                        parsed_args = {"path": clean_single or "."}
                    elif t_name == "read_file":
                        parsed_args = {"path": clean_single, "start_line": 1, "end_line": 200}
                    elif t_name == "find_files":
                        parsed_args = {"pattern": clean_single or "*"}
                    elif t_name == "search_code":
                        parsed_args = {"query": clean_single}
                    elif t_name == "run_command":
                        parsed_args = {"command": clean_single}
                    elif t_name == "web_search":
                        parsed_args = {"query": clean_single}
                    elif t_name == "fetch_web_page_content":
                        parsed_args = {"url": clean_single}
                    elif t_name == "audit_website_security":
                        parsed_args = {"url": clean_single}
                    elif t_name == "vault_get_secret":
                        parsed_args = {"secret_name": clean_single}
                    elif t_name in ("get_system_stats", "vault_list_secrets"):
                        parsed_args = {}

                if t_name:
                    calls.append({"tool": t_name, "args": parsed_args})

        return calls

    def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute the appropriate registry tool or ecosystem tool."""
        # 1. Local Developer Tools
        if tool_name == "search_code":
            return self.tools.search_code(args.get("query", ""), args.get("path", "."))
        elif tool_name == "find_files":
            return self.tools.find_files(args.get("pattern", "*"), args.get("path", "."))
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
                if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
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
            if role == "user" and content.startswith("Observation from ") and len(content) > 500:
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

    def run(self, user_prompt: str) -> str:
        """Run the full Autonomous ReAct Loop with real-time live display."""
        # 1. Build repomap
        with self.console.status("[bold cyan]🔍 Memindai arsitektur dan repomap proyek...[/bold cyan]"):
            repomap = self.repomap_gen.generate_repomap()

        system_instruction = AGENT_SYSTEM_PROMPT_TEMPLATE.format(
            repomap=repomap,
            root_name=self.root.name,
            root_path=str(self.root),
        )
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
            "cek folder", "lihat folder", "isi folder", "periksa folder",
            "struktur folder", "cek direktori", "list directory", "baca folder",
            "folder ini", "direktori ini", "ada file apa"
        ]
        if any(w in user_lower for w in folder_check_kws):
            dir_listing = self.tools.list_directory(".")
            self.console.print(f"[bold blue]📁 [REAL-TIME PERIKSA FOLDER][/bold blue] Memeriksa direktori root: [yellow]{self.root.name}[/yellow]")
            self.console.print(Panel(dir_listing, title=f"📁 Isi Direktori ({self.root.name})", border_style="blue", padding=(0, 1)))

            # Deep inspection: Read key files automatically (up to 3 files under 50KB)
            file_previews = []
            try:
                root_files = [
                    p for p in sorted(self.root.iterdir())
                    if p.is_file() and not p.name.startswith(".") and p.name not in RepomapGenerator.IGNORE_DIRS
                ]
                for f in root_files[:3]:
                    if f.stat().st_size <= 50000:
                        content_snip = self.tools.read_file(f.name, 1, 150)
                        self.console.print(f"[bold cyan]📖 [REAL-TIME INSPEKSI KONTEN][/bold cyan] Membaca berkas: [yellow]{f.name}[/yellow] ({f.stat().st_size} bytes)")
                        file_previews.append(f"--- BERKAS: {f.name} ({f.stat().st_size} bytes) ---\n{content_snip}")
            except Exception:
                pass

            proactive_info = f"[Sistem Lokal: Output real-time list_directory('.')]:\n{dir_listing}"
            if file_previews:
                proactive_info += "\n\n[Sistem Lokal: Isi Berkas Penting yang Ditemukan]:\n" + "\n\n".join(file_previews)

            conversation_history[0]["content"] += (
                f"\n\n{proactive_info}\n\n"
                "Instruksi Wajib: Berikan laporan analisis arsitektur proyek dan isi berkas secara sangat mendalam, terstruktur, dan komprehensif ala Google Antigravity / Cursor, "
                "mencakup ringkasan eksekutif, struktur & pemetaan berkas, bedah mendalam arsitektur isi berkas, evaluasi teknis, dan rekomendasi langkah selanjutnya."
            )

        final_answer = ""
        executed_calls_history: set[tuple[str, str]] = set()

        try:
            for turn in range(1, self.max_turns + 1):
                # Smart context pruning for token efficiency
                pruned_history = self._compress_conversation_history(
                    conversation_history, keep_recent_messages=4
                )
                prompt_text = ""
                for msg in pruned_history:
                    role_prefix = "User" if msg["role"] == "user" else "Assistant"
                    prompt_text += f"{role_prefix}: {msg['content']}\n\n"

                with self.console.status(f"[bold yellow]🧠 Turn #{turn}: AI sedang menganalisis & merencanakan tindakan...[/bold yellow]"):
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
                    self.console.print("[bold yellow]⚡ [REAL-TIME AUTO-OBSERVE][/bold yellow] Menginspeksi direktori lokal...")
                    self.console.print(Panel(dir_info, title="📁 [REAL-TIME] Isi Folder Lokal", border_style="blue", padding=(0, 1)))
                    conversation_history.append({"role": "assistant", "content": "Saya akan memeriksa isi folder lokal."})
                    conversation_history.append({
                        "role": "user",
                        "content": f"Anda memiliki akses lokal penuh di komputer ini. Berikut adalah isi folder proyek saat ini:\n{dir_info}\nSilakan langsung analisis folder ini dan berikan Final Answer secara lengkap.",
                    })
                    continue

                # Check for tool calls
                tool_calls = self._extract_tool_calls(response)

                if "Final Answer:" in response and not tool_calls:
                    final_part = response.split("Final Answer:", 1)[1].strip()
                    final_answer = final_part or response
                    break

                # Filter out redundant tool calls that were already executed with exact same arguments
                filtered_calls = []
                for call in tool_calls:
                    call_sig = (call.get("tool", ""), json.dumps(call.get("args", {}), sort_keys=True))
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
                    args_str = json.dumps(args)

                    # Confirmation barrier only for modifying commands
                    if not self.auto_approve and tool_name in ("run_command", "write_file", "patch_file"):
                        ans = input(f"\n   [Konfirmasi] Eksekusi {tool_name}({args_str[:80]}...)? [Y/n]: ").strip().lower()
                        if ans in ("n", "no"):
                            tool_result = "Eksekusi dibatalkan oleh pengguna."
                            self.console.print("   [dim]Dibatalkan oleh user.[/dim]")
                        else:
                            with self.console.status(f"[cyan]Menjalankan {tool_name}...[/cyan]"):
                                tool_result = self._execute_tool(tool_name, args)
                    else:
                        with self.console.status(f"[cyan]Menjalankan {tool_name}...[/cyan]"):
                            tool_result = self._execute_tool(tool_name, args)

                    # Real-time live display based on tool type:
                    if tool_name == "read_file":
                        file_p = args.get("path", "")
                        st = args.get("start_line", 1)
                        en = args.get("end_line", 200)
                        self.console.print(f"\n[bold cyan]📖 [REAL-TIME BACA FILE][/bold cyan] Membaca: [yellow]{file_p}[/yellow] (Baris {st}-{en})")
                        lines = tool_result.splitlines()
                        display_text = "\n".join(lines[:35]) + (f"\n... [{len(lines) - 35} baris lainnya]" if len(lines) > 35 else "")
                        self.console.print(Panel(display_text, title=f"📄 {file_p}", border_style="cyan", padding=(0, 1)))

                    elif tool_name == "write_file":
                        file_p = args.get("path", "")
                        self.console.print(f"\n[bold green]✍️ [REAL-TIME TULIS FILE][/bold green] Menulis: [yellow]{file_p}[/yellow]")
                        content = args.get("content", "")
                        ext = Path(file_p).suffix.lstrip(".")
                        lang = "python" if ext in ("py", "pyw") else "javascript" if ext in ("js", "ts", "jsx", "tsx") else ext or "text"
                        syntax = Syntax(content[:1500], lang, theme="monokai", line_numbers=True)
                        self.console.print(Panel(syntax, title=f"✨ {file_p}", border_style="green", padding=(0, 1)))

                    elif tool_name == "patch_file":
                        file_p = args.get("path", "")
                        self.console.print(f"\n[bold yellow]📝 [REAL-TIME PATCH FILE][/bold yellow] Menerapkan patch pada: [yellow]{file_p}[/yellow]")
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
                            self.console.print(Panel(syntax, title=f"📝 Diff Patch: {file_p}", border_style="yellow", padding=(0, 1)))

                    elif tool_name == "list_directory":
                        dir_p = args.get("path", ".")
                        self.console.print(f"\n[bold blue]📁 [REAL-TIME PERIKSA FOLDER][/bold blue] Memindai: [yellow]{dir_p}[/yellow]")
                        self.console.print(Panel(tool_result, title=f"📁 Isi Direktori ({dir_p})", border_style="blue", padding=(0, 1)))

                    elif tool_name in ("search_code", "find_files"):
                        q = args.get("query") or args.get("pattern", "")
                        self.console.print(f"\n[bold magenta]🔍 [REAL-TIME PENCARIAN][/bold magenta] Query: [yellow]'{q}'[/yellow]")
                        self.console.print(Panel(tool_result[:1500], title=f"🔍 Hasil Temuan ({q})", border_style="magenta", padding=(0, 1)))

                    elif tool_name == "run_command":
                        cmd_p = args.get("command", "")
                        self.console.print(f"\n[bold red]⚡ [REAL-TIME TERMINAL SHELL][/bold red] `$ {cmd_p}`")
                        self.console.print(Panel(tool_result[:2000], title="⚡ Output Shell", border_style="red", padding=(0, 1)))

                    else:
                        preview = tool_result.strip()[:400]
                        self.console.print(Panel(preview, title=f"📋 Observation ({tool_name})", border_style="dim"))

                    conversation_history.append({"role": "assistant", "content": response})
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
                    if msg.get("role") == "assistant" and len(content) > 100 and "```tool_call" not in content:
                        if "Final Answer:" in content:
                            final_answer = content.split("Final Answer:", 1)[1].strip()
                        else:
                            final_answer = content
                        break

            if not final_answer:
                # 2. Comprehensive fallback report using workspace data (AGY-standard)
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

            return final_answer

        finally:
            # Restore normal system prompt
            self.direct_ai.system_prompt = orig_sys_prompt
