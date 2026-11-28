"""Paket tes ALFA OS.

Keberhasilan impor plugin harness di tests/conftest.py
(`pytest_plugins = ["tests.harness.*"]`) bergantung pada direktori root repo
terdapat di sys.path. File ini menegakkan hal tersebut secara eksplisit dan
mendeklarasikan `tests` sebagai package — tanpa ini, menjalankan `pytest` dari
direktori repo dengan konfigurasi default (tanpa PYTHONPATH / importlib mode)
gagal dengan:

    ImportError: Error importing plugin "tests.harness.ptb_app":
    No module named 'tests.harness'

Catatan: `tests/` sengaja TIDAK ikut ter-package saat install
([tool.setuptools.packages.find] hanya menyertakan "alfa*" dan "plugins*").
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
