"""Unit test hermetik untuk unit handlers bot Telegram (rekomendasi #4).

- greeting_reply: sapaan instan (muat lengkap) vs campuran permintaan.
- get_forward_info: pesan terusan legacy & forward_origin modern semuanya
  terdeteksi benar (user / hidden_user / chat / channel / fallback).
- is_artifact_producing_tool & has_artifact_intent: gate intent artefak.
- check_and_send_media_artifacts: matriks kirim foto/dokumen, aturan
  kadaluwarsa-berkas, dedupe files dengan nama generik, dan gate percakapan.
- try_handle_fast_wa: fast-path WA masuk & bersihkan riwayat.

Tanpa network, tanpa DB produksi (lapisan conftest proteksi).
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import alfa.bot.handlers as h


# --- helpers mock -------------------------------------------------------------
def _mk_msg(**attrs):
    """MagicMock `message` dengan atribut forward eksplisit (bukan MagicMock)."""
    msg = MagicMock()
    msg.forward_origin = attrs.get("forward_origin")
    msg.forward_date = attrs.get("forward_date")
    msg.forward_from = attrs.get("forward_from")
    msg.forward_from_chat = attrs.get("forward_from_chat")
    msg.forward_sender_name = attrs.get("forward_sender_name")
    return msg


def _mk_context() -> MagicMock:
    ctx = MagicMock()
    ctx.bot.send_photo = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def _mk_update(text: str = "tes"):
    up = MagicMock()
    up.message = _mk_msg()
    up.message.text = text
    up.effective_chat = MagicMock()
    up.effective_chat.id = 222
    up.effective_user = MagicMock()
    up.effective_user.id = 111
    return up


# --- greeting_reply -----------------------------------------------------------
def test_greeting_reply_pure_matches():
    assert h.greeting_reply("Halo") is not None
    assert h.greeting_reply("  selamat pagi! ") is not None
    assert h.greeting_reply("Assalamualaikum?") is not None
    # sapaan bercampur permintaan -> bukan sapaan
    assert h.greeting_reply("oke tolong buatkan landing page") is None
    assert h.greeting_reply("") is None


# --- get_forward_info -----------------------------------------------------------
def test_get_forward_info_legacy_and_none():
    # Tidak ada isu forward -> None
    assert h.get_forward_info(_mk_msg()) is None
    assert h.get_forward_info(None) is None

    # Legacy: forward_from menerus
    sender = MagicMock()
    sender.full_name = "Fahmi Penuh"
    sender.username = "fahmi"
    assert h.get_forward_info(_mk_msg(forward_from=sender)) == {
        "sender": "Fahmi Penuh",
        "type": "legacy",
    }

    # Legacy: forward_from_chat
    chat = MagicMock()
    chat.title = "Grup Proyek"
    assert h.get_forward_info(_mk_msg(forward_from_chat=chat)) == {
        "sender": "Grup Proyek",
        "type": "legacy",
    }

    # Legacy: nama tersembunyi
    assert h.get_forward_info(_mk_msg(forward_sender_name="Si Hidden")) == {
        "sender": "Si Hidden",
        "type": "legacy",
    }

    # Legacy: forward_date saja -> sender generik
    import time as _t

    assert h.get_forward_info(_mk_msg(forward_date=_t.time())) == {
        "sender": "Pengirim",
        "type": "legacy",
    }


def test_get_forward_info_forward_origin_types():
    def mk_origin(otype, **kw):
        return MagicMock(type=otype, **kw)

    # user
    u = MagicMock(full_name="Budi", username="")
    o = mk_origin("user", sender_user=u)
    assert h.get_forward_info(_mk_msg(forward_origin=o))["sender"] == "Budi"
    assert h.get_forward_info(_mk_msg(forward_origin=o))["type"] == "user"

    # hidden_user
    o = mk_origin("hidden_user", sender_user_name="Anonim")
    assert h.get_forward_info(_mk_msg(forward_origin=o))["sender"] == "Anonim"

    # chat
    c = MagicMock(title="Ch Khusus")
    o = mk_origin("chat", sender_chat=c)
    assert h.get_forward_info(_mk_msg(forward_origin=o))["sender"] == "Ch Khusus"

    # channel
    ch = MagicMock(title="Kanal Resmi")
    o = mk_origin("channel", chat=ch)
    assert h.get_forward_info(_mk_msg(forward_origin=o))["sender"] == "Kanal Resmi"

    # fallback: tipe tak dikenal tapi sender_user ada
    fu = MagicMock(full_name="User Fallback", username="fb")
    o = mk_origin("alien_type", sender_user=fu)
    info = h.get_forward_info(_mk_msg(forward_origin=o))
    assert info["sender"] == "User Fallback" and info["type"] == "alien_type"


# --- artifact helpers -----------------------------------------------------------
def test_is_artifact_producing_tool_and_intent():
    assert h.is_artifact_producing_tool("capture_screenshot") is True
    assert h.is_artifact_producing_tool("build_excel_rekap") is True
    assert h.is_artifact_producing_tool("to_pdf") is True
    assert h.is_artifact_producing_tool("read_local_file") is False
    assert h.is_artifact_producing_tool("") is False

    assert h.has_artifact_intent("tolong screenshot layar") is True
    assert h.has_artifact_intent("buat grafik penjualan") is True
    assert h.has_artifact_intent("halo apa kabar") is False
    assert h.has_artifact_intent("") is False


# --- check_and_send_media_artifacts ---------------------------------------------
async def test_artifacts_skips_when_sandbox_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "SANDBOX_DIR", str(tmp_path / "tiga"))
    ctx = _mk_context()
    await h.check_and_send_media_artifacts(_mk_update(), ctx)
    assert not ctx.bot.send_photo.called


async def test_artifacts_conversational_turn_no_intent(monkeypatch, tmp_path):
    """Turn murni percakapan tanpa intent artefak -> skip total (gate).

    Gate kembali SEBELUM loop cleanup, jadi berkas tetap utuh (dipilih
    memang begitu — dunia luar menunggu langkah berikutnya).
    """
    monkeypatch.setattr(h, "SANDBOX_DIR", str(tmp_path))
    pdf = tmp_path / "download_laporan.pdf"
    png = tmp_path / "desktop_screen.png"
    pdf.write_bytes(b"PDF")
    png.write_bytes(b"PNG")

    ctx = _mk_context()
    await h.check_and_send_media_artifacts(
        _mk_update(), ctx, turn_start_time=999_999.0, user_prompt="halo apa kabar"
    )
    # Tidak ada yang dikirim, dan gate kembali sebelum cleanup
    assert not ctx.bot.send_photo.called and not ctx.bot.send_document.called
    assert pdf.exists() and png.exists()
    # Bersih-bersih buat tes berikutnya
    pdf.unlink()
    png.unlink()


async def test_artifacts_sends_named_and_generic_media(monkeypatch, tmp_path):
    """Artefak named_media + grafik terkirim, lalu dibersihkan dari sandbox."""
    import time

    now = time.time()
    monkeypatch.setattr(h, "SANDBOX_DIR", str(tmp_path))
    (tmp_path / "desktop_screen.png").write_bytes(b"S")
    (tmp_path / "generated_plot.png").write_bytes(b"P")

    ctx = _mk_context()
    await h.check_and_send_media_artifacts(
        _mk_update(),
        ctx,
        turn_start_time=now - 5,
        user_prompt="tolong screenshot dan buat grafik",
        executed_tools=["capture_desktop_screenshot", "execute_python_sandbox"],
    )
    # Kedua file terkirim lalu dihapus (finally: os.remove)
    assert ctx.bot.send_photo.call_count == 2
    assert not (tmp_path / "desktop_screen.png").exists()
    assert not (tmp_path / "generated_plot.png").exists()


async def test_artifacts_dedupes_generic_xlsx(monkeypatch, tmp_path):
    """data.xlsx generik dibuang; file spesifik dikirim lalu dibersihkan."""
    import time

    now = time.time()
    monkeypatch.setattr(h, "SANDBOX_DIR", str(tmp_path))
    generic = tmp_path / "data.xlsx"
    specific = tmp_path / "Rekap_Material_Gabungan.xlsx"
    generic.write_bytes(b"G")
    specific.write_bytes(b"S")

    ctx = _mk_context()
    await h.check_and_send_media_artifacts(
        _mk_update(), ctx, turn_start_time=now - 5, user_prompt="rekap excel",
        executed_tools=["generate_excel_file"],
    )
    assert not generic.exists()      # buang file generik
    assert not specific.exists()     # ...dan spesifiknya terkirim lalu dihapus
    assert ctx.bot.send_document.call_count == 1


async def test_artifacts_stale_named_media_removed(monkeypatch, tmp_path):
    """Named media lama (sebelum turn ini) dibersihkan dan tak dikirim."""
    import time

    now = time.time()
    monkeypatch.setattr(h, "SANDBOX_DIR", str(tmp_path))
    stale = tmp_path / "desktop_screen.png"
    stale.write_bytes(b"x")
    # Jadikan basi mtime-nya
    old = now - 60
    os.utime(stale, (old, old))

    ctx = _mk_context()
    await h.check_and_send_media_artifacts(
        _mk_update(),
        ctx,
        turn_start_time=now,
        user_prompt="screenshot",
        executed_tools=["capture_desktop_screenshot"],
    )
    assert not stale.exists()
    assert not ctx.bot.send_photo.called


# --- try_handle_fast_wa ---------------------------------------------------------
async def test_fast_wa_incoming(monkeypatch):
    update = _mk_update("cek wa masuk")
    ctx = MagicMock()
    ctx.bot = MagicMock()

    with (
        patch("alfa.bot.advanced_commands.wamasuk_command", new_callable=AsyncMock) as wc,
        patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock),
        patch("alfa.bot.handlers.database.save_chat_message", new_callable=AsyncMock) as db,
    ):
        handled = await h.try_handle_fast_wa(update, ctx, "Cek WA masuk!")
    assert handled is True
    wc.assert_called_once()
    # Chat message tersimpan w/ flag fast-path
    save_calls = [str(c.args[2]) for c in db.await_args_list]
    assert any("fast-path /wamasuk" in m for m in save_calls)
    assert save_calls[0] == "Cek WA masuk!"


async def test_fast_wa_clear_history(monkeypatch):
    update = _mk_update("wa hapus riwayat")
    ctx = MagicMock()
    ctx.bot = MagicMock()

    with (
        patch("alfa.tools.wa_clear_history") as clear,
        patch("alfa.bot.handlers.safe_send_message", new_callable=AsyncMock) as send,
        patch("alfa.bot.handlers.database.save_chat_message", new_callable=AsyncMock),
    ):
        handled = await h.try_handle_fast_wa(update, ctx, "WA, hapus riwayat teks")
    assert handled is True
    clear.assert_called_once_with(target="all", clear_archive=True, clear_read_state=True)
    teks = str(send.await_args)
    assert "Riwayat pesan WhatsApp berhasil dibersihkan" in teks


async def test_fast_wa_non_trigger_false():
    update = _mk_update("buat landing page nike")
    ctx = MagicMock()
    ctx.bot = MagicMock()
    handled = await h.try_handle_fast_wa(update, ctx, "buat landing page nike")
    assert handled is False
