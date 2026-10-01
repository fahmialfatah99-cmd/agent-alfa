"""Git, patch-rollback, and server-ops menus."""

from typing import Any

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from alfa.core.cli.constants import Colors, print_status


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
                cli.console.print(
                    Panel(Syntax(res.stdout, "diff", theme="monokai"), title="Git Diff")
                )
            else:
                print(res.stdout)
        else:
            print_status("Tidak ada perubahan uncommitted.", "info")

    elif act == "commit":
        msg = inquirer.text(message="Pesan Commit:").execute().strip()
        if msg:
            res = subprocess.run(
                ["git", "commit", "-am", msg], capture_output=True, text=True
            )
            print(res.stdout if res.stdout else res.stderr)

    elif act == "undo":
        target = (
            inquirer.text(
                message="Nama file yang ingin dibatalkan (Enter untuk semua):"
            )
            .execute()
            .strip()
        )
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
        Choice(
            "latest",
            f"↩️  Batalkan Perubahan Terakhir (#{patches[-1].id}: {patches[-1].filepath})",
        ),
        Separator(),
    ]
    for p in reversed(patches[-15:]):
        choices.append(
            Choice(str(p.id), f"#{p.id} [{p.timestamp}] {p.filepath} ({p.summary})")
        )
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
    print(
        f"  {'🟢' if dash['ok'] else '🔴'} Web Command Center : {Colors.CYAN}{dash['status']}{Colors.ENDC}"
    )
    print(
        f"  {'🔀' if r9['ok'] else '⚪'} 9Router AI Gateway : {Colors.CYAN}{r9['status']}{Colors.ENDC}"
    )
    print(
        f"  {'🤖' if bot['ok'] else '⚪'} Telegram AI Bot    : {Colors.CYAN}{bot['status']}{Colors.ENDC}\n"
    )

    choices = [
        Choice("start", "🟢 Nyalakan / Pastikan Semua Server Aktif"),
        Choice("restart", "🔄 Restart Semua Server Ekosistem"),
        Choice("stop", "⏹️  Hentikan Semua Server Latar Belakang"),
        Choice(
            "browser", "🌐 Buka Web Command Center di Browser (http://localhost:8080)"
        ),
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
