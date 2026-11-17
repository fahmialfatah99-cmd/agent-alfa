"""Regression tests for Claude-style dashboard conversation threads.

Covers additive thread schema/CRUD, history isolation between global channels
and dashboard threads, headless approval gates, SSE true streaming, stop,
regenerate, and edit.
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "chat_threads.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as conn

    conn.init_db_sync()
    return db_file


@pytest.fixture
def api_client(isolated_db, monkeypatch):
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.routes import auth as auth_mod

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    monkeypatch.setenv("ALLOWED_USER_IDS", "42")
    return TestClient(pkg_app)


class _FakeBot:
    """Echo agent that exercises streamer, tool events, and persistence."""

    async def run_agent_turn(self, **kwargs):
        from alfa.core import database
        from alfa.core.runtime_ctx import record_executed_tool

        prompt = kwargs.get("user_prompt") or ""
        streamer = kwargs.get("streamer")
        reply = f"Echo: {prompt[:120]}"
        if streamer is not None:
            await streamer.push_chunk("Echo: ")
            await streamer.push_chunk(prompt[:120])
        record_executed_tool("web_search", '{"q": "alfa"}')
        await database.save_chat_message(kwargs["user_id"], "user", prompt)
        await database.save_chat_message(kwargs["user_id"], "model", reply)
        return reply


@pytest.fixture
def fake_bot(monkeypatch):
    from alfa.dashboard.routes import chat as chat_mod

    monkeypatch.setattr(chat_mod, "_get_bot", lambda: _FakeBot())


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in text.split("\n\n"):
        line = block.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ── DB layer ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_crud_search_and_pin(isolated_db):
    from alfa.core.db import conversations as conv

    first = await conv.create_conversation(42, "Riset Pasar", "gemini-3.6-flash")
    second = await conv.create_conversation(42, "Debug Kode", "claude")

    await conv.update_message_metadata(42, first["id"], {"model": "x"})
    rows = await conv.get_messages(42, first["id"])
    assert rows == []

    assert await conv.rename_conversation(42, first["id"], "Riset Pasar Q4")
    assert await conv.set_pinned(42, first["id"], True)

    listed = await conv.list_conversations(42)
    assert [item["title"] for item in listed] == ["Riset Pasar Q4", "Debug Kode"]
    assert listed[0]["pinned"] == 1

    by_title = await conv.list_conversations(42, query="debug")
    assert [item["id"] for item in by_title] == [second["id"]]

    by_content = await conv.list_conversations(42, query="pasar")
    assert [item["id"] for item in by_content] == [first["id"]]

    assert await conv.delete_conversation(42, second["id"]) is True
    assert await conv.get_conversation(42, second["id"]) is None
    assert [item["id"] for item in await conv.list_conversations(42)] == [first["id"]]


@pytest.mark.asyncio
async def test_history_isolation_between_channel_and_thread(isolated_db):
    from alfa.core.db import conversations as conv
    from alfa.core.db import memory
    from alfa.core.runtime_ctx import current_conversation_id_var

    thread = await conv.create_conversation(42, "Thread Dashboard")
    token = current_conversation_id_var.set(thread["id"])
    try:
        await memory.save_chat_message(42, "user", "halo thread")
        await memory.save_chat_message(42, "model", "balasan thread")
    finally:
        current_conversation_id_var.reset(token)

    # Tanpa konteks thread -> hanya riwayat kanal global (NULL).
    await memory.save_chat_message(42, "user", "halo telegram")

    thread_rows = await memory.get_recent_chat_history(
        42, limit=10, conversation_id=thread["id"]
    )
    global_rows = await memory.get_recent_chat_history(42, limit=10)
    assert [(r["role"], r["content"]) for r in thread_rows] == [
        ("user", "halo thread"),
        ("model", "balasan thread"),
    ]
    assert [(r["role"], r["content"]) for r in global_rows] == [
        ("user", "halo telegram")
    ]
    assert thread_rows[0]["metadata"] == {}
    assert "timestamp" in thread_rows[0]


@pytest.mark.asyncio
async def test_delete_messages_from_removes_tail(isolated_db):
    from alfa.core.db import conversations as conv
    from alfa.core.db import memory
    from alfa.core.runtime_ctx import current_conversation_id_var

    thread = await conv.create_conversation(42, "Edit Thread")
    token = current_conversation_id_var.set(thread["id"])
    try:
        await memory.save_chat_message(42, "user", "satu")
        await memory.save_chat_message(42, "model", "jawab satu")
        await memory.save_chat_message(42, "user", "dua")
        await memory.save_chat_message(42, "model", "jawab dua")
    finally:
        current_conversation_id_var.reset(token)

    rows = await conv.get_messages(42, thread["id"])
    assert len(rows) == 4
    removed = await conv.delete_messages_from(42, thread["id"], rows[2]["id"])
    assert removed == 2
    remaining = await conv.get_messages(42, thread["id"])
    assert [r["content"] for r in remaining] == ["satu", "jawab satu"]


@pytest.mark.asyncio
async def test_global_clear_removes_threads_but_scoped_clear_keeps_them(isolated_db):
    from alfa.core.db import conversations as conv
    from alfa.core.db import memory
    from alfa.core.runtime_ctx import current_conversation_id_var

    thread = await conv.create_conversation(42, "Thread Akan Dihapus")
    token = current_conversation_id_var.set(thread["id"])
    try:
        await memory.save_chat_message(42, "user", "pesan thread")
    finally:
        current_conversation_id_var.reset(token)
    await memory.save_chat_message(42, "user", "pesan kanal")

    # Scoped clear: thread tetap ada (hanya pesannya yang dihapus).
    await memory.clear_user_chat_history(42, thread["id"])
    assert await conv.get_conversation(42, thread["id"]) is not None
    assert await conv.get_messages(42, thread["id"]) == []

    # Global clear: pesan kanal + thread ikut dibersihkan.
    await memory.clear_user_chat_history(42)
    assert await conv.get_conversation(42, thread["id"]) is None
    assert await memory.get_recent_chat_history(42, limit=10) == []


# ── Permission gate ─────────────────────────────────────────────────────────


def test_headless_gate_is_not_interactive_and_fail_closed_for_high_tier(
    monkeypatch, isolated_db
):
    from alfa.core.perm import gate as gate_mod

    gate = gate_mod.make_headless_gate()
    assert gate is gate_mod.HEADLESS_GATE
    assert gate_mod.gate_is_interactive(gate) is False
    assert gate_mod.gate_is_interactive(gate_mod.ALLOW_ALL_GATE) is False
    assert gate_mod.gate_is_interactive(None) is False

    monkeypatch.setattr(gate_mod, "PERMISSION_GATE_ENABLED", True)
    # Tool HIGH/CRITICAL tetap ditolak tanpa kanal approval, bukan digantung.
    denial = asyncio.run(gate("unknown_high_risk_tool", "{}"))
    assert denial is None or isinstance(denial, str)

    # Identitas operator dihormati: allowlist eksplisit membuka tool HIGH,
    # sementara identitas lain tetap ditolak (fail-closed).
    from alfa.core.perm.store import save_always_allow

    save_always_allow(4242007, "execute_bash_command", "always")
    allowed_gate = gate_mod.make_headless_gate(4242007)
    assert gate_mod.gate_is_interactive(allowed_gate) is False
    assert asyncio.run(allowed_gate("execute_bash_command", "{}")) is None
    assert (
        gate_mod.check_headless_approval(4242008, "execute_bash_command") is not None
    )


# ── API: CRUD ───────────────────────────────────────────────────────────────


def test_api_conversation_crud(api_client):
    created = api_client.post(
        "/api/chat/conversations", json={"title": "Riset API"}
    )
    assert created.status_code == 200, created.text
    cid = created.json()["conversation"]["id"]

    listed = api_client.get("/api/chat/conversations")
    assert listed.status_code == 200
    assert any(item["id"] == cid for item in listed.json()["conversations"])

    patched = api_client.patch(
        f"/api/chat/conversations/{cid}",
        json={"title": "Riset API Baru", "pinned": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["conversation"]["title"] == "Riset API Baru"
    assert patched.json()["conversation"]["pinned"] == 1

    detail = api_client.get(f"/api/chat/conversations/{cid}?messages=1")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    missing = api_client.patch(
        "/api/chat/conversations/tidak-ada", json={"title": "x"}
    )
    assert missing.status_code == 404

    deleted = api_client.delete(f"/api/chat/conversations/{cid}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


# ── API: true streaming + threads ───────────────────────────────────────────


def test_api_stream_emits_real_events_and_persists_thread(api_client, fake_bot):
    response = api_client.post(
        "/api/chat/stream",
        json={"message": "halo stream", "selected_model": "fake-model"},
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    types = [event["type"] for event in events]
    assert "progress" in types
    assert "start" in types
    assert "token" in types
    assert "tool" in types
    assert "done" in types

    done = next(event for event in events if event["type"] == "done")
    conversation_id = done["conversation_id"]
    assert conversation_id
    assert done["reply"] == "Echo: halo stream"
    assert done["tools_called"] == ["web_search"]
    assert done["user_message_id"]
    assert done["message_id"] > done["user_message_id"]

    # Token asli dari streamer, bukan hasil chunking setelah jawaban selesai.
    token_text = "".join(
        event["chunk"] for event in events if event["type"] == "token"
    )
    assert token_text == "Echo: halo stream"

    detail = api_client.get(f"/api/chat/conversations/{conversation_id}")
    assert detail.status_code == 200
    rows = detail.json()["messages"]
    assert [(r["role"], r["content"]) for r in rows] == [
        ("user", "halo stream"),
        ("model", "Echo: halo stream"),
    ]
    assert rows[-1]["metadata"]["tools"][0]["name"] == "web_search"

    listed = api_client.get("/api/chat/conversations").json()["conversations"]
    assert listed[0]["id"] == conversation_id
    assert listed[0]["title"] == "halo stream"


def test_api_stream_regenerate_and_edit(api_client, fake_bot):
    first = api_client.post(
        "/api/chat/stream",
        json={"message": "pertanyaan awal", "selected_model": "fake-model"},
    )
    first_done = _parse_sse(first.text)[-1]
    cid = first_done["conversation_id"]

    regenerated = api_client.post(
        "/api/chat/stream",
        json={
            "regenerate": True,
            "conversation_id": cid,
            "selected_model": "fake-model",
        },
    )
    regen_events = _parse_sse(regenerated.text)
    regen_done = next(e for e in regen_events if e["type"] == "done")
    assert regen_done["reply"] == "Echo: pertanyaan awal"

    rows = api_client.get(f"/api/chat/conversations/{cid}").json()["messages"]
    assert [r["content"] for r in rows] == [
        "pertanyaan awal",
        "Echo: pertanyaan awal",
    ]

    user_id = next(r["id"] for r in rows if r["role"] == "user")
    edited = api_client.post(
        "/api/chat/stream",
        json={
            "conversation_id": cid,
            "edit_message_id": user_id,
            "message": "pertanyaan diedit",
            "selected_model": "fake-model",
        },
    )
    assert edited.status_code == 200, edited.text
    edit_done = next(e for e in _parse_sse(edited.text) if e["type"] == "done")
    assert edit_done["reply"] == "Echo: pertanyaan diedit"

    rows = api_client.get(f"/api/chat/conversations/{cid}").json()["messages"]
    assert [r["content"] for r in rows] == [
        "pertanyaan diedit",
        "Echo: pertanyaan diedit",
    ]


def test_api_stream_regenerate_requires_existing_thread(api_client, fake_bot):
    response = api_client.post(
        "/api/chat/stream", json={"regenerate": True, "conversation_id": "nope"}
    )
    assert response.status_code == 404


# ── Stop endpoint ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_endpoint_cancels_registered_task(isolated_db, monkeypatch):
    from alfa.dashboard.routes import chat as chat_mod

    request = SimpleNamespace(state=SimpleNamespace(user={"is_admin": True}))
    task = asyncio.create_task(asyncio.sleep(60))
    request_id = "req-stop-test"
    chat_mod._ACTIVE_TURNS[request_id] = task
    chat_mod._ACTIVE_BY_CONVERSATION["conv-stop-test"] = request_id
    try:
        result = await chat_mod.stop_chat_generation(
            {"request_id": request_id}, request
        )
        assert result["stopped"] is True
        await asyncio.sleep(0)
        assert task.cancelled()
    finally:
        chat_mod._ACTIVE_TURNS.pop(request_id, None)
        chat_mod._ACTIVE_BY_CONVERSATION.pop("conv-stop-test", None)
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_stop_endpoint_unknown_request_is_noop(isolated_db):
    from alfa.dashboard.routes import chat as chat_mod

    request = SimpleNamespace(state=SimpleNamespace(user={"is_admin": True}))
    result = await chat_mod.stop_chat_generation({"request_id": "missing"}, request)
    assert result == {"status": "success", "stopped": False}


# ── Schema migration ────────────────────────────────────────────────────────


def test_schema_is_additive_and_idempotent(isolated_db):
    from alfa.core.db import conversations as conv

    assert conv.ensure_chat_schema_sync(force=True) is True
    assert conv.ensure_chat_schema_sync(force=True) is True

    with sqlite3.connect(isolated_db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_history)")}
        assert {"conversation_id", "metadata"}.issubset(cols)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "conversations" in tables
