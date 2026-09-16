"""Command handlers for ALFA CLI."""

import getpass
import json
import os
import sys

from alfa.core.cli.constants import (
    Colors,
    Console,
    Panel,
    RICH_AVAILABLE,
    print_status,
)

class CliSlashCommandsMixin:
    """Implements advanced slash commands (provider, settings, agents, etc.)."""

    def do_slash_provider(self, arg):
        """Set provider AI. Usage: /provider [openai|anthropic|google|local] [model_name]"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        providers = ['openai', 'anthropic', 'google', 'azure', 'local', 'ollama', 'groq', 'together']
        
        if not arg:
            # Show current provider
            res = self._request("GET", "/api/config/ai")
            if res and res.status_code == 200:
                data = res.json()
                print(f"\n{Colors.BOLD}🤖 Konfigurasi AI Saat Ini:{Colors.ENDC}")
                print(f"  {Colors.CYAN}Provider:{Colors.ENDC} {data.get('provider', 'Not set')}")
                print(f"  {Colors.CYAN}Model:{Colors.ENDC} {data.get('model', 'Not set')}")
                print(f"  {Colors.CYAN}Temperature:{Colors.ENDC} {data.get('temperature', 0.7)}")
                print(f"  {Colors.CYAN}Max Tokens:{Colors.ENDC} {data.get('max_tokens', 4096)}")
                print()
            else:
                print_status("Gagal mengambil konfigurasi AI.", "error")
            return
        
        parts = arg.split()
        if len(parts) < 1:
            print_status("Usage: /provider <provider> [model_name]", "error")
            return
        
        provider = parts[0].lower()
        model_name = parts[1] if len(parts) > 1 else None
        
        if provider not in providers:
            print_status(f"Provider tidak valid. Pilihan: {', '.join(providers)}", "error")
            return
        
        payload = {"provider": provider}
        if model_name:
            payload["model"] = model_name
        
        res = self._request("POST", "/api/config/ai", payload)
        if res and res.status_code == 200:
            data = res.json()
            print_status(f"✅ Provider diubah ke {provider}", "success")
            if model_name:
                print_status(f"   Model: {model_name}", "info")
            if data.get('temperature'):
                print_status(f"   Temperature: {data['temperature']}", "info")
        else:
            print_status(f"Gagal mengubah provider. Pastikan server mendukung endpoint ini.", "error")
    
    def do_slash_settings(self, arg):
        """Advanced AI settings. Usage: /settings temperature=0.7 max_tokens=4096 system_prompt='You are helpful'"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        if not arg:
            # Show all settings
            res = self._request("GET", "/api/config/ai")
            if res and res.status_code == 200:
                data = res.json()
                print(f"\n{Colors.BOLD}⚙️ Advanced AI Settings:{Colors.ENDC}\n")
                for key, value in data.items():
                    print(f"  {Colors.CYAN}{key}:{Colors.ENDC} {value}")
                print("\n💡 Tips: Gunakan /settings key=value untuk mengubah")
                print("   Contoh: /settings temperature=0.5 max_tokens=2048")
                print()
            return
        
        # Parse key=value pairs
        settings = {}
        for pair in arg.split():
            if '=' in pair:
                key, value = pair.split('=', 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                
                # Try to convert to appropriate type
                try:
                    if '.' in value:
                        value = float(value)
                    elif value.isdigit():
                        value = int(value)
                    elif value.lower() in ['true', 'yes']:
                        value = True
                    elif value.lower() in ['false', 'no']:
                        value = False
                except ValueError:
                    pass
                
                settings[key] = value
        
        if not settings:
            print_status("Format tidak valid. Gunakan key=value", "error")
            return
        
        res = self._request("POST", "/api/config/ai", settings)
        if res and res.status_code == 200:
            print_status(f"✅ Settings diperbarui: {', '.join(settings.keys())}", "success")
        else:
            print_status("Gagal memperbarui settings.", "error")
    
    def do_slash_switch(self, arg):
        """Quick switch between presets. Usage: /switch [fast|smart|creative|precise]"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        presets = {
            'fast': {'temperature': 0.3, 'max_tokens': 1024, 'description': 'Fast responses, lower quality'},
            'smart': {'temperature': 0.7, 'max_tokens': 4096, 'description': 'Balanced intelligence'},
            'creative': {'temperature': 0.9, 'max_tokens': 4096, 'description': 'High creativity, more varied'},
            'precise': {'temperature': 0.1, 'max_tokens': 2048, 'description': 'Very precise, deterministic'},
            'coding': {'temperature': 0.2, 'max_tokens': 8192, 'description': 'Optimized for code generation'}
        }
        
        if not arg or arg.lower() not in presets:
            print(f"\n{Colors.BOLD}🎯 Available Presets:{Colors.ENDC}")
            for name, config in presets.items():
                print(f"  {Colors.GREEN}/{name}{Colors.ENDC} - {config['description']}")
            print()
            return
        
        preset = presets[arg.lower()]
        res = self._request("POST", "/api/config/ai", preset)
        if res and res.status_code == 200:
            print_status(f"✅ Switched to '{arg.lower()}' preset", "success")
            print_status(f"   Temperature: {preset['temperature']}, Max Tokens: {preset['max_tokens']}", "info")
        else:
            print_status("Gagal switch preset.", "error")

    def do_slash_models(self, arg):
        """Lihat model AI aktif. Usage: /models"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        res = self._request("GET", "/api/models")
        if res and res.status_code == 200:
            data = res.json()
            models = data if isinstance(data, list) else data.get('models', [])
            print(f"\n{Colors.BOLD}🧠 Model AI Aktif:{Colors.ENDC}\n")
            for model in models:
                name = model.get('name', 'Unknown') if isinstance(model, dict) else str(model)
                status = model.get('status', 'active') if isinstance(model, dict) else 'active'
                print(f"  • {Colors.GREEN}{name}{Colors.ENDC} [{status}]")
            print()
        else:
            print_status("Gagal mengambil info model.", "error")
    
    def do_slash_agents(self, arg):
        """Lihat status swarm agents. Usage: /agents"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        res = self._request("GET", "/api/swarm/status")
        if res and res.status_code == 200:
            data = res.json()
            print(f"\n{Colors.BOLD}🤖 Swarm Agents Status:{Colors.ENDC}\n")
            agents = data.get('agents', [])
            for agent in agents:
                name = agent.get('name', 'Unknown')
                status = agent.get('status', 'idle')
                task = agent.get('current_task', 'No task')
                icon = "🟢" if status == 'active' else "🟡" if status == 'busy' else "⚪"
                print(f"  {icon} {Colors.CYAN}{name}{Colors.ENDC}: {status} - {task}")
            print()
        else:
            print_status("Gagal mengambil status agents.", "error")
    
    def do_slash_upload(self, arg):
        """Upload file. Usage: /upload <filepath>"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        filepath = arg.strip()
        if not filepath:
            filepath = input("Path file: ").strip()
        
        if not os.path.exists(filepath):
            print_status(f"File tidak ditemukan: {filepath}", "error")
            return
        
        try:
            files = {'file': open(filepath, 'rb')}
            res = self._request("POST", "/api/upload", headers={})
            # Note: Need custom request for file upload
            print_status("Fitur upload akan segera hadir.", "info")
        except Exception as e:
            print_status(f"Error upload: {e}", "error")
    
    def do_slash_download(self, arg):
        """Download file. Usage: /download <filename>"""
        if not self.session_token:
            print_status("Login terlebih dahulu.", "warning")
            return
        
        print_status("Fitur download akan segera hadir.", "info")

