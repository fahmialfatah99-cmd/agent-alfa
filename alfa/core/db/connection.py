"""
Database Connection Pooling, Session Context, and Schema Initialization for ALFA.
"""

import contextlib
import logging
import os
import sqlite3
import sys
import threading
from collections import deque

logger = logging.getLogger("DB.Connection")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DB_PATH = os.getenv("ALFA_DB_PATH", os.path.join(REPO_ROOT, "agent_data.db"))

_POOL_SIZE = int(os.getenv("ALFA_DB_POOL_SIZE", "10"))
_POOL_TIMEOUT = float(os.getenv("ALFA_DB_POOL_TIMEOUT", "30.0"))


def _get_db_path() -> str:
    """Dynamically resolve current DB_PATH, supporting test monkeypatching."""
    for mod_name in ("database", "alfa.core.database"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "DB_PATH"):
            return mod.DB_PATH
    return DB_PATH


class ConnectionPool:
    """Thread-safe SQLite connection pool with lazy initialization."""

    def __init__(self, db_path: str, pool_size: int = 10, timeout: float = 30.0):
        self.db_path = db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self._pool = deque(maxlen=pool_size)
        self._lock = threading.Lock()
        self._created = 0
        self._in_use = 0

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new optimized SQLite connection."""
        conn = sqlite3.connect(
            self.db_path, timeout=self.timeout, check_same_thread=False
        )
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.row_factory = sqlite3.Row
        return conn

    def acquire(self) -> sqlite3.Connection:
        """Acquire a connection from the pool (blocking if necessary)."""
        with self._lock:
            if self._pool:
                conn = self._pool.popleft()
                self._in_use += 1
                return conn

            if self._created < self.pool_size:
                self._created += 1
                self._in_use += 1
                return self._create_connection()

        import time

        start = time.time()
        while time.time() - start < self.timeout:
            with self._lock:
                if self._pool:
                    conn = self._pool.popleft()
                    self._in_use += 1
                    return conn
            time.sleep(0.01)

        raise TimeoutError(f"Connection pool exhausted (timeout={self.timeout}s)")

    def release(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool."""
        with self._lock:
            self._in_use -= 1
            if len(self._pool) < self.pool_size:
                try:
                    conn.execute("SELECT 1")
                    self._pool.append(conn)
                    return
                except Exception:
                    pass
            conn.close()

    def close_all(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            while self._pool:
                conn = self._pool.popleft()
                conn.close()

    @property
    def stats(self) -> dict[str, int]:
        """Return pool statistics."""
        with self._lock:
            return {
                "created": self._created,
                "in_use": self._in_use,
                "available": len(self._pool),
                "pool_size": self.pool_size,
            }


_db_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_connection_pool() -> ConnectionPool:
    """Get or create the global connection pool."""
    global _db_pool
    current_path = _get_db_path()
    if _db_pool is None or _db_pool.db_path != current_path:
        with _pool_lock:
            if _db_pool is None or _db_pool.db_path != current_path:
                _db_pool = ConnectionPool(current_path, _POOL_SIZE, _POOL_TIMEOUT)
    return _db_pool


def get_sync_db(timeout: float = 30.0):
    """Get a synchronous SQLite connection wrapped so `with` blocks close it."""
    conn = sqlite3.connect(_get_db_path(), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return contextlib.closing(conn)


def init_db_sync():
    """Synchronously ensure all SQLite tables and indices exist."""
    from alfa.core.db.crypto import encrypt_key, migrate_encrypt_api_keys

    db_path = _get_db_path()
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS knowledge_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT DEFAULT 'general',
                key_topic TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, key_topic)
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                reminder_time TEXT NOT NULL,
                message TEXT NOT NULL,
                is_executed INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS scheduled_cron_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                prompt_instruction TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                is_active INTEGER DEFAULT 1,
                last_run DATETIME,
                next_run DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS subagent_tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                result TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                voice_reply INTEGER DEFAULT 0,
                system_prompt_override TEXT,
                model_name TEXT DEFAULT 'gemini-3.6-flash'
            );
            CREATE TABLE IF NOT EXISTS knowledge_graph (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, entity, relation)
            );
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_time DATETIME NOT NULL,
                status TEXT DEFAULT 'active',
                notes TEXT,
                is_notified INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                api_key TEXT NOT NULL,
                base_url TEXT,
                default_model TEXT NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS custom_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL,
                persona TEXT NOT NULL,
                system_instruction TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'gemini',
                model TEXT NOT NULL DEFAULT 'gemini-3.6-flash',
                api_key_id INTEGER,
                avatar_emoji TEXT DEFAULT '🤖',
                color_theme TEXT DEFAULT 'cyan',
                is_enabled INTEGER DEFAULT 1,
                enable_tools INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
            );
            CREATE TABLE IF NOT EXISTS agent_meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                topic TEXT NOT NULL,
                participants TEXT NOT NULL,
                dialogue_transcript TEXT NOT NULL,
                consensus TEXT,
                action_plan TEXT,
                mode TEXT DEFAULT 'plan',
                execution_results TEXT DEFAULT '',
                status TEXT DEFAULT 'completed',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS agent_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER,
                agent_name TEXT NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                tool_name TEXT,
                tool_input TEXT,
                tool_output TEXT,
                status TEXT DEFAULT 'success',
                duration_ms REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS api_token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                provider TEXT NOT NULL,
                model TEXT DEFAULT '',
                key_id INTEGER,
                key_label TEXT DEFAULT '',
                context TEXT DEFAULT '',
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_atu_ts ON api_token_usage(ts);
            CREATE INDEX IF NOT EXISTS idx_atu_key ON api_token_usage(key_id);
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );
        """)

        # Seed default API key from environment if empty
        row = conn.execute("SELECT COUNT(*) as count FROM api_keys").fetchone()
        if row and row[0] == 0:
            env_gemini_key = os.getenv("GEMINI_API_KEY", "")
            if env_gemini_key:
                conn.execute(
                    """
                    INSERT INTO api_keys (name, provider, api_key, default_model, is_active)
                    VALUES ('Default Gemini Key', 'gemini', ?, 'gemini-3.6-flash', 1)
                    """,
                    (encrypt_key(env_gemini_key),),
                )

        # Seed default autonomous workforce agents if empty
        agent_count = conn.execute(
            "SELECT COUNT(*) as count FROM custom_agents"
        ).fetchone()
        if agent_count and agent_count[0] == 0:
            try:
                from alfa.swarm.personas import AGENTS as _AG
                from alfa.swarm.personas import DNA as _DNA

                _seed_persona = {
                    aid: d["system_instruction"].replace("{DNA}", _DNA)
                    for aid, d in _AG.items()
                }
                _seed_meta = {aid: d["persona"] for aid, d in _AG.items()}
            except Exception:
                _seed_persona, _seed_meta = {}, {}
            default_agents = [
                (
                    "Alpha Lead",
                    "Chief Orchestrator & War Room Conductor",
                    _seed_meta.get(1, "Koordinator tim ALFA."),
                    _seed_persona.get(
                        1, "Kamu adalah Alpha Lead, koordinator tim ALFA."
                    ),
                    "gemini",
                    "gemini-3.7-flash",
                    "👑",
                    "cyan",
                ),
                (
                    "Code Crafter",
                    "Principal Systems & Code Engineer",
                    _seed_meta.get(2, "Engineer kode ALFA."),
                    _seed_persona.get(
                        2, "Kamu adalah Code Crafter, engineer kode ALFA."
                    ),
                    "gemini",
                    "gemini-3.6-flash",
                    "⚡",
                    "emerald",
                ),
                (
                    "System Auditor",
                    "Security, Logic & Quality Critic",
                    _seed_meta.get(3, "Pengkritik kritis ALFA."),
                    _seed_persona.get(
                        3, "Kamu adalah System Auditor, penguji kritis ALFA."
                    ),
                    "gemini",
                    "gemini-3.6-flash",
                    "🛡️",
                    "rose",
                ),
                (
                    "Researcher Prime",
                    "Deep Intel & Fact-Checking Specialist",
                    _seed_meta.get(4, "Intel riset ALFA."),
                    _seed_persona.get(
                        4, "Kamu adalah Researcher Prime, spesialis riset ALFA."
                    ),
                    "gemini",
                    "gemini-3.6-flash",
                    "🌐",
                    "violet",
                ),
                (
                    "Strategic Planner",
                    "Product Strategist & UX Visionary",
                    _seed_meta.get(5, "Perancang strategi ALFA."),
                    _seed_persona.get(
                        5, "Kamu adalah Strategic Planner, perancang strategi ALFA."
                    ),
                    "gemini",
                    "gemini-3.6-flash",
                    "💡",
                    "amber",
                ),
                (
                    "Laguna Co-Pilot",
                    "First-Response Co-Pilot & Triage Specialist",
                    _seed_meta.get(6, "Garda depan triase ALFA."),
                    _seed_persona.get(
                        6, "Kamu adalah Laguna Co-Pilot, triase cepat ALFA."
                    ),
                    "gemini",
                    "gemini-3.6-flash",
                    "🚀",
                    "teal",
                ),
            ]
            for (
                name,
                role,
                persona,
                sys_inst,
                prov,
                model,
                emoji,
                color,
            ) in default_agents:
                conn.execute(
                    """
                    INSERT INTO custom_agents (name, role, persona, system_instruction, provider, model, avatar_emoji, color_theme, is_enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (name, role, persona, sys_inst, prov, model, emoji, color),
                )

        try:
            conn.execute(
                "ALTER TABLE agent_meetings ADD COLUMN mode TEXT DEFAULT 'plan'"
            )
        except Exception:
            pass
        try:
            conn.execute(
                "ALTER TABLE agent_meetings ADD COLUMN execution_results TEXT DEFAULT ''"
            )
        except Exception:
            pass
        try:
            conn.execute(
                "ALTER TABLE custom_agents ADD COLUMN enable_tools INTEGER DEFAULT 0"
            )
        except Exception:
            pass

        conn.commit()
    finally:
        conn.close()

    try:
        migrate_encrypt_api_keys()
    except Exception as _mig_err:
        logger.warning(f"migrate_encrypt_api_keys gagal: {_mig_err}")


async def init_db():
    """Initialize SQLite database tables and enable WAL mode (async wrapper)."""
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, init_db_sync)
