"""Slash-command mixin: session resume, clipboard copy, project init, AI commit message, local stats."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from alfa.core.cli.constants import Colors, print_status


class SlashExtrasMixin:
    """Modern AI-CLI conveniences: /resume, /copy, /init, /commitmsg, local /stats."""

    config: dict[str, Any]
    chat_history: list[dict[str, str]]
    direct_ai: Any

    def do_slash_resume(self, arg: str) -> None:
        """Lanjutkan sesi terakhir. Usage: /resume [nama_sesi]"""
        from alfa.core.cli.session_store import LAST_SESSION_NAME, SessionStore

        name = arg.strip() or LAST_SESSION_NAME
        data = SessionStore().load(name)
        if not data:
            print_status(f"Sesi '{name}' tidak ditemukan.", "error")
            return
        history = data.get("chat_history", [])
        self.chat_history = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in history
            if isinstance(m, dict)
        ]
        extra = data.get("extra", {}) or {}
        if "agent_mode" in extra:
            self.agent_mode = bool(extra["agent_mode"])
        if "agent_execution_mode" in extra:
            self.agent_execution_mode = str(extra["agent_execution_mode"])
        print_status(
            f"✅ Sesi '{name}' dilanjutkan ({len(self.chat_history)} pesan, workspace: {data.get('workspace', '-')}).",
            "success",
        )

    def do_slash_copy(self, arg: str) -> None:
        """Salin jawaban terakhir ke clipboard. Usage: /copy [n]"""
        index = int(arg.strip()) if arg.strip().isdigit() else 1
        assistant_msgs = [
            m for m in self.chat_history if m.get("role") == "assistant"
        ]
        if not assistant_msgs:
            print_status("Belum ada jawaban untuk disalin.", "warning")
            return
        target = assistant_msgs[-index] if index <= len(assistant_msgs) else None
        if target is None:
            print_status(f"Jawaban ke-{index} tidak ditemukan.", "warning")
            return
        text = target.get("content", "")
        ok = self._copy_to_clipboard(text)
        if ok:
            print_status(f"📋 {len(text)} karakter disalin ke clipboard.", "success")
        else:
            print_status(
                "Clipboard tidak tersedia. Install xclip/xsel atau jalankan di desktop.",
                "error",
            )

    def _copy_to_clipboard(self, text: str) -> bool:
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["wl-copy"]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
                    return True
                except Exception:
                    continue
        try:
            import pyperclip

            pyperclip.copy(text)
            return True
        except Exception:
            return False

    def do_slash_init(self, arg: str) -> None:
        """Generate ALFA.md dari struktur proyek. Usage: /init [--force]"""
        target = Path.cwd() / "ALFA.md"
        if target.exists() and "--force" not in arg:
            print_status(
                "ALFA.md sudah ada. Gunakan /init --force untuk menimpa.", "warning"
            )
            return
        print_status("🔍 Menganalisis proyek...", "info")
        try:
            repomap = getattr(self, "repomap_gen", None)
            if repomap is None:
                from alfa.core.cli.agent_engine.repomap import RepomapGenerator

                repomap = RepomapGenerator(Path.cwd())
            structure = repomap.generate_repomap() if hasattr(repomap, "generate_repomap") else ""
        except Exception:
            structure = ""

        files = []
        try:
            for p in sorted(Path.cwd().iterdir()):
                if p.name.startswith(".") or p.name in ("node_modules", "__pycache__", "venv"):
                    continue
                files.append(f"- {p.name}{'/' if p.is_dir() else ''}")
        except Exception:
            pass

        content = f"""# {Path.cwd().name}

## Struktur Direktori
{chr(10).join(files[:50]) if files else '- (kosong)'}

## Peta Repo (ringkas)
```
{str(structure)[:3000]}
```

## Catatan Pengembangan
- Tambahkan konvensi coding, cara menjalankan test, dan arsitektur di sini.
"""
        try:
            target.write_text(content, encoding="utf-8")
            print_status(f"✅ ALFA.md dibuat di {target}", "success")
        except Exception as e:
            print_status(f"Gagal menulis ALFA.md: {e}", "error")

    def do_slash_commitmsg(self, arg: str) -> None:
        """Generate commit message AI dari git diff lalu commit. Usage: /commitmsg"""
        try:
            diff = subprocess.run(
                ["git", "diff", "--cached"], capture_output=True, text=True, timeout=10
            ).stdout
            if not diff.strip():
                diff = subprocess.run(
                    ["git", "diff"], capture_output=True, text=True, timeout=10
                ).stdout
            if not diff.strip():
                print_status("Tidak ada perubahan untuk di-commit.", "info")
                return
        except Exception as e:
            print_status(f"Gagal membaca git diff: {e}", "error")
            return

        print_status("✍️ Membuat commit message...", "info")
        try:
            msg = self.direct_ai.generate(
                prompt=(
                    "Buatkan commit message git (format Conventional Commits, maks 72 karakter "
                    "baris pertama, lalu penjelasan singkat) untuk diff berikut:\n\n"
                    + diff[:6000]
                ),
                stream=False,
            ).strip()
        except Exception as e:
            print_status(f"Gagal generate pesan: {e}", "error")
            return

        print(f"\n{Colors.BOLD}Pesan commit:{Colors.ENDC}\n{msg}\n")
        ans = input("Commit dengan pesan ini? [Y/n]: ").strip().lower()
        if ans in ("", "y", "yes"):
            res = subprocess.run(
                ["git", "commit", "-am", msg], capture_output=True, text=True
            )
            print(res.stdout if res.stdout else res.stderr)
        else:
            print_status("Commit dibatalkan.", "info")

    def do_slash_stats(self, arg: str) -> None:  # type: ignore[override]
        """Statistik sesi lokal (atau server jika login). Usage: /stats"""
        if getattr(self, "session_token", None):
            try:
                return super().do_slash_stats(arg)  # type: ignore[misc]
            except AttributeError:
                pass

        started = getattr(self, "_session_start", None)
        duration = f"{int(time.time() - started)} detik" if started else "-"
        messages = len(getattr(self, "chat_history", []))
        user_msgs = sum(1 for m in self.chat_history if m.get("role") == "user")
        chars = sum(len(str(m.get("content", ""))) for m in self.chat_history)
        print(f"\n{Colors.BOLD}📊 Statistik Sesi Lokal{Colors.ENDC}")
        print(f"  • Durasi        : {duration}")
        print(f"  • Pesan total   : {messages} ({user_msgs} dari user)")
        print(f"  • Total karakter: {chars:,}")
        print(f"  • Mode          : {getattr(self, 'mode', '-')}")
        print(f"  • Provider/Model: {getattr(self.direct_ai, 'provider', '-')}/{getattr(self.direct_ai, 'model', '-')}\n")
