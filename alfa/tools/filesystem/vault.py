"""Secure vault credential and secrets management tools."""

import logging
from typing import Any

from alfa.tools.registry import register_tool

logger = logging.getLogger("AgentTools.Filesystem.Vault")


@register_tool(category="file")
def vault_store_secret(
    name: str, value: str, category: str = "api_key", notes: str = ""
) -> dict[str, Any]:
    """
    Encrypt and store a sensitive credential, API key, affiliate token, or secret note
    into αlfa Secure Vault with AES-256-GCM authenticated encryption.

    Args:
        name: Unique identifier name for the secret (e.g. 'KLING_AI_KEY', 'SHOPEE_COOKIE', 'DB_PASSWORD').
        value: Secret text/token/key to encrypt and store securely.
        category: Category of secret ('api_key', 'affiliate', 'password', 'note').
        notes: Optional description or context about the secret.
    """
    try:
        from alfa.security import vault as vault_engine

        res = vault_engine.vault.store_secret(
            name=name, value=value, category=category, notes=notes
        )
        return res
    except Exception as e:
        return {"status": "error", "message": f"Vault store error: {str(e)}"}


@register_tool(category="file")
def vault_get_secret(name_or_id: str) -> dict[str, Any]:
    """
    Retrieve and decrypt a sensitive secret from αlfa Secure Vault using AES-256-GCM.

    Args:
        name_or_id: The unique name or ID of the secret to decrypt.
    """
    try:
        from alfa.security import vault as vault_engine

        sec = vault_engine.vault.get_secret(name_or_id)
        if not sec:
            return {
                "status": "error",
                "message": f"Secret '{name_or_id}' tidak ditemukan di dalam vault.",
            }
        return {
            "status": "success",
            "name": sec["name"],
            "category": sec["category"],
            "value": sec["value"],
            "notes": sec["notes"],
            "updated_at": sec["updated_at"],
        }
    except Exception as e:
        return {"status": "error", "message": f"Vault retrieval error: {str(e)}"}


@register_tool(category="file")
def vault_list_secrets(category: str = "all") -> dict[str, Any]:
    """
    List all stored secrets metadata in αlfa Secure Vault without exposing decrypted plaintext.

    Args:
        category: Filter by category ('all', 'api_key', 'affiliate', 'password', 'note').
    """
    try:
        from alfa.security import vault as vault_engine

        items = vault_engine.vault.list_secrets(category=category)
        return {
            "status": "success",
            "total_secrets": len(items),
            "encryption": "AES-256-GCM (Authenticated)",
            "secrets": items,
        }
    except Exception as e:
        return {"status": "error", "message": f"Vault list error: {str(e)}"}


@register_tool(category="file")
def vault_delete_secret(secret_id: int) -> dict[str, Any]:
    """
    Permanently delete a secret from αlfa Secure Vault by ID.

    Args:
        secret_id: Numeric ID of the secret to delete.
    """
    try:
        from alfa.security import vault as vault_engine

        deleted = vault_engine.vault.delete_secret(int(secret_id))
        if deleted:
            return {
                "status": "success",
                "message": f"Secret ID {secret_id} berhasil dihapus permanen dari vault.",
            }
        return {"status": "error", "message": f"Secret ID {secret_id} tidak ditemukan."}
    except Exception as e:
        return {"status": "error", "message": f"Vault delete error: {str(e)}"}
