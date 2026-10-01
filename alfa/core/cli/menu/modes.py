"""Mode-switching menus."""

from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from alfa.core.cli.constants import print_status


def menu_switch_mode(cli: Any) -> None:
    """Interactive execution mode switcher."""
    curr_mode = getattr(cli, "mode", "auto")
    choices = [
        Choice(
            "auto",
            f"Auto        - Coba Server ALFA, otomatis fallback ke Standalone{' (aktif)' if curr_mode == 'auto' else ''}",
        ),
        Choice(
            "standalone",
            f"Standalone  - Langsung panggil API LLM (Google, NVIDIA, etc) tanpa server{' (aktif)' if curr_mode == 'standalone' else ''}",
        ),
        Choice(
            "server",
            f"Server      - Wajib terhubung ke server backend ALFA Sovereign Swarm{' (aktif)' if curr_mode == 'server' else ''}",
        ),
    ]

    selected_mode = inquirer.select(
        message="Pilih Mode Eksekusi CLI:",
        choices=choices,
        default=curr_mode,
    ).execute()

    if selected_mode:
        cli.do_slash_mode(selected_mode)


def menu_switch_agent_execution_mode(cli: Any) -> None:
    """Interactive selector to switch between Single Agent and Swarm Multi-Agent mode."""
    curr_mode = getattr(cli, "agent_execution_mode", "single")

    choices = [
        Choice(
            "single",
            f"⚡ Single Agent Mode  - 1 Autonomous ReAct Agent Cepat & Berfokus{' (AKTIF)' if curr_mode == 'single' else ''}",
        ),
        Choice(
            "swarm",
            f"🐝 Swarm Multi-Agent - Kolaborasi Seluruh Tim Spesialis (Planner, Coder, QA, Security){' (AKTIF)' if curr_mode == 'swarm' else ''}",
        ),
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

    label = (
        "SINGLE AGENT (Autonomous ReAct)"
        if sel == "single"
        else "SWARM MULTI-AGENT (Kolaboratif)"
    )
    print_status(f"Mode eksekusi agen berhasil diubah ke: {label}", "success")
