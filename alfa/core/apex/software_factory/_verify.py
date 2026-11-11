"""Verifikasi E2E: smoke test HTTP, audit, dan validasi perintah test."""
from __future__ import annotations

import functools
import http.server
import logging
import os
import re
import shlex
import socketserver
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from alfa.core.apex.software_factory._audit import (
    _audit_html_files,
    _audit_python_files,
)
from alfa.core.apex.software_factory._heal import _pick_entrypoint

logger = logging.getLogger(__name__)


class _ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

_HTTP_ERR = (OSError, ValueError, UnicodeDecodeError)

_DANGEROUS_PROGRAMS = {
    "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish", "eval", "exec", "xargs",
    "cmd", "cmd.exe", "powershell", "pwsh", "wmic",
}

_DANGEROUS_TOKENS = (
    "rm -rf", "rm -fr", "rm -r -f", "rm -f -r", "rm -rf/", "mkfs", "dd if=", ":(){",
    "shutdown", "reboot", "halt", "poweroff", "init 0", "init 6", "systemctl",
    "kill -9 1", "killall -9", "truncate -s 0", "chown -r /", "chmod -r 777 /",
    "chmod 777 /", "userdel", "iptables", "insmod", "modprobe", "wa-sheets-bot",
    "> /dev/sd", "/dev/sda", "/dev/sdb",
)

def _run_live_http_smoke_test(app_dir: str, entry_rel: str = "index.html") -> dict[str, Any]:
    """
    Spin up an ephemeral local HTTP server on a free OS port, perform a real HTTP GET
    request against the given entrypoint, verify HTTP 200 + non-empty DOM payload, and tear down.
    """
    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

    handler_cls = functools.partial(_QuietHandler, directory=app_dir)
    rel_path = entry_rel.lstrip("/") or "index.html"
    url_path = urllib.parse.quote(rel_path)
    try:
        with _ReuseTCPServer(("127.0.0.1", 0), handler_cls) as httpd:
            port = httpd.server_address[1]
            worker = threading.Thread(target=httpd.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{port}/{url_path}"
                try:
                    with urllib.request.urlopen(url, timeout=2.5) as resp:  # noqa: S310  # nosec B310 - server lokal ephemeral
                        status_code = resp.status
                        body = resp.read().decode("utf-8", errors="ignore")
                except urllib.error.HTTPError as exc:
                    status_code = exc.code
                    try:
                        body = exc.read().decode("utf-8", errors="ignore")
                    except _HTTP_ERR:  # pragma: no cover - defensive
                        body = ""
                return {
                    "passed": status_code == 200 and len(body) > 20,
                    "http_status": status_code,
                    "bytes_received": len(body),
                    "ephemeral_port_tested": port,
                    "entrypoint": rel_path,
                }
            finally:
                httpd.shutdown()
                worker.join(timeout=3)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as exc:  # noqa: BLE001 - pipeline build multi-langkah
        return {
            "passed": False,
            "http_status": 0,
            "bytes_received": 0,
            "error": str(exc),
            "entrypoint": rel_path,
        }

def verify_fullstack_project_e2e(app_dir: str) -> dict[str, Any]:
    """
    Run the 4-Stage Devin-Style E2E Verification Gate (including Live HTTP Smoke Test).

    Fail-closed: the live HTTP stage is mandatory whenever the project ships any HTML, and a
    stage that could not run is recorded as an issue (never as a silent pass).
    """
    empty_smoke: dict[str, Any] = {"passed": False, "http_status": 0, "bytes_received": 0}
    if not app_dir or not os.path.isdir(app_dir):
        return {
            "status": "error",
            "e2e_score": 0,
            "issues": [f"Directory not found: {app_dir}"],
            "passed_checks": [],
            "live_http_smoke": dict(empty_smoke),
            "stages": {"backend_ast": "skipped", "frontend_dom": "skipped", "live_http": "skipped"},
        }

    issues: list[str] = []
    passed_checks: list[str] = []
    score_box = [100]
    stages: dict[str, str] = {}

    # ---- Stage 1: Backend Python AST Verification (recursive) ----
    _audit_python_files(app_dir, issues, passed_checks, score_box)
    stages["backend_ast"] = "passed" if not issues else "failed"

    # ---- Stage 2: Frontend HTML/DOM & Interactive Elements Verification (recursive) ----
    _audit_html_files(app_dir, issues, passed_checks, score_box)
    stages["frontend_dom"] = "passed" if not issues else "failed"

    # ---- Stage 3: Live HTTP Server Smoke Test (mandatory when HTML exists) ----
    http_test: dict[str, Any] = dict(empty_smoke)
    entry = _pick_entrypoint(app_dir)
    if entry:
        entry_rel = os.path.relpath(entry, app_dir)
        http_test = _run_live_http_smoke_test(app_dir, entry_rel)
        if http_test.get("passed"):
            passed_checks.append(
                f"Live HTTP 200 OK Smoke Test Passed ({http_test.get('bytes_received')} bytes on port "
                f"{http_test.get('ephemeral_port_tested')})"
            )
            stages["live_http"] = "passed"
        else:
            issues.append(
                f"Live HTTP Smoke Test failed for '{entry_rel}': status={http_test.get('http_status')} "
                f"{http_test.get('error', '')}".strip()
            )
            score_box[0] -= 30
            stages["live_http"] = "failed"
    else:
        issues.append("No HTML frontend entrypoint found — live HTTP smoke test could not run.")
        score_box[0] -= 35
        stages["live_http"] = "skipped"

    score = max(0, min(100, score_box[0]))
    ver_status = "PRODUCTION_READY" if score >= 85 and not issues else "NEEDS_REPAIR"

    return {
        "status": ver_status,
        "e2e_score": score,
        "passed_checks": passed_checks,
        "issues": issues,
        "live_http_smoke": http_test,
        "stages": stages,
    }

def _restore_backups(backups: dict[str, str | None]) -> None:
    """Restore every snapshotted file. Never raises — a failed restore is logged, not fatal."""
    for target_p, prev_content in backups.items():
        try:
            if prev_content is None:
                if os.path.exists(target_p):
                    os.remove(target_p)
            else:
                with open(target_p, "w", encoding="utf-8") as rf:
                    rf.write(prev_content)
        except OSError as exc:
            logger.error("Rollback failed for %s: %s", target_p, exc)

def _validate_test_command(test_command: str) -> dict[str, Any]:
    """
    Validate a user/LLM supplied `test_command`.

    The command is executed with `shell=False`, so shell metacharacters cannot chain commands.
    This validator additionally refuses shell interpreters and destructive fragments.
    """
    raw = test_command.strip()
    if not raw:
        return {"ok": False, "error": "Blocked unsafe test_command: empty command."}

    normalized = re.sub(r"\s+", " ", raw.lower())
    for token in _DANGEROUS_TOKENS:
        if token in normalized:
            return {"ok": False, "error": f"Blocked unsafe test_command: contains {token!r}."}

    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        return {"ok": False, "error": f"Blocked unsafe test_command: cannot parse ({exc})."}

    if not argv:
        return {"ok": False, "error": "Blocked unsafe test_command: empty command."}

    program = os.path.basename(argv[0]).lower()
    if program in _DANGEROUS_PROGRAMS:
        return {
            "ok": False,
            "error": f"Blocked unsafe test_command: shell interpreter {program!r} is not allowed.",
        }

    return {"ok": True, "argv": argv}
