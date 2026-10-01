"""Slash-command mixin: AI provider, model, and settings commands."""

from typing import Any

from alfa.core.cli.constants import Colors, print_status
from alfa.core.cli.direct_ai import PRESETS, PROVIDERS_CATALOG


class SlashProvidersMixin:
    """AI provider, model, and settings commands."""

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
            print(
                f"  {Colors.CYAN}Active Mode:{Colors.ENDC} {getattr(self, 'mode', 'auto')}"
            )
            print(
                f"  {Colors.CYAN}Provider:{Colors.ENDC}    {prov} ({PROVIDERS_CATALOG.get(prov, {}).get('name', prov)})"
            )
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
            print_status(
                f"Provider tidak valid. Pilihan: {', '.join(canonical_providers)}",
                "error",
            )
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

        print_status(
            f"Provider diubah ke: {provider.upper()} ({PROVIDERS_CATALOG[provider]['name']})",
            "success",
        )
        if model_name or (hasattr(self, "direct_ai") and self.direct_ai.model):
            active_m = model_name or self.direct_ai.model
            print_status(f"Model: {active_m}", "info")

    def do_slash_settings(self, arg: str) -> None:
        """Atur parameter AI. Usage: /settings temperature=0.7 max_tokens=4096"""
        if not arg:
            direct = getattr(self, "direct_ai", None)
            print(f"\n{Colors.BOLD}⚙️ Parameter AI Saat Ini:{Colors.ENDC}")
            print(
                f"  {Colors.CYAN}temperature:{Colors.ENDC} {getattr(direct, 'temperature', 0.7)}"
            )
            print(
                f"  {Colors.CYAN}max_tokens:{Colors.ENDC}  {getattr(direct, 'max_tokens', 4096)}"
            )
            print(
                "\n💡 Tips: Gunakan '/settings temperature=0.5 max_tokens=2048' untuk mengubah\n"
            )
            return

        settings: dict[str, Any] = {}
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
                print(
                    f"  {Colors.GREEN}/switch {name:<8}{Colors.ENDC} : {cfg['description']} (temp: {cfg['temperature']})"
                )
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
        print_status(
            f"Temperature: {p['temperature']} | Max Tokens: {p['max_tokens']}", "info"
        )

    def do_slash_models(self, arg: str) -> None:
        """Lihat model AI yang didukung. Usage: /models"""
        print(f"\n{Colors.BOLD}🧠 Model AI Katalog (Multi-Provider):{Colors.ENDC}\n")
        for pkey, pinfo in PROVIDERS_CATALOG.items():
            is_active = (
                (getattr(self.direct_ai, "provider", "") == pkey)
                if hasattr(self, "direct_ai")
                else False
            )
            mark = f" {Colors.WARNING}(ACTIVE){Colors.ENDC}" if is_active else ""
            print(f"  {Colors.CYAN}{pinfo['name']}{mark}:{Colors.ENDC}")
            for m in pinfo["models"]:
                print(f"    • {Colors.GREEN}{m}{Colors.ENDC}")
        print()
