"""ALFA Sovereign AI - Unified CLI application class, subcommands, and main entrypoint.

Integrates Sovereign Swarm Server operations with DevCLI standalone coding capabilities.
"""

from __future__ import annotations

import argparse
import cmd
import getpass
import os
import subprocess
import sys
from pathlib import Path

import requests

from alfa.core.cli.agent_engine import (
    AutonomousAgentRunner,
    PatchHistoryManager,
    RepomapGenerator,
)
from alfa.core.cli.chat import CliChatMixin
from alfa.core.cli.commands import CliCommandsMixin
from alfa.core.cli.constants import (
    DEFAULT_MODE,
    DEFAULT_SERVER,
    RICH_AVAILABLE,
    VERSION,
    Colors,
    Console,
    print_banner,
    print_status,
)
from alfa.core.cli.direct_ai import (
    PROVIDERS_CATALOG,
    DirectAIClient,
)
from alfa.core.cli.session import CliSessionMixin


class AlfaCLI(CliSessionMixin, CliCommandsMixin, CliChatMixin, cmd.Cmd):
    intro = f"{Colors.GREEN}Selamat datang di ALFA Unified CLI v{VERSION}. Ketik '/help' untuk panduan atau langsung chatting!{Colors.ENDC}"

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER,
        mode: str = DEFAULT_MODE,
        attached_files: list[str] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ):
        super().__init__()
        self.server_url = server_url.rstrip("/")
        self.session_token = None
        self.username = None
        self.is_admin = False
        self.chat_history: list[dict[str, str]] = []
        self.config = self._load_config()
        self.streaming = self.config.get("streaming", True)
        self.console = Console() if RICH_AVAILABLE else None

        # Mode setup (auto, server, standalone)
        self.mode = mode or self.config.get("mode", DEFAULT_MODE)
        self.server_reachable = False

        # Inisialisasi Direct AI Client (Standalone Engine)
        target_provider = provider or self.config.get("provider")
        target_model = model
        if not target_model and (not provider or provider == self.config.get("provider")):
            target_model = self.config.get("model")

        self.direct_ai = DirectAIClient(
            provider=target_provider,
            model=target_model,
        )

        # Context files
        self.attached_files: list[str] = []
        if attached_files:
            for f in attached_files:
                p = Path(f)
                if p.exists():
                    self.attached_files.append(str(p))

        # Autonomous ReAct Agent Engine components
        self.agent_mode = self.config.get("agent_mode", True)
        self.agent_execution_mode = self.config.get("agent_execution_mode", "single")
        self.active_persona_name = None
        self.patch_manager = PatchHistoryManager(workspace_root=Path.cwd())
        self.repomap_gen = RepomapGenerator(root_dir=Path.cwd())
        self.agent_runner = AutonomousAgentRunner(
            direct_ai=self.direct_ai,
            workspace_root=Path.cwd(),
            console=self.console,
        )

        self._setup_readline()
        self._load_session()
        self._update_prompt()


def run_config_wizard() -> None:
    """Interactive wizard to configure AI provider, model, API keys, and execution mode."""
    print(f"\n{Colors.BOLD}⚙️  ALFA CLI - Interactive Configuration Setup{Colors.ENDC}\n")

    cli = AlfaCLI()
    current_cfg = cli.config
    direct = cli.direct_ai

    print("Konfigurasi saat ini:")
    print(f"  • Mode Operasi : {Colors.CYAN}{current_cfg.get('mode', 'auto')}{Colors.ENDC}")
    print(f"  • AI Provider  : {Colors.CYAN}{direct.provider}{Colors.ENDC}")
    print(f"  • Model Aktif  : {Colors.CYAN}{direct.model}{Colors.ENDC}")
    print(f"  • Server URL   : {Colors.CYAN}{cli.server_url}{Colors.ENDC}")
    print(f"  • API Key Set  : {Colors.GREEN if direct.get_api_key() else Colors.WARNING}{'Yes' if direct.get_api_key() else 'Belum Diatur'}{Colors.ENDC}\n")

    # 1. Pilih Provider
    print(f"{Colors.BOLD}Pilih AI Provider:{Colors.ENDC}")
    providers_list = list(PROVIDERS_CATALOG.keys())
    for i, p in enumerate(providers_list, 1):
        name = PROVIDERS_CATALOG[p]["name"]
        curr_mark = " (saat ini)" if p == direct.provider else ""
        print(f"  {i}. {p:<10} - {name}{curr_mark}")

    choice = input(f"\nMasukkan pilihan [1-{len(providers_list)}] (Enter untuk lewati): ").strip()
    selected_provider = direct.provider
    if choice.isdigit() and 1 <= int(choice) <= len(providers_list):
        selected_provider = providers_list[int(choice) - 1]

    # 2. Pilih Model
    catalog = PROVIDERS_CATALOG[selected_provider]
    print(f"\n{Colors.BOLD}Pilih Model untuk {catalog['name']}:{Colors.ENDC}")
    models_list = catalog["models"]
    for i, m in enumerate(models_list, 1):
        curr_mark = " (saat ini)" if m == direct.model else ""
        print(f"  {i}. {m}{curr_mark}")
    print(f"  {len(models_list) + 1}. Ketik nama model custom manual")

    model_choice = input(f"\nMasukkan pilihan [1-{len(models_list) + 1}] (Enter untuk lewati): ").strip()
    selected_model = direct.model
    if model_choice.isdigit():
        idx = int(model_choice)
        if 1 <= idx <= len(models_list):
            selected_model = models_list[idx - 1]
        elif idx == len(models_list) + 1:
            custom_m = input("Masukkan nama model custom: ").strip()
            if custom_m:
                selected_model = custom_m

    # 3. Masukkan API Key jika diperlukan
    api_key_env = catalog.get("env_keys", [None])[0] if catalog.get("env_keys") else None
    if api_key_env:
        print(f"\n{Colors.BOLD}Pengaturan API Key ({api_key_env}):{Colors.ENDC}")
        has_key = bool(direct.get_api_key())
        prompt_text = f"Masukkan {api_key_env} (sembunyi, Enter untuk lewati): " if has_key else f"Masukkan {api_key_env} (sembunyi): "
        new_key = getpass.getpass(prompt_text).strip()
    else:
        new_key = ""

    # 4. Mode Operasi Default
    print(f"\n{Colors.BOLD}Pilih Mode Operasi Default:{Colors.ENDC}")
    print("  1. auto       (Coba Server ALFA, fallback ke Standalone AI)")
    print("  2. standalone (Langsung panggil API LLM mandiri)")
    print("  3. server     (Hanya gunakan server backend ALFA)")
    mode_choice = input("Pilihan mode [1-3] (Enter untuk lewati): ").strip()
    selected_mode = current_cfg.get("mode", "auto")
    if mode_choice == "1":
        selected_mode = "auto"
    elif mode_choice == "2":
        selected_mode = "standalone"
    elif mode_choice == "3":
        selected_mode = "server"

    # Simpan ke config file
    current_cfg["provider"] = selected_provider
    current_cfg["model"] = selected_model
    current_cfg["mode"] = selected_mode
    if "api_keys" not in current_cfg:
        current_cfg["api_keys"] = {}
    if new_key:
        current_cfg["api_keys"][selected_provider] = new_key
        if api_key_env:
            os.environ[api_key_env] = new_key

    cli.config = current_cfg
    cli._save_config()

    # Opsi update .env di repo root
    from alfa.core.cli.server_manager import get_repo_root
    env_path = get_repo_root() / ".env"
    if env_path.exists() and new_key and api_key_env:
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
            found = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{api_key_env}="):
                    new_lines.append(f"{api_key_env}={new_key}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{api_key_env}={new_key}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print_status("Kunci tersimpan juga ke .env", "success")
        except Exception:
            pass

    # Sinkronkan ke Database SQLite Web Vault (agent_data.db)
    try:
        from alfa.core import database
        key_to_save = new_key or direct.get_api_key()
        if key_to_save:
            p_norm = "gemini" if selected_provider == "google" else selected_provider
            b_url = catalog.get("default_url", "")
            database.add_api_key_sync(
                name=f"{catalog.get('name', selected_provider.capitalize())} Key (CLI)",
                provider=p_norm,
                api_key=key_to_save,
                default_model=selected_model,
                base_url=b_url,
                set_active=True,
            )
            print_status("API Key berhasil disinkronkan ke Web Dashboard Vault!", "success")
    except Exception:
        pass

    print_status("Konfigurasi berhasil disimpan!", "success")
    print(f"Provider: {selected_provider} | Model: {selected_model} | Mode: {selected_mode}\n")


def show_config() -> None:
    """Display current CLI configurations."""
    cli = AlfaCLI()
    cfg = cli.config
    direct = cli.direct_ai

    print(f"\n{Colors.BOLD}📋 ALFA CLI Configuration Summary:{Colors.ENDC}")
    print(f"  • Version      : {VERSION}")
    print(f"  • Active Mode  : {Colors.CYAN}{cfg.get('mode', 'auto')}{Colors.ENDC}")
    agent_status = f"{Colors.GREEN}ENABLED (Autonomous ReAct Loop){Colors.ENDC}" if cfg.get("agent_mode", True) else f"{Colors.WARNING}DISABLED (Direct Chat){Colors.ENDC}"
    print(f"  • Agent Mode   : {agent_status}")
    print(f"  • AI Provider  : {Colors.GREEN}{direct.provider}{Colors.ENDC} ({PROVIDERS_CATALOG.get(direct.provider, {}).get('name', direct.provider)})")
    print(f"  • Active Model : {Colors.CYAN}{direct.model}{Colors.ENDC}")
    print(f"  • Server URL   : {Colors.CYAN}{cli.server_url}{Colors.ENDC}")
    print(f"  • Streaming    : {cfg.get('streaming', True)}")
    print(f"  • API Key Set  : {Colors.GREEN if direct.get_api_key() else Colors.FAIL}{'Yes' if direct.get_api_key() else 'No'}{Colors.ENDC}")

    print(f"\n{Colors.BOLD}Supported Providers:{Colors.ENDC}")
    for k, v in PROVIDERS_CATALOG.items():
        if k in ("gemini", "nim"):  # Skip duplicate alias keys in listing
            continue
        is_curr = " (active)" if k == direct.provider else ""
        print(f"  - {k:<12}: {v['name']}{is_curr}")

    cli.display_api_keys_vault()


def handle_ask_command(args: argparse.Namespace) -> None:
    """Handle one-shot question command (DevCLI ask equivalent)."""
    cli = AlfaCLI(
        server_url=args.server,
        mode="standalone" if args.standalone else args.mode,
        attached_files=args.file,
        provider=args.provider,
        model=args.model,
    )
    direct = cli.direct_ai

    # Jika dipanggil dengan mode --agent, jalankan Autonomous ReAct Runner
    if getattr(args, "agent", False):
        ans = cli.agent_runner.run(args.question)
        print(f"\n{Colors.GREEN}✨ Hasil Akhir Agent:{Colors.ENDC}\n{ans}\n")
        return

    # Cek file context
    context_files = list(args.file or [])

    try:
        if args.stream:
            print(f"{Colors.CYAN}🤖 ALFA ({direct.provider}/{direct.model}):{Colors.ENDC} ", end="", flush=True)

            def on_chunk(c: str) -> None:
                print(c, end="", flush=True)

            direct.generate(
                prompt=args.question,
                context_files=context_files,
                stream=True,
                stream_callback=on_chunk,
            )
            print()
        else:
            resp = direct.generate(
                prompt=args.question,
                context_files=context_files,
                stream=False,
            )
            if RICH_AVAILABLE and cli.console:
                from rich.markdown import Markdown
                cli.console.print(Markdown(resp))
            else:
                print(resp)
    except Exception as e:
        print_status(f"Error AI: {e}", "error")
        sys.exit(1)


def handle_run_command(args: argparse.Namespace) -> None:
    """Handle safe shell command execution (DevCLI run equivalent)."""
    cmd_str = args.command
    print(f"{Colors.WARNING}⚡ Menjalankan shell:{Colors.ENDC} {cmd_str}")
    try:
        res = subprocess.run(
            cmd_str,
            shell=True,
            text=True,
            capture_output=True,
        )
        if res.stdout:
            print(res.stdout, end="" if res.stdout.endswith("\n") else "\n")
        if res.stderr:
            print(f"{Colors.FAIL}{res.stderr}{Colors.ENDC}", end="")
        sys.exit(res.returncode)
    except Exception as e:
        print_status(f"Error eksekusi: {e}", "error")
        sys.exit(1)


def main():
    # Smart subcommand normalization:
    # If first arg is not a recognized subcommand or flag, default to 'chat'
    known_subcommands = {"chat", "ask", "run", "config", "help", "--help", "-h", "--version", "-v"}

    raw_args = sys.argv[1:]
    if raw_args and raw_args[0] not in known_subcommands and not raw_args[0].startswith("-"):
        # Could be directly asking or chatting
        sys.argv.insert(1, "chat")
    elif not raw_args or (raw_args[0].startswith("-") and raw_args[0] not in {"--help", "-h", "--version", "-v"}):
        # Starts with options (e.g. `python cli.py --stream`), treat as `chat`
        sys.argv.insert(1, "chat")

    parser = argparse.ArgumentParser(
        prog="alfa",
        description="ALFA Sovereign AI & Developer Unified CLI Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py                              # Masuk ke interactive chat
  python cli.py chat -f main.py -f brain.py  # Chat dengan konteks file
  python cli.py ask "Perbaiki fungsi ini" -f app.py   # Tanya cepat (one-shot)
  python cli.py run "pytest tests/"          # Jalankan shell command
  python cli.py config                       # Setup wizard (provider, model, API key)
  python cli.py --stream                     # Mulai chat dengan streaming
        """,
    )
    parser.add_argument("--version", "-v", action="version", version=f"ALFA CLI v{VERSION}")

    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommands")

    # --- Subcommand: CHAT ---
    chat_parser = subparsers.add_parser("chat", help="Mulai sesi interaktif chat & coding")
    chat_parser.add_argument("-f", "--file", action="append", default=[], help="Lampirkan file sebagai konteks (dapat diulang)")
    chat_parser.add_argument("--server", type=str, default=os.getenv("ALFA_SERVER", DEFAULT_SERVER), help="URL Server ALFA")
    chat_parser.add_argument("--mode", type=str, choices=["auto", "server", "standalone"], default="auto", help="Mode operasi")
    chat_parser.add_argument("--standalone", action="store_true", help="Paksa gunakan engine Direct AI tanpa server ALFA")
    chat_parser.add_argument("--provider", type=str, choices=list(PROVIDERS_CATALOG.keys()), help="Pilih AI provider")
    chat_parser.add_argument("--model", type=str, help="Pilih model AI")
    chat_parser.add_argument("--no-color", action="store_true", help="Matikan warna terminal")
    chat_parser.add_argument("--stream", action="store_true", help="Aktifkan streaming response")
    chat_parser.add_argument("--no-autostart", action="store_true", help="Jangan otomatis jalankan server di latar belakang")

    # --- Subcommand: ASK ---
    ask_parser = subparsers.add_parser("ask", help="Tanya cepat (one-shot) tanpa mode interaktif")
    ask_parser.add_argument("question", type=str, help="Pertanyaan atau perintah coding")
    ask_parser.add_argument("-f", "--file", action="append", default=[], help="Lampirkan file sebagai konteks")
    ask_parser.add_argument("--server", type=str, default=os.getenv("ALFA_SERVER", DEFAULT_SERVER), help="URL Server ALFA")
    ask_parser.add_argument("--mode", type=str, choices=["auto", "server", "standalone"], default="standalone", help="Mode operasi")
    ask_parser.add_argument("--standalone", action="store_true", default=True, help="Gunakan engine Direct AI")
    ask_parser.add_argument("--provider", type=str, choices=list(PROVIDERS_CATALOG.keys()), help="Pilih AI provider")
    ask_parser.add_argument("--model", type=str, help="Pilih model AI")
    ask_parser.add_argument("--stream", action="store_true", default=True, help="Streaming output")
    ask_parser.add_argument("--agent", action="store_true", default=False, help="Jalankan dalam mode Autonomous ReAct Agent")

    # --- Subcommand: RUN ---
    run_parser = subparsers.add_parser("run", help="Jalankan perintah shell lokal")
    run_parser.add_argument("command", type=str, help="Perintah shell yang akan dijalankan")

    # --- Subcommand: CONFIG ---
    config_parser = subparsers.add_parser("config", help="Pengaturan konfigurasi provider & CLI")
    config_parser.add_argument("--show", action="store_true", help="Tampilkan konfigurasi saat ini")

    args = parser.parse_args()

    if args.subcommand == "config":
        if args.show:
            show_config()
        else:
            run_config_wizard()
        return

    if args.subcommand == "run":
        handle_run_command(args)
        return

    if args.subcommand == "ask":
        handle_ask_command(args)
        return

    # Subcommand: CHAT (Default)
    if getattr(args, "no_color", False):
        Colors.disable()

    # Hanya tampilkan ASCII banner lama jika bukan interactive TTY (di mana Cursor UI banner akan dipakai)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print_banner()

    target_server = getattr(args, "server", DEFAULT_SERVER)
    force_standalone = getattr(args, "standalone", False)
    no_autostart = getattr(args, "no_autostart", False)
    chosen_mode = "standalone" if force_standalone else getattr(args, "mode", "auto")

    # Otomatis jalankan server ekosistem (Web Command Center, 9Router, Bot) jika tidak dicegah
    if not no_autostart and not force_standalone:
        try:
            from alfa.core.cli.server_manager import auto_start_all_servers
            auto_start_all_servers(verbose=True)
        except Exception as e:
            print_status(f"Server autostart info: {e}", "info")

    # Cek koneksi server jika mode auto atau server
    server_reachable = False
    if chosen_mode in ["auto", "server"]:
        try:
            r = requests.get(f"{target_server}/health", timeout=3)
            if r.status_code == 200:
                print_status(f"Terhubung ke server ALFA: {target_server}", "success")
                server_reachable = True
            else:
                print_status(f"Server ALFA merespons status code: {r.status_code}", "warning")
        except Exception:
            if chosen_mode == "server":
                print_status(f"Tidak dapat terhubung ke server di {target_server}.", "error")
                print("Pastikan server berjalan atau gunakan '--standalone' / '--mode standalone'.")
            else:
                print_status(
                    f"Server ALFA di {target_server} offline. Otomatis beralih ke Mode Standalone (Direct AI).",
                    "info",
                )


    try:
        cli = AlfaCLI(
            server_url=target_server,
            mode="standalone" if (chosen_mode == "auto" and not server_reachable) else chosen_mode,
            attached_files=getattr(args, "file", []),
            provider=getattr(args, "provider", None),
            model=getattr(args, "model", None),
        )
        cli.server_reachable = server_reachable

        if getattr(args, "stream", False):
            cli.streaming = True

        if cli.attached_files:
            print_status(f"Konteks file aktif ({len(cli.attached_files)} file): {', '.join(cli.attached_files)}", "info")

        # Launch modern Cursor-style interactive loop if running in a TTY
        if sys.stdin.isatty() and sys.stdout.isatty():
            from alfa.core.cli.cursor_ui import run_cursor_loop
            run_cursor_loop(cli)
        else:
            cli.cmdloop()
    except KeyboardInterrupt:
        print("\n")
        print_status("Interupsi diterima. Keluar...", "warning")
        sys.exit(0)


if __name__ == "__main__":
    main()
