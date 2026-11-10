"""Regression tests for the private-secrets-first env loader."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_LOAD_SCRIPT = """
import os
from pathlib import Path

from alfa.core import config

config.SECRETS_PATH = Path(os.environ["PRIVATE_ENV"])
config.ENV_PATH = Path(os.environ["REPO_ENV"])
config._loaded = False
config.ensure_env_loaded()
print(os.environ.get("ALFA_TEST_SECRET", ""))
"""


def _run_loader(tmp_path: Path, process_env: dict[str, str] | None = None) -> str:
    private = tmp_path / "secrets.env"
    private.write_text("ALFA_TEST_SECRET=from_private\n", encoding="utf-8")
    private.chmod(0o600)
    repo = tmp_path / "repo.env"
    repo.write_text("ALFA_TEST_SECRET=from_repo\n", encoding="utf-8")
    repo.chmod(0o600)

    env = os.environ.copy()
    env.pop("ALFA_TEST_SECRET", None)
    env["PRIVATE_ENV"] = str(private)
    env["REPO_ENV"] = str(repo)
    if process_env:
        env.update(process_env)

    result = subprocess.run(
        [sys.executable, "-c", _LOAD_SCRIPT],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def test_private_secrets_win_over_repo_dotenv(tmp_path):
    assert _run_loader(tmp_path) == "from_private"


def test_process_env_wins_over_both_files(tmp_path):
    assert _run_loader(tmp_path, {"ALFA_TEST_SECRET": "from_process"}) == "from_process"
