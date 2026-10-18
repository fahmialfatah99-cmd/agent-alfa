"""Service konfigurasi terpusat — satu-satunya titik load `.env`.

Sebelumnya `load_dotenv()` dipanggil dari 6 modul berbeda dengan untaian
serak-up: yang pertama kali diimpor menang, path resolusi tidak konsisten
(beberapa memakai CWD), dan urutan impor memicu error halus (mis. `# noqa:
E402` yang tersisa di dashboard). Modul ini menyeragamkan:

- `.env` dibaca **satu kali per proses** dari `REPO_ROOT/.env`
- `override=False` — varian env yang sudah diset (CI/test/CLI) SELALU menang
- Aman direkan-rekan dari modul mana pun: `ensure_env_loaded()`
- Baca env dengan default/validasi: `env_str`, `env_int`, `env_float`, `env_bool`
"""

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("Core.Config")

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

_loaded = False
_lock = threading.Lock()


def ensure_env_loaded() -> Path | None:
    """Load `.env` tepat sekali per proses; idempoten & thread-safe.

    Return path yang dibaca (atau None bila file tidak ada).
    Konvensi: override=False sehingga seluruh env yang sudah ada
    (shell/CI/launcher) tidak pernah ditimpa oleh `.env`.
    """
    global _loaded
    if _loaded:
        return ENV_PATH if ENV_PATH.exists() else None
    with _lock:
        if _loaded:
            return ENV_PATH if ENV_PATH.exists() else None
        try:
            from dotenv import load_dotenv

            if ENV_PATH.exists():
                load_dotenv(ENV_PATH, override=False)
                logger.debug(f".env dimuat dari {ENV_PATH}")
            else:
                logger.debug(f".env tidak ditemukan di {ENV_PATH} (skip)")
        except Exception as e:  # dotenv tidak wajib untuk runtime
            logger.warning(f"Gagal memuat .env: {e}")
        _loaded = True
    return ENV_PATH if ENV_PATH.exists() else None


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
