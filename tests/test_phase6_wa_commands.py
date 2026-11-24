"""Tes hermetik fase-6: perintah WhatsApp ``bot/advanced_commands/wa.py``.

Mencakup helper format/pengirim, seluruh cabang error & unauthorized, QR login
(HTTP API + cache file + render foto), daftar/riwayat chat, pesan masuk,
kirim pesan, format pencatatan, laporan, digest, dan pencarian. Tidak ada
koneksi HTTP/WhatsApp nyata — ``urllib`` dan semua tool WA dipalsukan.
"""

import base64
import json
import sys
import urllib.request
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import alfa.bot.advanced_commands as ac
import alfa.bot.advanced_commands.wa as wa_mod
from alfa import tools


def _update(user_id=123, chat_id=456):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id),
    )


def _context(args=None):
    return SimpleNamespace(args=list(args or []), bot=SimpleNamespace(send_photo=AsyncMock()))


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    items: list[str] = []

    async def fake_send(context, chat_id, text, **kw):
        items.append(str(text))

    monkeypatch.setattr(ac, "_is_authorized", lambda uid: True)
    monkeypatch.setattr(ac, "safe_send_message", fake_send)

    # Default tool WA sehat (test dapat menimpanya).
    monkeypatch.setattr(
        tools,
        "manage_wa_sheets_bot",
        lambda action="status": {"is_running": True, "enabled_on_boot": True},
    )
    monkeypatch.setattr(
        tools,
        "open_web_dashboard",
        lambda port=8080: {"network_url": "http://192.168.1.10:8080"},
    )
    monkeypatch.setattr(
        tools,
        "wa_get_chats",
        lambda limit=10: {"status": "success", "chats": []},
    )
    monkeypatch.setattr(
        tools,
        "wa_get_messages",
        lambda chat="", limit=15, **kw: {"status": "success", "chat_name": "Budi", "messages": []},
    )
    monkeypatch.setattr(
        tools,
        "wa_get_incoming",
        lambda limit=10, **kw: {"status": "success", "incoming": []},
    )
    monkeypatch.setattr(
        tools, "wa_send_message", lambda to="", message="": {"status": "success", "to": to}
    )
    monkeypatch.setattr(
        tools, "wa_list_formats", lambda: {"status": "success", "formats": []}
    )
    monkeypatch.setattr(
        tools,
        "wa_toggle_format",
        lambda name="", enabled=True: {"status": "success"},
    )
    monkeypatch.setattr(
        tools, "wa_add_format", lambda name="", keywords="", tab="": {"status": "success"}
    )
    monkeypatch.setattr(
        tools, "wa_delete_format", lambda name="": {"status": "success"}
    )
    monkeypatch.setattr(
        tools, "wa_get_records", lambda report_format="", limit=8: {"status": "success", "records": []}
    )
    monkeypatch.setattr(
        tools, "wa_search_messages", lambda query="": {"status": "success", "hits": []}
    )

    # Tidak ada HTTP nyata ke wa-sheets-bot; cache status juga tidak ada.
    def _offline(*a, **kw):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    monkeypatch.setattr(
        wa_mod,
        "os",
        SimpleNamespace(
            path=SimpleNamespace(expanduser=lambda p: "/tidak-ada/wa_status.json", exists=lambda p: False)
        ),
    )
    return items


def _status_file(monkeypatch, tmp_path, payload):
    path = tmp_path / "wa_status.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        wa_mod,
        "os",
        SimpleNamespace(
            path=SimpleNamespace(expanduser=lambda p: str(path), exists=lambda p: True)
        ),
    )
    return path


class _FakeImage:
    def save(self, buf, format="PNG"):
        buf.write(b"\x89PNG-fake")


class _FakeQRCode:
    @staticmethod
    def make(data):
        assert data
        return _FakeImage()


# ── Helper murni ─────────────────────────────────────────────────────────────
def test_wa_helpers_format_and_sender():
    assert wa_mod._wa_time("bukan-angka") == ""
    assert wa_mod._wa_time(None) == ""
    assert "/" in wa_mod._wa_time(1700000000)

    assert "/" in wa_mod._wa_time_iso("2026-10-14T14:16:22")  # naive → UTC
    assert wa_mod._wa_time_iso("") == ""
    assert wa_mod._wa_time_iso("2026-10-14T14:16:22Z")

    assert wa_mod._wa_sender({"sender_name": " Andi "}) == "Andi"
    assert wa_mod._wa_sender({"author": "6281234567890@c.us"}) == "7890"
    assert wa_mod._wa_sender({"chat": "12345"}) == "12345"
    assert wa_mod._wa_sender({"sender": "Budi"}) == "Budi"
    assert wa_mod._wa_sender({"author": ""}) == "?"
    assert wa_mod._wa_sender({}) == "?"

    assert wa_mod._wa_not_ready({"status": "error"}) == "WA error."
    assert wa_mod._wa_not_ready({"status": "error", "message": "putus"}) == "putus"
    assert wa_mod._wa_not_ready({"status": "success"}) is None


# ── /wa: status, dashboard, QR ───────────────────────────────────────────────
@pytest.mark.parametrize(
    "fn",
    [
        wa_mod.wa_command,
        wa_mod.wachat_command,
        wa_mod.wamasuk_command,
        wa_mod.wakirim_command,
        wa_mod.waformat_command,
        wa_mod.wareport_command,
        wa_mod.waringkas_command,
        wa_mod.wacari_command,
    ],
)
async def test_wa_commands_unauthorized(monkeypatch, fn):
    monkeypatch.setattr(ac, "_is_authorized", lambda uid: False)
    called = []
    monkeypatch.setattr(ac, "safe_send_message", AsyncMock(side_effect=called.append))
    await fn(_update(), _context(["x"]))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("READY", "Terhubung (Logged In)"),
        ("AUTHENTICATED", "Terhubung (Logged In)"),
        ("INITIALIZING", "Menyiapkan QR Code baru"),
        ("QR_READY", "Menunggu Scan QR Code"),
        ("MAINTENANCE", "MAINTENANCE (Perlu Scan QR)"),
    ],
)
async def test_wa_command_auth_status_from_cache(
    sent, monkeypatch, tmp_path, status, expected
):
    _status_file(monkeypatch, tmp_path, {"status": status})
    await wa_mod.wa_command(_update(), _context())
    assert expected in sent[-1]
    assert "Manajer WhatsApp" in sent[-1]


async def test_wa_command_http_qr_success(sent, monkeypatch):
    payload = {
        "status": "READY",
        "qr_string": "abc",
        "qr_data_url": None,
    }
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=0: _Resp(json.dumps(payload).encode()),
    )
    await wa_mod.wa_command(_update(), _context())
    assert "Terhubung (Logged In)" in sent[-1]


async def test_wa_command_dashboard_error_falls_back(sent, monkeypatch):
    def _boom(port=8080):
        raise RuntimeError

    monkeypatch.setattr(tools, "open_web_dashboard", _boom)
    monkeypatch.setattr(tools, "manage_wa_sheets_bot", lambda action="status": {})
    await wa_mod.wa_command(_update(), _context())
    assert "STOPPED (Mati)" in sent[-1]


async def test_wa_command_qr_photo_data_url(sent, monkeypatch):
    b64 = base64.b64encode(b"fake-png").decode()
    payload = {"status": "QR_READY", "qr_data_url": f"data:image/png;base64,{b64}"}
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=0: _Resp(json.dumps(payload).encode()),
    )
    ctx = _context()
    await wa_mod.wa_command(_update(), ctx)

    ctx.bot.send_photo.assert_awaited_once()
    kwargs = ctx.bot.send_photo.await_args.kwargs
    assert kwargs["chat_id"] == 456
    assert kwargs["parse_mode"] == "Markdown"
    assert "SCAN QR CODE" in kwargs["caption"]
    assert sent == []


async def test_wa_command_qr_photo_from_string(sent, monkeypatch, tmp_path):
    _status_file(monkeypatch, tmp_path, {"status": "QR_READY", "qr": "token-qr"})
    monkeypatch.setitem(sys.modules, "qrcode", _FakeQRCode())
    ctx = _context()
    await wa_mod.wa_command(_update(), ctx)
    ctx.bot.send_photo.assert_awaited_once()
    assert sent == []


async def test_wa_command_qr_photo_error_falls_back(sent, monkeypatch, tmp_path):
    _status_file(monkeypatch, tmp_path, {"status": "QR_READY", "qr": "token-qr"})
    monkeypatch.setitem(sys.modules, "qrcode", _FakeQRCode())
    ctx = _context()
    ctx.bot.send_photo = AsyncMock(side_effect=RuntimeError("telegram tolak foto"))
    await wa_mod.wa_command(_update(), ctx)
    assert "Manajer WhatsApp" in sent[-1]


async def test_wa_command_cache_parse_error(sent, monkeypatch, tmp_path):
    _status_file(monkeypatch, tmp_path, "{bukan json")
    await wa_mod.wa_command(_update(), _context())
    assert "UNKNOWN (Perlu Scan QR)" in sent[-1]


# ── /wachat ──────────────────────────────────────────────────────────────────
async def test_wachat_error_and_empty_list(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_chats",
        lambda limit=10: {"status": "error", "message": "belum siap"},
    )
    await wa_mod.wachat_command(_update(), _context())
    assert "belum siap" in sent[-1] and "scan QR" in sent[-1]

    monkeypatch.setattr(tools, "wa_get_chats", lambda limit=10: {"status": "success", "chats": []})
    await wa_mod.wachat_command(_update(), _context())
    assert "Belum ada chat WA" in sent[-1]


async def test_wachat_digit_error(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_chats",
        lambda limit=10: {"status": "error", "message": "gagal"},
    )
    await wa_mod.wachat_command(_update(), _context(["5"]))
    assert sent[-1] == "📵 gagal"


async def test_wachat_unread_flag_and_typeerror_fallback(sent, monkeypatch):
    calls = []

    def _messages(chat="", limit=15):
        calls.append(chat)
        return {
            "status": "success",
            "chat_name": "Budi",
            "messages": [{"from_me": False, "sender": "Budi", "body": "halo", "ts": 1}],
        }

    monkeypatch.setattr(tools, "wa_get_messages", _messages)
    await wa_mod.wachat_command(_update(), _context(["Budi", "baru"]))
    assert calls == ["Budi"]
    assert "Hanya Baru" in sent[-1]


async def test_wachat_message_error(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_messages",
        lambda chat="", limit=15, **kw: {"status": "error", "message": "timeout"},
    )
    await wa_mod.wachat_command(_update(), _context(["Budi"]))
    assert sent[-1] == "📵 timeout"


async def test_wachat_empty_variants(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_messages",
        lambda chat="", limit=15, **kw: {"status": "success", "chat_name": "Budi", "messages": []},
    )
    await wa_mod.wachat_command(_update(), _context(["Budi", "baru"]))
    assert "Tidak ada pesan baru" in sent[-1]

    await wa_mod.wachat_command(_update(), _context(["Budi"]))
    assert "Riwayat kosong" in sent[-1]


# ── /wamasuk ─────────────────────────────────────────────────────────────────
async def test_wamasuk_error(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_incoming",
        lambda limit=10, **kw: {"status": "error", "message": "mati"},
    )
    await wa_mod.wamasuk_command(_update(), _context())
    assert sent[-1] == "📵 mati"


async def test_wamasuk_empty_all_with_warning(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_incoming",
        lambda limit=10, **kw: {"status": "success", "incoming": [], "warning": "Data parsial"},
    )
    await wa_mod.wamasuk_command(_update(), _context(["semua"]))
    assert "Belum ada pesan WA masuk" in sent[-1]
    assert sent[-1].startswith("Data parsial")

    await wa_mod.wamasuk_command(_update(), _context(["baru"]))
    assert "Semua pesan WA sudah dilihat" in sent[-1]


async def test_wamasuk_renders_group_and_direct(sent, monkeypatch):
    incoming = [
        {
            "msg_type": "chat",
            "is_group": True,
            "from_me": False,
            "chat_name": "",
            "chat": "6281234567890@c.us",
            "sender_name": "",
            "author": "628999@c.us",
            "body": "laporan",
            "ts": "2026-10-14T14:16:22Z",
        },
        {
            "msg_type": "unknown",
            "is_group": False,
            "from_me": False,
            "chat_name": "Budi",
            "body": "",
            "msg_ts": 1700000000,
        },
    ]
    monkeypatch.setattr(
        tools,
        "wa_get_incoming",
        lambda limit=10, **kw: {
            "status": "success",
            "incoming": incoming,
            "warning": "Data parsial",
        },
    )
    await wa_mod.wamasuk_command(_update(), _context(["semua"]))
    body = sent[-1]
    assert body.startswith("Data parsial")
    assert "…7890" in body  # chat_name kosong → fallback 4 digit
    assert "999" in body  # author JID → 4 digit terakhir
    assert "Budi" in body and "(kosong)" in body


# ── /wakirim, /waformat, /wareport, /waringkas, /wacari ─────────────────────
async def test_wakirim_error(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_send_message",
        lambda to="", message="": {"status": "error", "message": "nomor salah"},
    )
    await wa_mod.wakirim_command(_update(), _context(["0812", "halo"]))
    assert sent[-1] == "📵 nomor salah"


async def test_waformat_list_error(sent, monkeypatch):
    monkeypatch.setattr(
        tools, "wa_list_formats", lambda: {"status": "error", "message": "gagal baca"}
    )
    await wa_mod.waformat_command(_update(), _context())
    assert sent[-1] == "📵 gagal baca"


async def test_waformat_mutation_errors(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_toggle_format",
        lambda name="", enabled=True: {"status": "error", "message": "tak ada"},
    )
    await wa_mod.waformat_command(_update(), _context(["off", "Stok"]))
    assert "❌ tak ada" in sent[-1]

    monkeypatch.setattr(
        tools,
        "wa_add_format",
        lambda name="", keywords="", tab="": {"status": "error", "message": "duplikat"},
    )
    await wa_mod.waformat_command(_update(), _context(["add", "Order", "|", "kw"]))
    assert "❌ duplikat" in sent[-1]

    monkeypatch.setattr(
        tools,
        "wa_delete_format",
        lambda name="": {"status": "error", "message": "tidak ditemukan"},
    )
    await wa_mod.waformat_command(_update(), _context(["del", "Stok"]))
    assert "❌ tidak ditemukan" in sent[-1]


async def test_wareport_error_and_empty(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_get_records",
        lambda report_format="", limit=8: {"status": "error", "message": "db rusak"},
    )
    await wa_mod.wareport_command(_update(), _context())
    assert sent[-1] == "📵 db rusak"

    monkeypatch.setattr(
        tools,
        "wa_get_records",
        lambda report_format="", limit=8: {"status": "success", "records": []},
    )
    await wa_mod.wareport_command(_update(), _context(["Stok"]))
    assert "Belum ada catatan format" in sent[-1] and "Stok" in sent[-1]


async def test_waringkas_success_failure_and_args(sent, monkeypatch):
    from alfa.bot import wa_digest

    digest = AsyncMock(return_value=True)
    monkeypatch.setattr(wa_digest, "send_digest", digest)
    await wa_mod.waringkas_command(_update(), _context(["Stok", "5"]))
    digest.assert_awaited_once()
    assert digest.await_args.kwargs["report_format"] == "Stok"
    assert "Menyusun digest" in sent[-1]

    digest.return_value = False
    await wa_mod.waringkas_command(_update(), _context())
    assert "Digest gagal disusun" in sent[-1]


async def test_wacari_error_and_no_hits(sent, monkeypatch):
    monkeypatch.setattr(
        tools,
        "wa_search_messages",
        lambda query="": {"status": "error", "message": "indeks mati"},
    )
    await wa_mod.wacari_command(_update(), _context(["stok"]))
    assert sent[-1] == "📵 indeks mati"

    monkeypatch.setattr(
        tools,
        "wa_search_messages",
        lambda query="": {"status": "success", "hits": []},
    )
    await wa_mod.wacari_command(_update(), _context(["stok"]))
    assert "Tidak ada hasil" in sent[-1]
