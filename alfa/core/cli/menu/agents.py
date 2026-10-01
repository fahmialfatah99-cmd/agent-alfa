"""Persona and agent-model configuration menus."""

from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from alfa.core.cli.constants import print_status
from alfa.core.cli.direct_ai import (
    PROVIDERS_CATALOG,
    normalize_provider,
    sync_providers_catalog,
)


def menu_switch_persona(cli: Any) -> None:
    """Interactive arrow-key selector for Swarm & Custom Agents (synchronized with Web)."""
    from alfa.core import database

    agents = []
    try:
        agents = database.list_custom_agents_sync()
    except Exception:
        pass

    if not agents:
        print_status(
            "Belum ada custom agent di database. Kunjungi Web Dashboard di http://localhost:8080/agents.",
            "warning",
        )
        return

    active_name = getattr(cli, "active_persona_name", None)
    choices = [
        Choice(
            "reset",
            f"👑 Default ALFA Orchestrator{' (aktif)' if not active_name else ''}",
        ),
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


def menu_configure_agent_models(cli: Any) -> None:
    """Interactive selector to set AI provider and model for each individual swarm agent."""
    from alfa.core import database

    agents = []
    try:
        agents = database.list_custom_agents_sync()
    except Exception:
        pass

    if not agents:
        print_status(
            "Belum ada agent di database. Kunjungi Web Dashboard di http://localhost:8080/agents.",
            "warning",
        )
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

    matched_agent = next(
        (a for a in agents if str(a.get("id")) == str(selected_agent_id)), None
    )
    if not matched_agent:
        return

    primary_order = [
        "9router",
        "google",
        "deepseek",
        "nvidia",
        "qwen",
        "openrouter",
        "antigravity",
        "openai",
        "anthropic",
        "minimax",
        "moonshot",
        "groq",
        "ollama",
    ]
    prov_choices = []
    curr_prov = matched_agent.get("provider", "google")
    for pkey in primary_order:
        if pkey not in PROVIDERS_CATALOG:
            continue
        pinfo = PROVIDERS_CATALOG[pkey]
        is_curr = (
            " (saat ini)"
            if normalize_provider(pkey) == normalize_provider(curr_prov)
            else ""
        )
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
        default=curr_mod
        if curr_mod in model_list
        else (model_list[0] if model_list else None),
    ).execute()

    if selected_model == "back" or not selected_model:
        return

    if selected_model == "__custom__":
        selected_model = (
            inquirer.text(
                message="Ketik nama model AI spesifik:",
                validate=lambda text: (
                    len(text.strip()) > 0 or "Nama model tidak boleh kosong."
                ),
            )
            .execute()
            .strip()
        )

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
