"""Agent execution helpers: approval, live display, refusal recovery."""

import difflib
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.syntax import Syntax


class ExecutionMixin:
    """Approval barriers, real-time display, and refusal intervention."""

    perm_store: Any
    console: Any
    auto_approve: bool
    tools: Any

    def _execute_tool(self, *args: Any, **kwargs: Any) -> Any: ...

    def _approved_execute(self, tool_name, args, args_str):
        """Run approval policy (deny/auto/allow/manual) and execute."""
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
            with self.console.status(f"[cyan]Menjalankan {tool_name}...[/cyan]"):
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
                with self.console.status(f"[cyan]Menjalankan {tool_name}...[/cyan]"):
                    tool_result = self._execute_tool(tool_name, args)
        return tool_result

    def _display_tool_result(self, tool_name, args, tool_result):
        """Render clean, minimalist tool status and concise output."""
        if tool_name == "read_file":
            file_p = args.get("path", "")
            lines = tool_result.splitlines()
            self.console.print(f"  [cyan]•[/cyan] Read [bold]{file_p}[/bold] [dim]({len(lines)} lines)[/dim]")

        elif tool_name == "write_file":
            file_p = args.get("path", "")
            content = args.get("content", "")
            ext = Path(file_p).suffix.lstrip(".")
            lang = (
                "python"
                if ext in ("py", "pyw")
                else "javascript"
                if ext in ("js", "ts", "jsx", "tsx")
                else ext or "text"
            )
            self.console.print(f"  [green]✓[/green] Wrote [bold]{file_p}[/bold]")
            if content.strip():
                syntax = Syntax(content[:800], lang, theme="monokai", line_numbers=True)
                self.console.print(
                    Panel(
                        syntax,
                        border_style="grey37",
                        padding=(0, 1),
                    )
                )

        elif tool_name == "patch_file":
            file_p = args.get("path", "")
            target_c = args.get("target_content", "")
            repl_c = args.get("replacement_content", "")
            diff = difflib.unified_diff(
                target_c.splitlines(keepends=True),
                repl_c.splitlines(keepends=True),
                fromfile="a/" + file_p,
                tofile="b/" + file_p,
            )
            diff_text = "".join(diff)
            self.console.print(f"  [green]✓[/green] Patched [bold]{file_p}[/bold]")
            if diff_text:
                syntax = Syntax(diff_text, "diff", theme="monokai")
                self.console.print(
                    Panel(
                        syntax,
                        border_style="grey37",
                        padding=(0, 1),
                    )
                )

        elif tool_name == "list_directory":
            dir_p = args.get("path", ".")
            count = len([line for line in tool_result.splitlines() if line.strip()])
            self.console.print(f"  [cyan]•[/cyan] Listed [bold]{dir_p}[/bold] [dim]({count} entries)[/dim]")

        elif tool_name in ("search_code", "find_files"):
            q = args.get("query") or args.get("pattern", "")
            lines = [line for line in tool_result.splitlines() if line.strip()]
            self.console.print(f"  [cyan]•[/cyan] Searched [bold]'{q}'[/bold] [dim]({len(lines)} matches)[/dim]")
            if lines and "Tidak" not in lines[0] and "Error" not in lines[0]:
                preview = "\n".join(lines[:8])
                if len(lines) > 8:
                    preview += f"\n[dim]... +{len(lines) - 8} more[/dim]"
                self.console.print(
                    Panel(
                        preview,
                        border_style="grey37",
                        padding=(0, 1),
                    )
                )

        elif tool_name == "run_command":
            cmd_p = args.get("command", "")
            self.console.print(f"  [yellow]•[/yellow] Executed [bold]$ {cmd_p}[/bold]")
            if tool_result.strip():
                lines = tool_result.strip().splitlines()
                preview = "\n".join(lines[:20])
                if len(lines) > 20:
                    preview += f"\n[dim]... +{len(lines) - 20} lines[/dim]"
                self.console.print(
                    Panel(
                        preview,
                        border_style="grey37",
                        padding=(0, 1),
                    )
                )

        else:
            preview = tool_result.strip()[:200]
            self.console.print(f"  [dim]• Tool {tool_name} completed: {preview}[/dim]")

    def _handle_refusal(self, response, conversation_history):
        """Recover from hallucinated local-access refusal. Returns True if handled."""
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
            return True
        return False
