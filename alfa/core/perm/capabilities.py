"""P2 Capability Security — grant berlingkup, berbatas waktu, dan berbatas pakai.

Layer ini duduk DI ATAS permission gate yang sudah ada:

- ``off``    : tidak menyimpan/memeriksa capability.
- ``shadow`` : grant dicatat, keputusan gate tidak diubah (default).
- ``on``     : grant valid otomatis menyetujui tool; bila
  ``ALFA_CAPABILITY_REQUIRED=true`` tool HIGH/CRITICAL tanpa grant ditolak.

Grant selalu terikat ke ``chat_id`` (dan ``user_id`` untuk audit), punya
``expires_at`` serta ``max_uses`` (0 = tanpa batas). Semua operasi fail-soft,
tetapi kegagalan validasi TIDAK pernah otomatis mengizinkan eksekusi.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any

from alfa.core.config import env_bool, env_int, env_str
from alfa.core.db.connection import get_sync_db

logger = logging.getLogger("CapabilitySecurity")

_DB_ERR = (
    sqlite3.Error,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    RuntimeError,
    UnicodeError,
    json.JSONDecodeError,
)

_DEFAULT_TTL_MINUTES = 60
_DEFAULT_MAX_USES = 10


def capability_mode() -> str:
    """Mode aktif: ``off`` | ``shadow`` | ``on``."""
    raw = env_str("ALFA_CAPABILITY_SECURITY", "shadow").strip().lower()
    if raw in {"1", "true", "yes"}:
        return "on"
    if raw in {"0", "false", "no"}:
        return "off"
    if raw in {"off", "shadow", "on"}:
        return raw
    return "shadow"


def capability_required() -> bool:
    """Apakah tool HIGH/CRITICAL wajib punya capability saat mode ``on``."""
    return env_bool("ALFA_CAPABILITY_REQUIRED", False)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grant_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 0,
            chat_id INTEGER NOT NULL DEFAULT 0,
            tool_name TEXT NOT NULL,
            scope_json TEXT DEFAULT '{}',
            max_uses INTEGER DEFAULT 0,
            uses INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL DEFAULT 0,
            revoked_at REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_capability_chat_tool "
        "ON capability_grants(chat_id, tool_name, expires_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_capability_grant "
        "ON capability_grants(grant_id)"
    )


def init_capability_tables() -> None:
    """Pastikan tabel capability ada."""
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.commit()
    except _DB_ERR as exc:
        logger.debug("init capability table dilewati: %s", exc)


def grant_capability_sync(
    chat_id: int,
    tool_name: str,
    *,
    user_id: int = 0,
    ttl_minutes: int | None = None,
    max_uses: int | None = None,
    scope: dict[str, Any] | None = None,
    note: str = "",
    source: str = "manual",
) -> dict[str, Any] | None:
    """Buat grant baru. Return ``None`` saat mode off atau input tidak valid."""
    if capability_mode() == "off":
        return None
    tool = str(tool_name or "").strip()
    if not tool:
        return None
    ttl = (
        env_int("ALFA_CAPABILITY_TTL_MINUTES", _DEFAULT_TTL_MINUTES, minimum=1)
        if ttl_minutes is None
        else max(1, int(ttl_minutes))
    )
    ttl = min(ttl, 10_080)  # maksimal 7 hari
    uses = (
        env_int("ALFA_CAPABILITY_MAX_USES", _DEFAULT_MAX_USES, minimum=0)
        if max_uses is None
        else max(0, int(max_uses))
    )
    now = time.time()
    grant_id = "cap_" + uuid.uuid4().hex[:12]
    try:
        scope_json = json.dumps(scope or {}, ensure_ascii=False, default=str)
    except (TypeError, ValueError, json.JSONDecodeError):
        scope_json = "{}"
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.execute(
                """
                INSERT INTO capability_grants
                    (grant_id, user_id, chat_id, tool_name, scope_json,
                     max_uses, uses, note, source, created_at, expires_at,
                     revoked_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 0)
                """,
                (
                    grant_id,
                    int(user_id or 0),
                    int(chat_id or 0),
                    tool,
                    scope_json,
                    uses,
                    str(note or "")[:300],
                    str(source or "manual")[:50],
                    now,
                    now + (ttl * 60),
                ),
            )
            conn.commit()
        return {
            "status": "ok",
            "grant_id": grant_id,
            "tool_name": tool,
            "chat_id": int(chat_id or 0),
            "user_id": int(user_id or 0),
            "ttl_minutes": ttl,
            "max_uses": uses,
            "expires_at": now + (ttl * 60),
            "mode": capability_mode(),
            "enforced": capability_mode() == "on",
        }
    except _DB_ERR as exc:
        logger.debug("Grant capability gagal: %s", exc)
        return None


def revoke_capability_sync(
    grant_id: str = "", *, chat_id: int = 0, tool_name: str = "", user_id: int = 0
) -> int:
    """Cabut grant berdasarkan id, atau semua grant tool di chat tertentu."""
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            now = time.time()
            if str(grant_id or "").strip():
                if user_id:
                    cursor = conn.execute(
                        "UPDATE capability_grants SET revoked_at = ? "
                        "WHERE grant_id = ? AND user_id = ? AND revoked_at = 0",
                        (now, str(grant_id).strip(), int(user_id)),
                    )
                else:
                    cursor = conn.execute(
                        "UPDATE capability_grants SET revoked_at = ? "
                        "WHERE grant_id = ? AND revoked_at = 0",
                        (now, str(grant_id).strip()),
                    )
            elif tool_name:
                cursor = conn.execute(
                    "UPDATE capability_grants SET revoked_at = ? "
                    "WHERE chat_id = ? AND tool_name = ? AND revoked_at = 0",
                    (now, int(chat_id or 0), str(tool_name).strip()),
                )
            else:
                return 0
            conn.commit()
            return max(0, int(cursor.rowcount or 0))
    except _DB_ERR as exc:
        logger.debug("Revoke capability gagal: %s", exc)
        return 0


def _row_to_dict(row: sqlite3.Row, now: float | None = None) -> dict[str, Any]:
    data = dict(row)
    now = time.time() if now is None else now
    expires_at = float(data.get("expires_at") or 0)
    max_uses = int(data.get("max_uses") or 0)
    uses = int(data.get("uses") or 0)
    revoked = float(data.get("revoked_at") or 0)
    data["expired"] = bool(expires_at and expires_at <= now)
    data["exhausted"] = bool(max_uses and uses >= max_uses)
    data["revoked"] = bool(revoked)
    data["valid"] = not (data["expired"] or data["exhausted"] or data["revoked"])
    try:
        scope = json.loads(str(data.get("scope_json") or "{}"))
        data["scope"] = scope if isinstance(scope, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        data["scope"] = {}
    return data


def list_capabilities_sync(
    *, chat_id: int = 0, tool_name: str = "", include_invalid: bool = True, limit: int = 50
) -> list[dict[str, Any]]:
    """Daftar grant terbaru (opsional per chat/tool)."""
    limit = max(1, min(int(limit), 200))
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            if chat_id and tool_name:
                rows = conn.execute(
                    "SELECT * FROM capability_grants "
                    "WHERE chat_id = ? AND tool_name = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (int(chat_id), str(tool_name).strip(), limit),
                ).fetchall()
            elif chat_id:
                rows = conn.execute(
                    "SELECT * FROM capability_grants WHERE chat_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (int(chat_id), limit),
                ).fetchall()
            elif tool_name:
                rows = conn.execute(
                    "SELECT * FROM capability_grants WHERE tool_name = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (str(tool_name).strip(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM capability_grants "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
    except _DB_ERR as exc:
        logger.debug("List capability gagal: %s", exc)
        return []
    else:
        now = time.time()
        results = [_row_to_dict(row, now) for row in rows]
        if not include_invalid:
            results = [item for item in results if item["valid"]]
        return results


def _find_valid_grant(
    conn: sqlite3.Connection, chat_id: int, tool_name: str
) -> sqlite3.Row | None:
    now = time.time()
    row: sqlite3.Row | None = conn.execute(
        """
        SELECT * FROM capability_grants
        WHERE chat_id = ? AND tool_name = ? AND revoked_at = 0
          AND (expires_at = 0 OR expires_at > ?)
          AND (max_uses = 0 OR uses < max_uses)
        ORDER BY expires_at ASC, id ASC LIMIT 1
        """,
        (int(chat_id or 0), str(tool_name).strip(), now),
    ).fetchone()
    return row


def inspect_capability_sync(
    chat_id: int, tool_name: str
) -> dict[str, Any]:
    """Periksa grant valid tanpa mengonsumsi kuota (read-only)."""
    mode = capability_mode()
    if mode == "off":
        return {"mode": mode, "allowed": False, "reason": "disabled"}
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            row = _find_valid_grant(conn, chat_id, tool_name)
            if row is None:
                return {"mode": mode, "allowed": False, "reason": "no_capability"}
            return {
                "mode": mode,
                "allowed": True,
                "reason": "capability",
                "grant": _row_to_dict(row),
            }
    except _DB_ERR as exc:
        logger.debug("Inspect capability gagal: %s", exc)
        return {"mode": mode, "allowed": False, "reason": "error", "error": str(exc)}


def consume_capability_sync(
    chat_id: int, tool_name: str, arguments_json: str = "{}"
) -> dict[str, Any]:
    """Konsumsi satu grant valid secara atomik.

    - ``shadow``: evaluasi tanpa mengonsumsi (agar observability tidak
      menghabiskan kuota); ``enforced`` selalu False.
    - ``on``: increment ``uses`` dalam ``BEGIN IMMEDIATE``; ``enforced`` True.
    """
    mode = capability_mode()
    if mode == "off":
        return {"mode": mode, "allowed": False, "reason": "disabled", "enforced": False}
    if mode == "shadow":
        result = inspect_capability_sync(chat_id, tool_name)
        result["enforced"] = False
        return result
    tool = str(tool_name or "").strip()
    if not tool:
        return {"mode": mode, "allowed": False, "reason": "invalid_tool", "enforced": True}
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = _find_valid_grant(conn, chat_id, tool)
            if row is None:
                conn.rollback()
                return {
                    "mode": mode,
                    "allowed": False,
                    "reason": "no_capability",
                    "enforced": True,
                }
            conn.execute(
                "UPDATE capability_grants SET uses = uses + 1 WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM capability_grants WHERE id = ?", (row["id"],)
            ).fetchone()
            data = _row_to_dict(updated) if updated else {}
            return {
                "mode": mode,
                "allowed": True,
                "reason": "capability",
                "enforced": True,
                "grant": data,
            }
    except _DB_ERR as exc:
        logger.debug("Consume capability gagal: %s", exc)
        return {
            "mode": mode,
            "allowed": False,
            "reason": "error",
            "enforced": True,
            "error": str(exc),
        }


def check_capability_for_tool(
    chat_id: int, tool_name: str, arguments_json: str = "{}"
) -> dict[str, Any]:
    """Keputusan capability untuk permission gate.

    Return dict dengan ``action``:
    - ``allow``  : auto-approve (mode on, grant valid; sudah dikonsumsi).
    - ``deny``   : tolak (mode on + required + tool HIGH/CRITICAL tanpa grant).
    - ``none``   : serahkan ke permission gate yang ada (shadow/off/optional).
    """
    mode = capability_mode()
    if mode == "off":
        return {"mode": mode, "action": "none", "reason": "disabled"}
    result = consume_capability_sync(chat_id, tool_name, arguments_json)
    if result.get("allowed"):
        if mode == "on":
            return {"mode": mode, "action": "allow", "reason": "capability", "result": result}
        return {"mode": mode, "action": "none", "reason": "shadow_capability"}

    if mode == "on" and capability_required() and result.get("reason") == "no_capability":
        try:
            from alfa.core.perm.constants import RiskTier
            from alfa.core.perm.gate import get_tool_tier

            tier = get_tool_tier(tool_name)
            if tier in (RiskTier.HIGH, RiskTier.CRITICAL):
                return {
                    "mode": mode,
                    "action": "deny",
                    "reason": "capability_required",
                    "tier": tier.value,
                }
        except (ImportError, AttributeError, ValueError, TypeError) as exc:
            logger.debug("Cek tier capability gagal: %s", exc)
            return {
                "mode": mode,
                "action": "deny",
                "reason": "capability_check_error",
            }
    return {
        "mode": mode,
        "action": "none",
        "reason": str(result.get("reason") or ""),
    }


def format_capability_status(chat_id: int) -> str:
    """Ringkasan untuk perintah /capability."""
    mode = capability_mode()
    grants = list_capabilities_sync(chat_id=chat_id, limit=20)
    valid = [item for item in grants if item["valid"]]
    return (
        f"• Capability Security: `{mode}` "
        f"(required={capability_required()})\n"
        f"• Grant di chat ini: {len(grants)} total, {len(valid)} valid"
    )


__all__ = [
    "capability_mode",
    "capability_required",
    "check_capability_for_tool",
    "consume_capability_sync",
    "format_capability_status",
    "grant_capability_sync",
    "init_capability_tables",
    "inspect_capability_sync",
    "list_capabilities_sync",
    "revoke_capability_sync",
]
