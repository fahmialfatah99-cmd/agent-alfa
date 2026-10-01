"""Slash-command mixin: API-key vault commands."""

from alfa.core.cli.constants import Colors, print_status


class SlashVaultMixin:
    """API-key vault commands."""

    def do_slash_keys(self, arg: str) -> None:
        """Tampilkan atau sinkronkan daftar API Key dari Web Vault (database SQLite) & gateway lokal. Usage: /keys [sync]"""
        if arg.strip().lower() == "sync":
            from alfa.core import database

            synced = database.sync_external_api_keys_sync()
            if synced:
                print_status(
                    f"Berhasil menyinkronkan {len(synced)} API key baru ke Web Dashboard Vault!",
                    "success",
                )
            else:
                print_status(
                    "Seluruh API key sudah tersinkronisasi dengan Web Dashboard Vault.",
                    "info",
                )
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
                    status_str = (
                        "[green]🟢 AKTIF[/green]"
                        if k.get("is_active")
                        else "[dim]⚪ Non-aktif[/dim]"
                    )
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
                masked_r = (
                    r_key[:7] + "••••••••" + r_key[-4:]
                    if len(r_key) > 12
                    else "••••••••"
                )
                print(
                    f"\n  🔀 [9Router AI Gateway]: Tersambung ke port 20128 (Key: {masked_r})"
                )
        except Exception:
            pass

        # 3. Local CLI Config Keys
        cfg_keys = getattr(self, "config", {}).get("api_keys", {})
        if cfg_keys:
            print("\n  📁 [Config Lokal CLI (~/.alfa/config.json)]:")
            for p, kv in cfg_keys.items():
                m_kv = kv[:6] + "••••••••" + kv[-4:] if len(kv) > 10 else "••••••••"
                print(f"    - {p.upper():<10}: {m_kv}")

        print(
            "\n💡 Tambah/kelola kunci: ketik '/menu' -> 'Kelola API Keys' atau melalui Web Dashboard.\n"
        )

    # --- Autonomous Agent Mode ---
