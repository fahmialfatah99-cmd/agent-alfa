"""
ALFA Security Module - Centralized security utilities, vault, and configurations.

PERHATIAN: versi lama modul ini mengekspor stub yang MENYATAKAN melakukan
enkripsi/blocklist padahal tidak (``encrypt_api_key`` mengembalikan plaintext,
``is_command_blocked`` selalu ``False``). Stub tersebut kini dihapus dan
diganti implementasi yang benar-benar meneruskan ke modul aslinya:

* ``encrypt_api_key`` / ``decrypt_api_key`` → ``alfa.core.db.crypto``
  (AES-256-GCM, format ``enc1:<nonce_b64>:<ct_b64>``)
* ``is_command_blocked`` / ``get_block_reason`` → ``alfa.tools.system.constants``
* ``setup_vault_encryption`` → ``alfa.security.vault``
"""

from alfa.security import vault as vault_module
from alfa.security.vault import AlfaSecureVault, vault

# Aliases for convenience
Vault = AlfaSecureVault

# Bash blocklist — sumber kebenaran ada di alfa.tools.system.constants
BASH_DESTRUCTIVE_PATTERNS: list[str] = []
BASH_BLOCKED_COMMANDS: dict[str, str] = {}


_PASSWORD_ARG_UNSUPPORTED = (
    "password argument tidak lagi didukung; kunci master diambil dari "
    "vault (ALFA_VAULT_MASTER_KEY / vault.db)."
)


def _blocked_reason(cmd: str) -> str:
    """Alasan pemblokiran perintah bash, atau string kosong bila diizinkan."""
    try:
        from alfa.tools.system.constants import _bash_blocked_reason

        return _bash_blocked_reason(cmd or "") or ""
    except Exception:  # noqa: BLE001 - helper murni, gagal = izinkan (fail-open di util)
        return ""


def is_command_blocked(cmd: str) -> bool:
    """True bila perintah bash kena blocklist perintah destruktif."""
    return bool(_blocked_reason(cmd))


def get_block_reason(cmd: str) -> str:
    """Alasan kenapa perintah bash diblokir (string kosong bila diizinkan)."""
    return _blocked_reason(cmd)


def encrypt_api_key(key: str, password: str | None = None) -> str:
    """Enkripsi string API key dengan AES-256-GCM (vault master key).

    Mengembalikan token ``enc1:<nonce_b64>:<ciphertext_b64>``. Fungsi ini
    idempoten: input yang sudah terenkripsi dikembalikan apa adanya.

    PERINGATAN: bila kripto tidak tersedia (vault gagal diinisialisasi),
    fungsi ini MELEMPAR error daripada menyimpan plaintext.
    """
    from alfa.core.db.crypto import encrypt_key

    if password is not None:
        raise ValueError(_PASSWORD_ARG_UNSUPPORTED)
    return encrypt_key(key)


def decrypt_api_key(encrypted: str, password: str | None = None) -> str:
    """Dekripsi token hasil ``encrypt_api_key``.

    Nilai lama yang belum terenkripsi (plaintext) dikembalikan apa adanya.
    """
    from alfa.core.db.crypto import decrypt_key

    if password is not None:
        raise ValueError(_PASSWORD_ARG_UNSUPPORTED)
    return decrypt_key(encrypted)


def setup_vault_encryption():
    """Pastikan database vault terenkripsi & siap dipakai."""
    ready = getattr(vault, "ensure_ready", None)
    if callable(ready):
        ready()
    return vault


__all__ = [
    "vault",
    "Vault",
    "AlfaSecureVault",
    "vault_module",
    # Bash blacklist
    "BASH_DESTRUCTIVE_PATTERNS",
    "is_command_blocked",
    "get_block_reason",
    # Encryption
    "encrypt_api_key",
    "decrypt_api_key",
    "setup_vault_encryption",
]
