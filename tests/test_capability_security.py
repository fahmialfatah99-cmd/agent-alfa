"""Tes P2 Capability Security: grant, expiry, max uses, revoke, gate action."""

from __future__ import annotations

import sqlite3
import time

import pytest

from alfa.core.db.connection import get_sync_db, init_db_sync
from alfa.core.perm import capabilities


@pytest.fixture()
def isolated_capability_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "capability_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "shadow")
    monkeypatch.setenv("ALFA_CAPABILITY_REQUIRED", "false")
    init_db_sync()
    with get_sync_db() as conn:
        try:
            conn.execute("DELETE FROM capability_grants")
            conn.commit()
        except sqlite3.Error:
            pass
    return db_file


def test_shadow_grant_is_recorded_but_not_enforced(isolated_capability_db):
    granted = capabilities.grant_capability_sync(
        100, "execute_bash_command", user_id=7, ttl_minutes=30, max_uses=2
    )
    assert granted is not None
    assert granted["enforced"] is False

    rows = capabilities.list_capabilities_sync(chat_id=100)
    assert len(rows) == 1
    assert rows[0]["valid"] is True
    assert rows[0]["tool_name"] == "execute_bash_command"

    inspected = capabilities.inspect_capability_sync(100, "execute_bash_command")
    assert inspected["allowed"] is True

    # Shadow tidak mengonsumsi kuota dan tidak mengubah gate.
    consumed = capabilities.consume_capability_sync(100, "execute_bash_command")
    assert consumed["allowed"] is True
    assert consumed["enforced"] is False
    assert capabilities.list_capabilities_sync(chat_id=100)[0]["uses"] == 0

    check = capabilities.check_capability_for_tool(100, "execute_bash_command")
    assert check["action"] == "none"
    assert check["reason"] == "shadow_capability"


def test_on_mode_consumes_until_exhausted(isolated_capability_db, monkeypatch):
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "on")
    granted = capabilities.grant_capability_sync(
        200, "write_file", ttl_minutes=30, max_uses=2
    )
    assert granted is not None
    assert granted["enforced"] is True

    first = capabilities.check_capability_for_tool(200, "write_file")
    assert first["action"] == "allow"
    assert capabilities.list_capabilities_sync(chat_id=200)[0]["uses"] == 1

    second = capabilities.check_capability_for_tool(200, "write_file")
    assert second["action"] == "allow"
    assert capabilities.list_capabilities_sync(chat_id=200)[0]["uses"] == 2

    third = capabilities.check_capability_for_tool(200, "write_file")
    assert third["action"] == "none"
    assert third["reason"] == "no_capability"


def test_expired_grant_is_invalid(isolated_capability_db, monkeypatch):
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "on")
    granted = capabilities.grant_capability_sync(300, "read_local_file", ttl_minutes=1)
    assert granted is not None
    with get_sync_db() as conn:
        conn.execute(
            "UPDATE capability_grants SET expires_at = ? WHERE grant_id = ?",
            (time.time() - 5, granted["grant_id"]),
        )
        conn.commit()

    rows = capabilities.list_capabilities_sync(chat_id=300)
    assert rows[0]["expired"] is True
    assert rows[0]["valid"] is False
    assert capabilities.check_capability_for_tool(300, "read_local_file")["action"] == "none"


def test_revoke_by_id_and_tool(isolated_capability_db):
    first = capabilities.grant_capability_sync(400, "tool_a")
    second = capabilities.grant_capability_sync(400, "tool_b")
    assert first and second

    assert capabilities.revoke_capability_sync(first["grant_id"]) == 1
    rows = capabilities.list_capabilities_sync(chat_id=400)
    revoked = [row for row in rows if row["grant_id"] == first["grant_id"]][0]
    assert revoked["revoked"] is True
    assert revoked["valid"] is False

    assert capabilities.revoke_capability_sync(chat_id=400, tool_name="tool_b") == 1
    assert all(
        not row["valid"] for row in capabilities.list_capabilities_sync(chat_id=400)
    )


def test_off_mode_and_invalid_input(isolated_capability_db, monkeypatch):
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "off")
    assert capabilities.grant_capability_sync(500, "tool_a") is None
    assert capabilities.check_capability_for_tool(500, "tool_a")["action"] == "none"
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "on")
    assert capabilities.grant_capability_sync(500, "") is None


def test_required_mode_denies_high_tier_without_grant(
    isolated_capability_db, monkeypatch
):
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "on")
    monkeypatch.setenv("ALFA_CAPABILITY_REQUIRED", "true")
    result = capabilities.check_capability_for_tool(600, "execute_bash_command")
    assert result["action"] == "deny"
    assert result["reason"] == "capability_required"

    granted = capabilities.grant_capability_sync(600, "execute_bash_command")
    assert granted is not None
    allowed = capabilities.check_capability_for_tool(600, "execute_bash_command")
    assert allowed["action"] == "allow"


def test_required_mode_allows_low_tier_without_grant(
    isolated_capability_db, monkeypatch
):
    monkeypatch.setenv("ALFA_CAPABILITY_SECURITY", "on")
    monkeypatch.setenv("ALFA_CAPABILITY_REQUIRED", "true")
    result = capabilities.check_capability_for_tool(700, "read_local_file")
    assert result["action"] == "none"
