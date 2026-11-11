"""Kontrol proses bot WA dan daftar upload Google Drive."""
import json
import logging
import os
import subprocess
import time
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Integrations")

@register_tool(category="system")
def manage_wa_sheets_bot(action: str = "status") -> dict[str, Any]:
    """
    ECOSYSTEM INTEGRATION: WhatsApp Google Sheets Bot Controller.
    Controls and monitors the wa-sheets-bot systemd user service.
    Can check status, start, stop, restart, enable auto-start, or view live logs.

    Args:
        action: 'status' (check running state & memory), 'start', 'stop', 'restart', 'logs' (recent 20 lines), 'enable' (enable autostart on boot).
    """
    try:
        act = action.lower().strip()
        svc_name = "wa-sheets-bot.service"

        if act == "status":
            res_active = subprocess.run(
                ["systemctl", "--user", "is-active", svc_name],
                capture_output=True,
                text=True,
            )
            res_enabled = subprocess.run(
                ["systemctl", "--user", "is-enabled", svc_name],
                capture_output=True,
                text=True,
            )
            res_status = subprocess.run(
                ["systemctl", "--user", "status", svc_name, "--no-pager", "-n", "5"],
                capture_output=True,
                text=True,
            )

            is_act = res_active.stdout.strip() == "active"
            return {
                "status": "success",
                "service": svc_name,
                "is_running": is_act,
                "state": res_active.stdout.strip(),
                "enabled_on_boot": res_enabled.stdout.strip() == "enabled",
                "details": res_status.stdout.strip(),
            }

        elif act in ["stop", "restart"]:
            return {
                "status": "error",
                "message": (
                    f"DITOLAK: Tindakan '{act}' pada {svc_name} diblokir oleh kebijakan mutlak "
                    "Perlindungan Sesi WhatsApp (Anti-Logout & Anti-Reset). Sesi login WhatsApp "
                    "wajib dijaga 100% tetap hidup dan tidak boleh diinterupsi."
                ),
            }

        elif act in ["start", "enable", "disable"]:
            res = subprocess.run(
                ["systemctl", "--user", act, svc_name], capture_output=True, text=True
            )
            if res.returncode == 0:
                time.sleep(1)
                res_active = subprocess.run(
                    ["systemctl", "--user", "is-active", svc_name],
                    capture_output=True,
                    text=True,
                )
                return {
                    "status": "success",
                    "message": f"Service '{svc_name}' berhasil di-{act}! Status saat ini: {res_active.stdout.strip()}.",
                    "current_state": res_active.stdout.strip(),
                }
            return {
                "status": "error",
                "message": f"Gagal mengeksekusi {act}: {res.stderr}",
            }

        elif act == "logs":
            res_logs = subprocess.run(
                ["journalctl", "--user", "-u", svc_name, "-n", "25", "--no-pager"],
                capture_output=True,
                text=True,
            )
            return {
                "status": "success",
                "service": svc_name,
                "logs": res_logs.stdout.strip(),
            }

        return {
            "status": "error",
            "message": f"Aksi '{action}' tidak dikenal. Gunakan: status, start, stop, restart, logs, enable.",
        }
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError) as e:
        return {"status": "error", "message": f"Manage wa-sheets-bot error: {str(e)}"}

@register_tool(category="system")
def list_wa_drive_uploads(limit: int = 20) -> dict[str, Any]:
    """
    Daftar berkas (foto/PDF/dokumen) yang otomatis diunggah dari WhatsApp ke Google Drive.

    Args:
        limit: Jumlah maksimal entri terbaru (default 20).
    """
    try:
        path = os.path.expanduser("~/wa-sheets-bot/drive_uploads.json")
        if not os.path.exists(path):
            return {
                "status": "success",
                "total": 0,
                "message": "Belum ada berkas WA yang terunggah ke Drive.",
                "uploads": [],
            }
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        uploads = (data.get("uploads") or [])[: max(1, min(int(limit), 100))]
        compact = [
            {
                "waktu": u.get("ts"),
                "nama_file": u.get("file_name"),
                "folder": u.get("folder"),
                "pengirim": u.get("sender"),
                "grup": u.get("group"),
                "link": u.get("web_link"),
            }
            for u in uploads
        ]
        return {
            "status": "success",
            "total": len(uploads),
            "message": f"{len(uploads)} berkas WA terakhir di Drive.",
            "uploads": compact,
        }
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError) as e:
        return {"status": "error", "message": f"Gagal membaca log unggahan: {str(e)}"}
