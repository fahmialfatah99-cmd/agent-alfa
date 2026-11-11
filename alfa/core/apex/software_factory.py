"""
Autonomous Full-Stack Software Factory & Live HTTP E2E Verifier for ALFA OS (Devin-Grade).

Enables ALFA OS to autonomously scaffold, self-heal, and E2E-verify full-stack web
applications (Backend Python + Frontend HTML/JS/CSS) with a 4-Stage Live Quality Gate:
1. Stage 1: Python Backend AST Syntax & Route Audit (recursive).
2. Stage 2: Frontend HTML/DOM Structural & Interactive Element Audit (with Auto-Repair).
3. Stage 3: Live Ephemeral HTTP Server Spin-Up & Real HTTP 200 OK Smoke Request (mandatory).
4. Stage 4: Automatic Registration into `/sites` (`~/Dokumen/ALFA_SWARM_OUTPUTS/websites/`).

Hardening notes (patch round 1):
- Every stage is fail-closed: a stage that cannot run is reported as a failure, never as a pass.
- Any exception (including subprocess timeouts) triggers the atomic rollback path.
- File I/O is binary-safe: invalid UTF-8 is reported as a diagnostic instead of crashing the gate.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import html as html_lib
import http.server
import json
import logging
import os
import re
import shlex
import socketserver
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("ApexSoftwareFactory")

#: Error realistis per konteks (bukan Exception blanket).
_HTTP_ERR = (OSError, ValueError, UnicodeDecodeError)
_AST_ERR = (ValueError, TypeError, RecursionError, MemoryError)
_DB_ERR = (sqlite3.Error, TypeError, ValueError)
_JSON_ERR = (json.JSONDecodeError, TypeError, ValueError)
_PROC_ERR = (OSError, subprocess.SubprocessError, ValueError)
_REGISTRY_ERR = (
    ImportError,
    AttributeError,
    TypeError,
    ValueError,
    KeyError,
    OSError,
    RuntimeError,
)

# Matches `OUTPUTS_DIR/websites` in `alfa/tools/system/sites.py` so `/sites` sees every build immediately
DEFAULT_FACTORY_SITES_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/websites")

# Hard ceiling for a user-supplied `test_command`.
TEST_COMMAND_TIMEOUT = 30

# Programs that re-introduce a shell (defeats the `shell=False` guarantee).
_DANGEROUS_PROGRAMS = {
    "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish", "eval", "exec", "xargs",
    "cmd", "cmd.exe", "powershell", "pwsh", "wmic",
}

# Destructive / state-mutating command fragments. Matched against a whitespace-normalized
# lowercase copy of the command so `rm  -rf` and `rm -fr` cannot slip through.
_DANGEROUS_TOKENS = (
    "rm -rf", "rm -fr", "rm -r -f", "rm -f -r", "rm -rf/", "mkfs", "dd if=", ":(){",
    "shutdown", "reboot", "halt", "poweroff", "init 0", "init 6", "systemctl",
    "kill -9 1", "killall -9", "truncate -s 0", "chown -r /", "chmod -r 777 /",
    "chmod 777 /", "userdel", "iptables", "insmod", "modprobe", "wa-sheets-bot",
    "> /dev/sd", "/dev/sda", "/dev/sdb",
)

# Module-level helper injected into healed backends that referenced `render_template('index.html')`.
_INDEX_READER_HELPER = '''

def _alfa_read_index() -> str:
    """Serve index.html relative to THIS file, never relative to the process CWD."""
    import os as _os

    _here = _os.path.dirname(_os.path.abspath(__file__))
    with open(_os.path.join(_here, "index.html"), encoding="utf-8") as _fh:
        return _fh.read()
'''


# --------------------------------------------------------------------------------------
# Low-level IO helpers (never raise on weird encodings / permissions)
# --------------------------------------------------------------------------------------
def _read_text_file(path: str) -> tuple[str, str | None]:
    """
    Read a text file as UTF-8 without ever raising.

    Returns `(text, decode_error)`. `decode_error` is None on a clean decode; otherwise it
    describes the problem and the text has invalid bytes replaced with U+FFFD so that
    downstream scanning can still continue instead of aborting the whole verification gate.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return "", f"unreadable file ({exc.__class__.__name__}: {exc})"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return raw.decode("utf-8", errors="replace"), f"invalid UTF-8 at byte offset {exc.start}"


def _row_value(row: Any, key: str, index: int, default: Any = None) -> Any:
    """Read a column from a DB row regardless of whether `row_factory` is `sqlite3.Row`."""
    if row is None:
        return default
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        pass
    try:
        return row[index]
    except (TypeError, IndexError, KeyError):
        return default


# --------------------------------------------------------------------------------------
# HTML structure helpers
# --------------------------------------------------------------------------------------
def _script_spans(html_text: str) -> list[tuple[int, int]]:
    """Character ranges covered by `<script>...</script>` blocks (unterminated included)."""
    spans: list[tuple[int, int]] = []
    low = html_text.lower()
    pos = 0
    while True:
        start = low.find("<script", pos)
        if start == -1:
            break
        tag_end = low.find(">", start)
        if tag_end == -1:
            spans.append((start, len(html_text)))
            break
        # A self-closing `<script src="..." />` has no body — it must not swallow the
        # rest of the document, otherwise every later `</body>` / `</html>` looks "inside script".
        if low[start:tag_end + 1].rstrip().endswith("/>"):
            pos = tag_end + 1
            continue
        end = low.find("</script>", tag_end)
        if end == -1:
            spans.append((start, len(html_text)))
            break
        end += len("</script>")
        spans.append((start, end))
        pos = end
    return spans


def _find_safe_close(html_text: str, tag: str) -> int:
    """
    Index of the LAST `</tag>` that is not inside a `<script>` block.

    Prevents the auto-healer from injecting markup into a JS string literal such as
    `var s = "</body>";`.
    """
    spans = _script_spans(html_text)
    best = -1
    for m in re.finditer(rf"</{tag}\s*>", html_text, re.I):
        if any(start <= m.start() < end for start, end in spans):
            continue
        best = m.start()
    return best


def _count_script_tags(html_text: str) -> tuple[int, int]:
    """
    Return `(unbalanced_open, unbalanced_close)` for `<script>` tags.

    Self-closing `<script src="..." />` is legal HTML5 and is NOT counted as an open tag.
    """
    low = html_text.lower()
    paired = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.S)
    rest = paired.sub("", low)
    opens = 0
    for m in re.finditer(r"<script\b[^>]*>", rest):
        if m.group(0).rstrip().endswith("/>"):
            continue
        opens += 1
    closes = len(re.findall(r"</script\s*>", rest))
    return opens, closes


def _pick_entrypoint(root: str) -> str | None:
    """
    Pick the HTML entrypoint used for the live HTTP smoke test.

    Priority: root `index.html` > root `index.htm` > any root HTML > first HTML anywhere.
    Returns an absolute path or None when the project ships no HTML at all.
    """
    root_abs = os.path.abspath(root)
    all_html: list[str] = []
    root_html: list[str] = []
    for walk_root, _dirs, walk_files in os.walk(root):
        for fname in sorted(walk_files):
            if fname.lower().endswith((".html", ".htm")):
                full = os.path.join(walk_root, fname)
                all_html.append(full)
                if os.path.abspath(walk_root) == root_abs:
                    root_html.append(full)
    for candidate in ("index.html", "index.htm"):
        for path in root_html:
            if os.path.basename(path).lower() == candidate:
                return path
    if root_html:
        return sorted(root_html)[0]
    if all_html:
        return sorted(all_html)[0]
    return None


# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------
def init_software_factory_tables() -> None:
    """Initialize SQLite table tracking autonomous full-stack software builds."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_software_factory_builds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_id TEXT UNIQUE,
                app_slug TEXT UNIQUE,
                title TEXT,
                app_dir TEXT,
                verification_status TEXT DEFAULT 'PRODUCTION_READY',
                e2e_score INTEGER DEFAULT 100,
                diagnostics_json TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


# --------------------------------------------------------------------------------------
# Auto-healing
# --------------------------------------------------------------------------------------
def _auto_heal_html(html_text: str, title: str) -> tuple[str, list[str]]:
    """Automatically repair missing structural HTML tags if a draft frontend is incomplete."""
    healed = html_text.strip()
    repairs: list[str] = []
    safe_title = html_lib.escape(title or "Untitled")

    if "<!doctype html>" not in healed.lower():
        healed = "<!DOCTYPE html>\n" + healed
        repairs.append("Added missing <!DOCTYPE html> declaration.")

    if "<html" not in healed.lower():
        healed = (
            f'<html lang="id">\n<head><meta charset="utf-8"><title>{safe_title}</title></head>\n'
            f"<body>\n{healed}\n</body>\n</html>"
        )
        repairs.append("Wrapped content in standard <html><head><body> structure.")
        return healed, repairs

    head_m = re.search(r"<head\b[^>]*>", healed, re.I)
    title_m = re.search(r"<title\b[^>]*>", healed, re.I)

    if not head_m:
        head_inner = '<meta charset="utf-8">'
        if not title_m:
            head_inner += f"<title>{safe_title}</title>"
        open_html_m = re.search(r"<html\b[^>]*>", healed, re.I)
        if open_html_m:
            pos = open_html_m.end()
            healed = f"{healed[:pos]}\n<head>{head_inner}</head>{healed[pos:]}"
        else:
            healed = f"<head>{head_inner}</head>\n{healed}"
        repairs.append("Injected missing <head> (with <title>) into the document.")
    elif not title_m:
        pos = head_m.end()
        healed = f"{healed[:pos]}<title>{safe_title}</title>{healed[pos:]}"
        repairs.append("Injected <title> tag into <head>.")

    if _find_safe_close(healed, "body") == -1:
        html_close = _find_safe_close(healed, "html")
        if html_close != -1:
            healed = f"{healed[:html_close]}\n</body>\n{healed[html_close:]}"
        else:
            healed += "\n</body>"
        repairs.append("Closed unclosed </body> tag.")

    if _find_safe_close(healed, "html") == -1:
        healed += "\n</html>"
        repairs.append("Closed unclosed </html> tag.")

    return healed, repairs


def _heal_backend_and_anti_mockup(html_text: str, backend_py: str, title: str) -> tuple[str, str, list[str]]:
    """
    Anti-Mockup & Runtime Self-Healing Engine:
    1. Fixes Flask `render_template('index.html')` when `templates/` folder does not exist so root
       `index.html` is served cleanly — resolved relative to the module file, not the process CWD.
    2. Injects a non-blocking Toast notification + real `localStorage` state persistence helper if raw
       `alert()` calls exist. The toast is anchored on a script-safe `</body>` so it can never be
       injected into a JavaScript string literal.
    """
    repairs: list[str] = []
    healed_py = backend_py.strip()
    healed_html = html_text

    if healed_py and "render_template(" in healed_py:
        rewritten = re.sub(
            r"render_template\(\s*['\"]index\.html['\"]\s*\)",
            "_alfa_read_index()",
            healed_py,
        )
        if rewritten != healed_py:
            if "def _alfa_read_index" not in healed_py:
                rewritten = rewritten + _INDEX_READER_HELPER
            healed_py = rewritten
            repairs.append(
                "Replaced Flask render_template('index.html') with a CWD-independent index.html reader."
            )

    if "alert(" in healed_html and "alfa-anti-mockup-runtime" not in healed_html:
        toast_script = """
<script id="alfa-anti-mockup-runtime">
window.alfaToast = function(msg) {
    let box = document.getElementById('alfa-live-toast');
    if (!box) {
        box = document.createElement('div');
        box.id = 'alfa-live-toast';
        box.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#0f172a;color:#38bdf8;border:1px solid #0284c7;padding:12px 18px;border-radius:10px;font-family:system-ui,sans-serif;font-size:13px;z-index:99999;box-shadow:0 10px 25px rgba(0,0,0,0.5);transition:opacity 0.25s;';
        document.body.appendChild(box);
    }
    box.textContent = '⚡ ' + msg;
    box.style.opacity = '1';
    clearTimeout(window._alfaToastTimer);
    window._alfaToastTimer = setTimeout(() => { box.style.opacity = '0'; }, 3500);
};
</script>
"""
        anchor = _find_safe_close(healed_html, "body")
        if anchor == -1:
            anchor = _find_safe_close(healed_html, "html")
        if anchor != -1:
            healed_html = f"{healed_html[:anchor]}{toast_script}\n{healed_html[anchor:]}"
            repairs.append("Injected non-blocking live toast notification runtime.")
        else:
            healed_html = f"{healed_html}{toast_script}"
            repairs.append("Injected non-blocking live toast notification runtime (appended at end).")

    return healed_html, healed_py, repairs


# --------------------------------------------------------------------------------------
# Live HTTP verification
# --------------------------------------------------------------------------------------
class _ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


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


def _audit_python_files(root: str, issues: list[str], passed: list[str], score_box: list[int]) -> list[dict[str, Any]]:
    """Recursively AST-check every `.py` file under `root`. Returns structured error locations."""
    locations: list[dict[str, Any]] = []
    for walk_root, _dirs, walk_files in os.walk(root):
        for fname in sorted(walk_files):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(walk_root, fname)
            rel_f = os.path.relpath(fpath, root)
            src, decode_err = _read_text_file(fpath)
            if decode_err:
                issues.append(f"Unreadable source in {rel_f}: {decode_err}")
                score_box[0] -= 15
                continue
            try:
                ast.parse(src, filename=rel_f)
                passed.append(f"Backend AST Valid: {rel_f}")
            except SyntaxError as exc:
                issues.append(f"SyntaxError in {rel_f} line {exc.lineno}: {exc.msg}")
                locations.append(
                    {"file": rel_f, "line": exc.lineno or 1, "symbol": "SyntaxError", "lang": "python"}
                )
                score_box[0] -= 40
            except _AST_ERR as exc:
                issues.append(f"Failed to parse {rel_f}: {exc}")
                score_box[0] -= 20
    return locations


def _audit_html_files(
    root: str, issues: list[str], passed: list[str], score_box: list[int]
) -> list[dict[str, Any]]:
    """Recursively audit every `.html`/`.htm` file under `root` (DOM + script balance + primitives)."""
    for walk_root, _dirs, walk_files in os.walk(root):
        for fname in sorted(walk_files):
            if not fname.lower().endswith((".html", ".htm")):
                continue
            fpath = os.path.join(walk_root, fname)
            rel_f = os.path.relpath(fpath, root)
            h_src, decode_err = _read_text_file(fpath)
            if decode_err:
                issues.append(f"Unreadable HTML in {rel_f}: {decode_err}")
                score_box[0] -= 15
                continue
            h_low = h_src.lower()

            if "<html" in h_low and _find_safe_close(h_src, "html") != -1:
                passed.append(f"DOM Structure Valid: {rel_f}")
            else:
                issues.append(f"Incomplete DOM structure in {rel_f}")
                score_box[0] -= 20

            interactive_count = len(re.findall(r"<(button|input|select|textarea|form|a)\b", h_low))
            passed.append(f"Interactive UI Elements in {rel_f}: {interactive_count}")

            opens, closes = _count_script_tags(h_src)
            if opens != closes:
                issues.append(f"Mismatched <script> tags in {rel_f} (open={opens}, close={closes})")
                score_box[0] -= 25

            real_primitives = len(
                re.findall(
                    r"\b(fetch|addEventListener|getElementById|querySelector|localStorage|FileReader|"
                    r"createObjectURL|AudioContext|MediaRecorder|canvas)\b",
                    h_src,
                )
            )
            dummy_alerts = len(re.findall(r"\balert\s*\(", h_src))
            passed.append(
                f"Anti-Mockup Functional Primitives in {rel_f}: {real_primitives} real ops (alerts={dummy_alerts})"
            )
    return []


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


# --------------------------------------------------------------------------------------
# Rollback helper
# --------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------
# test_command safety
# --------------------------------------------------------------------------------------
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


# --------------------------------------------------------------------------------------
# Single-app build pipeline
# --------------------------------------------------------------------------------------
def build_and_verify_fullstack_app(
    app_slug: str,
    title: str,
    frontend_html: str,
    backend_py: str = "",
    auto_heal: bool = True,
    sites_root: str | None = None,
    atomic_rollback_on_failure: bool = True,
) -> dict[str, Any]:
    """
    Autonomous Software Factory Pipeline:
    1. Scaffolds project directory directly in `~/Dokumen/ALFA_SWARM_OUTPUTS/websites/<slug>` (or `sites_root`).
    2. Applies Self-Healing HTML/AST repairs if `auto_heal=True`.
    3. Executes 4-Stage E2E Verification Gate (including Live HTTP 200 Smoke Test).
    4. Syncs with `/sites` registry (`refresh_registry()`) so the app immediately appears in `/sites`.

    A build that does not reach `PRODUCTION_READY` is rolled back and is NOT published to `/sites`.
    """
    try:
        init_software_factory_tables()
    except _DB_ERR as exc:
        return {"status": "error", "message": f"DB initialization failed: {exc}"}

    slug_clean = re.sub(r"[^a-z0-9_\-]", "-", app_slug.strip().lower()).strip("-") or "alfa-app"
    root = sites_root or DEFAULT_FACTORY_SITES_DIR
    app_dir = os.path.join(root, slug_clean)
    os.makedirs(app_dir, exist_ok=True)

    # Snapshot existing artifacts so a failed build never leaves broken code behind.
    tracked = ("index.html", "app.py", "site.json")
    prior: dict[str, str | None] = {}
    for name in tracked:
        path = os.path.join(app_dir, name)
        prior[name] = _read_text_file(path)[0] if os.path.exists(path) else None

    repairs_applied: list[str] = []
    final_html = frontend_html
    final_py = backend_py
    if auto_heal:
        final_html, html_repairs = _auto_heal_html(frontend_html, title)
        repairs_applied.extend(html_repairs)
        final_html, final_py, extra_repairs = _heal_backend_and_anti_mockup(final_html, backend_py, title)
        repairs_applied.extend(extra_repairs)

    index_path = os.path.join(app_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(final_html)

    backend_path = os.path.join(app_dir, "app.py")
    if final_py.strip():
        with open(backend_path, "w", encoding="utf-8") as f:
            f.write(final_py.strip() + "\n")
    elif os.path.exists(backend_path):
        os.remove(backend_path)
        repairs_applied.append("Removed stale app.py (this build shipped no backend).")

    manifest = {
        "slug": slug_clean,
        "title": title,
        "generator": "ALFA_Apex_Software_Factory_v2",
        "auto_repairs": repairs_applied,
    }
    with open(os.path.join(app_dir, "site.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    e2e = verify_fullstack_project_e2e(app_dir)
    e2e["auto_repairs_applied"] = repairs_applied

    # Atomic rollback for failed builds (keeps the sites directory free of broken apps).
    rolled_back = False
    if e2e["status"] != "PRODUCTION_READY" and atomic_rollback_on_failure:
        _restore_backups({os.path.join(app_dir, name): prior[name] for name in tracked})
        rolled_back = True
        e2e["atomic_rolled_back"] = True

    # Stage 4: Sync directly with ALFA `/sites` registry — only for healthy builds.
    sites_registered = False
    if e2e["status"] == "PRODUCTION_READY" and not rolled_back:
        try:
            from alfa.tools.system.sites import refresh_registry

            reg = refresh_registry()
            sites_registered = slug_clean in reg
        except _REGISTRY_ERR as exc:
            logger.debug("Optional sites registry sync note: %s", exc)
    else:
        logger.info(
            "Build '%s' scored %s (%s) — not registered in /sites.",
            slug_clean,
            e2e["e2e_score"],
            e2e["status"],
        )

    bid_hash = hashlib.sha256(f"{slug_clean}:{title}".encode()).hexdigest()[:10]
    build_id = f"build_{slug_clean}_{bid_hash}"

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_software_factory_builds
            (build_id, app_slug, title, app_dir, verification_status, e2e_score, diagnostics_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(app_slug) DO UPDATE SET
                build_id = excluded.build_id,
                title = excluded.title,
                app_dir = excluded.app_dir,
                verification_status = excluded.verification_status,
                e2e_score = excluded.e2e_score,
                diagnostics_json = excluded.diagnostics_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                build_id,
                slug_clean,
                title,
                app_dir,
                e2e["status"],
                e2e["e2e_score"],
                json.dumps(e2e),
            ),
        )
        conn.commit()

    return {
        "status": "success" if e2e["status"] == "PRODUCTION_READY" else "needs_attention",
        "build_id": build_id,
        "app_slug": slug_clean,
        "title": title,
        "app_dir": app_dir,
        "registered_in_sites_menu": sites_registered,
        "atomic_rolled_back": rolled_back,
        "e2e_verification": e2e,
    }


# --------------------------------------------------------------------------------------
# Stack trace parsing
# --------------------------------------------------------------------------------------
def parse_stack_trace_locations(trace_text: str) -> list[dict[str, Any]]:
    """
    DEVIN-CLASS STACK TRACE PARSER:
    Extracts structured (file, line, error_summary) tuples from Python tracebacks,
    Pytest failures, TypeScript/Node stack traces, and GCC/Go/Rust compiler errors.
    """
    if not trace_text:
        return []
    locations: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    # 0) Exception summary line, e.g. `ValueError: boom` / `AssertionError: nope`
    error_summary = ""
    summaries = re.findall(
        r"([A-Za-z_][\w.]*(?:Error|Exception|Warning|Interrupt|Exit|Timeout))\s*:\s*([^\n]+)",
        trace_text,
    )
    if summaries:
        exc_type, exc_msg = summaries[-1]
        error_summary = f"{exc_type}: {exc_msg.strip()[:300]}"
    else:
        bare = re.findall(r"([A-Za-z_][\w.]*(?:Error|Exception))\s*$", trace_text, re.M)
        if bare:
            error_summary = bare[-1]

    def _add(fpath: str, line: int, symbol: str, lang: str, extra: dict[str, Any] | None = None) -> None:
        key = (fpath, line)
        if key in seen:
            return
        seen.add(key)
        loc: dict[str, Any] = {"file": fpath, "line": line, "symbol": symbol, "lang": lang}
        if error_summary:
            loc["error_summary"] = error_summary
        if extra:
            loc.update(extra)
        locations.append(loc)

    # 1) Python standard traceback: File "path/to/file.py", line 42, in func_name
    for m in re.finditer(r'File "([^"]+)", line (\d+)(?:, in ([^\n]+))?', trace_text):
        _add(m.group(1), int(m.group(2)), (m.group(3) or "").strip(), "python")

    # 2) Pytest / Node / TS / Go / Rust format: path/to/file.ext:123:45: error...
    for m in re.finditer(r"([a-zA-Z0-9_./\\\-]+\.(?:py|ts|tsx|js|jsx|go|rs)):(\d+)(?::(\d+))?", trace_text):
        col = int(m.group(3) or 1)
        _add(m.group(1), int(m.group(2)), "", "polyglot", {"column": col})

    # 3) Pytest collection/failure markers: FAILED tests/test_x.py::test_name
    for m in re.finditer(
        r"^(?:FAILED|ERROR)\s+([^\s:]+?\.(?:py|ts|tsx|js|jsx|go|rs))(?:::([^\s]+))?", trace_text, re.M
    ):
        test_name = m.group(2) or ""
        _add(m.group(1), 0, test_name, "python", {"test_name": test_name} if test_name else None)

    return locations


# --------------------------------------------------------------------------------------
# Multi-file repository pipeline
# --------------------------------------------------------------------------------------
def build_and_verify_multifile_repo(
    repo_slug: str,
    title: str,
    files_manifest: dict[str, str],
    test_command: str = "",
    auto_heal: bool = True,
    atomic_rollback_on_failure: bool = True,
    sites_root: str | None = None,
) -> dict[str, Any]:
    """
    DEVIN-CLASS MULTI-FILE REPOSITORY ARCHITECT & ATOMIC TRANSACTION ENGINE:
    1. Scaffolds or patches multi-folder repositories (`src/`, `tests/`, `frontend/`, etc.) from `files_manifest`.
    2. Snapshots existing files before writing so any broken build or failed test triggers an instant
       Atomic Rollback (guaranteed zero broken state — including timeouts and unexpected exceptions).
    3. Recursively validates all Python ASTs, JSON configs, and HTML templates across all subdirectories.
    4. Runs optional `test_command` (e.g., pytest / unittest) and parses stack traces into structured file:line diagnostics.
    """
    try:
        init_software_factory_tables()
    except _DB_ERR as exc:
        return {"status": "error", "message": f"DB initialization failed: {exc}"}

    slug_clean = re.sub(r"[^a-z0-9_\-]", "-", repo_slug.strip().lower()).strip("-") or "alfa-repo"
    root = sites_root or DEFAULT_FACTORY_SITES_DIR
    repo_dir = os.path.join(root, slug_clean)
    os.makedirs(repo_dir, exist_ok=True)

    if not isinstance(files_manifest, dict) or not files_manifest:
        return {"status": "error", "message": "files_manifest tidak boleh kosong."}

    backups: dict[str, str | None] = {}
    written_files: list[str] = []
    repairs_applied: list[str] = []
    issues: list[str] = []
    passed_checks: list[str] = []
    stack_locations: list[dict[str, Any]] = []
    score_box = [100]
    test_output = ""
    http_test: dict[str, Any] = {"passed": False, "http_status": 0, "bytes_received": 0}
    ver_status = "NEEDS_REPAIR"
    rolled_back = False
    fatal_error: str | None = None

    try:
        # ---- Write phase -----------------------------------------------------------
        repo_abs = os.path.abspath(repo_dir)
        for rel_path, content in files_manifest.items():
            # Prevent path traversal outside repo_dir
            clean_rel = os.path.normpath(str(rel_path)).lstrip("/\\")
            if clean_rel.startswith(".."):
                raise ValueError(f"Path tidak valid (traversal): {rel_path}")
            abs_target = os.path.abspath(os.path.join(repo_dir, clean_rel))
            if not abs_target.startswith(repo_abs + os.sep):
                raise ValueError(f"Path tidak valid (traversal): {rel_path}")
            parent = os.path.dirname(abs_target)
            if parent:
                os.makedirs(parent, exist_ok=True)

            if os.path.exists(abs_target):
                with open(abs_target, "rb") as bf:
                    backups[abs_target] = bf.read().decode("utf-8", errors="replace")
            else:
                backups[abs_target] = None

            file_text = str(content or "")
            if auto_heal and clean_rel.lower().endswith((".html", ".htm")):
                file_text, html_repairs = _auto_heal_html(file_text, title)
                repairs_applied.extend(f"{clean_rel}: {r}" for r in html_repairs)

            with open(abs_target, "w", encoding="utf-8") as wf:
                wf.write(file_text)
            written_files.append(clean_rel)

        # ---- Recursive verification across all subdirectories ------------------------
        stack_locations.extend(_audit_python_files(repo_dir, issues, passed_checks, score_box))
        for walk_root, _dirs, walk_files in os.walk(repo_dir):
            for fname in sorted(walk_files):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(walk_root, fname)
                rel_f = os.path.relpath(fpath, repo_dir)
                raw, decode_err = _read_text_file(fpath)
                if decode_err:
                    issues.append(f"Unreadable JSON in {rel_f}: {decode_err}")
                    score_box[0] -= 25
                    continue
                try:
                    json.loads(raw)
                    passed_checks.append(f"JSON Valid: {rel_f}")
                except _JSON_ERR as je:
                    issues.append(f"Invalid JSON in {rel_f}: {je}")
                    score_box[0] -= 25
        _audit_html_files(repo_dir, issues, passed_checks, score_box)

        # ---- Optional test execution (e.g. pytest / unittest) -----------------------
        if test_command.strip() and not issues:
            check = _validate_test_command(test_command)
            if not check["ok"]:
                issues.append(check["error"])
                score_box[0] -= 50
            else:
                try:
                    proc = subprocess.run(
                        check["argv"],
                        cwd=repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=TEST_COMMAND_TIMEOUT,
                        shell=False,
                    )
                    test_output = (proc.stdout + "\n" + proc.stderr).strip()[:2000]
                    if proc.returncode == 0:
                        passed_checks.append(f"Test suite passed: `{test_command}`")
                    else:
                        issues.append(f"Test command failed (exit {proc.returncode}): `{test_command}`")
                        stack_locations.extend(parse_stack_trace_locations(test_output))
                        score_box[0] -= 45
                except subprocess.TimeoutExpired:
                    issues.append(
                        f"Test command timed out after {TEST_COMMAND_TIMEOUT}s: `{test_command}`"
                    )
                    test_output = f"TimeoutExpired after {TEST_COMMAND_TIMEOUT}s"
                    score_box[0] -= 45
                except _PROC_ERR as exc:
                    issues.append(f"Test command could not be executed: {exc}")
                    test_output = str(exc)
                    score_box[0] -= 45

        # ---- Live HTTP check if an HTML entrypoint exists ----------------------------
        entry = _pick_entrypoint(repo_dir)
        if entry:
            entry_rel = os.path.relpath(entry, repo_dir)
            if not issues:
                http_test = _run_live_http_smoke_test(repo_dir, entry_rel)
                if http_test.get("passed"):
                    passed_checks.append(f"Live HTTP 200 OK ({http_test.get('bytes_received')} bytes)")
                else:
                    issues.append(
                        f"Live HTTP Smoke Test failed for '{entry_rel}': status={http_test.get('http_status')} "
                        f"{http_test.get('error', '')}".strip()
                    )
                    score_box[0] -= 25

        score = max(0, min(100, score_box[0]))
        ver_status = (
            "PRODUCTION_READY"
            if score >= 85 and not issues
            else "ROLLED_BACK"
            if (issues and atomic_rollback_on_failure)
            else "NEEDS_REPAIR"
        )
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, RuntimeError, OSError, ArithmeticError, UnicodeError, sqlite3.Error) as exc:  # noqa: BLE001 - pipeline build multi-langkah
        fatal_error = f"Multi-file repo build error: {exc}"
        issues.append(fatal_error)
        score_box[0] = 0
        ver_status = "ROLLED_BACK" if atomic_rollback_on_failure else "NEEDS_REPAIR"
        logger.exception("Multi-file build failed for '%s'", slug_clean)
    finally:
        # Atomic rollback — runs for verification failures AND for unexpected exceptions.
        if issues and atomic_rollback_on_failure:
            _restore_backups(backups)
            rolled_back = True

    score = max(0, min(100, score_box[0]))

    # Ensure site.json manifest exists if not rolled back
    sites_registered = False
    if not rolled_back:
        manifest_path = os.path.join(repo_dir, "site.json")
        if not os.path.exists(manifest_path):
            with open(manifest_path, "w", encoding="utf-8") as mf:
                json.dump(
                    {
                        "slug": slug_clean,
                        "title": title,
                        "generator": "ALFA_Apex_MultiFile_Architect",
                        "files_count": len(written_files),
                    },
                    mf,
                    indent=2,
                )
        if ver_status == "PRODUCTION_READY":
            try:
                from alfa.tools.system.sites import refresh_registry

                reg = refresh_registry()
                sites_registered = slug_clean in reg
            except _REGISTRY_ERR as e:
                logger.debug("Registrasi /sites dilewati untuk '%s': %s", slug_clean, e)
        else:
            logger.info(
                "Repo '%s' scored %s (%s) — not registered in /sites.",
                slug_clean,
                score,
                ver_status,
            )

    e2e_summary = {
        "status": ver_status,
        "e2e_score": score,
        "files_written": written_files,
        "passed_checks": passed_checks,
        "issues": issues,
        "stack_trace_locations": stack_locations,
        "atomic_rolled_back": rolled_back,
        "auto_repairs_applied": repairs_applied,
        "live_http_smoke": http_test,
        "test_output_preview": test_output[:500] if test_output else "",
        "fatal_error": fatal_error,
    }

    bid_hash = hashlib.sha256(f"{slug_clean}:{title}:multifile".encode()).hexdigest()[:10]
    build_id = f"repo_{slug_clean}_{bid_hash}"

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_software_factory_builds
            (build_id, app_slug, title, app_dir, verification_status, e2e_score, diagnostics_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(app_slug) DO UPDATE SET
                build_id = excluded.build_id,
                title = excluded.title,
                app_dir = excluded.app_dir,
                verification_status = excluded.verification_status,
                e2e_score = excluded.e2e_score,
                diagnostics_json = excluded.diagnostics_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                build_id,
                slug_clean,
                title,
                repo_dir,
                ver_status,
                score,
                json.dumps(e2e_summary),
            ),
        )
        conn.commit()

    return {
        "status": "success" if ver_status == "PRODUCTION_READY" else "rolled_back" if rolled_back else "needs_attention",
        "build_id": build_id,
        "repo_slug": slug_clean,
        "title": title,
        "repo_dir": repo_dir,
        "registered_in_sites_menu": sites_registered,
        "e2e_verification": e2e_summary,
    }


# --------------------------------------------------------------------------------------
# Telemetry
# --------------------------------------------------------------------------------------
def get_software_factory_metrics() -> dict[str, Any]:
    """Return telemetry for the Autonomous Full-Stack Software Factory."""
    empty = {"total_builds": 0, "production_ready_builds": 0, "avg_e2e_score": 100.0}
    try:
        init_software_factory_tables()
        with get_sync_db() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_builds,
                    COALESCE(SUM(CASE WHEN verification_status = 'PRODUCTION_READY' THEN 1 ELSE 0 END), 0) AS prod_ready,
                    COALESCE(AVG(e2e_score), 100.0) AS avg_score
                FROM alfa_software_factory_builds
                """
            ).fetchone()
    except _DB_ERR as exc:
        logger.warning("Software factory metrics unavailable: %s", exc)
        return empty
    return {
        "total_builds": int(_row_value(row, "total_builds", 0, 0) or 0),
        "production_ready_builds": int(_row_value(row, "prod_ready", 1, 0) or 0),
        "avg_e2e_score": round(float(_row_value(row, "avg_score", 2, 100.0) or 100.0), 1),
    }
