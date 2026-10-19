"""Database persistence, trust scoring, and always-allow permissions store."""

import sqlite3
import time

from alfa.core.perm.constants import DB_PATH, logger


def _get_db_path() -> str:
    """Resolusi path DB — resolver tunggal (``alfa/core/db/paths.py``).

    Versi lama hanya menghormati ``ALFA_DB_PATH`` dan mengabaikan
    ``DATABASE_URL``, sehingga permission store bisa mendarat di database
    yang berbeda dari data yang dilindunginya.
    """
    from alfa.core.db.paths import resolve_db_path

    return resolve_db_path(fallback=DB_PATH)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS tool_permissions(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               permission_type TEXT DEFAULT 'always',
               created_at REAL,
               expires_at REAL,
               UNIQUE(chat_id, tool_name))""")
    # Add audit trail table
    conn.execute("""CREATE TABLE IF NOT EXISTS permission_audit(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               chat_id INTEGER NOT NULL,
               tool_name TEXT NOT NULL,
               tier TEXT,
               decision TEXT,
               arguments_json TEXT,
               created_at REAL,
               response_time_sec REAL)""")
    # Add trust score table
    conn.execute("""CREATE TABLE IF NOT EXISTS user_trust_scores(
               chat_id INTEGER PRIMARY KEY,
               trust_score REAL DEFAULT 0.5,
               total_approvals INTEGER DEFAULT 0,
               safe_approvals INTEGER DEFAULT 0,
               risky_approvals INTEGER DEFAULT 0,
               last_updated REAL)""")
    # Trust per-tier: skor dihitung per (chat_id, tier) supaya persetujuan
    # tool LOW tidak pernah menaikkan confianza tool HIGH/CRITICAL.
    conn.execute("""CREATE TABLE IF NOT EXISTS user_tier_trust(
               chat_id INTEGER NOT NULL,
               tier TEXT NOT NULL,
               trust_score REAL DEFAULT 0.5,
               total_approvals INTEGER DEFAULT 0,
               safe_approvals INTEGER DEFAULT 0,
               risky_approvals INTEGER DEFAULT 0,
               last_updated REAL,
               PRIMARY KEY(chat_id, tier))""")
    return conn


def get_trust_score(chat_id: int | None) -> float:
    """Get user's global trust score (0.0 - 1.0).

    Nilai ini hanya untuk ditampilkan/diagnostic. Keputusan auto-approve
    memakai skor per-tier via :func:`get_tier_trust`.
    """
    if chat_id is None:
        return 0.0
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT trust_score FROM user_trust_scores WHERE chat_id=?",
                (int(chat_id),),
            ).fetchone()
        return float(row[0]) if row else 0.5
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"get trust score gagal: {e}")
        return 0.5


def get_tier_trust(chat_id: int | None, tier: str) -> tuple[float, int]:
    """Trust score + jumlah persetujuan eksplisit untuk satu tier.

    Return ``(trust_score, explicit_approvals)``. ``trust_score`` 0.0 bila
    chat belum punya catatan; ``explicit_approvals`` adalah banyaknya
    persetujuan manusia eksplisit ("once"/"always") pada tier tersebut.
    """
    if chat_id is None:
        return 0.0, 0
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT trust_score, total_approvals FROM user_tier_trust "
                "WHERE chat_id=? AND tier=?",
                (int(chat_id), str(tier)),
            ).fetchone()
        if not row:
            return 0.0, 0
        return float(row[0]), int(row[1])
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"get tier trust gagal: {e}")
        return 0.0, 0


def update_tier_trust(
    chat_id: int,
    tier: str,
    was_safe: bool,
    response_time: float,
) -> None:
    """Perbarui trust score KHVATUR (chat_id, tier).

    Hanya dipanggil untuk keputusan manusia EKSPLISIT: "once"/"always"
    (``was_safe=True``) atau "deny" (``was_safe=False``). Auto-approve TIDAK
    pernah menaikkan skor — jika tidak, satu tool LOW yang auto-lolos akan
    menaikkan trust ke 1.0 dan membuka tool CRITICAL tanpa persetujuan.

    Risiko tool sudah tercermin di dimensi ``tier``; di dalam satu tier,
    ``was_safe`` berarti "user mengizinkan" vs "user menolak".
    """
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT trust_score, total_approvals, safe_approvals, risky_approvals "
                "FROM user_tier_trust WHERE chat_id=? AND tier=?",
                (int(chat_id), str(tier)),
            ).fetchone()
            if row:
                _, total, safe, risky = row
            else:
                _, total, safe, risky = 0.5, 0, 0, 0

            total += 1
            if was_safe:
                safe += 1
            else:
                risky += 1

            # Rasio persetujuan eksplisit vs penolakan pada tier ini.
            base_ratio = safe / total if total > 0 else 0.5
            speed_bonus = max(0.0, 0.02 * (1.0 - min(response_time, 300.0) / 300.0))
            new_trust = min(1.0, max(0.0, base_ratio + speed_bonus))

            conn.execute(
                """INSERT OR REPLACE INTO user_tier_trust
                   (chat_id, tier, trust_score, total_approvals, safe_approvals,
                    risky_approvals, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(chat_id),
                    str(tier),
                    new_trust,
                    total,
                    safe,
                    risky,
                    time.time(),
                ),
            )
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"update tier trust gagal: {e}")


def update_trust_score(chat_id: int, was_safe: bool, response_time: float) -> None:
    """Update user's trust score based on their decision."""
    try:
        with _connect() as conn:
            # Get current stats
            row = conn.execute(
                "SELECT trust_score, total_approvals, safe_approvals, risky_approvals "
                "FROM user_trust_scores WHERE chat_id=?",
                (int(chat_id),),
            ).fetchone()

            if row:
                _, total, safe, risky = row
            else:
                _, total, safe, risky = 0.5, 0, 0, 0

            # Update counters
            total += 1
            if was_safe:
                safe += 1
            else:
                risky += 1

            # Calculate new trust score (simple heuristic)
            # More safe decisions = higher trust.
            # Speed bonus: full when responding instantly, decaying linearly
            # to zero at 5 minutes (previously a constant due to min-cap bug).
            base_ratio = safe / total if total > 0 else 0.5
            speed_bonus = max(0.0, 0.02 * (1.0 - min(response_time, 300.0) / 300.0))
            new_trust = min(1.0, max(0.0, base_ratio + speed_bonus))

            conn.execute(
                """INSERT OR REPLACE INTO user_trust_scores
                   (chat_id, trust_score, total_approvals, safe_approvals, risky_approvals, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (int(chat_id), new_trust, total, safe, risky, time.time()),
            )
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"update trust score gagal: {e}")


def log_permission_decision(
    chat_id: int,
    tool_name: str,
    tier: str,
    decision: str,
    args_json: str,
    response_time: float,
) -> None:
    """Log permission decision for audit trail."""
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO permission_audit
                   (chat_id, tool_name, tier, decision, arguments_json, created_at, response_time_sec)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(chat_id),
                    tool_name,
                    tier,
                    decision,
                    args_json,
                    time.time(),
                    response_time,
                ),
            )
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"log audit trail gagal: {e}")


def is_always_allowed(chat_id: int | None, tool_name: str) -> bool:
    if chat_id is None:
        return False
    try:
        with _connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM tool_permissions
                   WHERE chat_id=? AND tool_name=?
                   AND (permission_type='always' OR (permission_type='session' AND expires_at > ?))""",
                (int(chat_id), tool_name, time.time()),
            ).fetchone()
        return row is not None
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"cek tool_permissions gagal (lolos-aman): {e}")
        return False


def save_always_allow(
    chat_id: int, tool_name: str, perm_type: str = "always", duration_hours: int = 24
) -> None:
    """Save permission with type and optional expiration."""
    try:
        expires_at = (
            time.time() + (duration_hours * 3600) if perm_type == "session" else None
        )
        with _connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tool_permissions
                   (chat_id, tool_name, permission_type, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (int(chat_id), tool_name, perm_type, time.time(), expires_at),
            )
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning(f"simpan tool_permissions gagal: {e}")


def list_always_allowed(chat_id: int) -> list[str]:
    try:
        with _connect() as conn:
            return [
                r[0]
                for r in conn.execute(
                    """SELECT tool_name FROM tool_permissions
                   WHERE chat_id=? AND (permission_type='always'
                   OR (permission_type='session' AND expires_at > ?))
                   ORDER BY tool_name""",
                    (int(chat_id), time.time()),
                ).fetchall()
            ]
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return []
