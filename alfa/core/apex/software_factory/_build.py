"""Build aplikasi fullstack & repo multi-file (dengan rollback atomik)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
from typing import Any

from alfa.core.apex.software_factory._audit import (
    _audit_html_files,
    _audit_python_files,
)
from alfa.core.apex.software_factory._db import init_software_factory_tables
from alfa.core.apex.software_factory._heal import (
    _auto_heal_html,
    _heal_backend_and_anti_mockup,
    _pick_entrypoint,
    _read_text_file,
)
from alfa.core.apex.software_factory._verify import (
    _restore_backups,
    _run_live_http_smoke_test,
    _validate_test_command,
    verify_fullstack_project_e2e,
)
from alfa.core.db.connection import get_sync_db

logger = logging.getLogger(__name__)

#: Error realistis untuk akses SQLite.
_DB_ERR = (sqlite3.Error, RuntimeError, ValueError, TypeError)

DEFAULT_FACTORY_SITES_DIR = os.path.expanduser("~/Dokumen/ALFA_SWARM_OUTPUTS/websites")

TEST_COMMAND_TIMEOUT = 30

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
