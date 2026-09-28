"""Command handlers for ALFA CLI - Slash Commands Mixin."""

from __future__ import annotations

import os
from pathlib import Path

from alfa.core.cli.constants import (
    Colors,
    print_status,
)
from alfa.core.cli.direct_ai import PRESETS, PROVIDERS_CATALOG


class CliSlashCommandsMixin:
    """Implements slash commands for server orchestration, direct AI, and developer tools."""

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
            print(f"  • Mode Eksekusi Agen : {Colors.GREEN}{curr_exec.upper()}{Colors.ENDC} ({'1 Agen Otonom ReAct Cepat' if curr_exec == 'single' else 'Swarm Multi-Agen Kolaboratif'})")
            print(f"  • Mode Koneksi       : {Colors.CYAN}{curr_conn.upper()}{Colors.ENDC} (auto / standalone / server)")
            print(f"\n{Colors.BOLD}Cara Beralih Mode Agen:{Colors.ENDC}")
            print(f"  • {Colors.CYAN}/mode single{Colors.ENDC}     - Mode Single Agent (1 autonomous coding agent)")
            print(f"  • {Colors.CYAN}/mode swarm{Colors.ENDC}      - Mode Swarm Multi-Agent (seluruh tim agen berkolaborasi)")
            print(f"\n{Colors.BOLD}Cara Beralih Mode Koneksi:{Colors.ENDC}")
            print(f"  • {Colors.CYAN}/mode standalone{Colors.ENDC} - Chat/eksekusi langsung ke API LLM tanpa server")
            print(f"  • {Colors.CYAN}/mode auto{Colors.ENDC}       - Otomatis coba server ALFA, fallback standalone")
            print(f"  • {Colors.CYAN}/mode server{Colors.ENDC}     - Hubungkan hanya ke backend server ALFA\n")
            return

        if target in ("single", "agent", "solo"):
            self.agent_execution_mode = "single"
            self.config["agent_execution_mode"] = "single"
            self._save_config()
            self._update_prompt()
            print_status("Mode Agen dialihkan ke: SINGLE AGENT (Autonomous ReAct Cepat & Fokus).", "success")
            return

        if target in ("swarm", "multi", "team"):
            self.agent_execution_mode = "swarm"
            self.config["agent_execution_mode"] = "swarm"
            self._save_config()
            self._update_prompt()
            print_status("Mode Agen dialihkan ke: SWARM MULTI-AGENT (Kolaborasi Seluruh Tim Agen).", "success")
            return

        if target in ["auto", "server", "standalone"]:
            self.mode = target
            self.config["mode"] = target
            self._save_config()
            print_status(f"Mode koneksi diubah ke: {target.upper()}", "success")
            self._update_prompt()
            return

        print_status("Mode tidak valid. Pilihan: single, swarm, auto, server, atau standalone.", "error")

    # --- File Context Management ---

    def do_slash_file(self, arg: str) -> None:
        """Kelola konteks file yang dilampirkan ke AI. Usage: /file [add|list|clear|remove] <filepath>"""
        parts = arg.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        param = parts[1].strip() if len(parts) > 1 else ""

        if not hasattr(self, "attached_files"):
            self.attached_files = []

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
            rel_path = str(p.relative_to(Path.cwd())) if str(p).startswith(str(Path.cwd())) else str(p)
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
                print_status(f"File '{param}' tidak ditemukan dalam daftar konteks.", "warning")

        elif sub == "clear":
            self.attached_files.clear()
            print_status("Semua konteks file dibersihkan.", "success")

        elif sub == "list":
            if not self.attached_files:
                print_status("Belum ada file konteks terlampir. Gunakan '/file add <path>' atau ketik '@file.py' di pesan.", "info")
            else:
                print(f"\n{Colors.BOLD}📎 File Konteks Aktif ({len(self.attached_files)}):{Colors.ENDC}")
                for i, f in enumerate(self.attached_files, 1):
                    print(f"  {i}. {Colors.CYAN}{f}{Colors.ENDC}")
                print()

        else:
            print_status("Subcommand tidak dikenal. Pilihan: add, remove, list, clear", "error")

    # --- Shell Runner Inside Chat ---

    def do_slash_run(self, arg: str) -> None:
        """Jalankan perintah shell lokal. Usage: /run <command>"""
        if hasattr(self, "_execute_shell_command"):
            self._execute_shell_command(arg.strip())

    # --- Provider & Settings ---

    def do_slash_provider(self, arg: str) -> None:
        """Set provider AI. Usage: /provider [9router|google|nvidia|deepseek|qwen|openrouter|...] [model_name]"""
        from alfa.core.cli.direct_ai import normalize_provider, sync_providers_catalog

        try:
            sync_providers_catalog()
        except Exception:
            pass

        canonical_providers = [
            "9router",
            "google",
            "nvidia",
            "deepseek",
            "qwen",
            "minimax",
            "moonshot",
            "openrouter",
            "antigravity",
            "openai",
            "anthropic",
            "groq",
            "ollama",
        ]

        if not arg:
            # Show current provider
            direct = getattr(self, "direct_ai", None)
            prov = direct.provider if direct else "google"
            mod = direct.model if direct else "default"
            temp = direct.temperature if direct else 0.7
            tokens = direct.max_tokens if direct else 4096

            print(f"\n{Colors.BOLD}🤖 Konfigurasi AI Saat Ini:{Colors.ENDC}")
            print(f"  {Colors.CYAN}Active Mode:{Colors.ENDC} {getattr(self, 'mode', 'auto')}")
            print(f"  {Colors.CYAN}Provider:{Colors.ENDC}    {prov} ({PROVIDERS_CATALOG.get(prov, {}).get('name', prov)})")
            print(f"  {Colors.CYAN}Model:{Colors.ENDC}       {mod}")
            print(f"  {Colors.CYAN}Temperature:{Colors.ENDC} {temp}")
            print(f"  {Colors.CYAN}Max Tokens:{Colors.ENDC}  {tokens}")
            print("\n💡 Ubah dengan: /provider <nama_provider> [model]")
            print(f"   Pilihan: {', '.join(canonical_providers)}\n")
            return

        parts = arg.split()
        raw_provider = parts[0].lower()
        provider = normalize_provider(raw_provider)
        model_name = parts[1] if len(parts) > 1 else None

        if provider not in PROVIDERS_CATALOG:
            print_status(f"Provider tidak valid. Pilihan: {', '.join(canonical_providers)}", "error")
            return

        # Update direct AI client
        if hasattr(self, "direct_ai") and self.direct_ai:
            self.direct_ai.set_provider(provider, model_name)
            self.config["provider"] = provider
            if model_name:
                self.config["model"] = model_name
            self._save_config()

        # Update SQLite DB vault default model
        try:
            from alfa.core import database

            db_prov = "gemini" if provider == "google" else provider
            k_row = database.get_active_api_key_sync(db_prov)
            if k_row and model_name:
                database.update_api_key_model(k_row["id"], model_name)
        except Exception:
            pass

        # Also update server config if logged in
        if getattr(self, "session_token", None):
            payload = {"provider": provider}
            if model_name:
                payload["model"] = model_name
            self._request("POST", "/api/config/ai", payload)

        print_status(f"Provider diubah ke: {provider.upper()} ({PROVIDERS_CATALOG[provider]['name']})", "success")
        if model_name or (hasattr(self, "direct_ai") and self.direct_ai.model):
            active_m = model_name or self.direct_ai.model
            print_status(f"Model: {active_m}", "info")

    def do_slash_settings(self, arg: str) -> None:
        """Atur parameter AI. Usage: /settings temperature=0.7 max_tokens=4096"""
        if not arg:
            direct = getattr(self, "direct_ai", None)
            print(f"\n{Colors.BOLD}⚙️ Parameter AI Saat Ini:{Colors.ENDC}")
            print(f"  {Colors.CYAN}temperature:{Colors.ENDC} {getattr(direct, 'temperature', 0.7)}")
            print(f"  {Colors.CYAN}max_tokens:{Colors.ENDC}  {getattr(direct, 'max_tokens', 4096)}")
            print("\n💡 Tips: Gunakan '/settings temperature=0.5 max_tokens=2048' untuk mengubah\n")
            return

        settings = {}
        for pair in arg.split():
            if "=" in pair:
                key, value = pair.split("=", 1)
                key = key.strip()
                val_str = value.strip().strip("'\"")
                try:
                    if "." in val_str:
                        settings[key] = float(val_str)
                    elif val_str.isdigit():
                        settings[key] = int(val_str)
                    else:
                        settings[key] = val_str
                except ValueError:
                    settings[key] = val_str

        if not settings:
            print_status("Format tidak valid. Gunakan: /settings key=value", "error")
            return

        if hasattr(self, "direct_ai") and self.direct_ai:
            if "temperature" in settings:
                self.direct_ai.temperature = float(settings["temperature"])
                self.config["temperature"] = self.direct_ai.temperature
            if "max_tokens" in settings:
                self.direct_ai.max_tokens = int(settings["max_tokens"])
                self.config["max_tokens"] = self.direct_ai.max_tokens
            self._save_config()

        if getattr(self, "session_token", None):
            self._request("POST", "/api/config/ai", settings)

        print_status(f"Settings diperbarui: {', '.join(settings.keys())}", "success")

    def do_slash_switch(self, arg: str) -> None:
        """Beralih preset AI secara instan. Usage: /switch [fast|smart|creative|precise|coding]"""
        target = arg.strip().lower()
        if not target or target not in PRESETS:
            print(f"\n{Colors.BOLD}🎯 Available Presets:{Colors.ENDC}")
            for name, cfg in PRESETS.items():
                print(f"  {Colors.GREEN}/switch {name:<8}{Colors.ENDC} : {cfg['description']} (temp: {cfg['temperature']})")
            print()
            return

        if hasattr(self, "direct_ai") and self.direct_ai:
            self.direct_ai.apply_preset(target)
            self.config["preset"] = target
            self._save_config()

        if getattr(self, "session_token", None):
            p = PRESETS[target]
            self._request("POST", "/api/config/ai", p)

        print_status(f"Switched to '{target.upper()}' preset!", "success")
        p = PRESETS[target]
        print_status(f"Temperature: {p['temperature']} | Max Tokens: {p['max_tokens']}", "info")

    def do_slash_models(self, arg: str) -> None:
        """Lihat model AI yang didukung. Usage: /models"""
        print(f"\n{Colors.BOLD}🧠 Model AI Katalog (Multi-Provider):{Colors.ENDC}\n")
        for pkey, pinfo in PROVIDERS_CATALOG.items():
            is_active = (getattr(self.direct_ai, "provider", "") == pkey) if hasattr(self, "direct_ai") else False
            mark = f" {Colors.WARNING}(ACTIVE){Colors.ENDC}" if is_active else ""
            print(f"  {Colors.CYAN}{pinfo['name']}{mark}:{Colors.ENDC}")
            for m in pinfo["models"]:
                print(f"    • {Colors.GREEN}{m}{Colors.ENDC}")
        print()

    def do_slash_agents(self, arg: str) -> None:
        """Lihat status swarm & custom agents yang sinkron dengan Web Command Center. Usage: /agents"""
        from alfa.core import database

        agents = []
        try:
            agents = database.list_custom_agents_sync()
        except Exception:
            pass

        # Also fetch live activity from web server if available
        activity_map = {}
        if getattr(self, "server_reachable", False):
            try:
                r = self._request("GET", "/api/agent-activity")
                if r and r.status_code == 200:
                    data = r.json()
                    for item in data.get("agents", []):
                        activity_map[item.get("id")] = item
            except Exception:
                pass

        print(f"\n{Colors.BOLD}👥 ALFA Autonomous Workforce & Swarm Agents (Sinkron Web):{Colors.ENDC}\n")

        if not agents:
            print("  Belum ada custom agent di database. Kunjungi Web Dashboard di http://localhost:8080/agents.")
            return

        active_p = getattr(self, "active_persona_name", None)

        if getattr(self, "console", None):
            from rich.table import Table

            tbl = Table(title="Daftar Agen Swarm & Personas (Database SQLite & Web Command Center)")
            tbl.add_column("ID", style="cyan", justify="right")
            tbl.add_column("Avatar", justify="center")
            tbl.add_column("Nama Agen", style="bold white")
            tbl.add_column("Peran / Spesialisasi", style="green")
            tbl.add_column("Provider/Model", style="yellow")
            tbl.add_column("Status Live", style="magenta")

            for a in agents:
                aid = a.get("id")
                name = a.get("name", "Unknown")
                is_active = (name == active_p)
                name_str = f"[bold green]{name}[/bold green] [yellow](AKTIF)[/yellow]" if is_active else name
                avatar = a.get("avatar_emoji", "🤖")
                role = a.get("role", "-")
                prov_mod = f"{a.get('provider', '-')}/{a.get('model', '-')}"

                live_status = "🟢 STANDBY"
                if aid in activity_map:
                    live_status = activity_map[aid].get("current_state", "🟢 STANDBY")

                tbl.add_row(str(aid), avatar, name_str, role, prov_mod, live_status)

            self.console.print(tbl)
        else:
            for a in agents:
                name = a.get("name", "Unknown")
                is_active = " (AKTIF DI CLI)" if name == active_p else ""
                avatar = a.get("avatar_emoji", "🤖")
                role = a.get("role", "-")
                prov = a.get("provider", "-")
                mod = a.get("model", "-")
                print(f"  {avatar} #{a.get('id')} {Colors.CYAN}{name}{Colors.ENDC}{is_active}: {role} [{prov}/{mod}]")

        print(f"\n💡 Aktifkan persona agen: {Colors.CYAN}/persona <nama atau id>{Colors.ENDC} (Contoh: {Colors.GREEN}/persona Code Crafter{Colors.ENDC})")
        print(f"💡 Atau buka menu interaktif: {Colors.CYAN}/menu{Colors.ENDC} -> Ganti Persona Swarm\n")

    def _set_agent_model_command(self, arg: str) -> None:
        """Helper to set provider & model for a specific swarm agent."""
        import shlex

        from alfa.core import database
        from alfa.core.cli.direct_ai import (
            PROVIDERS_CATALOG,
            normalize_provider,
            sync_providers_catalog,
        )

        try:
            sync_providers_catalog()
        except Exception:
            pass

        try:
            parts = shlex.split(arg)
        except Exception:
            parts = arg.strip().split()

        agents = []
        try:
            agents = database.list_custom_agents_sync()
        except Exception:
            pass

        if not parts:
            print(f"\n{Colors.BOLD}⚙️  Pengaturan Model AI per Agen Swarm:{Colors.ENDC}\n")
            print("Format perintah:")
            print(f"  {Colors.CYAN}/swarm model <id|nama_agen> <provider> [nama_model]{Colors.ENDC}")
            print(f"  {Colors.CYAN}/agent model <id|nama_agen> <provider> [nama_model]{Colors.ENDC}\n")
            print("Contoh penggunaan:")
            print("  • /swarm model \"Code Crafter\" deepseek deepseek-coder")
            print("  • /swarm model 2 9router antigravity")
            print("  • /swarm model 4 google gemini-3.8-flash")
            print("  • /swarm model \"Security Sentinel\" nvidia meta/llama-3.3-70b-instruct\n")
            print("Daftar agen saat ini:")
            for a in agents:
                print(f"  #{a.get('id')} {a.get('avatar_emoji', '🤖')} {Colors.CYAN}{a.get('name'):<20}{Colors.ENDC} - {a.get('role'):<25} [{a.get('provider')}/{a.get('model')}]")
            print(f"\n💡 Atau atur via menu interaktif: {Colors.CYAN}/menu{Colors.ENDC} -> 'Atur Model AI per Agen'\n")
            return

        target_agent = parts[0]
        # Match agent
        matched = None
        if target_agent.isdigit():
            aid = int(target_agent)
            matched = next((a for a in agents if a.get("id") == aid), None)
        if not matched:
            t_lower = target_agent.lower()
            matched = next((a for a in agents if t_lower in a.get("name", "").lower()), None)

        if not matched:
            print_status(f"Agen '{target_agent}' tidak ditemukan di database. Ketik '/agents' untuk melihat daftar.", "error")
            return

        if len(parts) < 2:
            print(f"\n{Colors.BOLD}Agen Terpilih:{Colors.ENDC} {matched.get('avatar_emoji', '🤖')} {matched.get('name')} ({matched.get('role')})")
            print(f"Provider/Model saat ini: {Colors.CYAN}{matched.get('provider')}/{matched.get('model')}{Colors.ENDC}")
            print("\nUntuk mengubah, tentukan provider dan model:")
            print(f"  {Colors.CYAN}/swarm model \"{matched.get('name')}\" <provider> [model]{Colors.ENDC}")
            print(f"Pilihan provider: {', '.join(list(PROVIDERS_CATALOG.keys())[:8])}\n")
            return

        raw_provider = parts[1]
        target_provider = normalize_provider(raw_provider)
        if target_provider not in PROVIDERS_CATALOG:
            print_status(f"Provider '{raw_provider}' tidak dikenal. Pilihan: {', '.join(PROVIDERS_CATALOG.keys())}", "warning")

        cat = PROVIDERS_CATALOG.get(target_provider, {})
        default_model = cat.get("default_model") or (cat.get("models", ["default"])[0] if cat.get("models") else "default")
        target_model = parts[2] if len(parts) > 2 else default_model

        # Update database
        try:
            res = database.update_custom_agent_sync(
                matched["id"],
                {"provider": target_provider, "model": target_model},
            )
            if res.get("status") == "success":
                print_status(
                    f"Model AI untuk {matched.get('avatar_emoji', '🤖')} {matched.get('name')} "
                    f"berhasil diubah ke: {target_provider.upper()} / {target_model}",
                    "success",
                )
                if getattr(self, "active_persona_name", None) == matched.get("name"):
                    if hasattr(self, "direct_ai") and self.direct_ai:
                        self.direct_ai.set_provider(target_provider, target_model)
                        self._update_prompt()
            else:
                print_status(f"Gagal update agen: {res.get('message')}", "error")
        except Exception as err:
            print_status(f"Error memperbarui database agen: {err}", "error")

    def do_slash_swarm(self, arg: str) -> None:
        """Kelola atau jalankan Swarm Multi-Agent & atur model per agen. Usage: /swarm [list|single|swarm|model|run]"""
        sub = arg.strip()
        parts = sub.split(maxsplit=1)
        action = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if action in ("single", "solo"):
            self.do_slash_mode("single")
            return
        elif action in ("swarm", "on", "enable", "start", "multi"):
            self.do_slash_mode("swarm")
            return
        elif action in ("model", "set-model"):
            self._set_agent_model_command(rest)
            return
        elif action == "run":
            if not rest:
                print_status("Tentukan tugas untuk Swarm. Contoh: /swarm run Buat landing page modern", "warning")
                return
            self._run_swarm_execution(rest)
            return

        # Default: list all agents
        self.do_slash_agents(arg)

    def do_slash_persona(self, arg: str) -> None:
        """Ganti persona aktif ke salah satu Swarm / Custom Agent (sinkron Web). Usage: /persona [name|id|reset]"""
        target = arg.strip()
        from alfa.core import database

        agents = []
        try:
            agents = database.list_custom_agents_sync()
        except Exception:
            pass

        if not target:
            curr = getattr(self, "active_persona_name", None)
            curr_str = f"{Colors.GREEN}{curr}{Colors.ENDC}" if curr else f"{Colors.WARNING}Default (Orchestrator){Colors.ENDC}"
            print(f"\n{Colors.BOLD}🎭 Persona Swarm Saat Ini:{Colors.ENDC} {curr_str}")
            print("Pilihan yang tersedia:")
            for a in agents:
                print(f"  • #{a.get('id')} {a.get('avatar_emoji', '🤖')} {Colors.CYAN}{a.get('name')}{Colors.ENDC} - {a.get('role')}")
            print(f"\nGanti dengan: {Colors.CYAN}/persona <nama|id>{Colors.ENDC} atau kembalikan dengan: {Colors.CYAN}/persona reset{Colors.ENDC}\n")
            return

        if target.lower() in ("reset", "default", "none", "clear"):
            self.active_persona_name = None
            if hasattr(self, "direct_ai") and self.direct_ai:
                self.direct_ai.system_prompt = None
            self._update_prompt()
            print_status("Persona di-reset ke Default ALFA Autonomous Orchestrator.", "success")
            return

        # Find matching agent by ID or substring in name
        matched = None
        if target.isdigit():
            target_id = int(target)
            matched = next((a for a in agents if a.get("id") == target_id), None)
        if not matched:
            t_lower = target.lower()
            matched = next((a for a in agents if t_lower in a.get("name", "").lower()), None)

        if not matched:
            print_status(f"Persona '{target}' tidak ditemukan. Gunakan '/persona' untuk melihat daftar.", "error")
            return

        self.active_persona_name = matched.get("name")
        sys_inst = matched.get("system_instruction") or f"Kamu adalah {matched.get('name')}, seorang {matched.get('role')}."

        if hasattr(self, "direct_ai") and self.direct_ai:
            self.direct_ai.system_prompt = sys_inst

            # Switch model if defined for this agent and supported
            prov = matched.get("provider")
            mod = matched.get("model")
            if prov and prov in PROVIDERS_CATALOG:
                try:
                    self.direct_ai.set_provider(prov, mod)
                except Exception:
                    pass

        self._update_prompt()
        avatar = matched.get("avatar_emoji", "🤖")
        print_status(f"Beralih ke persona: {avatar} {matched.get('name')} ({matched.get('role')})", "success")
        print(f"{Colors.BOLD}Deskripsi Instruksi Sistem:{Colors.ENDC}")
        first_line = sys_inst.strip().splitlines()[0] if sys_inst else ""
        print(f"  {Colors.CYAN}{first_line[:120]}...{Colors.ENDC}\n")

    def do_slash_servers(self, arg: str) -> None:
        """Kelola & pantau server latar belakang ALFA (Dashboard, 9Router, Bot). Usage: /servers [status|start|stop|restart]"""
        from alfa.core.cli.server_manager import (
            auto_start_all_servers,
            get_servers_status,
            stop_all_servers,
        )

        sub = arg.strip().lower() or "status"

        if sub == "status":
            statuses = get_servers_status()
            print(f"\n{Colors.BOLD}🌐 Status Server Ekosistem ALFA:{Colors.ENDC}")
            dash = statuses["dashboard"]
            r9 = statuses["9router"]
            bot = statuses["bot"]

            print(f"  {'🟢' if dash['ok'] else '🔴'} Web Command Center : {Colors.CYAN}{dash['status']}{Colors.ENDC}")
            print(f"  {'🔀' if r9['ok'] else '⚪'} 9Router AI Gateway : {Colors.CYAN}{r9['status']}{Colors.ENDC}")
            print(f"  {'🤖' if bot['ok'] else '⚪'} Telegram AI Bot    : {Colors.CYAN}{bot['status']}{Colors.ENDC}\n")
            print(f"Perintah: {Colors.CYAN}/servers start{Colors.ENDC} | {Colors.CYAN}/servers restart{Colors.ENDC} | {Colors.CYAN}/servers stop{Colors.ENDC}\n")

        elif sub == "start":
            print_status("Memulai semua server ekosistem ALFA...", "info")
            auto_start_all_servers(verbose=True)
            self.server_reachable = True

        elif sub == "stop":
            print_status("Menghentikan server latar belakang...", "warning")
            stop_all_servers()
            self.server_reachable = False
            print_status("Server berhasil dihentikan.", "success")

        elif sub == "restart":
            print_status("Me-restart semua server ekosistem ALFA...", "info")
            stop_all_servers()
            import time
            time.sleep(1)
            auto_start_all_servers(verbose=True)
            self.server_reachable = True

        else:
            print_status("Subcommand tidak dikenal. Pilihan: status, start, stop, restart", "error")


    def do_slash_upload(self, arg: str) -> None:
        """Upload file ke server ALFA. Usage: /upload <filepath>"""
        if not getattr(self, "session_token", None):
            print_status("Login terlebih dahulu.", "warning")
            return
        filepath = arg.strip()
        if not filepath:
            filepath = input("Path file: ").strip()
        if not os.path.exists(filepath):
            print_status(f"File tidak ditemukan: {filepath}", "error")
            return
        print_status("Endpoint upload sedang disiapkan di backend server.", "info")

    def do_slash_download(self, arg: str) -> None:
        """Download file dari server ALFA. Usage: /download <filename>"""
        if not getattr(self, "session_token", None):
            print_status("Login terlebih dahulu.", "warning")
            return
        print_status("Endpoint download sedang disiapkan di backend server.", "info")

    def do_slash_keys(self, arg: str) -> None:
        """Tampilkan atau sinkronkan daftar API Key dari Web Vault (database SQLite) & gateway lokal. Usage: /keys [sync]"""
        if arg.strip().lower() == "sync":
            from alfa.core import database
            synced = database.sync_external_api_keys_sync()
            if synced:
                print_status(f"Berhasil menyinkronkan {len(synced)} API key baru ke Web Dashboard Vault!", "success")
            else:
                print_status("Seluruh API key sudah tersinkronisasi dengan Web Dashboard Vault.", "info")
        self.display_api_keys_vault()

    def do_slash_key(self, arg: str) -> None:
        """Alias untuk /keys."""
        self.do_slash_keys(arg)

    def display_api_keys_vault(self) -> None:
        """Display full table of API Keys from Web Dashboard SQLite Vault & local sources."""
        print(f"\n{Colors.BOLD}🔐 ALFA Vault - Daftar API Key Terdaftar:{Colors.ENDC}")

        # 1. Fetch from database vault (Web Dashboard)
        db_keys = []
        try:
            from alfa.core import database

            db_keys = database.list_api_keys_sync()
        except Exception:
            pass

        if db_keys:
            if getattr(self, "console", None):
                from rich.table import Table

                tbl = Table(title="Database Web Dashboard Vault (agent_data.db)")
                tbl.add_column("ID", style="cyan", justify="right")
                tbl.add_column("Nama Label", style="bold white")
                tbl.add_column("Provider", style="green")
                tbl.add_column("Masked Key", style="yellow")
                tbl.add_column("Default Model", style="magenta")
                tbl.add_column("Status", justify="center")

                for k in db_keys:
                    status_str = "[green]🟢 AKTIF[/green]" if k.get("is_active") else "[dim]⚪ Non-aktif[/dim]"
                    tbl.add_row(
                        str(k.get("id")),
                        k.get("name", "-"),
                        k.get("provider", "-").upper(),
                        k.get("masked_key", "-"),
                        k.get("default_model", "-"),
                        status_str,
                    )
                self.console.print(tbl)
            else:
                for k in db_keys:
                    act = "🟢 AKTIF" if k.get("is_active") else "⚪ Non-aktif"
                    print(
                        f"  • #{k.get('id')} [{k.get('provider', '').upper()}] {k.get('name')}: {k.get('masked_key')} (Model: {k.get('default_model')}) - {act}"
                    )
        else:
            print("  [Database Web Vault]: Belum ada kunci tersimpan di database.")

        # 2. 9Router Gateway Status
        try:
            from alfa.core.cli.direct_ai import DirectAIClient

            r_client = DirectAIClient(provider="9router")
            r_key = r_client.get_api_key()
            if r_key:
                masked_r = r_key[:7] + "••••••••" + r_key[-4:] if len(r_key) > 12 else "••••••••"
                print(f"\n  🔀 [9Router AI Gateway]: Tersambung ke port 20128 (Key: {masked_r})")
        except Exception:
            pass

        # 3. Local CLI Config Keys
        cfg_keys = getattr(self, "config", {}).get("api_keys", {})
        if cfg_keys:
            print("\n  📁 [Config Lokal CLI (~/.alfa/config.json)]:")
            for p, kv in cfg_keys.items():
                m_kv = kv[:6] + "••••••••" + kv[-4:] if len(kv) > 10 else "••••••••"
                print(f"    - {p.upper():<10}: {m_kv}")

        print("\n💡 Tambah/kelola kunci: ketik '/menu' -> 'Kelola API Keys' atau melalui Web Dashboard.\n")

    # --- Autonomous Agent Mode ---

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
            print(f"  • Mode Eksekusi      : {Colors.CYAN}{exec_mode.upper()}{Colors.ENDC} ({'Single ReAct' if exec_mode == 'single' else 'Swarm Multi-Agen'})")
            print("\n💡 Pilihan perintah:")
            print(f"  • {Colors.CYAN}/agent single{Colors.ENDC} - Beralih ke Single Agent Mode")
            print(f"  • {Colors.CYAN}/agent swarm{Colors.ENDC}  - Beralih ke Swarm Multi-Agent Mode")
            print(f"  • {Colors.CYAN}/agent model <agen> <provider> [model]{Colors.ENDC} - Atur model AI spesifik untuk agen")
            print(f"  • {Colors.CYAN}/agent on{Colors.ENDC} / {Colors.CYAN}/agent off{Colors.ENDC} - Toggle tools aktif/nonaktif\n")
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
            import subprocess

            res = subprocess.run(["git", "restore", "."], capture_output=True, text=True)
            if res.returncode == 0:
                print_status("Tidak ada jurnal patch; git restore . berhasil dijalankan.", "info")
            else:
                print_status("Belum ada riwayat patch untuk dibatalkan.", "warning")
            return

        latest = patches[-1]
        confirm = input(
            f"Batalkan perubahan terakhir pada '{latest.filepath}' (Patch #{latest.id})? [Y/n]: "
        ).strip().lower()
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
            ("search_code", "Ripgrep / Fallback", "Pencarian regex/string di seluruh codebase"),
            ("find_files", "Fd / Globbing", "Pencarian file berdasarkan pola wildcard (*.py, *auth*)"),
            ("read_file", "Builtin IO", "Membaca rentang baris file lokal dengan nomor baris"),
            ("write_file", "Transactional IO", "Membuat/menimpa file dengan auto-backup (.alfa_backups)"),
            ("patch_file", "Precision Patcher", "Mengganti potongan blok kode secara presisi"),
            ("run_command", "Sandbox Shell", "Menjalankan perintah terminal & verifikasi test otomatis"),
            ("list_directory", "Filesystem", "Melihat hierarki file dan struktur direktori real-time"),
        ]

        eco_tools = [
            ("web_search", "DuckDuckGo / Tavily", "Pencarian web real-time & fakta terkini"),
            ("fetch_web_page_content", "Web Extractor", "Membaca & merangkum konten artikel/dokumentasi web"),
            ("universal_deep_scraper", "Scraper Engine", "Scraping halaman web mendalam (dinamis/JS)"),
            ("audit_website_security", "Security Auditor", "Audit kerentanan situs, SSL/TLS, & HTTP headers"),
            ("get_system_stats", "System Telemetry", "Cek CPU, RAM, Disk, Jaringan, dan Baterai komputer"),
            ("vault_get_secret", "SQLite Vault", "Mengambil rahasia/token dari brankas terenkripsi ALFA"),
            ("vault_store_secret", "SQLite Vault", "Menyimpan kredensial baru ke brankas aman"),
            ("vault_list_secrets", "SQLite Vault", "Daftar kunci rahasia yang tersimpan di brankas"),
        ]

        if getattr(self, "console", None):
            tbl_dev = Table(title="💻 1. Local Developer Tools (Coding & Proyek)")
            tbl_dev.add_column("Tool Name", style="bold cyan")
            tbl_dev.add_column("Engine", style="dim")
            tbl_dev.add_column("Deskripsi", style="green")
            for t_name, t_eng, t_desc in dev_tools:
                tbl_dev.add_row(t_name, t_eng, t_desc)
            self.console.print(tbl_dev)

            tbl_eco = Table(title="🌐 2. Web & Ecosystem Tools (Sinkron Web Dashboard & Bot)")
            tbl_eco.add_column("Tool Name", style="bold magenta")
            tbl_eco.add_column("Engine", style="dim")
            tbl_eco.add_column("Deskripsi", style="yellow")
            for t_name, t_eng, t_desc in eco_tools:
                tbl_eco.add_row(t_name, t_eng, t_desc)
            self.console.print(tbl_eco)
        else:
            print(f"\n{Colors.BOLD}💻 1. Local Developer Tools (Coding & Proyek):{Colors.ENDC}")
            for t_name, t_eng, t_desc in dev_tools:
                print(f"  • {Colors.CYAN}{t_name:<15}{Colors.ENDC} ({t_eng}): {t_desc}")

            print(f"\n{Colors.BOLD}🌐 2. Web & Ecosystem Tools (Sinkron Web Dashboard):{Colors.ENDC}")
            for t_name, t_eng, t_desc in eco_tools:
                print(f"  • {Colors.GREEN}{t_name:<24}{Colors.ENDC} ({t_eng}): {t_desc}")
            print()

        print("💡 [Sinkronisasi]: ReAct Agent di CLI & Web Command Center memiliki akses ke seluruh tools di atas.\n")

