"""
ALFA Security Module - Centralized security utilities and configurations.
"""

# Re-export security constants and utilities
from .bash_blacklist import BASH_DESTRUCTIVE_PATTERNS, is_command_blocked, get_block_reason
from .encryption import encrypt_api_key, decrypt_api_key, setup_vault_encryption

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
