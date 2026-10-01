"""Interactive menu dispatcher (open_interactive_menu)."""

from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from alfa.core.cli.constants import print_status
from alfa.core.cli.menu.agents import menu_configure_agent_models, menu_switch_persona
from alfa.core.cli.menu.files_ctx import menu_manage_context_files
from alfa.core.cli.menu.models import (
    menu_setup_api_keys,
    menu_switch_model,
    menu_switch_preset,
)
from alfa.core.cli.menu.modes import menu_switch_agent_execution_mode, menu_switch_mode
from alfa.core.cli.menu.ops import (
    menu_git_actions,
    menu_manage_servers,
    menu_undo_patch,
)


def open_interactive_menu(cli: Any) -> None:
    """Launch the main interactive menu palette (like Cursor/OpenCode/Qwen)."""
    direct = cli.direct_ai

    while True:
        agent_active = getattr(cli, "agent_mode", True)
        agent_label = (
            "🟢 AKTIF (ReAct + Tools)" if agent_active else "⚪ NON-AKTIF (Direct Chat)"
        )
        exec_mode = getattr(cli, "agent_execution_mode", "single")
        exec_label = (
            "⚡ Single Agent" if exec_mode == "single" else "🐝 Swarm Multi-Agent"
        )
        active_persona = (
            getattr(cli, "active_persona_name", None) or "Default Orchestrator"
        )

        menu_choices = [
            Choice(
                "exec_mode", f"🔀 Mode Agen: Single vs Swarm (Saat ini: {exec_label})"
            ),
            Choice("swarm_models", "⚙️ Atur Model AI per Agen Swarm (Custom Models)"),
            Choice("agent", f"🤖 Toggle Agent Tools (Saat ini: {agent_label})"),
            Choice("persona", f"👥 Ganti Persona Swarm (Saat ini: {active_persona})"),
            Choice(
                "servers",
                "🚀 Status & Kelola Server Ekosistem (Dashboard, 9Router, Bot)",
            ),
            Choice("repomap", "🗺️  Peta Arsitektur Proyek (Repomap)"),
            Choice("tools", "🛠️  Lihat Tools Tersedia (Developer & Web Ecosystem)"),
            Choice("undo", "↩️  Rollback Patch / Undo Riwayat Perubahan File"),
            Choice(
                "model",
                f"🧠 Switch Model & Provider Utama (Saat ini: {direct.provider.upper()}/{direct.model})",
            ),
            Choice(
                "files",
                f"📁 Pilih Konteks File Proyek ({len(getattr(cli, 'attached_files', []))} terpilih)",
            ),
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
            new_state = (
                "AKTIF (ReAct + Tools)" if cli.agent_mode else "NON-AKTIF (Direct Chat)"
            )
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
