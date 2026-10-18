"""Provider/model/preset/API-key menus."""

import os
from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from alfa.core.cli.constants import print_status
from alfa.core.cli.direct_ai import (
    PRESETS,
    PROVIDERS_CATALOG,
    DirectAIClient,
    normalize_provider,
    sync_providers_catalog,
)


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
    model_choices: list[Any] = []
    for m in catalog["models"]:
        is_m_curr = (
            " (aktif)"
            if m == direct.model
            and normalize_provider(selected_provider)
            == normalize_provider(direct.provider)
            else ""
        )
        model_choices.append(Choice(m, f"{m}{is_m_curr}"))
    model_choices.append(Separator())
    model_choices.append(Choice("__custom__", "✍️ Masukkan nama model custom..."))

    selected_model = inquirer.select(
        message=f"Pilih Model untuk {catalog['name']}:",
        choices=model_choices,
        default=direct.model
        if direct.model in catalog["models"]
        else catalog["default_model"],
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


def menu_switch_preset(cli: Any) -> None:
    """Interactive preset switcher."""
    preset_choices = []
    for name, p in PRESETS.items():
        preset_choices.append(
            Choice(
                name,
                f"{name.upper():<10} - {p['description']} (temp: {p['temperature']})",
            )
        )

    chosen = inquirer.select(
        message="Pilih Preset Respon AI:",
        choices=preset_choices,
    ).execute()

    if chosen:
        cli.do_slash_switch(chosen)


def menu_setup_api_keys(cli: Any) -> None:
    """Interactive API Key configuration wizard with Web Vault sync."""
    action = inquirer.select(
        message="Kelola API Keys (Web Vault & CLI):",
        choices=[
            Choice("list", "📋 Lihat Daftar API Key Vault (Web & Database)"),
            Choice(
                "sync", "🔄 Sinkronkan Kunci Otomatis (9Router, CLI, .env ➔ Web Vault)"
            ),
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
                print_status(
                    f"Berhasil menyinkronkan {len(synced)} API key baru ke Web Dashboard Vault!",
                    "success",
                )
            else:
                print_status(
                    "Seluruh API key sudah tersinkronisasi penuh dengan Web Dashboard Vault.",
                    "info",
                )
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
                database.activate_api_key_sync(chosen_id)
                print_status(
                    f"API Key #{chosen_id} berhasil diaktifkan di Web Vault & CLI!",
                    "success",
                )
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

    key_input = (
        inquirer.secret(
            message=f"Masukkan {env_key} untuk {catalog.get('name', chosen_prov)}:",
        )
        .execute()
        .strip()
    )

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
            lines = (
                env_path.read_text(encoding="utf-8").splitlines()
                if env_path.exists()
                else []
            )
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
