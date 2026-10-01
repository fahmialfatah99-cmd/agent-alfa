"""Slash-command mixin: Navigation, mode, file-context, and shell-runner commands."""

from pathlib import Path

from alfa.core.cli.constants import Colors, print_status


class SlashNavigationMixin:
    """Navigation, mode, file-context, and shell-runner commands."""

    # --- Interactive Menu Palette ---

    def do_slash_menu(self, arg: str) -> None:
        """Buka menu interaktif (Command Palette) ala Cursor/OpenCode/Qwen. Usage: /menu"""
        from alfa.core.cli.interactive_menu import open_interactive_menu

        open_interactive_menu(self)

    # --- Mode Switcher ---

    def do_slash_mode(self, arg: str) -> None:
        """Ubah mode operasi CLI. Usage: /mode [single|swarm|auto|server|standalone]"""
        target = arg.strip().lower()
        curr_conn = getattr(self, "mode", "auto")
        curr_exec = getattr(self, "agent_execution_mode", "single")

        if not target:
            print(f"\n{Colors.BOLD}🧭 Status Mode Operasi ALFA CLI:{Colors.ENDC}")
            print(
                f"  • Mode Eksekusi Agen : {Colors.GREEN}{curr_exec.upper()}{Colors.ENDC} ({'1 Agen Otonom ReAct Cepat' if curr_exec == 'single' else 'Swarm Multi-Agen Kolaboratif'})"
            )
            print(
                f"  • Mode Koneksi       : {Colors.CYAN}{curr_conn.upper()}{Colors.ENDC} (auto / standalone / server)"
            )
            print(f"\n{Colors.BOLD}Cara Beralih Mode Agen:{Colors.ENDC}")
            print(
                f"  • {Colors.CYAN}/mode single{Colors.ENDC}     - Mode Single Agent (1 autonomous coding agent)"
            )
            print(
                f"  • {Colors.CYAN}/mode swarm{Colors.ENDC}      - Mode Swarm Multi-Agent (seluruh tim agen berkolaborasi)"
            )
            print(f"\n{Colors.BOLD}Cara Beralih Mode Koneksi:{Colors.ENDC}")
            print(
                f"  • {Colors.CYAN}/mode standalone{Colors.ENDC} - Chat/eksekusi langsung ke API LLM tanpa server"
            )
            print(
                f"  • {Colors.CYAN}/mode auto{Colors.ENDC}       - Otomatis coba server ALFA, fallback standalone"
            )
            print(
                f"  • {Colors.CYAN}/mode server{Colors.ENDC}     - Hubungkan hanya ke backend server ALFA\n"
            )
            return

        if target in ("single", "agent", "solo"):
            self.agent_execution_mode = "single"
            self.config["agent_execution_mode"] = "single"
            self._save_config()
            self._update_prompt()
            print_status(
                "Mode Agen dialihkan ke: SINGLE AGENT (Autonomous ReAct Cepat & Fokus).",
                "success",
            )
            return

        if target in ("swarm", "multi", "team"):
            self.agent_execution_mode = "swarm"
            self.config["agent_execution_mode"] = "swarm"
            self._save_config()
            self._update_prompt()
            print_status(
                "Mode Agen dialihkan ke: SWARM MULTI-AGENT (Kolaborasi Seluruh Tim Agen).",
                "success",
            )
            return

        if target in ["auto", "server", "standalone"]:
            self.mode = target
            self.config["mode"] = target
            self._save_config()
            print_status(f"Mode koneksi diubah ke: {target.upper()}", "success")
            self._update_prompt()
            return

        print_status(
            "Mode tidak valid. Pilihan: single, swarm, auto, server, atau standalone.",
            "error",
        )

    # --- File Context Management ---

    def do_slash_file(self, arg: str) -> None:
        """Kelola konteks file yang dilampirkan ke AI. Usage: /file [add|list|clear|remove] <filepath>"""
        parts = arg.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        param = parts[1].strip() if len(parts) > 1 else ""

        if not hasattr(self, "attached_files"):
            self.attached_files: list[str] = []

        if sub == "add":
            if not param:
                print_status("Cantumkan path file: /file add <path>", "warning")
                return
            p = Path(param)
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                print_status(f"File tidak ditemukan: {param}", "error")
                return
            if not p.is_file():
                print_status(f"Bukan file: {param}", "error")
                return
            rel_path = (
                str(p.relative_to(Path.cwd()))
                if str(p).startswith(str(Path.cwd()))
                else str(p)
            )
            if rel_path not in self.attached_files:
                self.attached_files.append(rel_path)
                print_status(f"File '{rel_path}' ditambahkan ke konteks.", "success")
            else:
                print_status(f"File '{rel_path}' sudah ada di konteks.", "info")

        elif sub == "remove":
            if param in self.attached_files:
                self.attached_files.remove(param)
                print_status(f"File '{param}' dihapus dari konteks.", "success")
            else:
                print_status(
                    f"File '{param}' tidak ditemukan dalam daftar konteks.", "warning"
                )

        elif sub == "clear":
            self.attached_files.clear()
            print_status("Semua konteks file dibersihkan.", "success")

        elif sub == "list":
            if not self.attached_files:
                print_status(
                    "Belum ada file konteks terlampir. Gunakan '/file add <path>' atau ketik '@file.py' di pesan.",
                    "info",
                )
            else:
                print(
                    f"\n{Colors.BOLD}📎 File Konteks Aktif ({len(self.attached_files)}):{Colors.ENDC}"
                )
                for i, f in enumerate(self.attached_files, 1):
                    print(f"  {i}. {Colors.CYAN}{f}{Colors.ENDC}")
                print()

        else:
            print_status(
                "Subcommand tidak dikenal. Pilihan: add, remove, list, clear", "error"
            )

    # --- Shell Runner Inside Chat ---

    def do_slash_run(self, arg: str) -> None:
        """Jalankan perintah shell lokal. Usage: /run <command>"""
        if hasattr(self, "_execute_shell_command"):
            self._execute_shell_command(arg.strip())
