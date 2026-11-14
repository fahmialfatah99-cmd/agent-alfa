"""Evidence Ledger — bukti deterministik untuk setiap eksekusi tool.

Tabel SQLite aditif (``evidence_ledger``) yang mencatat tool, path artefak,
SHA-256 file, ukuran, cuplikan output, dan waktu. Desainnya mengikuti
``run_trace``: satu tabel baru, tidak mengubah skema lama, dan SELALU
gagal-lembut agar kegagalan pencatatan tidak pernah mengganggu jalur utama.

Mode diatur lewat ``ALFA_EVIDENCE_LEDGER``:

- ``off``    — tidak mencatat apa pun.
- ``shadow`` — mencatat bukti, TIDAK mengubah balasan (default).
- ``on``     — mencatat bukti dan menambahkan blok bukti ke balasan.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from alfa.core.config import env_int, env_str
from alfa.core.db.connection import get_sync_db
from alfa.core.runtime_ctx import (
    get_current_chat_id,
    get_current_turn_id,
    redact_sensitive,
    summarize_tool_args,
)

logger = logging.getLogger("DB.Evidence")

_TABLE = "evidence_ledger"

#: Batas ukuran file yang di-hash penuh (byte). File lebih besar hanya
#: dicatat ukurannya agar tool tidak melambat karena hashing file raksasa.
_MAX_HASH_BYTES = 64 * 1024 * 1024

#: Panjang cuplikan output yang disimpan (setelah redaksi rahasia).
_EXCERPT_LIMIT = 400

#: Prefix nama tool yang dianggap memutasi artefak.
_MUTATION_PREFIXES = (
    "write_",
    "edit_",
    "update_",
    "create_",
    "generate_",
    "save_",
    "delete_",
    "move_",
    "copy_",
    "upload_",
    "download_",
    "restore_",
    "extract_",
    "convert_",
    "compress_",
    "merge_",
    "split_",
    "record_",
    "tidy_",
    "append_",
)

#: Nama tool mutasi yang tidak mengikuti prefix di atas.
_MUTATION_TOOLS = frozenset(
    {
        "execute_bash_command",
        "ssh_execute_command",
        "git_commit",
        "git_push",
        "record_material_to_sheets",
        "boq_consolidate_master_workbook",
        "send_telegram_file",
        "send_whatsapp_message",
    }
)

#: Key output/argumen yang menunjuk ke artefak file.
_PATH_KEYS = frozenset(
    {
        "file_path",
        "output_path",
        "zip_path",
        "target_path",
        "image_path",
        "pdf_path",
        "backup_path",
        "restored_path",
        "restored_from",
        "saved_path",
        "destination",
        "dest_path",
        "source_path",
        "path",
        "filename",
    }
)

_SQL_CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS {t} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id TEXT NOT NULL DEFAULT '',
            chat_id INTEGER NOT NULL DEFAULT 0,
            tool TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'tool_exec',
            status TEXT NOT NULL DEFAULT 'success',
            path TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            excerpt TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL
        )
        """
_SQL_CREATE_TURN_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_evidence_turn "
    "ON {t} (turn_id, id DESC)"
)
_SQL_CREATE_TIME_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_evidence_created "
    "ON {t} (created_at DESC)"
)
_SQL_CREATE_PATH_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_evidence_path ON {t} (path)"
)
_SQL_INSERT = """
            INSERT INTO {t}
                (turn_id, chat_id, tool, action, status, path, sha256,
                 size_bytes, excerpt, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
_SQL_LIST_ALL = "SELECT * FROM {t} ORDER BY id DESC LIMIT ?"
_SQL_LIST_TURN = "SELECT * FROM {t} WHERE turn_id = ? ORDER BY id DESC LIMIT ?"
_SQL_LIST_PATH = "SELECT * FROM {t} WHERE path = ? ORDER BY id DESC LIMIT ?"
_SQL_LIST_TURN_PATH = (
    "SELECT * FROM {t} WHERE turn_id = ? AND path = ? "
    "ORDER BY id DESC LIMIT ?"
)
_SQL_COUNT = "SELECT COUNT(*) AS n FROM {t}"
_SQL_COUNT_SINCE = "SELECT COUNT(*) AS n FROM {t} WHERE created_at >= ?"
_SQL_BY_STATUS = (
    "SELECT status, COUNT(*) AS n FROM {t} "
    "WHERE created_at >= ? GROUP BY status ORDER BY n DESC"
)
_SQL_BY_TOOL = (
    "SELECT tool, COUNT(*) AS n FROM {t} "
    "WHERE created_at >= ? GROUP BY tool ORDER BY n DESC LIMIT ?"
)
_SQL_UNIQUE_PATHS = (
    "SELECT COUNT(DISTINCT path) AS n FROM {t} "
    "WHERE created_at >= ? AND path <> ''"
)
_SQL_LAST = "SELECT MAX(created_at) AS last FROM {t}"
_SQL_DELETE_OLD = "DELETE FROM {t} WHERE created_at < ?"
_SQL_DELETE_EXCESS = (
    "DELETE FROM {t} WHERE id NOT IN "
    "(SELECT id FROM {t} ORDER BY id DESC LIMIT ?)"
)

#: Retensi default: 90 hari / 100 ribu baris. 0 = nonaktif.
_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_MAX_ROWS = 100_000
_PRUNE_EVERY_WRITES = 100

_write_count = 0
_write_lock = threading.Lock()

#: Error realistis untuk pencatatan/ pembacaan evidence.
_EVIDENCE_ERR = (
    sqlite3.Error,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    RuntimeError,
    UnicodeError,
)


def _sql(template: str) -> str:
    """Ganti penampung {t} dengan nama tabel (konstanta modul, literal)."""
    return template.replace("{t}", _TABLE)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_sql(_SQL_CREATE_TABLE))
    conn.execute(_sql(_SQL_CREATE_TURN_INDEX))
    conn.execute(_sql(_SQL_CREATE_TIME_INDEX))
    conn.execute(_sql(_SQL_CREATE_PATH_INDEX))


def _retention_settings() -> tuple[int, int]:
    return (
        env_int(
            "ALFA_EVIDENCE_RETENTION_DAYS",
            _DEFAULT_RETENTION_DAYS,
            minimum=0,
        ),
        env_int(
            "ALFA_EVIDENCE_MAX_ROWS", _DEFAULT_MAX_ROWS, minimum=0
        ),
    )


def _prune_with_conn(
    conn: sqlite3.Connection, days: int, max_rows: int
) -> dict[str, int]:
    """Hapus evidence lama/berlebih pada koneksi yang sudah terbuka."""
    deleted_old = 0
    deleted_excess = 0
    if days > 0:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat(timespec="seconds")
        deleted_old = max(
            0, conn.execute(_sql(_SQL_DELETE_OLD), (cutoff,)).rowcount or 0
        )
    if max_rows > 0:
        deleted_excess = max(
            0,
            conn.execute(_sql(_SQL_DELETE_EXCESS), (max_rows,)).rowcount or 0,
        )
    return {"deleted_old": deleted_old, "deleted_excess": deleted_excess}


def prune_evidence_sync(
    days: int | None = None, max_rows: int | None = None
) -> dict[str, int | str]:
    """Bersihkan evidence lama/berlebih (retensi). Fail-soft."""
    env_days, env_max_rows = _retention_settings()
    days = env_days if days is None else max(0, int(days))
    max_rows = env_max_rows if max_rows is None else max(0, int(max_rows))
    result: dict[str, int | str] = {
        "status": "error",
        "deleted_old": 0,
        "deleted_excess": 0,
        "days": days,
        "max_rows": max_rows,
    }
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            deleted = _prune_with_conn(conn, days, max_rows)
            conn.commit()
        result = {"status": "ok", **deleted, "days": days, "max_rows": max_rows}
    except _EVIDENCE_ERR as exc:
        logger.debug("Prune evidence gagal: %s", exc)
    return result


def _maybe_prune(conn: sqlite3.Connection) -> None:
    """Prune oportunistik tiap 100 penulisan (murah, tidak tiap tool call)."""
    global _write_count
    try:
        with _write_lock:
            _write_count += 1
            due = _write_count % _PRUNE_EVERY_WRITES == 0
        if not due:
            return
        days, max_rows = _retention_settings()
        if days <= 0 and max_rows <= 0:
            return
        _prune_with_conn(conn, days, max_rows)
    except _EVIDENCE_ERR as exc:
        logger.debug("Auto-prune evidence gagal: %s", exc)


def ledger_mode() -> str:
    """Mode ledger aktif: ``off`` | ``shadow`` | ``on``."""
    raw = env_str("ALFA_EVIDENCE_LEDGER", "shadow").strip().lower()
    if raw in {"1", "true", "yes"}:
        return "on"
    if raw in {"0", "false", "no"}:
        return "off"
    if raw in {"off", "shadow", "on"}:
        return raw
    return "shadow"


def _parse_obj(value: Any) -> Any:
    """Parse JSON string bila memungkinkan; selain itu kembalikan apa adanya."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


def _is_mutating(tool: str, parsed_args: Any) -> bool:
    name = (tool or "").strip().lower()
    if name in _MUTATION_TOOLS or name.startswith(_MUTATION_PREFIXES):
        return True
    if isinstance(parsed_args, dict):
        if parsed_args.get("dry_run") is True:
            return True
        for key in ("mode", "action"):
            value = str(parsed_args.get(key) or "").lower()
            if value in {"write", "append", "replace", "upsert", "delete"}:
                return True
    return False


def _path_candidates(value: Any, depth: int = 0) -> list[str]:
    """Kumpulkan kandidat path dari struktur output/argumen (maks. depth 3)."""
    found: list[str] = []
    if depth > 3:
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                str(key).lower() in _PATH_KEYS
                and isinstance(item, str)
                and item.strip()
            ):
                found.append(item.strip())
            elif isinstance(item, (dict, list)):
                found.extend(_path_candidates(item, depth + 1))
    elif isinstance(value, (list, tuple)):
        for item in value[:20]:
            if isinstance(item, (dict, list, tuple)):
                found.extend(_path_candidates(item, depth + 1))
    return found


def _existing_paths(paths: list[str]) -> list[str]:
    """Normalisasi, dedup, dan saring path yang benar-benar ada."""
    result: list[str] = []
    for raw in paths:
        if not raw or "://" in raw or len(raw) > 1000:
            continue
        try:
            candidate = os.path.realpath(os.path.expanduser(raw))
        except (OSError, ValueError):
            continue
        if not os.path.isfile(candidate):
            continue
        if candidate not in result:
            result.append(candidate)
        if len(result) >= 8:
            break
    return result


def hash_file(path: str) -> tuple[str, int]:
    """SHA-256 + ukuran file. File terlalu besar hanya dicatat ukurannya."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "", 0
    if size > _MAX_HASH_BYTES:
        return "", size
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "", size
    return digest.hexdigest(), size


def _evidence_status(output: Any, status: str) -> str:
    parsed = _parse_obj(output)
    if isinstance(parsed, dict):
        if parsed.get("dry_run") is True:
            return "preview"
        if str(parsed.get("status") or "").lower() == "error":
            return "error"
    if status in {"error", "preview", "success"}:
        return status
    return "success"


def record_tool_evidence(
    tool: str,
    arguments: str = "",
    output: Any = "",
    status: str = "success",
) -> list[dict[str, Any]]:
    """Catat bukti satu eksekusi tool. Selalu fail-soft (return [] saat gagal).

    Hanya tool yang menyentuh artefak (path nyata) atau tool mutasi yang
    dicatat, agar ledger tidak membengkak oleh ribuan tool baca.
    """
    mode = ledger_mode()
    if mode == "off" or not tool:
        return []
    rows: list[dict[str, Any]] = []
    try:
        parsed_out = _parse_obj(output)
        parsed_args = _parse_obj(arguments)
        mutating = _is_mutating(tool, parsed_args)
        paths = _existing_paths(
            _path_candidates(parsed_out) + _path_candidates(parsed_args)
        )
        resolved_status = _evidence_status(parsed_out, status)
        if not paths and not mutating:
            return []
        if resolved_status == "error":
            # Jangan mengklaim hash file yang mungkin setengah tertulis.
            paths = []

        turn_id = get_current_turn_id()
        chat_id = get_current_chat_id()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if isinstance(output, str):
            excerpt_source = output
        else:
            excerpt_source = json.dumps(output, ensure_ascii=False, default=str)
        excerpt = redact_sensitive(excerpt_source, limit=_EXCERPT_LIMIT)
        meta = {
            "args": summarize_tool_args(arguments, limit=300),
            "mutating": mutating,
            "dry_run": resolved_status == "preview",
            "mode": mode,
        }
        with get_sync_db() as conn:
            _ensure_table(conn)
            for path in paths or [""]:
                sha256, size_bytes = hash_file(path) if path else ("", 0)
                conn.execute(
                    _sql(_SQL_INSERT),
                    (
                        turn_id,
                        int(chat_id or 0),
                        str(tool),
                        "tool_exec",
                        resolved_status,
                        path,
                        sha256,
                        int(size_bytes),
                        excerpt,
                        json.dumps(meta, ensure_ascii=False),
                        now,
                    ),
                )
                rows.append(
                    {
                        "turn_id": turn_id,
                        "chat_id": int(chat_id or 0),
                        "tool": str(tool),
                        "status": resolved_status,
                        "path": path,
                        "sha256": sha256,
                        "size_bytes": int(size_bytes),
                        "created_at": now,
                    }
                )
            _maybe_prune(conn)
            conn.commit()
        logger.debug(
            "evidence: %s status=%s paths=%d turn=%s",
            tool,
            resolved_status,
            len(paths),
            turn_id or "-",
        )
    except _EVIDENCE_ERR as exc:
        logger.debug("Pencatatan evidence tool '%s' gagal: %s", tool, exc)
        return []
    return rows


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw_meta = data.get("meta") or "{}"
    try:
        data["meta"] = dict(json.loads(raw_meta))
    except (ValueError, TypeError):
        data["meta"] = {}
    return data


def list_evidence_sync(
    limit: int = 50,
    turn_id: str = "",
    path: str = "",
) -> list[dict[str, Any]]:
    """Ambil bukti terbaru (opsional filter turn_id/path)."""
    limit = max(1, min(int(limit), 200))
    turn_id = (turn_id or "").strip()
    path = (path or "").strip()
    with get_sync_db() as conn:
        _ensure_table(conn)
        conn.row_factory = sqlite3.Row
        if turn_id and path:
            cursor = conn.execute(
                _sql(_SQL_LIST_TURN_PATH), (turn_id, path, limit)
            )
        elif turn_id:
            cursor = conn.execute(_sql(_SQL_LIST_TURN), (turn_id, limit))
        elif path:
            cursor = conn.execute(_sql(_SQL_LIST_PATH), (path, limit))
        else:
            cursor = conn.execute(_sql(_SQL_LIST_ALL), (limit,))
        rows = [_row_to_dict(row) for row in cursor.fetchall()]
    return rows


def turn_evidence_sync(turn_id: str) -> list[dict[str, Any]]:
    """Semua bukti untuk satu giliran (terbaru dulu)."""
    if not (turn_id or "").strip():
        return []
    return list_evidence_sync(limit=200, turn_id=turn_id)


def evidence_summary_sync(hours: int = 24, top_tools: int = 10) -> dict[str, Any]:
    """Ringkasan bukti untuk dashboard (read-only, anti-throwing)."""
    hours = max(1, min(int(hours), 24 * 30))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat(timespec="seconds")
    retention_days, max_rows = _retention_settings()
    summary: dict[str, Any] = {
        "mode": ledger_mode(),
        "hours": hours,
        "total": 0,
        "recent": 0,
        "unique_paths": 0,
        "by_status": {},
        "top_tools": [],
        "last_created_at": "",
        "retention_days": retention_days,
        "max_rows": max_rows,
    }
    try:
        with get_sync_db() as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            summary["total"] = int(
                conn.execute(_sql(_SQL_COUNT)).fetchone()["n"] or 0
            )
            summary["recent"] = int(
                conn.execute(_sql(_SQL_COUNT_SINCE), (cutoff,)).fetchone()["n"]
                or 0
            )
            summary["unique_paths"] = int(
                conn.execute(_sql(_SQL_UNIQUE_PATHS), (cutoff,)).fetchone()["n"]
                or 0
            )
            summary["by_status"] = {
                str(row["status"]): int(row["n"] or 0)
                for row in conn.execute(_sql(_SQL_BY_STATUS), (cutoff,))
            }
            summary["top_tools"] = [
                {"tool": str(row["tool"]), "count": int(row["n"] or 0)}
                for row in conn.execute(
                    _sql(_SQL_BY_TOOL), (cutoff, max(1, min(top_tools, 50)))
                )
            ]
            last_row = conn.execute(_sql(_SQL_LAST)).fetchone()
            summary["last_created_at"] = str(last_row["last"] or "") if last_row else ""
    except _EVIDENCE_ERR as exc:
        logger.debug("Ringkasan evidence gagal: %s", exc)
        summary["error"] = "evidence summary unavailable"
    return summary


def _human_size(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def proof_block_for_turn(turn_id: str, max_items: int = 5) -> str:
    """Format blok bukti ringkas untuk balasan (string kosong bila tidak ada)."""
    rows = turn_evidence_sync(turn_id)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        path = str(row.get("path") or "")
        status = str(row.get("status") or "")
        if not path or status not in {"success", "preview"}:
            continue
        key = (str(row.get("tool") or ""), path, str(row.get("sha256") or ""))
        if key in seen:
            continue
        seen.add(key)
        items.append(row)
        if len(items) >= max(1, min(int(max_items), 10)):
            break
    if not items:
        return ""
    lines = ["🔐 *Bukti eksekusi (evidence ledger):*"]
    for row in items:
        tool = str(row.get("tool") or "?").replace("`", "'")
        path = str(row.get("path") or "").replace("`", "'")
        sha = str(row.get("sha256") or "")
        label = "preview" if row.get("status") == "preview" else "ok"
        if sha:
            digest = f"sha256 `{sha[:12]}…`"
        else:
            digest = "sha256 (file besar, tidak di-hash)"
        size = _human_size(int(row.get("size_bytes") or 0))
        lines.append(f"• `{tool}` · `{path}` · {digest} · {size} · {label}")
    return "\n".join(lines)


def decorate_with_evidence(reply: str, turn_id: str = "") -> str:
    """Tambahkan blok bukti ke balasan bila mode ``on`` dan ada bukti.

    Idempoten dan fail-soft: pada mode ``shadow`` hanya mencatat log; pada
    error apa pun balasan asli dikembalikan tanpa perubahan.
    """
    if not isinstance(reply, str) or not reply:
        return reply
    try:
        mode = ledger_mode()
        turn_id = (turn_id or get_current_turn_id()).strip()
        if mode == "off" or not turn_id:
            return reply
        block = proof_block_for_turn(turn_id)
        if not block:
            return reply
        if mode == "shadow":
            logger.debug("evidence shadow turn=%s\n%s", turn_id, block)
            return reply
        if "Bukti eksekusi (evidence ledger)" in reply:
            return reply
        return f"{reply.rstrip()}\n\n{block}"
    except _EVIDENCE_ERR as exc:
        logger.debug("Dekorasi evidence gagal: %s", exc)
        return reply


__all__ = [
    "decorate_with_evidence",
    "evidence_summary_sync",
    "hash_file",
    "ledger_mode",
    "list_evidence_sync",
    "proof_block_for_turn",
    "prune_evidence_sync",
    "record_tool_evidence",
    "turn_evidence_sync",
]
