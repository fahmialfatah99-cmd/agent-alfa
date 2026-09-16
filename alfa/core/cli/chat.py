"""Chat interaction loop, streaming handler, and markdown rendering for CLI."""

import json
import sys

from alfa.core.cli.constants import (
    Colors,
    Live,
    Markdown,
    RICH_AVAILABLE,
    Spinner,
    print_status,
)


class CliChatMixin:
    """Handles default prompt input, chat streaming, and rich markdown printing."""

    def default(self, line):
        """Menangani input chat biasa atau slash commands."""
        # Handle slash commands
        if line.startswith('/'):
            parts = line[1:].split(' ', 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ''
            
            # Try to call the corresponding slash command method
            method_name = f'do_slash_{cmd}'
            if hasattr(self, method_name):
                return getattr(self, method_name)(args)
            else:
                print_status(f"Perintah tidak dikenal: {line}", "error")
                print("Ketik /help untuk daftar perintah.", "info")
                return
        
        # Handle regular chat
        if not self.session_token:
            print_status("Anda harus login dulu untuk chatting. Ketik /login atau /register.", "warning")
            return

        message = line.strip()
        if not message:
            return

        # Kirim pesan ke endpoint chat agent
        payload = {"message": message, "stream": self.streaming}
        
        # Show thinking indicator
        if self.streaming:
            print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC} ", end="")
            if RICH_AVAILABLE and self.console:
                with Live(Spinner('dots', text='Thinking...', style='cyan'), refresh_per_second=10) as live:
                    res = self._request("POST", "/api/chat/stream", payload)
                    live.update(Spinner('dots', text='Streaming...', style='green'))
                    
                    if res and res.status_code == 200:
                        # Handle streaming response
                        full_response = ""
                        for chunk in res.iter_lines():
                            if chunk:
                                chunk_data = json.loads(chunk.decode('utf-8'))
                                token = chunk_data.get('token', '')
                                full_response += token
                                print(token, end='', flush=True)
                        print()
                        
                        self.chat_history.append({"role": "user", "content": message})
                        self.chat_history.append({"role": "assistant", "content": full_response})
                    else:
                        print(f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons.")
            else:
                res = self._request("POST", "/api/chat", payload)
                sys.stdout.write("\033[K")
                
                if res and res.status_code == 200:
                    data = res.json()
                    response_text = data.get('response') or data.get('message') or str(data)
                    
                    # Render dengan Rich jika tersedia
                    if RICH_AVAILABLE and self.console and self.config.get('markdown', True):
                        self.console.print(Markdown(response_text))
                    else:
                        print(f"\n{Colors.WHITE}{response_text}{Colors.ENDC}\n")
                    
                    self.chat_history.append({"role": "user", "content": message})
                    self.chat_history.append({"role": "assistant", "content": response_text})
                else:
                    print(f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons dari agen.")
                    if res:
                        try:
                            err = res.json()
                            print(f"Detail: {err}")
                        except:
                            print(f"Status: {res.status_code}")
        else:
            # Non-streaming mode
            print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC} Sedang berpikir...", end="\r")
            
            res = self._request("POST", "/api/chat", payload)
            
            # Hapus baris "Sedang berpikir..."
            sys.stdout.write("\033[K") 

            if res and res.status_code == 200:
                data = res.json()
                response_text = data.get('response') or data.get('message') or str(data)
                
                # Render dengan Rich jika tersedia
                if RICH_AVAILABLE and self.console and self.config.get('markdown', True):
                    print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
                    self.console.print(Markdown(response_text))
                else:
                    print(f"\n{Colors.CYAN}🤖 ALFA:{Colors.ENDC}")
                    print(f"{Colors.WHITE}{response_text}{Colors.ENDC}\n")
                
                # Simpan ke history lokal
                self.chat_history.append({"role": "user", "content": message})
                self.chat_history.append({"role": "assistant", "content": response_text})
            else:
                print(f"\n{Colors.FAIL}❌ Error:{Colors.ENDC} Gagal mendapatkan respons dari agen.")
                if res:
                    try:
                        err = res.json()
                        print(f"Detail: {err}")
                    except:
                        print(f"Status: {res.status_code}")

    def emptyline(self):
        pass

