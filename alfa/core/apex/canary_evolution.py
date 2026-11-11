"""
Level 5+ Shadow-Git Canary Evolution & Dynamic Tool Synthesis Engine for ALFA OS.

Enables ALFA OS to autonomously write and verify Python tools (AST security check +
out-of-process smoke test). Hot-loading into the main process is opt-in via
``ALFA_ALLOW_DYNAMIC_TOOLS=true``; when enabled, the Canary Guard automatically rolls
back a tool after any runtime fault.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any, cast

from alfa.core.apex.hardware_governor import IMMUTABLE_PROTECTED_SERVICES
from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("ApexCanaryEvolution")

DYNAMIC_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tools", "dynamic")
)

# Forbidden patterns in synthesized tools to guarantee host & WhatsApp session safety
_FORBIDDEN_CODE_PATTERNS: tuple[str, ...] = (
    "wa-sheets-bot",
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",
)

# Synthesized calculation tools should not need process/network primitives.
# These checks are defense-in-depth; the real boundary is the subprocess smoke
# test plus opt-in hot-load.
_RESERVED_TOOL_NAMES: frozenset[str] = frozenset({"__init__", "__main__", "__pycache__"})

_FORBIDDEN_AST_IMPORTS: frozenset[str] = frozenset(
    {"subprocess", "ctypes", "socket", "multiprocessing", "pty", "importlib"}
)
_FORBIDDEN_AST_CALLS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "os.system",
        "os.popen",
        "os.execv",
        "os.execve",
        "os.execl",
        "os.execlp",
        "os.spawnl",
        "os.spawnv",
    }
)


def _dotted_name(node: ast.AST) -> str:
    """Return ``os.system`` for an ``ast.Attribute`` chain, else a short name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _safe_description(description: str, limit: int = 300) -> str:
    """Flatten an LLM/user description so it cannot escape a file docstring."""
    clean = " ".join(str(description or "").split())
    clean = clean.replace("\\", "/").replace('"', "'")
    return clean[:limit]

# Hot-loading arbitrary synthesized code into the main process is dangerous.
# It is opt-in only; verification and smoke tests always run out-of-process.
_DYNAMIC_TOOL_ENV_FLAG = "ALFA_ALLOW_DYNAMIC_TOOLS"
_SMOKE_TIMEOUT_SECONDS = 8.0

# Executed inside a separate Python interpreter. It never inherits ALFA's
# environment, working directory, or loaded modules.
_SMOKE_RUNNER = r"""
import json
import sys
import traceback

try:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
except Exception:
    pass

payload = json.loads(sys.stdin.read())
if payload.get("project_root"):
    sys.path.insert(0, payload["project_root"])

namespace = {"__builtins__": __builtins__}
try:
    exec(compile(payload["code"], "<canary-smoke>", "exec"), namespace)
    fn = namespace.get(payload["tool_name"])
    if not callable(fn):
        raise TypeError(f"Function '{payload['tool_name']}' is not callable")
    result = fn(**(payload.get("args") or {}))
    print(json.dumps({"ok": True, "result": result}, default=str))
except BaseException as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
    )
"""


def _dynamic_tools_enabled() -> bool:
    """Return True only when the owner explicitly opts into in-process hot-load."""
    return os.getenv(_DYNAMIC_TOOL_ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _run_smoke_test_in_subprocess(
    tool_name: str,
    code_source: str,
    smoke_test_args: dict[str, Any],
) -> dict[str, Any]:
    """Run a smoke test in a throwaway interpreter with timeout and rlimits.

    This is process isolation, not a full security sandbox: the child still has
    the same filesystem/network rights as the ALFA user. It does, however,
    prevent synthesized top-level code from executing inside the bot process.
    """
    try:
        payload = json.dumps(
            {
                "tool_name": tool_name,
                "code": code_source,
                "args": smoke_test_args,
                "project_root": _project_root(),
            }
        )
    except (TypeError, ValueError) as exc:
        return {
            "ok": False,
            "error": f"smoke_test_args must be JSON-serializable: {exc}",
        }

    workdir = tempfile.mkdtemp(prefix="alfa-canary-smoke-")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": workdir,
        "TMPDIR": workdir,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", _SMOKE_RUNNER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(payload, timeout=_SMOKE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            if proc.pid:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            stdout, stderr = proc.communicate()
            return {
                "ok": False,
                "error": f"Smoke test timed out after {_SMOKE_TIMEOUT_SECONDS:.0f}s",
            }

        if proc.returncode != 0:
            tail = (stderr or stdout or "").strip()[-2000:]
            return {
                "ok": False,
                "error": f"Smoke test process exited with code {proc.returncode}: {tail}",
            }

        lines = [line for line in (stdout or "").splitlines() if line.strip()]
        if not lines:
            tail = (stderr or "").strip()[-2000:]
            return {"ok": False, "error": f"Smoke test produced no result. stderr: {tail}"}
        try:
            result = json.loads(lines[-1])
        except json.JSONDecodeError:
            tail = (stdout or "").strip()[-2000:]
            return {"ok": False, "error": f"Invalid smoke test result: {tail}"}

        if not isinstance(result, dict) or not result.get("ok"):
            err = result.get("error") if isinstance(result, dict) else str(result)
            return {"ok": False, "error": str(err or "Smoke test failed")}
        return {"ok": True, "result": result.get("result")}
    except OSError as exc:
        return {"ok": False, "error": f"Failed to start smoke test process: {exc}"}
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        shutil.rmtree(workdir, ignore_errors=True)


def _materialize_callable(tool_name: str, code_source: str) -> Callable:
    """Load a verified tool into the current process.

    Callers must explicitly opt in via ``ALFA_ALLOW_DYNAMIC_TOOLS``. This is
    intentionally kept separate from verification so the default path never
    executes synthesized code in-process.
    """
    namespace: dict[str, Any] = {"__builtins__": __builtins__}
    compiled = compile(code_source, filename=f"<canary:{tool_name}>", mode="exec")
    exec(compiled, namespace)  # noqa: S102  # nosec B102 - opt-in only, documented hot-load boundary
    fn_obj = namespace.get(tool_name)
    if not callable(fn_obj):
        raise TypeError(f"Function '{tool_name}' is not callable")  # noqa: TRY003
    return cast("Callable[..., Any]", fn_obj)


def init_canary_tables() -> None:
    """Initialize SQLite table tracking autonomous code evolutions and canary status."""
    with get_sync_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alfa_canary_evolutions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evolution_id TEXT UNIQUE,
                tool_name TEXT UNIQUE,
                description TEXT,
                code_source TEXT,
                verification_status TEXT DEFAULT 'VERIFIED',
                active INTEGER DEFAULT 1,
                execution_count INTEGER DEFAULT 0,
                rollback_count INTEGER DEFAULT 0,
                last_error TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def verify_code_via_canary_gate(
    tool_name: str,
    code_source: str,
    smoke_test_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    3-Stage Canary Verification Gate:
    Stage 1: AST Syntax & Quarantine Safety Audit.
    Stage 2: Compilation & function-definition check (no execution).
    Stage 3: Smoke Test Execution in an isolated subprocess.

    This function never executes synthesized code in the calling process.
    """
    if (
        not tool_name
        or not tool_name.isidentifier()
        or tool_name in _RESERVED_TOOL_NAMES
    ):
        return {
            "passed": False,
            "stage": "STAGE_1_IDENTIFIER",
            "error": f"Invalid or reserved tool_name: '{tool_name}'",
        }

    low_code = code_source.lower()
    for forbidden in _FORBIDDEN_CODE_PATTERNS:
        if forbidden.lower() in low_code:
            return {
                "passed": False,
                "stage": "STAGE_1_SECURITY_QUARANTINE",
                "error": f"Forbidden pattern '{forbidden}' detected in synthesized code.",
            }

    for protected in IMMUTABLE_PROTECTED_SERVICES:
        if protected.lower() in low_code:
            return {
                "passed": False,
                "stage": "STAGE_1_SERVICE_QUARANTINE",
                "error": f"Attempted to reference quarantined service '{protected}'.",
            }

    # Stage 1: AST Parsing
    try:
        tree = ast.parse(code_source)
    except SyntaxError as e:
        return {"passed": False, "stage": "STAGE_1_AST_SYNTAX", "error": f"SyntaxError: {e}"}

    fn_defs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    if tool_name not in fn_defs:
        return {
            "passed": False,
            "stage": "STAGE_1_FUNCTION_DEF",
            "error": f"Function '{tool_name}' not found in code_source (found: {fn_defs}).",
        }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_AST_IMPORTS:
                    return {
                        "passed": False,
                        "stage": "STAGE_1_AST_SECURITY",
                        "error": f"Import '{alias.name}' is not allowed in synthesized tools.",
                    }
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _FORBIDDEN_AST_IMPORTS:
                return {
                    "passed": False,
                    "stage": "STAGE_1_AST_SECURITY",
                    "error": f"Import from '{node.module}' is not allowed in synthesized tools.",
                }
        elif isinstance(node, ast.Call):
            called = _dotted_name(node.func)
            if called in _FORBIDDEN_AST_CALLS or called.split(".")[0] in _FORBIDDEN_AST_CALLS:
                return {
                    "passed": False,
                    "stage": "STAGE_1_AST_SECURITY",
                    "error": f"Call to '{called}' is not allowed in synthesized tools.",
                }

    # Stage 2: Compilation only (never exec in the main process).
    try:
        compile(tree, filename=f"<canary:{tool_name}>", mode="exec")
    except Exception as e:
        return {"passed": False, "stage": "STAGE_2_COMPILE", "error": f"Compilation failed: {e}"}

    # Stage 3: Optional smoke test in an isolated subprocess.
    smoke_output = None
    if smoke_test_args is not None:
        smoke = _run_smoke_test_in_subprocess(tool_name, code_source, smoke_test_args)
        if not smoke.get("ok"):
            return {
                "passed": False,
                "stage": "STAGE_3_SMOKE_TEST",
                "error": str(smoke.get("error") or "Smoke test failed"),
            }
        smoke_output = smoke.get("result")

    return {
        "passed": True,
        "stage": "ALL_STAGES_PASSED",
        # Kept for response-shape compatibility; callers must opt in to
        # materializing a live callable via ``synthesize_and_hotload_tool``.
        "callable": None,
        "smoke_output": smoke_output,
    }


def _wrap_with_canary_rollback_guard(tool_name: str, fn: Callable) -> Callable:
    """Wrap a dynamically synthesized tool so any runtime failure triggers automatic Canary logging/rollback."""
    @functools.wraps(fn)
    def _guarded(*args: Any, **kwargs: Any) -> Any:
        init_canary_tables()
        try:
            res = fn(*args, **kwargs)
            with get_sync_db() as conn:
                conn.execute(
                    "UPDATE alfa_canary_evolutions SET execution_count = execution_count + 1, updated_at = CURRENT_TIMESTAMP WHERE tool_name = ?",
                    (tool_name,),
                )
                conn.commit()
            return res
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            logger.warning("Canary Guard caught exception in dynamic tool '%s': %s", tool_name, err_msg)
            with get_sync_db() as conn:
                conn.execute(
                    """
                    UPDATE alfa_canary_evolutions
                    SET rollback_count = rollback_count + 1,
                        active = 0,
                        verification_status = 'ROLLED_BACK',
                        last_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tool_name = ?
                    """,
                    (err_msg[:500], tool_name),
                )
                conn.commit()
            return {
                "status": "canary_rolled_back",
                "tool_name": tool_name,
                "error": err_msg,
                "message": f"Dynamic tool '{tool_name}' encountered an error and was safely rolled back by Apex Canary Guard.",
            }

    return _guarded


def synthesize_and_hotload_tool(
    tool_name: str,
    description: str,
    code_source: str,
    smoke_test_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Synthesize a new Python tool, verify it through the 3-Stage Canary Gate,
    and persist it to `alfa/tools/dynamic/`.

    Hot-registration only happens when ``ALFA_ALLOW_DYNAMIC_TOOLS`` is explicitly
    enabled. Without that opt-in, the tool is verified and saved but never
    executed in the main process (``status="verified"``, ``hot_loaded=False``).
    """
    init_canary_tables()
    gate = verify_code_via_canary_gate(tool_name, code_source, smoke_test_args=smoke_test_args)
    if not gate.get("passed"):
        return {
            "status": "rejected",
            "tool_name": tool_name,
            "failed_stage": gate.get("stage"),
            "error": gate.get("error"),
        }

    os.makedirs(DYNAMIC_TOOLS_DIR, exist_ok=True)
    init_file = os.path.join(DYNAMIC_TOOLS_DIR, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w", encoding="utf-8") as f:
            f.write('"""Dynamically synthesized Level 5+ Apex tools."""\n')

    tool_path = os.path.join(DYNAMIC_TOOLS_DIR, f"{tool_name}.py")
    safe_desc = _safe_description(description)
    with open(tool_path, "w", encoding="utf-8") as f:
        f.write(f'"""Auto-synthesized Apex Tool: {safe_desc}"""\n\n{code_source.strip()}\n')

    ev_hash = hashlib.sha256(f"{tool_name}:{code_source}".encode()).hexdigest()[:10]
    evolution_id = f"evo_{tool_name}_{ev_hash}"

    hot_loaded = False
    if _dynamic_tools_enabled():
        try:
            fn_obj = _materialize_callable(tool_name, code_source)
        except Exception as e:
            return {
                "status": "rejected",
                "tool_name": tool_name,
                "failed_stage": "STAGE_4_MATERIALIZE",
                "error": f"Verified code could not be loaded: {type(e).__name__}: {e}",
            }

        guarded_fn = _wrap_with_canary_rollback_guard(tool_name, fn_obj)

        # Hot-register into ALFA's central tool registry if available
        try:
            from alfa.tools.registry import register_tool
            register_tool(category="apex_dynamic")(guarded_fn)
            hot_loaded = True
        except Exception as e:
            logger.debug("Optional registry hot-bind note: %s", e)

    verification_status = "VERIFIED" if hot_loaded else "VERIFIED_HOTLOAD_DISABLED"
    active = 1 if hot_loaded else 0

    with get_sync_db() as conn:
        conn.execute(
            """
            INSERT INTO alfa_canary_evolutions
            (evolution_id, tool_name, description, code_source, verification_status, active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tool_name) DO UPDATE SET
                evolution_id = excluded.evolution_id,
                description = excluded.description,
                code_source = excluded.code_source,
                verification_status = excluded.verification_status,
                active = excluded.active,
                last_error = '',
                updated_at = CURRENT_TIMESTAMP
            """,
            (evolution_id, tool_name, description, code_source, verification_status, active),
        )
        conn.commit()

    if hot_loaded:
        message = (
            f"Tool '{tool_name}' passed 3-Stage Canary Verification and is now hot-loaded "
            "into ALFA OS."
        )
        status = "success"
    else:
        message = (
            f"Tool '{tool_name}' passed 3-Stage Canary Verification and was persisted to "
            f"'{tool_path}'. Hot-load is disabled by default; set "
            f"{_DYNAMIC_TOOL_ENV_FLAG}=true only if you explicitly trust synthesized code."
        )
        status = "verified"

    return {
        "status": status,
        "evolution_id": evolution_id,
        "tool_name": tool_name,
        "file_path": tool_path,
        "hot_loaded": hot_loaded,
        "smoke_output": gate.get("smoke_output"),
        "message": message,
    }


def get_canary_evolution_metrics() -> dict[str, Any]:
    """Return telemetry for Shadow-Git Canary Evolution & Dynamic Tool Synthesis."""
    init_canary_tables()
    with get_sync_db() as conn:
        total_active = conn.execute(
            "SELECT COUNT(*) FROM alfa_canary_evolutions WHERE active = 1"
        ).fetchone()[0]
        total_rollbacks = conn.execute(
            "SELECT COALESCE(SUM(rollback_count), 0) FROM alfa_canary_evolutions"
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT tool_name, description, verification_status, execution_count, rollback_count
            FROM alfa_canary_evolutions
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        tools_list = [dict(r) for r in rows]

    return {
        "active_synthesized_tools": int(total_active),
        "total_canary_rollbacks": int(total_rollbacks),
        "recent_evolutions": tools_list,
    }
