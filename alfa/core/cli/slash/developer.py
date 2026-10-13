"""Slash-command mixin: Autonomous agent, patch-rollback, repomap, and tools reference."""

from pathlib import Path

from alfa.core.cli.constants import Colors, print_status


class SlashDeveloperMixin:
    """Autonomous agent, patch-rollback, repomap, and tools reference."""

    def do_slash_agent(self, arg: str) -> None:
        """Aktifkan/kelola mode Agent & model per agen. Usage: /agent [on|off|single|swarm|model]"""
        parts = arg.strip().split(maxsplit=1)
        action = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if action in ("model", "set-model"):
            self._set_agent_model_command(rest)
            return
        elif action in ("single", "solo"):
            self.do_slash_mode("single")
            return
        elif action in ("swarm", "multi"):
            self.do_slash_mode("swarm")
            return

        # Fallback to status/on/off
        target = action
        curr = getattr(self, "agent_mode", True)
        exec_mode = getattr(self, "agent_execution_mode", "single")

        if not target or target == "status":
            status_tag = (
                f"{Colors.GREEN}AKTIF (Loop Tools){Colors.ENDC}"
                if curr
                else f"{Colors.WARNING}NON-AKTIF (Direct Chat Mode){Colors.ENDC}"
            )
            print(f"\n{Colors.BOLD}🤖 Autonomous Agent Settings:{Colors.ENDC}")
            print(f"  • Status Agent Tools : {status_tag}")
            auto = bool(
                getattr(getattr(self, "agent_runner", None), "auto_approve", False)
            )
            auto_tag = (
                f"{Colors.WARNING}AUTO-APPROVE (tanpa konfirmasi){Colors.ENDC}"
                if auto
                else f"{Colors.GREEN}MANUAL (konfirmasi per aksi mutasi){Colors.ENDC}"
            )
            print(f"  • Mode Approval      : {auto_tag} (atur via /auto on|off)")
            print(
                f"  • Mode Eksekusi      : {Colors.CYAN}{exec_mode.upper()}{Colors.ENDC} ({'Single ReAct' if exec_mode == 'single' else 'Swarm Multi-Agen'})"
            )
            _runner = getattr(self, "agent_runner", None)
            if _runner is not None:
                print(
                    f"  • Budget Turn        : {Colors.CYAN}{getattr(_runner, 'max_turns', '?')}{Colors.ENDC} turn + "
                    f"{Colors.CYAN}{getattr(_runner, 'max_continuations', '?')}x{Colors.ENDC} lanjut otomatis (env ALFA_MAX_TURNS)"
                )
            print("\n💡 Pilihan perintah:")
            print(
                f"  • {Colors.CYAN}/agent single{Colors.ENDC} - Beralih ke Single Agent Mode"
            )
            print(
                f"  • {Colors.CYAN}/agent swarm{Colors.ENDC}  - Beralih ke Swarm Multi-Agent Mode"
            )
            print(
                f"  • {Colors.CYAN}/agent model <agen> <provider> [model]{Colors.ENDC} - Atur model AI spesifik untuk agen"
            )
            print(
                f"  • {Colors.CYAN}/agent on{Colors.ENDC} / {Colors.CYAN}/agent off{Colors.ENDC} - Toggle tools aktif/nonaktif\n"
            )
            return

        if target in ("on", "true", "1", "enable"):
            self.agent_mode = True
            self.config["agent_mode"] = True
            self._save_config()
            print_status(
                "Autonomous ReAct Agent Mode diaktifkan! AI dapat menginspeksi & mengedit file dengan tools.",
                "success",
            )
        elif target in ("off", "false", "0", "disable"):
            self.agent_mode = False
            self.config["agent_mode"] = False
            self._save_config()
            print_status(
                "Autonomous Agent Mode dinonaktifkan. Beralih ke Fast Direct Chat.",
                "info",
            )
        else:
            print_status("Penggunaan: /agent [on|off|single|swarm|model]", "warning")

    # --- Patch History & Rollback ---

    def do_slash_undo(self, arg: str) -> None:
        """Rollback perubahan file dari riwayat patch. Usage: /undo [latest|<patch_id>|list]"""
        if not hasattr(self, "patch_manager") or self.patch_manager is None:
            from alfa.core.cli.agent_engine import PatchHistoryManager

            self.patch_manager = PatchHistoryManager(workspace_root=Path.cwd())

        target = arg.strip().lower()

        if target == "list":
            patches = self.patch_manager.list_patches()
            if not patches:
                print_status("Belum ada riwayat patch di workspace ini.", "info")
                return

            if getattr(self, "console", None):
                from rich.table import Table

                tbl = Table(title="Riwayat Patch Transaksional (.alfa_backups/)")
                tbl.add_column("ID", style="cyan", justify="right")
                tbl.add_column("Waktu", style="dim")
                tbl.add_column("File Target", style="bold white")
                tbl.add_column("Perubahan", style="green")
                for p in patches[-20:]:
                    tbl.add_row(str(p.id), p.timestamp, p.filepath, p.summary)
                self.console.print(tbl)
            else:
                print(f"\n{Colors.BOLD}Riwayat Patch Terkini:{Colors.ENDC}")
                for p in patches[-20:]:
                    print(f"  • #{p.id} [{p.timestamp}] {p.filepath} ({p.summary})")
                print()
            print("💡 Batalkan patch tertentu dengan: /undo <patch_id>\n")
            return

        if target.isdigit():
            pid = int(target)
            success, msg = self.patch_manager.rollback_patch(pid)
            if success:
                print_status(msg, "success")
            else:
                print_status(msg, "error")
            return

        # Default: rollback latest patch
        patches = self.patch_manager.list_patches()
        if not patches:
            # SAFETY: never run bare `git restore .` here — it would wipe
            # unrelated uncommitted work in the user's repo. Just inform.
            print_status("Belum ada riwayat patch untuk dibatalkan.", "warning")
            return

        latest = patches[-1]
        confirm = (
            input(
                f"Batalkan perubahan terakhir pada '{latest.filepath}' (Patch #{latest.id})? [Y/n]: "
            )
            .strip()
            .lower()
        )
        if confirm in ("n", "no"):
            print_status("Rollback dibatalkan.", "info")
            return

        success, msg = self.patch_manager.rollback_latest()
        if success:
            print_status(msg, "success")
        else:
            print_status(msg, "error")

    # --- Repomap Architectural Inspector ---

    def do_slash_repomap(self, arg: str) -> None:
        """Tampilkan peta arsitektur dan simbol kode (Repomap). Usage: /repomap"""
        if not hasattr(self, "repomap_gen") or self.repomap_gen is None:
            from alfa.core.cli.agent_engine import RepomapGenerator

            self.repomap_gen = RepomapGenerator(root_dir=Path.cwd())

        from rich.panel import Panel

        from alfa.core.cli.constants import RICH_AVAILABLE

        repomap = self.repomap_gen.generate_repomap()
        if getattr(self, "console", None) and RICH_AVAILABLE:
            self.console.print(
                Panel(
                    repomap,
                    title="🗺️ [bold cyan]ALFA Workspace Repomap (Simbol Arsitektur)[/bold cyan]",
                    border_style="cyan",
                )
            )
        else:
            print(f"\n--- ALFA Workspace Repomap ---\n{repomap}\n")

    # --- Developer Tools Reference ---

    def do_slash_tools(self, arg: str) -> None:
        """Tampilkan daftar tools yang tersedia (Local Developer Tools & Web Ecosystem Tools). Usage: /tools"""
        from rich.table import Table

        dev_tools = [
            (
                "search_code",
                "Ripgrep / Fallback",
                "Pencarian regex/string di seluruh codebase",
            ),
            (
                "find_files",
                "Fd / Globbing",
                "Pencarian file berdasarkan pola wildcard (*.py, *auth*)",
            ),
            (
                "read_file",
                "Builtin IO",
                "Membaca rentang baris file lokal dengan nomor baris",
            ),
            (
                "write_file",
                "Transactional IO",
                "Membuat/menimpa file dengan auto-backup (.alfa_backups)",
            ),
            (
                "patch_file",
                "Precision Patcher",
                "Mengganti potongan blok kode secara presisi",
            ),
            (
                "run_command",
                "Sandbox Shell",
                "Menjalankan perintah terminal & verifikasi test otomatis",
            ),
            (
                "list_directory",
                "Filesystem",
                "Melihat hierarki file dan struktur direktori real-time",
            ),
            (
                "edit_file_precise",
                "Precision Editor",
                "Edit blok teks exact-match (ekosistem)",
            ),
            (
                "apply_unified_diff",
                "Diff Applier",
                "Terapkan unified-diff multi-hunk (ekosistem)",
            ),
            (
                "grep_workspace",
                "Workspace Grep",
                "Grep cepat lintas workspace + filter file (ekosistem)",
            ),
            (
                "index_codebase",
                "Code Index",
                "Indeks codebase untuk pencarian semantik (ekosistem)",
            ),
            (
                "search_codebase",
                "Semantic Search",
                "Cari kode by makna via indeks (ekosistem)",
            ),
            (
                "lsp_find_symbol_definition",
                "LSP",
                "Lompat ke definisi simbol/fungsi/kelas (ekosistem)",
            ),
            (
                "lsp_find_symbol_references",
                "LSP",
                "Semua referensi simbol (ekosistem)",
            ),
            (
                "git_operations",
                "Git Aman",
                "status/diff/log/add/commit terkurasi (ekosistem)",
            ),
        ]

        eco_tools = [
            (
                "web_search",
                "DuckDuckGo / Tavily",
                "Pencarian web real-time & fakta terkini",
            ),
            (
                "fetch_web_page_content",
                "Web Extractor",
                "Membaca & merangkum konten artikel/dokumentasi web",
            ),
            (
                "universal_deep_scraper",
                "Scraper Engine",
                "Scraping halaman web mendalam (dinamis/JS)",
            ),
            (
                "audit_website_security",
                "Security Auditor",
                "Audit kerentanan situs, SSL/TLS, & HTTP headers",
            ),
            (
                "get_system_stats",
                "System Telemetry",
                "Cek CPU, RAM, Disk, Jaringan, dan Baterai komputer",
            ),
            (
                "vault_get_secret",
                "SQLite Vault",
                "Mengambil rahasia/token dari brankas terenkripsi ALFA",
            ),
            (
                "vault_store_secret",
                "SQLite Vault",
                "Menyimpan kredensial baru ke brankas aman",
            ),
            (
                "vault_list_secrets",
                "SQLite Vault",
                "Daftar kunci rahasia yang tersimpan di brankas",
            ),
        ]

        if getattr(self, "console", None):
            tbl_dev = Table(title="💻 1. Local Developer Tools (Coding & Proyek)")
            tbl_dev.add_column("Tool Name", style="bold cyan")
            tbl_dev.add_column("Engine", style="dim")
            tbl_dev.add_column("Deskripsi", style="green")
            for t_name, t_eng, t_desc in dev_tools:
                tbl_dev.add_row(t_name, t_eng, t_desc)
            self.console.print(tbl_dev)

            tbl_eco = Table(
                title="🌐 2. Web & Ecosystem Tools (Sinkron Web Dashboard & Bot)"
            )
            tbl_eco.add_column("Tool Name", style="bold magenta")
            tbl_eco.add_column("Engine", style="dim")
            tbl_eco.add_column("Deskripsi", style="yellow")
            for t_name, t_eng, t_desc in eco_tools:
                tbl_eco.add_row(t_name, t_eng, t_desc)
            self.console.print(tbl_eco)
        else:
            print(
                f"\n{Colors.BOLD}💻 1. Local Developer Tools (Coding & Proyek):{Colors.ENDC}"
            )
            for t_name, t_eng, t_desc in dev_tools:
                print(f"  • {Colors.CYAN}{t_name:<15}{Colors.ENDC} ({t_eng}): {t_desc}")

            print(
                f"\n{Colors.BOLD}🌐 2. Web & Ecosystem Tools (Sinkron Web Dashboard):{Colors.ENDC}"
            )
            for t_name, t_eng, t_desc in eco_tools:
                print(
                    f"  • {Colors.GREEN}{t_name:<24}{Colors.ENDC} ({t_eng}): {t_desc}"
                )
            print()

        print(
            "💡 [Sinkronisasi]: ReAct Agent di CLI & Web Command Center memiliki akses ke seluruh tools di atas.\n"
        )

    def do_slash_test(self, arg: str) -> None:
        """Jalankan test suite. Usage: /test [path|file::test] (default: tests/ -q)"""
        target = arg.strip() or "tests/ -q"
        if not target.startswith("tests/") and not target.startswith("test_"):
            print_status(
                "Demi keamanan, /test hanya menjalankan di dalam tests/.",
                "warning",
            )
            return
        cmd = f"python -m pytest {target}"
        if hasattr(self, "_execute_shell_command"):
            print_status(f"🧪 Menjalankan: {cmd}", "info")
            self._execute_shell_command(cmd)
        else:
            print_status("Shell executor tidak tersedia.", "error")

    def do_slash_git(self, arg: str) -> None:
        """Git read-only cepat. Usage: /git [status|diff|log|branch]"""
        sub = (arg.strip().lower() or "status").split()[0]
        cmds = {
            "status": "git status -s",
            "diff": "git diff --stat",
            "log": "git log --oneline -10",
            "branch": "git branch --show-current",
        }
        if sub in ("commit", "add", "push", "reset", "checkout"):
            print_status(
                "Aksi mutasi git hanya via Agent mode (/agent on) dengan konfirmasi.",
                "warning",
            )
            return
        cmd = cmds.get(sub)
        if not cmd:
            print_status(
                f"Subcommand tak dikenal: {sub} (status|diff|log|branch).", "error"
            )
            return
        if hasattr(self, "_execute_shell_command"):
            self._execute_shell_command(cmd)
        else:
            print_status("Shell executor tidak tersedia.", "error")

    def _plan_file(self) -> Path:
        root = Path(getattr(self, "root", Path.cwd()))
        plan_dir = root / ".alfa_backups"
        try:
            plan_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            plan_dir = Path.cwd()
        return plan_dir / "last_plan.md"

    def do_slash_plan(self, arg: str) -> None:
        """Susun rencana eksekusi TANPA mengubah apa pun. Usage: /plan <tugas>"""
        task = arg.strip()
        if not task:
            print_status("Usage: /plan <deskripsi tugas>", "warning")
            return
        runner = getattr(self, "agent_runner", None)
        if runner is None:
            print_status("Agent runner belum siap.", "error")
            return
        runner.direct_ai = getattr(self, "direct_ai", runner.direct_ai)
        print_status(
            "📝 PLAN MODE (read-only): menyusun rencana tanpa eksekusi...", "info"
        )
        try:
            plan = runner.run(f"Susun rencana eksekusi untuk: {task}", plan_mode=True)
        except Exception as e:
            print_status(f"Gagal menyusun rencana: {e}", "error")
            return
        self.last_plan = {"task": task, "plan": plan}
        try:
            self._plan_file().write_text(
                f"# Rencana: {task}\n\n{plan}\n", encoding="utf-8"
            )
        except OSError as e:
            print_status(f"Tidak bisa menyimpan rencana: {e}", "warning")
        print_status(
            "✅ Rencana tersimpan. Setujui dengan /approve untuk eksekusi.", "success"
        )

    def do_slash_approve(self, arg: str) -> None:
        """Eksekusi rencana tersimpan dari /plan. Usage: /approve [catatan tambahan]"""
        plan_data = getattr(self, "last_plan", None)
        if not plan_data:
            plan_file = self._plan_file()
            if plan_file.exists():
                try:
                    text = plan_file.read_text(encoding="utf-8")
                    plan_data = {"task": "(dari file)", "plan": text}
                    self.last_plan = plan_data
                except OSError:
                    plan_data = None
        if not plan_data:
            print_status(
                "Belum ada rencana. Buat dulu dengan /plan <tugas>.", "warning"
            )
            return
        runner = getattr(self, "agent_runner", None)
        if runner is None:
            print_status("Agent runner belum siap.", "error")
            return
        runner.direct_ai = getattr(self, "direct_ai", runner.direct_ai)
        extra = arg.strip()
        instruction = (
            f"Eksekusi rencana yang telah disetujui berikut LANGKAH DEMI LANGKAH "
            f"dengan verifikasi test. Tugas asal: {plan_data['task']}\n\n"
            f"RENCANA:\n{plan_data['plan']}"
        )
        if extra:
            instruction += f"\n\nCatatan tambahan user: {extra}"
        print_status("🚀 Mengeksekusi rencana yang disetujui...", "info")
        try:
            runner.run(instruction)
        except Exception as e:
            print_status(f"Eksekusi gagal: {e}", "error")

    def do_slash_auto(self, arg: str) -> None:
        """Atur mode approval. Usage: /auto [on|off|status]"""
        runner = getattr(self, "agent_runner", None)
        if runner is None:
            print_status("Agent runner belum siap.", "error")
            return
        target = (arg.strip().lower() or "status").split()[0]
        if target in ("on", "enable", "auto", "yes", "1"):
            runner.auto_approve = True
            self.config["auto_approve"] = True
            self._save_config()
            print_status(
                "⚡ AUTO-APPROVE AKTIF: tool mutasi berjalan tanpa konfirmasi. "
                "Hati-hati — gunakan /auto off untuk kembali manual.",
                "warning",
            )
        elif target in ("off", "disable", "manual", "no", "0"):
            runner.auto_approve = False
            self.config["auto_approve"] = False
            self._save_config()
            print_status(
                "✅ MANUAL-APPROVE AKTIF: setiap aksi mutasi meminta konfirmasi [Y/n/a].",
                "success",
            )
        else:
            state = "ON (auto)" if runner.auto_approve else "OFF (manual)"
            print_status(
                f"Mode approval saat ini: {state}. Usage: /auto [on|off]", "info"
            )

    def do_slash_permit(self, arg: str) -> None:
        """Atur izin per-tool persisten. Usage: /permit [tool] [allow|ask|deny|reset]"""
        from alfa.core.cli.agent_engine.permissions import VALID_RULES

        runner = getattr(self, "agent_runner", None)
        if runner is None or getattr(runner, "perm_store", None) is None:
            print_status("Agent runner belum siap.", "error")
            return
        store = runner.perm_store
        parts = arg.strip().split()
        if not parts:
            rules = store.as_dict()
            if not rules:
                print_status(
                    "Belum ada aturan kustom. Default: ask untuk tool mutasi, "
                    "allow untuk tool baca. Contoh: /permit run_command deny",
                    "info",
                )
            else:
                print(f"\n{Colors.BOLD}🔐 Aturan Permission Tools:{Colors.ENDC}")
                for tool in sorted(rules):
                    print(f"  • {Colors.CYAN}{tool:<28}{Colors.ENDC} {rules[tool]}")
                print()
            return
        tool = parts[0]
        action = parts[1].lower() if len(parts) > 1 else "status"
        if action == "status":
            print_status(f"{tool}: {store.get(tool)}", "info")
        elif action == "reset":
            if store.reset(tool):
                print_status(f"Aturan {tool} dikembalikan ke default.", "success")
            else:
                print_status(f"Tidak ada aturan kustom untuk {tool}.", "warning")
        elif action in VALID_RULES:
            store.set(tool, action)
            print_status(f"Aturan {tool} → {action} (tersimpan).", "success")
        else:
            print_status("Usage: /permit [tool] [allow|ask|deny|reset]", "error")

    def _todo_manager(self):
        from alfa.core.cli.agent_engine.todos import TodoManager

        root = Path(getattr(self, "root", Path.cwd()))
        return TodoManager(root)

    def do_slash_todo(self, arg: str) -> None:
        """Kelola todo tugas multi-langkah. Usage: /todo [add <tugas>|list|done <id>|clear]"""
        parts = arg.strip().split(maxsplit=1)
        action = parts[0].lower() if parts else "list"
        rest = parts[1] if len(parts) > 1 else ""
        mgr = self._todo_manager()
        if action == "add":
            if not rest:
                print_status("Usage: /todo add <deskripsi tugas>", "warning")
                return
            item = mgr.add(rest)
            print_status(
                f"⬜ Todo #{item['id']} ditambahkan: {item['task']}", "success"
            )
        elif action == "list" or not action:
            print(f"\n{Colors.BOLD}📝 Todo List:{Colors.ENDC}\n{mgr.summary()}\n")
        elif action == "done":
            if rest.strip().isdigit() and mgr.done(int(rest.strip())):
                print_status(f"✅ Todo #{rest.strip()} selesai.", "success")
            else:
                print_status(f"Todo #{rest.strip()} tidak ditemukan.", "error")
        elif action == "clear":
            removed = mgr.clear(done_only=True)
            print_status(f"🧹 {removed} todo selesai dihapus.", "success")
        else:
            print_status("Usage: /todo [add <tugas>|list|done <id>|clear]", "error")

    def do_slash_status(self, arg: str) -> None:
        """Tampilkan status kerja agent terakhir dari STATE nyata. Usage: /status"""
        runner = getattr(self, "agent_runner", None)
        if runner is None or not hasattr(runner, "format_last_run"):
            print_status("Agent runner belum siap.", "error")
            return
        print(f"\n{runner.format_last_run()}\n")
