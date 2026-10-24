"""Shared brain configuration constants."""

import os

from alfa.core.config import ensure_env_loaded
from alfa.core.tuning import max_tool_output, tool_exec_timeout

ensure_env_loaded()

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

PROJECT_DIR = REPO_ROOT
# Batas putaran tool-call per turn. Naik dari 8 -> 24 agar tugas kompleks
# multi-langkah tidak kehabisan "napas". Bisa dioverride via env.
MAX_ITERATIONS = int(os.getenv("ALFA_MAX_TOOL_ITERATIONS", "24"))
# Output tool dipotong head+tail (lihat alfa.core.tuning.truncate_middle).
# Default 12000; override via ALFA_MAX_TOOL_OUTPUT.
MAX_TOOL_OUTPUT = max_tool_output()
# Selalu > ALFA_HOST_TIMEOUT agar tool sempat membunuh subprocess sendiri.
# Override via ALFA_TOOL_TIMEOUT.
TOOL_EXEC_TIMEOUT = tool_exec_timeout()
# Budget total karakter konteks percakapan; dilewabi -> kompaksi otomatis.
TOOL_CONTEXT_BUDGET = int(os.getenv("ALFA_TOOL_CONTEXT_BUDGET", "120000"))
_TOOL_KEEP_RECENT = 6  # jumlah pesan tool terakhir yang dijaga utuh
