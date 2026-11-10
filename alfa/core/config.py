"""Service konfigurasi terpusat — satu-satunya titik load `.env`.

Sebelumnya `load_dotenv()` dipanggil dari 6 modul berbeda dengan untaian
serak-up: yang pertama kali diimpor menang, path resolusi tidak konsisten
(beberapa memakai CWD), dan urutan impor memicu error halus (mis. `# noqa:
E402` yang tersisa di dashboard). Modul ini menyeragamkan:

- Secrets pribadi dibaca dari `ALFA_SECRETS_FILE` (default
  `~/.config/alfa/secrets.env`), lalu `REPO_ROOT/.env`
- `override=False` — env proses/CI/CLI SELALU menang; secrets pribadi menang
  atas `.env` repository
- Aman direkan-rekan dari modul mana pun: `ensure_env_loaded()`
- Baca env dengan default/validasi: `env_str`, `env_int`, `env_float`, `env_bool`
"""

import logging
import os
import stat
import threading
from pathlib import Path

logger = logging.getLogger("Core.Config")

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"
# Secrets outside the repository are loaded first so they win over a local
# `.env`, while explicit process/CI environment variables still win over both.
SECRETS_PATH = Path(
    os.getenv("ALFA_SECRETS_FILE", "~/.config/alfa/secrets.env")
).expanduser()

_loaded = False
_lock = threading.Lock()


def _warn_if_world_readable(path: Path) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        logger.warning(
            "File secret %s dapat dibaca grup/orang lain (mode %o); "
            "disarankan chmod 600.",
            path,
            mode,
        )


def _load_env_file(path: Path, *, required: bool = False) -> bool:
    """Load one dotenv file without overriding existing process env."""
    if not path.exists():
        if required:
            logger.warning("File env tidak ditemukan: %s", path)
        else:
            logger.debug("File env tidak ditemukan: %s (skip)", path)
        return False
    try:
        from dotenv import load_dotenv

        _warn_if_world_readable(path)
        load_dotenv(path, override=False)
        logger.debug("Env dimuat dari %s", path)
    except Exception as e:  # dotenv tidak wajib untuk runtime
        logger.warning("Gagal memuat %s: %s", path, e)
        return False
    return True


def ensure_env_loaded() -> Path | None:
    """Load secrets + `.env` tepat sekali per proses; idempoten & thread-safe.

    Urutan (yang lebih dulu menang): environment proses -> secrets pribadi ->
    `.env` repository. Return path utama yang dibaca (atau None bila tidak ada).
    Konvensi ``override=False`` sehingga shell/CI/launcher tidak pernah ditimpa.
    """
    global _loaded
    if _loaded:
        return ENV_PATH if ENV_PATH.exists() else (SECRETS_PATH if SECRETS_PATH.exists() else None)
    with _lock:
        if _loaded:
            return ENV_PATH if ENV_PATH.exists() else (SECRETS_PATH if SECRETS_PATH.exists() else None)
        _load_env_file(SECRETS_PATH)
        _load_env_file(ENV_PATH)
        _loaded = True
    if ENV_PATH.exists():
        return ENV_PATH
    return SECRETS_PATH if SECRETS_PATH.exists() else None


def env_file_paths() -> list[Path]:
    """Semua file env runtime, urut prioritas (private > repo).

    Dipakai pembacaan langsung (dashboard/CLI) agar file secret di luar
    repo ikut terbaca — bukan hanya `.env`.
    """
    paths: list[Path] = []
    if SECRETS_PATH.exists():
        paths.append(SECRETS_PATH)
    if ENV_PATH.exists() and ENV_PATH not in paths:
        paths.append(ENV_PATH)
    return paths


def active_env_path() -> Path:
    """Tujuan penulisan env baru: file privat bila ada, else `.env` repo."""
    return SECRETS_PATH if SECRETS_PATH.exists() else ENV_PATH


def env_str(name: str, default: str = "") -> str:
    ensure_env_loaded()
    value = os.getenv(name)
    return value.strip() if value is not None else default


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_str(name, "true" if default else "false")
    return raw.lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = env_str(name)
    try:
        value = int(raw) if raw else default
    except (TypeError, ValueError):
        logger.warning(f"Env {name}='{raw}' tidak valid; pakai default {default}")
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = env_str(name)
    try:
        value = float(raw) if raw else default
    except (TypeError, ValueError):
        logger.warning(f"Env {name}='{raw}' tidak valid; pakai default {default}")
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value
