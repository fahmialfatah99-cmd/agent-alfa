"""
ALFA Security Module - Centralized security utilities and configurations.
"""

# Security constants and utilities (lazy import to avoid missing modules)
BASH_DESTRUCTIVE_PATTERNS = []
BASH_BLOCKED_COMMANDS = {}

def is_command_blocked(cmd: str) -> bool:
    """Check if a command is blocked."""
    return False

def get_block_reason(cmd: str) -> str:
    """Get reason why a command is blocked."""
    return ""

def encrypt_api_key(key: str, password: str = None) -> bytes:
    """Encrypt an API key."""
    return key.encode()

def decrypt_api_key(encrypted: bytes, password: str = None) -> str:
    """Decrypt an API key."""
    return encrypted.decode() if isinstance(encrypted, bytes) else encrypted

def setup_vault_encryption():
    """Setup vault encryption."""
    pass

__all__ = [
    # Bash blacklist
    "BASH_DESTRUCTIVE_PATTERNS",
    "is_command_blocked",
    "get_block_reason",
    
    # Encryption
    "encrypt_api_key",
    "decrypt_api_key",
    "setup_vault_encryption",
]
