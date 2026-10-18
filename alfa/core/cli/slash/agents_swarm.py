"""Slash-command mixin: Swarm workforce, persona, and agent-model commands."""

from typing import Any

from alfa.core.cli.constants import Colors, print_status
from alfa.core.cli.direct_ai import PROVIDERS_CATALOG


class SlashSwarmMixin:
    """Swarm workforce, persona, and agent-model commands."""

    console: Any

    def _request(self, *args: Any, **kwargs: Any) -> Any: ...
    def _update_prompt(self) -> None: ...
    def do_slash_mode(self, arg: str) -> None: ...
    def _run_swarm_execution(self, *args: Any, **kwargs: Any) -> Any: ...

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

        print(
            f"\n{Colors.BOLD}👥 ALFA Autonomous Workforce & Swarm Agents (Sinkron Web):{Colors.ENDC}\n"
        )

        if not agents:
            print(
                "  Belum ada custom agent di database. Kunjungi Web Dashboard di http://localhost:8080/agents."
            )
            return

        active_p = getattr(self, "active_persona_name", None)

        if getattr(self, "console", None):
            from rich.table import Table

            tbl = Table(
                title="Daftar Agen Swarm & Personas (Database SQLite & Web Command Center)"
            )
            tbl.add_column("ID", style="cyan", justify="right")
            tbl.add_column("Avatar", justify="center")
            tbl.add_column("Nama Agen", style="bold white")
            tbl.add_column("Peran / Spesialisasi", style="green")
            tbl.add_column("Provider/Model", style="yellow")
            tbl.add_column("Status Live", style="magenta")

            for a in agents:
                aid = a.get("id")
                name = a.get("name", "Unknown")
                is_active = name == active_p
                name_str = (
                    f"[bold green]{name}[/bold green] [yellow](AKTIF)[/yellow]"
                    if is_active
                    else name
                )
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
                print(
                    f"  {avatar} #{a.get('id')} {Colors.CYAN}{name}{Colors.ENDC}{is_active}: {role} [{prov}/{mod}]"
                )

        print(
            f"\n💡 Aktifkan persona agen: {Colors.CYAN}/persona <nama atau id>{Colors.ENDC} (Contoh: {Colors.GREEN}/persona Code Crafter{Colors.ENDC})"
        )
        print(
            f"💡 Atau buka menu interaktif: {Colors.CYAN}/menu{Colors.ENDC} -> Ganti Persona Swarm\n"
        )

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
            print(
                f"\n{Colors.BOLD}⚙️  Pengaturan Model AI per Agen Swarm:{Colors.ENDC}\n"
            )
            print("Format perintah:")
            print(
                f"  {Colors.CYAN}/swarm model <id|nama_agen> <provider> [nama_model]{Colors.ENDC}"
            )
            print(
                f"  {Colors.CYAN}/agent model <id|nama_agen> <provider> [nama_model]{Colors.ENDC}\n"
            )
            print("Contoh penggunaan:")
            print('  • /swarm model "Code Crafter" deepseek deepseek-coder')
            print("  • /swarm model 2 9router antigravity")
            print("  • /swarm model 4 google gemini-3.8-flash")
            print(
                '  • /swarm model "Security Sentinel" nvidia meta/llama-3.3-70b-instruct\n'
            )
            print("Daftar agen saat ini:")
            for a in agents:
                print(
                    f"  #{a.get('id')} {a.get('avatar_emoji', '🤖')} {Colors.CYAN}{a.get('name'):<20}{Colors.ENDC} - {a.get('role'):<25} [{a.get('provider')}/{a.get('model')}]"
                )
            print(
                f"\n💡 Atau atur via menu interaktif: {Colors.CYAN}/menu{Colors.ENDC} -> 'Atur Model AI per Agen'\n"
            )
            return

        target_agent = parts[0]
        # Match agent
        matched = None
        if target_agent.isdigit():
            aid = int(target_agent)
            matched = next((a for a in agents if a.get("id") == aid), None)
        if not matched:
            t_lower = target_agent.lower()
            matched = next(
                (a for a in agents if t_lower in a.get("name", "").lower()), None
            )

        if not matched:
            print_status(
                f"Agen '{target_agent}' tidak ditemukan di database. Ketik '/agents' untuk melihat daftar.",
                "error",
            )
            return

        if len(parts) < 2:
            print(
                f"\n{Colors.BOLD}Agen Terpilih:{Colors.ENDC} {matched.get('avatar_emoji', '🤖')} {matched.get('name')} ({matched.get('role')})"
            )
            print(
                f"Provider/Model saat ini: {Colors.CYAN}{matched.get('provider')}/{matched.get('model')}{Colors.ENDC}"
            )
            print("\nUntuk mengubah, tentukan provider dan model:")
            print(
                f'  {Colors.CYAN}/swarm model "{matched.get("name")}" <provider> [model]{Colors.ENDC}'
            )
            print(
                f"Pilihan provider: {', '.join(list(PROVIDERS_CATALOG.keys())[:8])}\n"
            )
            return

        raw_provider = parts[1]
        target_provider = normalize_provider(raw_provider)
        if target_provider not in PROVIDERS_CATALOG:
            print_status(
                f"Provider '{raw_provider}' tidak dikenal. Pilihan: {', '.join(PROVIDERS_CATALOG.keys())}",
                "warning",
            )

        cat = PROVIDERS_CATALOG.get(target_provider, {})
        default_model = cat.get("default_model") or (
            cat.get("models", ["default"])[0] if cat.get("models") else "default"
        )
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
                print_status(
                    "Tentukan tugas untuk Swarm. Contoh: /swarm run Buat landing page modern",
                    "warning",
                )
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
            curr_str = (
                f"{Colors.GREEN}{curr}{Colors.ENDC}"
                if curr
                else f"{Colors.WARNING}Default (Orchestrator){Colors.ENDC}"
            )
            print(f"\n{Colors.BOLD}🎭 Persona Swarm Saat Ini:{Colors.ENDC} {curr_str}")
            print("Pilihan yang tersedia:")
            for a in agents:
                print(
                    f"  • #{a.get('id')} {a.get('avatar_emoji', '🤖')} {Colors.CYAN}{a.get('name')}{Colors.ENDC} - {a.get('role')}"
                )
            print(
                f"\nGanti dengan: {Colors.CYAN}/persona <nama|id>{Colors.ENDC} atau kembalikan dengan: {Colors.CYAN}/persona reset{Colors.ENDC}\n"
            )
            return

        if target.lower() in ("reset", "default", "none", "clear"):
            self.active_persona_name = None
            if hasattr(self, "direct_ai") and self.direct_ai:
                self.direct_ai.system_prompt = None
            self._update_prompt()
            print_status(
                "Persona di-reset ke Default ALFA Autonomous Orchestrator.", "success"
            )
            return

        # Find matching agent by ID or substring in name
        matched = None
        if target.isdigit():
            target_id = int(target)
            matched = next((a for a in agents if a.get("id") == target_id), None)
        if not matched:
            t_lower = target.lower()
            matched = next(
                (a for a in agents if t_lower in a.get("name", "").lower()), None
            )

        if not matched:
            print_status(
                f"Persona '{target}' tidak ditemukan. Gunakan '/persona' untuk melihat daftar.",
                "error",
            )
            return

        self.active_persona_name = matched.get("name")
        sys_inst = (
            matched.get("system_instruction")
            or f"Kamu adalah {matched.get('name')}, seorang {matched.get('role')}."
        )

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
        print_status(
            f"Beralih ke persona: {avatar} {matched.get('name')} ({matched.get('role')})",
            "success",
        )
        print(f"{Colors.BOLD}Deskripsi Instruksi Sistem:{Colors.ENDC}")
        first_line = sys_inst.strip().splitlines()[0] if sys_inst else ""
        print(f"  {Colors.CYAN}{first_line[:120]}...{Colors.ENDC}\n")
