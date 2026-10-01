"""Shared brain configuration constants."""

import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

PROJECT_DIR = REPO_ROOT
# Batas putaran tool-call per turn. Naik dari 8 -> 24 agar tugas kompleks
# multi-langkah tidak kehabisan "napas". Bisa dioverride via env.
MAX_ITERATIONS = int(os.getenv("ALFA_MAX_TOOL_ITERATIONS", "24"))
MAX_TOOL_OUTPUT = 4000  # potong output tool agar konteks efisien
TOOL_EXEC_TIMEOUT = 300  # rapat/swarm bisa berjalan beberapa menit
# Budget total karakter konteks percakapan; dilewabi -> kompaksi otomatis.
TOOL_CONTEXT_BUDGET = int(os.getenv("ALFA_TOOL_CONTEXT_BUDGET", "120000"))
_TOOL_KEEP_RECENT = 6  # jumlah pesan tool terakhir yang dijaga utuh
