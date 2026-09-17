"""Network scanning, SSH remote execution, email, and download tools."""

import logging
import os
import socket
import ssl
import subprocess
from typing import Any

from alfa.tools.registry import register_tool
from alfa.tools.system.constants import SANDBOX_DIR

logger = logging.getLogger("AgentTools.System")


@register_tool(category="system")
def scan_local_network() -> dict[str, Any]:
    """
    Scan connected local LAN devices, IP neighbors, and active gateways.
    """
    try:
        res = subprocess.run(
            "ip neigh || arp -a", shell=True, capture_output=True, text=True, timeout=10
        )
        return {
            "status": "success",
            "devices": res.stdout.strip()
            or "Tidak ada perangkat terdeteksi di tabel ARP/Neighbor.",
        }
    except Exception as err:
        return {"status": "error", "message": str(err)}


@register_tool(category="system")
def audit_network_security(
    target_host: str = "127.0.0.1", scan_type: str = "quick_ports"
) -> dict[str, Any]:
    """
    GOD MODE: Network Security & Port Sentinel.
    """
    try:
        result = {"target": target_host, "scan_type": scan_type}

        if target_host in ["127.0.0.1", "localhost", "0.0.0.0"]:
            res_ss = subprocess.run(
                "ss -tuln 2>/dev/null || netstat -tuln 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            listening_lines = [
                ln
                for ln in res_ss.stdout.strip().splitlines()
                if "LISTEN" in ln or "State" in ln
            ][:20]
            result["local_listening_sockets"] = "\n".join(listening_lines)

            res_ufw = subprocess.run(
                "sudo -n ufw status 2>/dev/null || ufw status 2>/dev/null",
                shell=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            result["firewall_status"] = (
                res_ufw.stdout.strip()
                if res_ufw.stdout.strip()
                else "UFW status tidak memerlukan sudo / tidak aktif."
            )
        else:
            common_ports = [21, 22, 25, 80, 443, 3000, 3306, 5432, 8000, 8080, 8443]
            open_ports = []
            for p in common_ports:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                res = s.connect_ex((target_host, p))
                if res == 0:
                    open_ports.append(p)
                s.close()
            result["open_ports_detected"] = open_ports

            if (
                443 in open_ports
                or target_host.startswith("http")
                or "." in target_host
            ):
                try:
                    ctx = ssl.create_default_context()
                    with ctx.wrap_socket(
                        socket.socket(), server_hostname=target_host
                    ) as s:
                        s.settimeout(5)
                        s.connect((target_host, 443))
                        cert = s.getpeercert()
                        not_after = cert.get("notAfter", "")
                        result["ssl_certificate"] = {
                            "subject": dict(x[0] for x in cert.get("subject", ())),
                            "issuer": dict(x[0] for x in cert.get("issuer", ())),
                            "expires_at": not_after,
                            "version": cert.get("version", ""),
                        }
                except Exception as ssl_err:
                    result["ssl_error"] = str(ssl_err)

        return {"status": "success", "audit_report": result}
    except Exception as e:
        return {"status": "error", "message": f"Security audit error: {str(e)}"}


@register_tool(category="system")
def ssh_execute_command(
    host: str, command: str, username: str = "", port: int = 22, key_path: str = ""
) -> dict[str, Any]:
    """
    Execute a command on a remote Linux server via SSH and return the output.
    """
    try:
        import paramiko

        ssh_user = username or os.environ.get("USER", "root")
        ssh_key = (
            os.path.expanduser(key_path)
            if key_path
            else os.path.expanduser("~/.ssh/id_rsa")
        )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": host,
            "port": port,
            "username": ssh_user,
            "timeout": 10,
        }
        if os.path.exists(ssh_key):
            connect_kwargs["key_filename"] = ssh_key

        client.connect(**connect_kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=30)

        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        client.close()

        return {
            "status": "success",
            "host": host,
            "exit_code": exit_code,
            "stdout": out[:8000],
            "stderr": err[:2000] if err else "",
        }
    except Exception as e:
        return {"status": "error", "message": f"SSH error: {str(e)}"}


@register_tool(category="system")
def send_email(
    to: str, subject: str, body: str, attachment_path: str = ""
) -> dict[str, Any]:
    """
    Send an email via SMTP (supports Gmail, Outlook, custom SMTP servers).
    """
    try:
        import smtplib
        from email import encoders
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        smtp_email = os.environ.get("SMTP_EMAIL", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))

        if not smtp_email or not smtp_password:
            return {
                "status": "error",
                "message": "SMTP_EMAIL dan SMTP_PASSWORD belum dikonfigurasi di file .env.",
            }

        msg = MIMEMultipart()
        msg["From"] = smtp_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if attachment_path:
            expanded = os.path.expanduser(attachment_path)
            if os.path.exists(expanded):
                with open(expanded, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(expanded)}",
                    )
                    msg.attach(part)

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, to, msg.as_string())
        server.quit()

        return {
            "status": "success",
            "message": f"Email berhasil dikirim ke {to} dengan subjek '{subject}'.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengirim email: {str(e)}"}


@register_tool(category="system")
def download_file_from_url(url: str, filename: str = "") -> dict[str, Any]:
    """
    Download a file from a URL on the internet to the local computer and optionally send it to Telegram.
    """
    try:
        import httpx

        if not filename:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "downloaded_file"

        dest_path = os.path.join(SANDBOX_DIR, filename)

        with httpx.Client(follow_redirects=True, timeout=60) as client:
            resp = client.get(url)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(resp.content)

        size_mb = os.path.getsize(dest_path) / (1024 * 1024)

        if size_mb > 50:
            return {
                "status": "success",
                "message": f"File '{filename}' ({round(size_mb, 2)} MB) berhasil diunduh ke {dest_path}. Terlalu besar untuk dikirim via Telegram (>50MB), tetapi tersedia di disk lokal.",
                "file_path": dest_path,
                "sent_to_telegram": False,
            }

        return {
            "status": "success",
            "message": f"File '{filename}' ({round(size_mb, 2)} MB) berhasil diunduh dan akan dikirim ke Telegram.",
            "file_path": dest_path,
            "sent_to_telegram": True,
        }
    except Exception as e:
        return {"status": "error", "message": f"Gagal mengunduh: {str(e)}"}
