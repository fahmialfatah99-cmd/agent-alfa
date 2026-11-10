"""End-to-end hermetik: Telegram, WhatsApp bridge, dan Dashboard.

Alur diuji lintas lapisan (bukan per-fungsi): event eksternal → handler/tool
→ efek yang terlihat (pesan terkirim, data terparser, respons HTTP).

Semua sumber eksternal dipalsukan (HTTP server lokal, LLM, Telegram API) dan
DB diarahkan ke SQLite sementara — tidak ada jaringan ke luar maupun data
produksi yang tersentuh.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# ── Fixture umum ─────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Arahkan semua lapisan DB ke SQLite sementara."""
    db_file = str(tmp_path / "e2e_test.db")
    monkeypatch.setenv("ALFA_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection as _conn

    _conn.init_db_sync()
    return db_file


class _WaStubHandler(BaseHTTPRequestHandler):
    """Stub API bot wa-sheets-bot (pola respons sama dengan server Node)."""

    payload: dict = {}

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond  # noqa: N815
    do_POST = _respond  # noqa: N815

    def log_message(self, *args):  # noqa: ANN002, ANN201
        return


@pytest.fixture
def wa_stub_server():
    """HTTP server lokal yang menyamar sebagai bot wa-sheets-bot."""
    handler = type("Handler", (_WaStubHandler,), {"payload": {}})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, handler
    finally:
        server.shutdown()
        server.server_close()


# ── E2E-1: Telegram — pesan teks → agent turn → balasan terkirim ────────────


class _FakeStreamer:
    """Pengganti TelegramStreamer: mencatat teks final, tanpa API Telegram."""

    sent: list[dict] = []

    def __init__(self, context=None, chat_id=None, initial_text=None):
        self.chat_id = chat_id

    async def start(self):
        return None

    async def push(self, chunk: str):
        return None

    async def finalize(self, text: str):
        type(self).sent.append({"chat_id": self.chat_id, "text": text})


def _fake_telegram_update(text: str, chat_id: int, user_id: int = 4242003):
    from unittest.mock import AsyncMock, MagicMock

    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = user_id
    update.message.text = text
    update.message.chat.id = chat_id
    update.message.from_user.id = user_id
    update.message.message_id = 1
    update.message.reply_text = AsyncMock()
    # Pesan biasa (bukan terusan) — atribut forward harus None, bukan mock.
    update.message.forward_from = None
    update.message.forward_from_chat = None
    update.message.forward_sender_name = None
    update.message.forward_date = None
    update.message.forward_origin = None
    context = MagicMock()
    context.bot = MagicMock()
    return update, context


async def test_e2e_telegram_greeting_is_answered_and_persisted(isolated_db, monkeypatch):
    """Sapaan murni -> balasan instan + riwayat chat tersimpan di DB."""
    import alfa.bot.handlers as h

    sent: list[dict] = []

    async def fake_send(context, chat_id, text, **kw):
        sent.append({"chat_id": chat_id, "text": text})

    monkeypatch.setattr(h, "_is_authorized", lambda user_id: True)
    monkeypatch.setattr(h, "safe_send_message", fake_send)

    update, context = _fake_telegram_update("halo", 4242)

    await h.handle_text_message(update, context)

    assert sent, "sapaan tidak dibalas"
    assert sent[-1]["chat_id"] == 4242

    from alfa.core.db.memory import get_recent_chat_history

    rows = await get_recent_chat_history(4242003, limit=10)
    contents = [str(r.get("content", "")) for r in rows]
    assert any("halo" in c for c in contents), "pesan user tidak tersimpan"
    assert len(contents) >= 2, "balasan model tidak tersimpan"


async def test_e2e_telegram_text_message_leads_to_reply(isolated_db, monkeypatch):
    """Pesan user -> handler -> agent turn -> balasan dikirim ke chat yang sama."""
    import alfa.bot.handlers as h

    sent: list[dict] = []
    prompts: list[str] = []

    async def fake_send(context, chat_id, text, **kw):
        sent.append({"chat_id": chat_id, "text": text})

    async def fake_agent_turn(*args, **kwargs):
        prompts.append(str(kwargs.get("user_prompt", "")))
        return "Rekap cluster Lahat: 160 batang bersih."

    class _Streamer(_FakeStreamer):
        pass

    _Streamer.sent = sent

    monkeypatch.setattr(h, "_is_authorized", lambda user_id: True)
    monkeypatch.setattr(h, "_get_bot_module", lambda: None)
    monkeypatch.setattr(h, "safe_send_message", fake_send)
    monkeypatch.setattr(h, "run_agent_turn", fake_agent_turn)
    monkeypatch.setattr(h, "TelegramStreamer", _Streamer)

    update, context = _fake_telegram_update("berapa total tiang cluster lahat?", 4242)

    await h.handle_text_message(update, context)

    assert prompts, "agent turn tidak dipanggil"
    assert "tiang cluster lahat" in prompts[0]
    assert sent, "balasan tidak terkirim ke chat"
    assert sent[-1]["chat_id"] == 4242
    assert "160 batang" in sent[-1]["text"]


# ── E2E-2: WhatsApp bridge — HTTP API → tool → data terparser ───────────────


def test_e2e_wa_api_roundtrip_through_tool(wa_stub_server, monkeypatch):
    """Tool WA membaca API bot lokal lewat HTTP nyata dan mem-parsing respons."""
    server, handler = wa_stub_server
    handler.payload = {
        "status": "success",
        "chats": [
            {"id": "120363@g.us", "name": "Grup Material Lahat"},
            {"id": "120364@g.us", "name": "Grup Material Curup"},
        ],
    }

    from alfa.tools.system.integrations import _api, wa_get_chats

    monkeypatch.setattr(
        _api, "WA_BOT_URL", f"http://127.0.0.1:{server.server_address[1]}"
    )

    res = wa_get_chats(limit=10)
    assert res.get("status") == "success"
    assert any("Lahat" in str(c) for c in res.get("chats", []))


def test_e2e_wa_api_error_payload_is_surfaced(wa_stub_server, monkeypatch):
    """Respons error dari bot WA harus diteruskan, bukan ditelan."""
    server, handler = wa_stub_server
    handler.payload = {"status": "error", "message": "bot belum login"}

    from alfa.tools.system.integrations import _api, wa_get_me

    monkeypatch.setattr(
        _api, "WA_BOT_URL", f"http://127.0.0.1:{server.server_address[1]}"
    )

    res = wa_get_me()
    assert res.get("status") == "error"
    assert "belum login" in str(res.get("message", ""))


# ── E2E-3: Dashboard — HTTP request → auth → respons settings ───────────────


def test_e2e_dashboard_settings_reads_private_secrets_and_masks(tmp_path, monkeypatch):
    """Dashboard membaca file env privat dan tidak pernah membocorkan nilainya."""
    from fastapi.testclient import TestClient

    import alfa.core.config as config_mod
    from alfa.dashboard import app as pkg_app
    from alfa.dashboard.routes import auth as auth_mod

    secrets = tmp_path / "secrets.env"
    secrets.write_text(
        "TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGHIJK\nGEMINI_API_KEY=AIzaSyDUMMYKEY123456\n",
        encoding="utf-8",
    )
    secrets.chmod(0o600)
    monkeypatch.setattr(config_mod, "SECRETS_PATH", secrets)

    monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
    client = TestClient(pkg_app)

    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "success"

    raw = json.dumps(data)
    assert "AIzaSyDUMMYKEY123456" not in raw, "API key mentah bocor ke respons"
    assert "1234567890:ABCDEFGHIJK" not in raw, "token bot bocor ke respons"


def test_e2e_dashboard_health_reports_database_state():
    """Endpoint health dashboard menampilkan status DB."""
    from fastapi.testclient import TestClient

    from alfa.dashboard import app as pkg_app

    client = TestClient(pkg_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("healthy", "degraded")
    assert "database" in body
