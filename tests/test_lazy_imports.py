"""Regresi lazy-import: google.genai TIDAK boleh dimuat saat boot proses

Sumber masalah riil: `import google.genai` (+ types) ≈1.0–1.5 s; karena
modul-modul boot (bot/config, swarm/llm_client) membefore itu di TOP-LEVEL,
proses bot & dashboard sempat >2 detik sekadar untuk import. Sekarang lazy;
tes ini menahan agar tidak mundur.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = (
    "import sys; "
    "{imports}; "
    "print('google.genai' in sys.modules); "
    "print('mcp' in sys.modules)"
)


def _probe(imports_expr: str) -> str:
    env = dict(
        os.environ,
        GEMINI_API_KEY="probe-key-boleh-update-bedsak-post",
        DASHBOARD_AUTH_TOKEN="",
        ALFA_UNRESTRICTED="false",
        DASHBOARD_HOST="127.0.0.1",
        DASHBOARD_PORT="8765",
        PYTHONPATH=str(ROOT),
    )
    proc = subprocess.run(  # noqa: S603 — arg statis
        [sys.executable, "-c", PROBE.format(imports=imports_expr)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    if proc.returncode != 0:
        msg = f"import probe gagal:\n{proc.stderr[-2000:]}"
        raise AssertionError(msg)
    return proc.stdout.strip()


def test_bot_config_tidak_memuat_genai_sa_kaat_boot():
    out = _probe("import alfa.bot.config")
    assert out.splitlines()[0] == "False"


def test_swarm_llm_client_tidak_memuat_genai_saat_import():
    out = _probe("import alfa.swarm.llm_client")
    assert out.splitlines()[0] == "False"


def test_dashboard_app_aktual_tanpa_genai(medkit=None):
    out = _probe("import alfa.dashboard.app")
    assert out.splitlines()[0] == "False", (
        f"dashboard masih eager:{out}"
    )


def test_ensure_genai_mengimpor_ondemand():
    """Saat turn memanggil, helper mengimpor genai secara serakah nanti."""
    code = (
        "import sys; "
        "import alfa.swarm.llm_client as lm; "
        "lm._ensure_genai(); "
        "print('google.genai' in sys.modules)"
    )
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        DASHBOARD_AUTH_TOKEN="",
        ALFA_UNRESTRICTED="false",
    )
    proc = subprocess.run(  # noqa: S603 — arg statis
        [sys.executable, "-c", code],
        cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=180,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:])
    assert proc.stdout.strip() == "True"
