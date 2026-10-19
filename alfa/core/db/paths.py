"""Resolusi path database — SATU sumber kebenaran.

Sebelumnya ada tiga resolver terpisah:

1. ``alfa/core/db/connection.py::_get_db_path`` — honor ``ALFA_DB_PATH`` +
   ``DATABASE_URL``.
2. ``alfa/core/perm/store.py::_get_db_path`` — honor ``ALFA_DB_PATH`` saja;
   ``DATABASE_URL`` diabaikan sehingga permission store & audit trail bisa
   mendarat di database yang berbeda dari data yang dilindunginya.
3. ``alfa/security/vault.py::_vault_db_path`` — punya urutan sendiri (attr
   patch > env > resolver core > statis).

Akibatnya, layer yang berbeda bisa menulis ke file DB berbeda dalam satu
proses. Modul ini menyediakan resolver tunggal yang dipakai semua layer.

Preseden resolusi:

1. ``ALFA_DB_PATH`` — override eksplisit, menang atas segalanya.
2. ``DATABASE_URL`` — mis. ``sqlite:///./agent_data.db`` (prefix ``sqlite:///``
   dilepas).
3. Atribut ``DB_PATH`` pada modul database/vault bila di-patch eksplisit
   (pola isolasi test lama).
4. Default repo root ``agent_data.db``.
"""

from __future__ import annotations

import os

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "agent_data.db")

_SQLITE_PREFIX = "sqlite:///"


def _from_env(value: str) -> str:
    """Normalisasi nilai env menjadi path filesystem."""
    value = value.strip()
    if not value:
        return ""
    if value.startswith(_SQLITE_PREFIX):
        return value[len(_SQLITE_PREFIX) :]
    return value


def resolve_db_path(
    *,
    fallback: str | None = None,
    module_attr: str = "DB_PATH",
    modules: tuple[str, ...] = ("database", "alfa.core.database"),
) -> str:
    """Resolusi path DB secara dinamis (bukan diikat saat import).

    Args:
        fallback: path terakhir kalau tidak ada env/attr yang cocok.
        module_attr: nama atribut yang dicari pada modul fallback.
        modules: nama modul yang diperiksa untuk atribut tersebut.
    """
    for env_key in ("ALFA_DB_PATH", "DATABASE_URL"):
        resolved = _from_env(os.getenv(env_key, ""))
        if resolved:
            return resolved

    import sys

    for mod_name in modules:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        attr = getattr(mod, module_attr, None)
        if attr:
            return str(attr)

    return str(fallback or DEFAULT_DB_PATH)


__all__ = [
    "DEFAULT_DB_PATH",
    "REPO_ROOT",
    "resolve_db_path",
]
