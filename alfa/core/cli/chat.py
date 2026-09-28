"""Chat interaction loop, streaming handler, markdown rendering, and shell runner for CLI."""

from __future__ import annotations

import json
import subprocess
import sys

from alfa.core.cli.constants import (
    RICH_AVAILABLE,
    Colors,
    Live,
    Markdown,
    Spinner,
    print_status,
)


class CliChatMixin:
    """Handles prompt input, multi-mode AI routing (Server & Direct), streaming, and shell execution."""

    def default(self, line: str) -> None:
        """Menangani input chat biasa, perintah shell (!cmd), atau slash commands (/cmd)."""
        line_str = line.strip()
        if not line_str:
            return

        # 1. Handle Shell Commands langsung jika diawali '!'
        if line_str.startswith("!"):
            shell_cmd = line_str[1:].strip()
            self._execute_shell_command(shell_cmd)
            return

        # 2. Handle Slash Commands (/help, /mode, /provider, dsb)
        if line_str.startswith("/"):
            parts = line_str[1:].split(" ", 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            method_name = f"do_slash_{cmd}"
            if hasattr(self, method_name):
                return getattr(self, method_name)(args)
            else:
                print_status(f"Perintah tidak dikenal: {line_str}", "error")
                print("Ketik /help untuk daftar perintah.", "info")
                return

        # 3. Mode Routing: Tentukan apakah menggunakan Server ALFA atau Direct Standalone AI
        use_direct = False
        if getattr(self, "mode", "auto") == "standalone":
            use_direct = True
        elif getattr(self, "mode", "auto") == "auto":
            if not getattr(self, "server_reachable", False) or not getattr(
                self, "session_token", None
            ):
                use_direct = True

        if use_direct:
            self._chat_direct_standalone(line_str)
        else:
            self._chat_via_server(line_str)

    def _execute_shell_command(self, cmd: str) -> None:
        """Execute a local shell command safely and print output."""
        if not cmd:
            print_status("Perintah shell kosong.", "warning")
            return

        print(f"{Colors.WARNING}⚡ Menjalankan shell:{Colors.ENDC} {cmd}")
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                text=True,
                capture_output=True,
                timeout=120,
            )
            if res.stdout:
                print(res.stdout, end="" if res.stdout.endswith("\n") else "\n")
            if res.stderr:
                print(f"{Colors.FAIL}{res.stderr}{Colors.ENDC}", end="")
            if res.returncode != 0:
                print_status(f"Exit code: {res.returncode}", "warning")
        except subprocess.TimeoutExpired:
            print_status("Perintah timeout setelah 120 detik.", "error")
        except Exception as e:
            print_status(f"Gagal menjalankan perintah shell: {e}", "error")

    def _chat_direct_standalone(self, message: str) -> None:
        """Kirim pesan langsung ke engine Direct AI (Multi-provider LLM) tanpa server ALFA."""
        if not hasattr(self, "direct_ai") or self.direct_ai is None:
            print_status("Engine Direct AI belum siap.", "error")
            return

        direct = self.direct_ai
        # Sampaikan info konteks file jika ada
        _, mentions = direct.scan_file_mentions(message)
        context_files = list(getattr(self, "attached_files", [])) + mentions
        if context_files:
            unique_contexts = list(dict.fromkeys(context_files))
            print(
                f"{Colors.GRAY}📎 Konteks file aktif: {', '.join(unique_contexts)}{Colors.ENDC}"
            )

        # Check Execution Mode: Swarm vs Single Agent
        exec_mode = getattr(self, "agent_execution_mode", "single")
        if exec_mode == "swarm":
            self._run_swarm_execution(message)
            return

        # Autonomous ReAct Agent Loop:
        # Default True, atau otomatis terpicu jika ada intensi inspeksi/coding lokal
        is_agent = getattr(self, "agent_mode", True)
        local_intent_keywords = [
            "cek folder", "lihat folder", "isi folder", "list folder", "struktur folder",
            "cek direktori", "cek file", "baca file", "lihat file", "periksa file",
            "periksa", "baca kode", "edit", "ubah", "perbaiki", "fix", "tulis",
            "buat file", "create", "hapus", "cari", "search", "temukan", "jalankan",
            "run", "test", "pytest", "git", "diff", "arsitektur", "repomap", "analisis",
        ]
        msg_lower = message.lower()
        has_local_intent = any(kw in msg_lower for kw in local_intent_keywords)

        if (is_agent or has_local_intent) and getattr(self, "agent_runner", None):
            self.agent_runner.direct_ai = self.direct_ai
            try:
                final_answer = self.agent_runner.run(message)
                self.chat_history.append({"role": "user", "content": message})
                self.chat_history.append({"role": "assistant", "content": final_answer})
                if (
                    RICH_AVAILABLE
                    and self.console
                    and self.config.get("markdown", True)
                ):
                    self.console.print(Markdown(final_answer))
                else:
                    print(f"\n{final_answer}\n")
            except Exception as e:
                print(f"\n{Colors.FAIL}❌ Error Autonomous Agent:{Colors.ENDC} {e}")
                if "API Key" in str(e) or "API_KEY" in str(e):
                    print(
                        f"{Colors.WARNING}💡 Tips:{Colors.ENDC} Jalankan '/config' atau atur API Key di '/menu'."
                    )
            return

        print(
            f"\n{Colors.CYAN}🤖 ALFA ({direct.provider.upper()}/{direct.model}):{Colors.ENDC} ",
            end="",
            flush=True,
        )

        try:
            if self.streaming:
                accumulated = []

                def on_chunk(chunk: str) -> None:
                    accumulated.append(chunk)
                    print(chunk, end="", flush=True)

                response_text = direct.generate(
                    prompt=message,
                    context_files=context_files,
                    stream=True,
                    stream_callback=on_chunk,
                )
                print()
            else:
                response_text = direct.generate(
                    prompt=message,
                    context_files=context_files,
                    stream=False,
                )
                if (
                    RICH_AVAILABLE
                    and self.console
                    and self.config.get("markdown", True)
                ):
                    print()
                    self.console.print(Markdown(response_text))
                else:
                    print(f"\n{response_text}\n")

            # Catat riwayat chat
            self.chat_history.append({"role": "user", "content": message})
            self.chat_history.append({"role": "assistant", "content": response_text})

        except Exception as e:
            print(f"\n{Colors.FAIL}❌ Error Direct AI:{Colors.ENDC} {e}")
            if "API Key" in str(e) or "API_KEY" in str(e):
                print(
                    f"{Colors.WARNING}💡 Tips:{Colors.ENDC} Jalankan '/config setup' atau export API Key di terminal."
                )

    def _chat_via_server(self, message: str) -> None:
        """Kirim pesan ke backend server ALFA Sovereign AI."""
        if not getattr(self, "session_token", None):
            print_status(
                "Belum login ke server ALFA. Ketik '/login' atau gunakan '/mode standalone' untuk chat langsung.",
                "warning",
            )
            return

        # Periksa apakah ada konteks file atau @file
        attached = getattr(self, "attached_files", [])
        if hasattr(self, "direct_ai") and self.direct_ai:
            final_message = self.direct_ai.build_prompt_with_context(
                message, attached
            )
        else:
            final_message = message

        payload = {"message": final_message, "stream": self.streaming}

        if self.streaming:
            print(f"\n{Colors.CYAN}🤖 ALFA (Server):{Colors.ENDC} ", end="", flush=True)
            if RICH_AVAILABLE and self.console:
                with Live(
                    Spinner("dots", text="Thinking...", style="cyan"),
                    refresh_per_second=10,
                ) as live:
                    res = self._request("POST", "/api/chat/stream", payload)
                    live.update(Spinner("dots", text="Streaming...", style="green"))

                    if res and res.status_code == 200:
                        full_response = ""
                        for chunk in res.iter_lines():
                            if chunk:
                                try:
                                    chunk_data = json.loads(chunk.decode("utf-8"))
                                    token = chunk_data.get("token", "")
                                    full_response += token
                                    print(token, end="", flush=True)
                                except Exception:
                                    pass
                        print()
                        self.chat_history.append({"role": "user", "content": message})
                        self.chat_history.append(
                            {"role": "assistant", "content": full_response}
                        )
                    else:
                        print(
                            f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons dari server ALFA."
                        )
            else:
                res = self._request("POST", "/api/chat", payload)
                sys.stdout.write("\033[K")
                if res and res.status_code == 200:
                    data = res.json()
                    response_text = (
                        data.get("response") or data.get("message") or str(data)
                    )
                    print(f"\n{Colors.WHITE}{response_text}{Colors.ENDC}\n")
                    self.chat_history.append({"role": "user", "content": message})
                    self.chat_history.append(
                        {"role": "assistant", "content": response_text}
                    )
                else:
                    print(
                        f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons dari server ALFA."
                    )
        else:
            # Non-streaming mode
            print(
                f"\n{Colors.CYAN}🤖 ALFA (Server):{Colors.ENDC} Sedang berpikir...",
                end="\r",
            )
            res = self._request("POST", "/api/chat", payload)
            sys.stdout.write("\033[K")

            if res and res.status_code == 200:
                data = res.json()
                response_text = data.get("response") or data.get("message") or str(data)
                print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
                if (
                    RICH_AVAILABLE
                    and self.console
                    and self.config.get("markdown", True)
                ):
                    self.console.print(Markdown(response_text))
                else:
                    print(f"{Colors.WHITE}{response_text}{Colors.ENDC}\n")

                self.chat_history.append({"role": "user", "content": message})
                self.chat_history.append(
                    {"role": "assistant", "content": response_text}
                )
            else:
                print(
                    f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal berkomunikasi dengan server ALFA."
                )

    def _run_swarm_execution(self, message: str) -> None:
        """Execute task using multi-agent swarm orchestration with custom models per agent."""
        import asyncio
        from pathlib import Path

        from alfa.core import database
        from alfa.swarm import engine as swarm_engine

        agents = []
        try:
            agents = database.list_custom_agents_sync()
        except Exception:
            pass

        active_agents = [a for a in agents if a.get("is_enabled", 1)]
        if not active_agents:
            print_status("Tidak ada agen aktif di Swarm. Buka '/agents' atau atur di Web Dashboard.", "warning")
            return

        if RICH_AVAILABLE and self.console:
            from rich.panel import Panel
            from rich.table import Table

            tbl = Table(title="🐝 Partisipan Swarm & Model AI yang Ditugaskan", border_style="yellow")
            tbl.add_column("Avatar", justify="center")
            tbl.add_column("Nama Agen", style="bold white")
            tbl.add_column("Peran / Spesialisasi", style="green")
            tbl.add_column("AI Provider / Model", style="cyan")

            for a in active_agents:
                tbl.add_row(
                    a.get("avatar_emoji", "🤖"),
                    a.get("name", "Unknown"),
                    a.get("role", "-"),
                    f"{a.get('provider', 'gemini')}/{a.get('model', 'default')}",
                )

            self.console.print(
                Panel(
                    f"[bold yellow]🐝 ALFA Multi-Agent Swarm Orchestrator Aktif[/bold yellow]\n"
                    f"[dim]Direktori Kerja Target: {Path.cwd().name} ({Path.cwd()})[/dim]\n"
                    f"[dim]Jumlah Agen Berkolaborasi: {len(active_agents)} Agen[/dim]",
                    border_style="yellow",
                )
            )
            self.console.print(tbl)
        else:
            print(f"\n{Colors.BOLD}🐝 ALFA Multi-Agent Swarm Orchestrator Aktif{Colors.ENDC}")
            print(f"Target Direktori: {Path.cwd()}")
            for a in active_agents:
                print(f"  • {a.get('avatar_emoji', '🤖')} {a.get('name')}: {a.get('provider')}/{a.get('model')}")

        target_dir = str(Path.cwd())
        print(f"\n{Colors.CYAN}🚀 Memulai koordinasi dan eksekusi kolaboratif tim agen...{Colors.ENDC}\n")

        try:
            result = asyncio.run(
                swarm_engine.conduct_multi_agent_meeting(
                    topic=message,
                    rounds=2,
                    mode="execute",
                    target_folder=target_dir,
                )
            )
            consensus = (
                result.get("consensus")
                or result.get("action_plan")
                or result.get("status")
                or "Eksekusi swarm selesai."
            )
            self.chat_history.append({"role": "user", "content": message})
            self.chat_history.append({"role": "assistant", "content": str(consensus)})

            if RICH_AVAILABLE and self.console and self.config.get("markdown", True):
                self.console.print(Markdown(f"### 🏁 Hasil Konsensus & Eksekusi Swarm\n\n{consensus}"))
            else:
                print(f"\n{Colors.GREEN}🏁 Hasil Konsensus & Eksekusi Swarm:{Colors.ENDC}\n{consensus}\n")

        except Exception as e:
            print_status(f"Error eksekusi swarm: {e}", "error")

    def emptyline(self) -> None:
        pass
