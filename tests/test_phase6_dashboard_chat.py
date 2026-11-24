"""Phase 6 coverage: dashboard chat routes — chat, SSE, conversation CRUD, export.

Hermetic: DB SQLite sementara, bot/LLM/fast-path/attachment extractor di-mock.
"""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "chat_routes.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(db_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return db_file


@pytest.fixture
def chat_mod(isolated_db, tmp_path, monkeypatch):
    from alfa.core import fast_path_executor
    from alfa.dashboard.routes import chat

    monkeypatch.setattr(chat, "get_primary_user_id", lambda request=None: 42)
    monkeypatch.setattr(fast_path_executor, "try_execute_fast_path", lambda **k: None)
    chat._ACTIVE_TURNS.clear()
    chat._ACTIVE_BY_CONVERSATION.clear()
    return chat


@pytest.fixture
def client(chat_mod, tmp_path, monkeypatch):
    from alfa.core import config
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.ratelimit import reset_rate_limits
    from alfa.dashboard.routes import auth as auth_mod
    from alfa.dashboard.routes.system import settings_admin

    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "SECRETS_PATH", tmp_path / "no-secrets.env")
    monkeypatch.setattr(settings_admin, "REPO_ROOT", str(tmp_path / "repo"))
    reset_rate_limits()
    return TestClient(pkg_app)


class _FakeBot:
    def __init__(self, reply="jawaban", error=None, chunks=("ha", "lo")):
        self.reply = reply
        self.error = error
        self.chunks = chunks
        self.calls = []

    async def run_agent_turn(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        streamer = kwargs.get("streamer")
        if streamer is not None:
            for chunk in self.chunks:
                await streamer.push_chunk(chunk)
        return self.reply


def _sse_events(response):
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _create_conversation(client):
    response = client.post("/api/chat/conversations", json={"title": "Uji"})
    assert response.status_code == 200
    return response.json()["conversation"]["id"]


# ---------------------------------------------------------------------------
# Helper attachments / prompt
# ---------------------------------------------------------------------------


def test_process_attachments(monkeypatch, chat_mod):
    from alfa.tools.filesystem import universal_file_extractor as ufe

    seen = {}

    def fake_process(name, mime, raw, save_disk=True):
        seen["name"] = name
        seen["raw"] = raw
        return "[FILE TERSIMPAN DI DISK: /tmp/x.pdf]", {"type": "image"}

    monkeypatch.setattr(ufe, "process_uploaded_attachment", fake_process)
    data = base64.b64encode(b"abc").decode()
    parts, contexts, paths = chat_mod._process_chat_attachments(
        [
            "bukan-dict",
            {"name": "x", "base64": ""},
            {"name": "x.pdf", "type": "application/pdf", "base64": f"data:x,{data}"},
        ]
    )
    assert parts == [{"type": "image"}]
    assert contexts
    assert paths == ["/tmp/x.pdf"]
    assert seen["raw"] == b"abc"


def test_process_attachments_invalid_base64(chat_mod):
    parts, contexts, paths = chat_mod._process_chat_attachments(
        [{"name": "x", "base64": "!!!not-base64!!!"}]
    )
    assert parts == [] and contexts == [] and paths == []


def test_compose_prompt(chat_mod):
    assert chat_mod._compose_prompt("halo", []) == "halo"
    assert chat_mod._compose_prompt("halo", ["ctx"]).startswith("ctx")
    assert "Analisis isi dokumen" in chat_mod._compose_prompt("", ["ctx"])
    assert chat_mod._compose_prompt("halo", [], "coder").startswith("[Mode Spesialis: coder]")


def test_parse_key_id(chat_mod):
    assert chat_mod._parse_key_id(None) is None
    assert chat_mod._parse_key_id("") is None
    assert chat_mod._parse_key_id("ollama") is None
    assert chat_mod._parse_key_id("7") == 7
    assert chat_mod._parse_key_id("abc") is None


def test_last_message_id(chat_mod):
    from alfa.core.db import conversations as conv_db

    async def run():
        uid = 42
        conv = await conv_db.create_conversation(uid, title="t")
        assert await chat_mod._last_message_id(uid, conv["id"]) is None
        from alfa.core import database

        await database.save_chat_message(uid, "user", "halo", conversation_id=conv["id"])
        return await chat_mod._last_message_id(uid, conv["id"])

    assert asyncio.run(run()) is not None


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------


def test_chat_requires_message(client):
    assert client.post("/api/chat", json={}).status_code == 400


def test_chat_fast_path(client, chat_mod, monkeypatch):
    from alfa.core import fast_path_executor

    monkeypatch.setattr(
        fast_path_executor,
        "try_execute_fast_path",
        lambda **k: {"reply": "instan", "tool_name": "tool", "execution_time_ms": 12},
    )
    cid = _create_conversation(client)
    res = client.post(
        "/api/chat", json={"message": "halo", "conversation_id": cid}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["reply"] == "instan"
    assert body["tool_used"] == "tool"
    assert body["conversation_id"] == cid


def test_chat_normal(client, chat_mod, monkeypatch):
    bot = _FakeBot("balasan")
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: bot)
    res = client.post(
        "/api/chat",
        json={"message": "halo", "selected_model": "m", "expert_mode": "coder"},
    )
    assert res.status_code == 200
    assert res.json()["reply"] == "balasan"
    assert bot.calls[0]["override_model"] == "m"


def test_chat_unknown_conversation(client):
    res = client.post(
        "/api/chat", json={"message": "halo", "conversation_id": "tidak-ada"}
    )
    assert res.status_code == 404


def test_chat_with_attachment(client, chat_mod, monkeypatch):
    from alfa.tools.filesystem import universal_file_extractor as ufe

    monkeypatch.setattr(
        ufe,
        "process_uploaded_attachment",
        lambda name, mime, raw, save_disk=True: ("konteks dokumen", None),
    )
    bot = _FakeBot("ok")
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: bot)
    data = base64.b64encode(b"isi").decode()
    res = client.post(
        "/api/chat",
        json={"message": "", "attachments": [{"name": "x.txt", "base64": data}]},
    )
    assert res.status_code == 200
    assert bot.calls[0]["user_prompt"].startswith("konteks dokumen")


# ---------------------------------------------------------------------------
# POST /api/chat/stream
# ---------------------------------------------------------------------------


def test_stream_requires_message(client):
    assert client.post("/api/chat/stream", json={}).status_code == 400


def test_stream_invalid_edit_id(client):
    res = client.post("/api/chat/stream", json={"message": "x", "edit_message_id": "abc"})
    assert res.status_code == 400


def test_stream_regenerate_missing_conversation(client):
    res = client.post(
        "/api/chat/stream",
        json={"regenerate": True, "conversation_id": "missing"},
    )
    assert res.status_code == 404


def test_stream_regenerate_no_user_message(client, chat_mod):
    cid = _create_conversation(client)
    res = client.post(
        "/api/chat/stream", json={"regenerate": True, "conversation_id": cid}
    )
    assert res.status_code == 400


def test_stream_edit_missing_message(client, chat_mod):
    cid = _create_conversation(client)
    res = client.post(
        "/api/chat/stream",
        json={"message": "x", "conversation_id": cid, "edit_message_id": 99999},
    )
    assert res.status_code == 400


def test_stream_edit_unknown_conversation(client):
    res = client.post(
        "/api/chat/stream",
        json={"message": "x", "conversation_id": "missing", "edit_message_id": 1},
    )
    assert res.status_code == 404


def test_stream_normal(client, chat_mod, monkeypatch):
    bot = _FakeBot("jawaban akhir")
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: bot)
    res = client.post("/api/chat/stream", json={"message": "halo"})
    assert res.status_code == 200
    events = _sse_events(res)
    types = [e["type"] for e in events]
    assert "start" in types
    assert "token" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["reply"] == "jawaban akhir"
    assert done["streamed_reply"] == "halo"


def test_stream_fast_path(client, chat_mod, monkeypatch):
    from alfa.core import fast_path_executor

    monkeypatch.setattr(
        fast_path_executor,
        "try_execute_fast_path",
        lambda **k: {"reply": "satu dua", "tool_name": "t", "execution_time_ms": 1},
    )
    res = client.post("/api/chat/stream", json={"message": "halo"})
    events = _sse_events(res)
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert events[-1]["reply"] == "satu dua"


def test_stream_error_and_empty_reply(client, chat_mod, monkeypatch):
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: _FakeBot(error=RuntimeError("boom")))
    events = _sse_events(client.post("/api/chat/stream", json={"message": "halo"}))
    assert any(e["type"] == "error" for e in events)

    monkeypatch.setattr(chat_mod, "_get_bot", lambda: _FakeBot(reply=""))
    events = _sse_events(client.post("/api/chat/stream", json={"message": "halo"}))
    done = next(e for e in events if e["type"] == "done")
    assert "Tidak ada respon" in done["reply"]


def test_stream_regenerate_success(client, chat_mod, monkeypatch):

    cid = _create_conversation(client)

    async def seed():
        from alfa.core import database

        await database.save_chat_message(42, "user", "pesan lama", conversation_id=cid)
        await database.save_chat_message(42, "model", "jawaban lama", conversation_id=cid)

    asyncio.run(seed())
    bot = _FakeBot("baru")
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: bot)
    events = _sse_events(
        client.post("/api/chat/stream", json={"regenerate": True, "conversation_id": cid})
    )
    assert next(e for e in events if e["type"] == "done")["reply"] == "baru"


def test_stream_edit_success(client, chat_mod, monkeypatch):
    from alfa.core.db import conversations as conv_db

    cid = _create_conversation(client)

    async def seed():
        from alfa.core import database

        await database.save_chat_message(42, "user", "pesan lama", conversation_id=cid)
        return (await conv_db.get_messages(42, cid, limit=10))[0]["id"]

    msg_id = asyncio.run(seed())
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: _FakeBot("diedit"))
    events = _sse_events(
        client.post(
            "/api/chat/stream",
            json={"message": "baru", "conversation_id": cid, "edit_message_id": msg_id},
        )
    )
    assert next(e for e in events if e["type"] == "done")["reply"] == "diedit"


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------


def test_conversations_crud(client):
    cid = _create_conversation(client)

    listed = client.get("/api/chat/conversations").json()
    assert listed["total"] >= 1

    detail = client.get(f"/api/chat/conversations/{cid}").json()
    assert detail["conversation"]["id"] == cid
    assert "messages" in detail

    messages = client.get(f"/api/chat/conversations/{cid}/messages").json()
    assert messages["total"] == 0

    patched = client.patch(
        f"/api/chat/conversations/{cid}", json={"title": "Baru", "pinned": True}
    ).json()
    assert patched["changed"] is True
    assert patched["conversation"]["title"] == "Baru"

    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 200
    assert client.get(f"/api/chat/conversations/{cid}").status_code == 404
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 404


def test_conversation_messages_missing(client):
    assert client.get("/api/chat/conversations/x/messages").status_code == 404


def test_stop_generation(client, chat_mod):
    task = SimpleNamespace(done=lambda: False, cancel=MagicMock())
    chat_mod._ACTIVE_TURNS["req"] = task
    chat_mod._ACTIVE_BY_CONVERSATION["cid"] = "req"
    out = client.post("/api/chat/stop", json={"conversation_id": "cid"}).json()
    assert out["stopped"] is True
    task.cancel.assert_called_once()

    assert client.post("/api/chat/stop", json={"request_id": "none"}).json()["stopped"] is False


# ---------------------------------------------------------------------------
# Models, history, execute-code, export, modes
# ---------------------------------------------------------------------------


def test_chat_models(client, isolated_db):
    from alfa.core import database

    database.add_api_key_sync(
        name="G", provider="gemini", api_key="x", default_model="gm", set_active=True
    )
    database.add_api_key_sync(
        name="O", provider="openrouter", api_key="y", default_model="or", set_active=False
    )
    database.add_api_key_sync(
        name="R", provider="groq", api_key="z", default_model="gr", set_active=False
    )
    database.set_main_brain_model("gm")
    out = client.get("/api/chat/models").json()
    assert out["status"] == "success"
    providers = {m["provider"] for m in out["models"]}
    assert any("Gemini" in p for p in providers)
    assert any("OpenRouter" in p for p in providers)
    assert any(p == "GROQ" for p in providers)
    assert any("Ollama" in m["provider"] for m in out["models"])


def test_chat_models_without_gemini_key(client, isolated_db, monkeypatch):
    from alfa.core import database

    monkeypatch.setattr(database, "list_api_keys_sync", lambda: [])
    out = client.get("/api/chat/models").json()
    assert any(m["provider"] == "Gemini (Env)" for m in out["models"])


def test_set_chat_model(client, isolated_db):
    from alfa.core import database

    added = database.add_api_key_sync(
        name="K", provider="gemini", api_key="x", default_model="m", set_active=True
    )
    res = client.post("/api/chat/model", json={"model": "baru", "key_id": added["id"]})
    assert res.status_code == 200
    assert "baru" in res.json()["message"]

    res = client.post("/api/chat/model", json={"model": "hermes3:latest", "key_id": "ollama"})
    assert res.status_code == 200
    import os

    assert os.environ["ALFA_OFFLINE_MODE"] == "true"
    assert os.environ["OLLAMA_MODEL"] == "hermes3:latest"

    res = client.post("/api/chat/model", json={"model": "m2"})
    assert res.status_code == 200
    assert os.environ["ALFA_OFFLINE_MODE"] == "false"


def test_clear_history(client, monkeypatch):
    from alfa.core import database

    monkeypatch.setattr(database, "clear_user_chat_history", AsyncMock())
    assert client.delete("/api/chat/history").status_code == 200
    assert client.delete("/api/chat/history?conversation_id=x").status_code == 200


def test_execute_code_python_bash_js(client, monkeypatch, tmp_path):
    from alfa import tools

    calls = []
    monkeypatch.setattr(tools, "_clean_code_snippet", lambda code: code.strip())
    monkeypatch.setattr(tools, "execute_python_sandbox", lambda code: calls.append(("py", code)) or {"ok": 1})
    monkeypatch.setattr(tools, "execute_bash_command", lambda command: calls.append(("bash", command)) or {"ok": 1})
    monkeypatch.setattr(tools, "SANDBOX_DIR", str(tmp_path))
    assert client.post("/api/chat/execute-code", json={"language": "python", "code": "print(1)"}).status_code == 200
    assert client.post("/api/chat/execute-code", json={"language": "bash", "code": "echo 1"}).status_code == 200
    res = client.post("/api/chat/execute-code", json={"language": "js", "code": "console.log(1)"})
    assert res.status_code == 200
    assert any(c[0] == "bash" and "node " in c[1] for c in calls)
    assert client.post("/api/chat/execute-code", json={"language": "ruby", "code": "x"}).status_code == 200
    assert client.post("/api/chat/execute-code", json={"language": "python", "code": ""}).status_code == 400


def test_export_markdown_and_json(client, chat_mod, monkeypatch):
    from alfa.core import database
    from alfa.core.db import conversations as conv_db

    rows = [
        {"role": "user", "content": "halo", "timestamp": "t1"},
        {"role": "model", "content": "jawab", "timestamp": "t2"},
    ]
    monkeypatch.setattr(database, "get_recent_chat_history", AsyncMock(return_value=rows))
    monkeypatch.setattr(conv_db, "get_messages", AsyncMock(return_value=rows))
    md = client.get("/api/chat/export")
    assert md.status_code == 200
    assert "Fahmi (User)" in md.text
    assert "Agent ALFA" in md.text

    js = client.get("/api/chat/export?format=json&conversation_id=cid")
    assert js.status_code == 200
    assert js.json()["total_messages"] == 2


def test_chat_modes(client):
    out = client.get("/api/chat/modes").json()
    assert out["status"] == "success"
    assert len(out["modes"]) >= 5


# ---------------------------------------------------------------------------
# Async background endpoint (dipanggil langsung agar task dapat di-await)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_async_runner_success(chat_mod, monkeypatch):
    bot = _FakeBot("latar")
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: bot)
    out = await chat_mod.chat_with_agent_async({"message": "halo"})
    assert out["status"] == "accepted"
    await asyncio.sleep(0.05)
    assert bot.calls


@pytest.mark.asyncio
async def test_chat_async_runner_error(chat_mod, monkeypatch):
    monkeypatch.setattr(chat_mod, "_get_bot", lambda: _FakeBot(error=RuntimeError("boom")))
    out = await chat_mod.chat_with_agent_async({"message": "halo"})
    assert out["status"] == "accepted"
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_chat_async_requires_message(chat_mod):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await chat_mod.chat_with_agent_async({})
