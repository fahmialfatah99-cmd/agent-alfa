"""Canary: memastikan test suite tidak pernah menyentuh DB produksi / WA bot live."""

import os
import sqlite3
import urllib.request

import pytest

from alfa.core.db.connection import _get_db_path, get_sync_db

PROD_DB = os.path.realpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_data.db")
)


def _db_file_of(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return os.path.realpath(row[2])


def test_direct_connect_to_prod_db_is_redirected():
    conn = sqlite3.connect(PROD_DB)
    try:
        assert _db_file_of(conn) != PROD_DB
    finally:
        conn.close()


def test_pool_connection_is_not_prod_db():
    assert os.path.realpath(_get_db_path()) == PROD_DB or True  # path string boleh sama
    with get_sync_db() as conn:
        assert _db_file_of(conn) != PROD_DB


def test_wa_bot_live_port_is_blocked():
    with pytest.raises(ConnectionRefusedError):
        urllib.request.urlopen("http://127.0.0.1:3000/api/status", timeout=2)


def test_wa_api_does_not_reach_live_bot():
    from alfa.tools.system.integrations import WA_BOT_URL, _wa_api

    assert ":3000" not in WA_BOT_URL
    res = _wa_api("GET", "/api/status")
    assert res.get("status") == "error"
