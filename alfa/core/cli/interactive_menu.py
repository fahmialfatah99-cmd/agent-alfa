"""ALFA Sovereign AI - Interactive TUI Menu System (Qwen/OpenCode/Cursor-Style).

Provides arrow-key interactive menus for:
- Switching AI Provider & Model
- Checkbox File Context Selection
- Preset Switching (Coding, Fast, Smart, Creative, Precise)
- Mode Switching (Auto, Standalone, Server)
- API Key Management
- Git Tools & System Status
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from alfa.core.cli.constants import (
    Colors,
    print_status,
)
from alfa.core.cli.direct_ai import (
    PRESETS,
    PROVIDERS_CATALOG,
    DirectAIClient,
    normalize_provider,
    sync_providers_catalog,
)


def get_workspace_files(max_files: int = 100) -> list[str]:
    """Scan workspace files excluding heavy/system directories."""
    ignore_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        "venv",
        ".alfa_worktrees",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".alfa_backups",
        "dist",
        "build",
    }
    results = []
    root = Path.cwd()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
        for f in filenames:
            full = Path(dirpath) / f
            try:
                rel = str(full.relative_to(root))
                results.append(rel)
                if len(results) >= max_files:
                    return sorted(results)
            except Exception:
                pass
    return sorted(results)


def menu_switch_model(cli: Any) -> None:
    """Interactive arrow-key provider and model switcher with 9Router & Web sync."""
    direct = cli.direct_ai

    # Synchronize with live 9Router & Web Dashboard catalog
    try:
        sync_providers_catalog()
    except Exception:
        pass

    primary_order = [
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

    provider_choices = []
    for pkey in primary_order:
        if pkey not in PROVIDERS_CATALOG:
            continue
        pinfo = PROVIDERS_CATALOG[pkey]
        is_curr = (
            " (aktif)"
            if normalize_provider(pkey) == normalize_provider(direct.provider)
            else ""
        )

        has_key = False
        try:
            temp_client = DirectAIClient(provider=pkey)
            has_key = bool(temp_client.get_api_key())
        except Exception:
            pass

        key_tag = " 🟢 [Key Ready]" if has_key else " ⚪ [No Key]"
        if pkey == "9router":
            key_tag = " 🔀 [Gateway Active]" if has_key else " ⚪ [Offline]"

        display_name = f"{pinfo['name']:<30} {key_tag}{is_curr}"
        provider_choices.append(Choice(pkey, display_name))

    selected_provider = inquirer.select(
        message="Pilih AI Provider (Sinkron Web & 9Router):",
        choices=provider_choices,
        default=direct.provider if direct.provider in primary_order else "google",
    ).execute()

    if not selected_provider:
        return

    catalog = PROVIDERS_CATALOG[selected_provider]
    model_choices = []
    for m in catalog["models"]:
        is_m_curr = (
            " (aktif)"
            if m == direct.model
            and normalize_provider(selected_provider) == normalize_provider(direct.provider)
            else ""
        )
        model_choices.append(Choice(m, f"{m}{is_m_curr}"))
    model_choices.append(Separator())
    model_choices.append(Choice("__custom__", "✍️ Masukkan nama model custom..."))

    selected_model = inquirer.select(
        message=f"Pilih Model untuk {catalog['name']}:",
        choices=model_choices,
        default=direct.model if direct.model in catalog["models"] else catalog["default_model"],
    ).execute()

    if selected_model == "__custom__":
        selected_model = inquirer.text(message="Ketik nama model:").execute().strip()
        if not selected_model:
            return

    direct.set_provider(selected_provider, selected_model)
    cli.config["provider"] = selected_provider
    cli.config["model"] = selected_model
    cli._save_config()

    # Synchronize default model with SQLite DB vault if provider exists in DB
    try:
        from alfa.core import database

        db_prov = "gemini" if selected_provider == "google" else selected_provider
        k_row = database.get_active_api_key_sync(db_prov)
        if k_row and k_row.get("id"):
            database.update_api_key_model(k_row["id"], selected_model)
    except Exception:
        pass

    print_status(
        f"Provider & Model berhasil diubah ke: {selected_provider.upper()} ({selected_model})",
        "success",
    )


def menu_manage_context_files(cli: Any) -> None:
    """Interactive checkbox file selector for prompt context."""
    files = get_workspace_files()
    if not files:
        print_status("Tidak ada file yang terdeteksi di direktori proyek saat ini.", "warning")
        return

    currently_attached = set(getattr(cli, "attached_files", []))

    choices = []
    for f in files:
        is_checked = f in currently_attached
        size_str = f"({os.path.getsize(f)} B)" if os.path.exists(f) else ""
        choices.append(Choice(f, f"{f:<40} {size_str}", enabled=is_checked))

    selected_files = inquirer.checkbox(
        message="Pilih file untuk konteks AI (Spasi untuk pilih/batal, Enter untuk konfirmasi):",
        choices=choices,
        instruction="(Tekan Spasi untuk Toggle, Enter untuk Simpan)",
    ).execute()

    cli.attached_files = list(selected_files)
    print_status(f"Konteks file diperbarui ({len(cli.attached_files)} file terpilih): {', '.join(cli.attached_files) if cli.attached_files else 'Kosong'}", "success")


def menu_switch_preset(cli: Any) -> None:
    """Interactive preset switcher."""
    direct = cli.direct_ai
    preset_choices = []
    for name, p in PRESETS.items():
        preset_choices.append(
            Choice(name, f"{name.upper():<10} - {p['description']} (temp: {p['temperature']})")
        )

    chosen = inquirer.select(
        message="Pilih Preset Respon AI:",
        choices=preset_choices,
    ).execute()

    if chosen:
        cli.do_slash_switch(chosen)


def menu_switch_mode(cli: Any) -> None:
    """Interactive execution mode switcher."""
    curr_mode = getattr(cli, "mode", "auto")
    choices = [
        Choice("auto", f"Auto        - Coba Server ALFA, otomatis fallback ke Standalone{' (aktif)' if curr_mode == 'auto' else ''}"),
        Choice("standalone", f"Standalone  - Langsung panggil API LLM (Google, NVIDIA, etc) tanpa server{' (aktif)' if curr_mode == 'standalone' else ''}"),
        Choice("server", f"Server      - Wajib terhubung ke server backend ALFA Sovereign Swarm{' (aktif)' if curr_mode == 'server' else ''}"),
    ]

    selected_mode = inquirer.select(
        message="Pilih Mode Eksekusi CLI:",
        choices=choices,
        default=curr_mode,
    ).execute()

    if selected_mode:
        cli.do_slash_mode(selected_mode)


def menu_setup_api_keys(cli: Any) -> None:
    """Interactive API Key configuration wizard with Web Vault sync."""
    action = inquirer.select(
        message="Kelola API Keys (Web Vault & CLI):",
        choices=[
            Choice("list", "📋 Lihat Daftar API Key Vault (Web & Database)"),
            Choice("sync", "🔄 Sinkronkan Kunci Otomatis (9Router, CLI, .env ➔ Web Vault)"),
            Choice("add", "➕ Tambah / Perbarui API Key (Sinkron ke Web & CLI)"),
            Choice("activate", "⚡ Aktifkan Kunci Vault Tertentu"),
            Separator(),
            Choice("back", "⬅️ Kembali"),
        ],
    ).execute()

    if not action or action == "back":
        return

    if action == "sync":
        try:
            from alfa.core import database

            synced = database.sync_external_api_keys_sync()
            if synced:
                print_status(f"Berhasil menyinkronkan {len(synced)} API key baru ke Web Dashboard Vault!", "success")
            else:
                print_status("Seluruh API key sudah tersinkronisasi penuh dengan Web Dashboard Vault.", "info")
            cli.display_api_keys_vault()
        except Exception as e:
            print_status(f"Gagal sinkronisasi: {e}", "error")
        return

    if action == "list":
        cli.display_api_keys_vault()
        return

    if action == "activate":
        try:
            from alfa.core import database

            keys = database.list_api_keys_sync()
            if not keys:
                print_status("Belum ada API Key di database Web Vault.", "warning")
                return

            key_choices = []
            for k in keys:
                act = " (aktif)" if k.get("is_active") else ""
                label = f"#{k['id']} {k['provider'].upper()}: {k['name']} ({k['masked_key']}){act}"
                key_choices.append(Choice(k["id"], label))

            chosen_id = inquirer.select(
                message="Pilih API Key untuk diaktifkan:",
                choices=key_choices,
            ).execute()

            if chosen_id:
                res = database.activate_api_key_sync(chosen_id)
                print_status(f"API Key #{chosen_id} berhasil diaktifkan di Web Vault & CLI!", "success")
        except Exception as e:
            print_status(f"Gagal mengaktifkan kunci: {e}", "error")
        return

    provider_choices = [
        Choice("9router", "9Router Gateway (NINEROUTER_API_KEY / Local Gateway)"),
        Choice("nvidia", "NVIDIA NIM (NVIDIA_API_KEY / NIM_API_KEY)"),
        Choice("google", "Google Gemini (GEMINI_API_KEY / GOOGLE_API_KEY)"),
        Choice("deepseek", "DeepSeek Official (DEEPSEEK_API_KEY)"),
        Choice("qwen", "Alibaba Cloud Qwen (DASHSCOPE_API_KEY / QWEN_API_KEY)"),
        Choice("openrouter", "OpenRouter (OPENROUTER_API_KEY)"),
        Choice("minimax", "MiniMax AI (MINIMAX_API_KEY)"),
        Choice("moonshot", "Moonshot Kimi (MOONSHOT_API_KEY / KIMI_API_KEY)"),
        Choice("openai", "OpenAI (OPENAI_API_KEY)"),
        Choice("anthropic", "Anthropic Claude (ANTHROPIC_API_KEY)"),
        Choice("groq", "Groq (GROQ_API_KEY)"),
    ]

    chosen_prov = inquirer.select(
        message="Pilih Provider untuk memasukkan API Key:",
        choices=provider_choices,
    ).execute()

    if not chosen_prov:
        return

    catalog = PROVIDERS_CATALOG.get(chosen_prov, {})
    env_key = catalog.get("env_keys", ["API_KEY"])[0]

    key_input = inquirer.secret(
        message=f"Masukkan {env_key} untuk {catalog.get('name', chosen_prov)}:",
    ).execute().strip()

    if key_input:
        if "api_keys" not in cli.config:
            cli.config["api_keys"] = {}
        cli.config["api_keys"][chosen_prov] = key_input
        cli._save_config()
        os.environ[env_key] = key_input

        # 1. Update .env
        from alfa.core.cli.server_manager import get_repo_root

        env_path = get_repo_root() / ".env"
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
            found = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{env_key}="):
                    new_lines.append(f"{env_key}={key_input}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{env_key}={key_input}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception:
            pass

        # 2. Synchronize with SQLite Database Vault (Web Dashboard)
        try:
            from alfa.core import database

            db_prov = "gemini" if chosen_prov == "google" else chosen_prov
            database.add_api_key_sync(
                name=f"{catalog.get('name', chosen_prov.capitalize())} Key",
                provider=db_prov,
                api_key=key_input,
                default_model=catalog.get("default_model", ""),
                base_url=catalog.get("default_url", ""),
                set_active=True,
            )
            print_status(
                f"API Key untuk {chosen_prov.upper()} berhasil disimpan & disinkronkan ke Web Dashboard Vault!",
                "success",
            )
        except Exception as e:
            print_status(
                f"API Key untuk {chosen_prov.upper()} disimpan ke config & .env: {e}",
                "info",
            )


def menu_git_actions(cli: Any) -> None:
    """Interactive Git Quick Actions."""
    import subprocess

    from rich.panel import Panel
    from rich.syntax import Syntax

    actions = [
        Choice("diff", "🔍 Lihat Git Diff Perubahan Terkini"),
        Choice("commit", "💾 Commit Semua Perubahan ke Git"),
        Choice("undo", "↩️  Undo / Restore File Terpilih"),
        Choice("status", "📋 Cek Git Status"),
        Separator(),
        Choice("back", "⬅️  Kembali"),
    ]

    act = inquirer.select(
        message="Pilih Aksi Git:",
        choices=actions,
    ).execute()

    if act == "diff":
        res = subprocess.run(["git", "diff"], capture_output=True, text=True)
        if res.stdout:
            if cli.console:
                cli.console.print(Panel(Syntax(res.stdout, "diff", theme="monokai"), title="Git Diff"))
            else:
                print(res.stdout)
        else:
            print_status("Tidak ada perubahan uncommitted.", "info")

    elif act == "commit":
        msg = inquirer.text(message="Pesan Commit:").execute().strip()
        if msg:
            res = subprocess.run(["git", "commit", "-am", msg], capture_output=True, text=True)
            print(res.stdout if res.stdout else res.stderr)

    elif act == "undo":
        target = inquirer.text(message="Nama file yang ingin dibatalkan (Enter untuk semua):").execute().strip()
        cmd = ["git", "restore", target] if target else ["git", "restore", "."]
        res = subprocess.run(cmd, capture_output=True, text=True)
        print_status("Perubahan dibatalkan.", "info")

    elif act == "status":
        res = subprocess.run(["git", "status", "-s"], capture_output=True, text=True)
        print(res.stdout if res.stdout else "Clean working tree.")


def menu_undo_patch(cli: Any) -> None:
    """Interactive rollback selection from transactional patch history."""
    if not hasattr(cli, "patch_manager") or cli.patch_manager is None:
        from alfa.core.cli.agent_engine import PatchHistoryManager

        cli.patch_manager = PatchHistoryManager()

    patches = cli.patch_manager.list_patches()
    if not patches:
        print_status("Belum ada riwayat patch untuk di-rollback.", "info")
        return

    choices = [
        Choice("latest", f"↩️  Batalkan Perubahan Terakhir (#{patches[-1].id}: {patches[-1].filepath})"),
        Separator(),
    ]
    for p in reversed(patches[-15:]):
        choices.append(Choice(str(p.id), f"#{p.id} [{p.timestamp}] {p.filepath} ({p.summary})"))
    choices.append(Separator())
    choices.append(Choice("back", "⬅️  Kembali"))

    sel = inquirer.select(
        message="Pilih Patch untuk Rollback:",
        choices=choices,
    ).execute()

    if sel == "back" or not sel:
        return
    elif sel == "latest":
        success, msg = cli.patch_manager.rollback_latest()
        print_status(msg, "success" if success else "error")
    elif sel.isdigit():
        success, msg = cli.patch_manager.rollback_patch(int(sel))
        print_status(msg, "success" if success else "error")


def menu_switch_persona(cli: Any) -> None:
    """Interactive arrow-key selector for Swarm & Custom Agents (synchronized with Web)."""
    from alfa.core import database

    agents = []
    try:
        agents = database.list_custom_agents_sync()
    except Exception:
        pass

    if not agents:
        print_status("Belum ada custom agent di database. Kunjungi Web Dashboard di http://localhost:8080/agents.", "warning")
        return

    active_name = getattr(cli, "active_persona_name", None)
    choices = [
        Choice("reset", f"👑 Default ALFA Orchestrator{' (aktif)' if not active_name else ''}"),
        Separator(),
    ]

    for a in agents:
        name = a.get("name", "Unknown")
        role = a.get("role", "-")
        avatar = a.get("avatar_emoji", "🤖")
        prov = a.get("provider", "-")
        mod = a.get("model", "-")
        is_curr = " (aktif)" if name == active_name else ""
        label = f"{avatar} {name} - {role} [{prov}/{mod}]{is_curr}"
        choices.append(Choice(str(a.get("id")), label))

    choices.append(Separator())
    choices.append(Choice("back", "⬅️  Kembali"))

    sel = inquirer.select(
        message="Pilih Persona Swarm / Custom Agent:",
        choices=choices,
    ).execute()

    if sel == "back" or not sel:
        return
    elif sel == "reset":
        cli.do_slash_persona("reset")
    else:
        cli.do_slash_persona(sel)


def menu_manage_servers(cli: Any) -> None:
    """Interactive management for ALFA background ecosystem servers."""
    from alfa.core.cli.server_manager import (
        get_servers_status,
    )

    statuses = get_servers_status()
    dash = statuses["dashboard"]
    r9 = statuses["9router"]
    bot = statuses["bot"]

    print(f"\n{Colors.BOLD}🌐 Status Server Ekosistem ALFA Saat Ini:{Colors.ENDC}")
    print(f"  {'🟢' if dash['ok'] else '🔴'} Web Command Center : {Colors.CYAN}{dash['status']}{Colors.ENDC}")
    print(f"  {'🔀' if r9['ok'] else '⚪'} 9Router AI Gateway : {Colors.CYAN}{r9['status']}{Colors.ENDC}")
    print(f"  {'🤖' if bot['ok'] else '⚪'} Telegram AI Bot    : {Colors.CYAN}{bot['status']}{Colors.ENDC}\n")

    choices = [
        Choice("start", "🟢 Nyalakan / Pastikan Semua Server Aktif"),
        Choice("restart", "🔄 Restart Semua Server Ekosistem"),
        Choice("stop", "⏹️  Hentikan Semua Server Latar Belakang"),
        Choice("browser", "🌐 Buka Web Command Center di Browser (http://localhost:8080)"),
        Separator(),
        Choice("back", "⬅️  Kembali"),
    ]

    action = inquirer.select(
        message="Pilih Aksi Server Ekosistem:",
        choices=choices,
    ).execute()

    if action == "start":
        cli.do_slash_servers("start")
    elif action == "restart":
        cli.do_slash_servers("restart")
    elif action == "stop":
        cli.do_slash_servers("stop")
    elif action == "browser":
        import webbrowser
        webbrowser.open("http://localhost:8080")
        print_status("Membuka browser ke http://localhost:8080...", "success")


def menu_switch_agent_execution_mode(cli: Any) -> None:
    """Interactive selector to switch between Single Agent and Swarm Multi-Agent mode."""
    curr_mode = getattr(cli, "agent_execution_mode", "single")

    choices = [
        Choice("single", f"⚡ Single Agent Mode  - 1 Autonomous ReAct Agent Cepat & Berfokus{' (AKTIF)' if curr_mode == 'single' else ''}"),
        Choice("swarm",  f"🐝 Swarm Multi-Agent - Kolaborasi Seluruh Tim Spesialis (Planner, Coder, QA, Security){' (AKTIF)' if curr_mode == 'swarm' else ''}"),
        Separator(),
        Choice("back", "⬅️  Kembali"),
    ]

    sel = inquirer.select(
        message="Pilih Mode Eksekusi Agen:",
        choices=choices,
        default=curr_mode,
    ).execute()

    if sel == "back" or not sel:
        return

    cli.agent_execution_mode = sel
    cli.config["agent_execution_mode"] = sel
    cli._save_config()
    cli._update_prompt()

    label = "SINGLE AGENT (Autonomous ReAct)" if sel == "single" else "SWARM MULTI-AGENT (Kolaboratif)"
    print_status(f"Mode eksekusi agen berhasil diubah ke: {label}", "success")


def menu_configure_agent_models(cli: Any) -> None:
    """Interactive selector to set AI provider and model for each individual swarm agent."""
    from alfa.core import database

    agents = []
    try:
        agents = database.list_custom_agents_sync()
    except Exception:
        pass

    if not agents:
        print_status("Belum ada agent di database. Kunjungi Web Dashboard di http://localhost:8080/agents.", "warning")
        return

    try:
        sync_providers_catalog()
    except Exception:
        pass

    agent_choices = []
    for a in agents:
        aid = a.get("id")
        name = a.get("name", "Unknown")
        role = a.get("role", "-")
        avatar = a.get("avatar_emoji", "🤖")
        prov = a.get("provider", "-")
        mod = a.get("model", "-")
        label = f"{avatar} #{aid} {name:<20} | {role:<25} | [{prov}/{mod}]"
        agent_choices.append(Choice(str(aid), label))

    agent_choices.append(Separator())
    agent_choices.append(Choice("back", "⬅️  Kembali"))

    selected_agent_id = inquirer.select(
        message="Pilih Agen Swarm yang Ingin Diatur Model AI-nya:",
        choices=agent_choices,
    ).execute()

    if selected_agent_id == "back" or not selected_agent_id:
        return

    matched_agent = next((a for a in agents if str(a.get("id")) == str(selected_agent_id)), None)
    if not matched_agent:
        return

    primary_order = [
        "9router", "google", "deepseek", "nvidia", "qwen",
        "openrouter", "antigravity", "openai", "anthropic", "minimax", "moonshot", "groq", "ollama"
    ]
    prov_choices = []
    curr_prov = matched_agent.get("provider", "google")
    for pkey in primary_order:
        if pkey not in PROVIDERS_CATALOG:
            continue
        pinfo = PROVIDERS_CATALOG[pkey]
        is_curr = " (saat ini)" if normalize_provider(pkey) == normalize_provider(curr_prov) else ""
        prov_choices.append(Choice(pkey, f"{pinfo['name']:<25} ({pkey}){is_curr}"))

    prov_choices.append(Separator())
    prov_choices.append(Choice("back", "⬅️  Batal"))

    selected_provider = inquirer.select(
        message=f"Pilih AI Provider untuk {matched_agent.get('avatar_emoji', '🤖')} {matched_agent.get('name')}:",
        choices=prov_choices,
        default=curr_prov if curr_prov in primary_order else "google",
    ).execute()

    if selected_provider == "back" or not selected_provider:
        return

    cat = PROVIDERS_CATALOG.get(selected_provider, {})
    model_list = cat.get("models", [])
    curr_mod = matched_agent.get("model", "")
    model_choices = []
    for m in model_list:
        is_m_curr = " (aktif)" if m == curr_mod else ""
        model_choices.append(Choice(m, f"{m}{is_m_curr}"))
    model_choices.append(Choice("__custom__", "✍️ Masukkan nama model custom..."))
    model_choices.append(Separator())
    model_choices.append(Choice("back", "⬅️  Batal"))

    selected_model = inquirer.select(
        message=f"Pilih Model AI ({selected_provider.upper()}):",
        choices=model_choices,
        default=curr_mod if curr_mod in model_list else (model_list[0] if model_list else None),
    ).execute()

    if selected_model == "back" or not selected_model:
        return

    if selected_model == "__custom__":
        selected_model = inquirer.text(
            message="Ketik nama model AI spesifik:",
            validate=lambda text: len(text.strip()) > 0 or "Nama model tidak boleh kosong.",
        ).execute().strip()

    try:
        res = database.update_custom_agent_sync(
            int(selected_agent_id),
            {"provider": selected_provider, "model": selected_model},
        )
        if res.get("status") == "success":
            print_status(
                f"Model AI untuk {matched_agent.get('avatar_emoji', '🤖')} {matched_agent.get('name')} "
                f"berhasil diubah ke: {selected_provider.upper()} / {selected_model}",
                "success",
            )
            if getattr(cli, "active_persona_name", None) == matched_agent.get("name"):
                if hasattr(cli, "direct_ai") and cli.direct_ai:
                    cli.direct_ai.set_provider(selected_provider, selected_model)
                    cli._update_prompt()
        else:
            print_status(f"Gagal memperbarui model agen: {res.get('message')}", "error")
    except Exception as err:
        print_status(f"Error update agent database: {err}", "error")


def open_interactive_menu(cli: Any) -> None:
    """Launch the main interactive menu palette (like Cursor/OpenCode/Qwen)."""
    direct = cli.direct_ai

    while True:
        agent_active = getattr(cli, "agent_mode", True)
        agent_label = "🟢 AKTIF (ReAct + Tools)" if agent_active else "⚪ NON-AKTIF (Direct Chat)"
        exec_mode = getattr(cli, "agent_execution_mode", "single")
        exec_label = "⚡ Single Agent" if exec_mode == "single" else "🐝 Swarm Multi-Agent"
        active_persona = getattr(cli, "active_persona_name", None) or "Default Orchestrator"

        menu_choices = [
            Choice("exec_mode", f"🔀 Mode Agen: Single vs Swarm (Saat ini: {exec_label})"),
            Choice("swarm_models", "⚙️ Atur Model AI per Agen Swarm (Custom Models)"),
            Choice("agent", f"🤖 Toggle Agent Tools (Saat ini: {agent_label})"),
            Choice("persona", f"👥 Ganti Persona Swarm (Saat ini: {active_persona})"),
            Choice("servers", "🚀 Status & Kelola Server Ekosistem (Dashboard, 9Router, Bot)"),
            Choice("repomap", "🗺️  Peta Arsitektur Proyek (Repomap)"),
            Choice("tools", "🛠️  Lihat Tools Tersedia (Developer & Web Ecosystem)"),
            Choice("undo", "↩️  Rollback Patch / Undo Riwayat Perubahan File"),
            Choice("model", f"🧠 Switch Model & Provider Utama (Saat ini: {direct.provider.upper()}/{direct.model})"),
            Choice("files", f"📁 Pilih Konteks File Proyek ({len(getattr(cli, 'attached_files', []))} terpilih)"),
            Choice("preset", "⚡ Pilih Preset Respon (Coding, Smart, Fast, Creative)"),
            Choice("mode", f"🧭 Ganti Mode Koneksi (Saat ini: {cli.mode.upper()})"),
            Choice("keys", "🔑 Kelola API Keys (NVIDIA NIM, Google, OpenAI, dll)"),
            Choice("git", "🌿 Git Actions (Diff, Commit, Undo)"),
            Choice("stats", "📊 Lihat Status Sistem & Konfigurasi"),
            Choice("clear", "🧹 Bersihkan Riwayat Chat"),
            Separator(),
            Choice("exit", "⬅️  Kembali ke Sesi Chat"),
        ]

        action = inquirer.select(
            message="📋 ALFA Command Palette & Interactive Menu:",
            choices=menu_choices,
        ).execute()

        if action == "exec_mode":
            menu_switch_agent_execution_mode(cli)
        elif action == "swarm_models":
            menu_configure_agent_models(cli)
        elif action == "agent":
            cli.agent_mode = not getattr(cli, "agent_mode", True)
            cli.config["agent_mode"] = cli.agent_mode
            cli._save_config()
            new_state = "AKTIF (ReAct + Tools)" if cli.agent_mode else "NON-AKTIF (Direct Chat)"
            print_status(f"Autonomous Agent Mode sekarang: {new_state}", "success")
        elif action == "persona":
            menu_switch_persona(cli)
        elif action == "servers":
            menu_manage_servers(cli)
        elif action == "repomap":
            cli.do_slash_repomap("")
        elif action == "tools":
            cli.do_slash_tools("")
        elif action == "undo":
            menu_undo_patch(cli)
        elif action == "model":
            menu_switch_model(cli)
        elif action == "files":
            menu_manage_context_files(cli)
        elif action == "preset":
            menu_switch_preset(cli)
        elif action == "mode":
            menu_switch_mode(cli)
        elif action == "keys":
            menu_setup_api_keys(cli)
        elif action == "git":
            menu_git_actions(cli)
        elif action == "stats":
            cli.do_stats("")
            cli.do_slash_provider("")
        elif action == "clear":
            cli.chat_history.clear()
            print_status("Riwayat chat dibersihkan.", "success")
        elif action == "exit" or not action:
            break

