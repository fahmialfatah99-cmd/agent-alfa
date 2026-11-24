"""Tes hermetik fase-6: sisa cabang ``bot/handlers/menus.py``.

Menutup blok rekapitulasi material (Lahat/Curup), executive briefing,
peluncuran ArtCraft, ekspor/eksekusi hasil rapat swarm, serta fallback
perintah menu via ``bot_module()``. Semua efek samping (WhatsApp reconciliation,
GUI desktop, engine swarm, pengiriman dokumen Telegram) dipalsukan — tanpa
DB produksi, tanpa proses/jendela nyata.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import alfa.bot.handlers as h
import alfa.bot.handlers.menus as menus_mod


# ── Helper & fixture ─────────────────────────────────────────────────────────
def _upd(user_id=77):
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = user_id
    update.effective_chat.id = 42
    return update, query


@pytest.fixture
def sent(monkeypatch):
    """Rekam seluruh pesan keluar (termasuk reply_markup)."""
    items: list[dict] = []

    async def fake_send(context, chat_id, text, **kw):
        items.append({"chat_id": chat_id, "text": text, "kw": kw})

    monkeypatch.setattr(h, "safe_send_message", fake_send)
    return items


@pytest.fixture
def routers_off(monkeypatch):
    """Semua sub-router callback mengembalikan False (tidak menangani)."""
    monkeypatch.setattr(h, "handle_doc_action_callback", AsyncMock(return_value=False))
    monkeypatch.setattr(
        h, "handle_forward_action_callback", AsyncMock(return_value=False)
    )
    for dotted in (
        "alfa.bot.mode_commands.handle_persona_callback",
        "alfa.bot.wa_menu.handle_wa_callback",
        "alfa.bot.advanced_commands.handle_sites_callback",
        "alfa.bot.cloud_menu.handle_cloud_callback",
    ):
        mod_name, _, attr = dotted.rpartition(".")
        mod = __import__(mod_name, fromlist=[attr])
        monkeypatch.setattr(mod, attr, AsyncMock(return_value=False))


def _patch_fn(monkeypatch, dotted, ret=None, side_effect=None):
    mod_name, _, attr = dotted.rpartition(".")
    mod = __import__(mod_name, fromlist=[attr])
    m = MagicMock(return_value=ret, side_effect=side_effect)
    monkeypatch.setattr(mod, attr, m)
    return m


def _patch_async(monkeypatch, dotted, ret=None):
    mod_name, _, attr = dotted.rpartition(".")
    mod = __import__(mod_name, fromlist=[attr])
    m = AsyncMock(return_value=ret)
    monkeypatch.setattr(mod, attr, m)
    return m


def _fake_os(monkeypatch, exists):
    """Ganti ``menus.os`` agar expanduser/exists deterministik."""
    fake = SimpleNamespace(
        path=SimpleNamespace(
            expanduser=lambda p: "/rumah" + p[1:],
            exists=lambda _p: exists,
        )
    )
    monkeypatch.setattr(menus_mod, "os", fake)
    return fake


# ── handle_callback_query: rantai router & dispatch normal ───────────────────
async def test_callback_query_router_chain_dispatches(sent, routers_off, monkeypatch):
    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    upd, query = _upd()
    query.data = "btn_help"
    ctx = MagicMock()

    await h.handle_callback_query(upd, ctx)

    query.answer.assert_awaited_once()
    assert "Daftar Perintah Lengkap" in sent[-1]["text"]
    # Target edit menu dibersihkan setelah dispatch (tidak bocor ke update lain).
    from alfa.bot import helpers

    assert id(ctx) not in helpers._MENU_TARGET


async def test_callback_query_router_errors_are_logged(sent, monkeypatch):
    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    boom = AsyncMock(side_effect=RuntimeError("router rusak"))
    monkeypatch.setattr(h, "handle_doc_action_callback", boom)
    monkeypatch.setattr(h, "handle_forward_action_callback", boom)
    for dotted in (
        "alfa.bot.mode_commands.handle_persona_callback",
        "alfa.bot.wa_menu.handle_wa_callback",
        "alfa.bot.advanced_commands.handle_sites_callback",
        "alfa.bot.cloud_menu.handle_cloud_callback",
    ):
        mod_name, _, attr = dotted.rpartition(".")
        mod = __import__(mod_name, fromlist=[attr])
        monkeypatch.setattr(mod, attr, boom)

    upd, query = _upd()
    query.data = "btn_help"
    await h.handle_callback_query(upd, MagicMock())

    # Enam router error, tetapi dispatch menu tetap berjalan.
    assert boom.await_count == 6
    assert "Daftar Perintah Lengkap" in sent[-1]["text"]


@pytest.mark.parametrize(
    "target", ["doc", "forward", "persona", "wa", "sites", "cloud"]
)
async def test_callback_query_router_short_circuit(
    sent, routers_off, monkeypatch, target
):
    """Router yang menangani callback harus menghentikan dispatch menu."""
    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    if target == "doc":
        monkeypatch.setattr(h, "handle_doc_action_callback", AsyncMock(return_value=True))
    elif target == "forward":
        monkeypatch.setattr(
            h, "handle_forward_action_callback", AsyncMock(return_value=True)
        )
    else:
        dotted = {
            "persona": "alfa.bot.mode_commands.handle_persona_callback",
            "wa": "alfa.bot.wa_menu.handle_wa_callback",
            "sites": "alfa.bot.advanced_commands.handle_sites_callback",
            "cloud": "alfa.bot.cloud_menu.handle_cloud_callback",
        }[target]
        mod_name, _, attr = dotted.rpartition(".")
        mod = __import__(mod_name, fromlist=[attr])
        monkeypatch.setattr(mod, attr, AsyncMock(return_value=True))

    upd, query = _upd()
    query.data = "btn_help"
    await h.handle_callback_query(upd, MagicMock())

    # Tidak sampai dispatch menu (btn_help tidak mengirim apa pun).
    assert sent == []


@pytest.mark.parametrize("cluster", ["curup", "lahat"])
@pytest.mark.parametrize("exists", [True, False])
async def test_callback_query_artcraft_launch(
    sent, routers_off, monkeypatch, cluster, exists
):
    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    fake_os = _fake_os(monkeypatch, exists)
    launch = _patch_fn(
        monkeypatch,
        "alfa.tools.desktop.artcraft.artcraft_launch_gui",
        ret={"message": "GridCraft siap"},
    )

    upd, query = _upd()
    query.data = f"artcraft|open|gridcraft|{cluster}"
    await h.handle_callback_query(upd, MagicMock())

    expected = fake_os.path.expanduser(
        "~/alfa_projects/curup_material/Rekap_Pengambilan_Material_Curup.xlsx"
        if cluster == "curup"
        else "~/alfa_projects/lahat_material/Rekap_Pengambilan_Material_Lahat.xlsx"
    )
    launch.assert_called_once_with("gridcraft", expected if exists else None)
    assert "GridCraft siap" in sent[-1]["text"]


async def test_callback_query_artcraft_defaults(sent, routers_off, monkeypatch):
    # Callback tanpa argumen aplikasi/cluster → default gridcraft + lahat.
    monkeypatch.setattr(h, "_is_authorized", lambda uid: True)
    _fake_os(monkeypatch, False)
    launch = _patch_fn(
        monkeypatch, "alfa.tools.desktop.artcraft.artcraft_launch_gui", ret={}
    )

    upd, query = _upd()
    query.data = "artcraft|open"
    await h.handle_callback_query(upd, MagicMock())

    launch.assert_called_once_with("gridcraft", None)
    assert "Aplikasi diluncurkan." in sent[-1]["text"]


# ── Rekapitulasi material Lahat / Curup ──────────────────────────────────────
async def test_rekap_lahat_full_material(sent, monkeypatch):
    res = {
        "status": "success",
        "total_cable_m": 1234.5,
        "accessories_breakdown": {
            "ACC-STOPING": 3,
            "ACC-DEADEND": 4,
            "ACC-FULCLAM": 5,
            "ACC-SUSPEN": 6,
            "ACC-BELT": 7,
            "ACC-HANGER": 8,
        },
        "total_net": 10,
        "total_bruto": 12,
        "total_retur": 2,
        "mandors": ["Andi", "Budi"],
        "excel_file": "/data/lahat.xlsx",
    }
    reconcile = _patch_fn(
        monkeypatch, "alfa.tools.telecom_tools.reconcile_whatsapp_material_group", res
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_rekap_lahat", 77, 42)

    reconcile.assert_called_once_with(
        group_name_or_id="pengambilan material lahat",
        auto_launch_gridcraft=False,
    )
    assert "Menyusun Rekapitulasi" in sent[0]["text"]
    body = sent[-1]["text"]
    assert "KU 24" in body and "1,234" in body
    assert "Aksesoris FTTH" in body and "Stoping: 3" in body
    assert "Andi, Budi" in body and "/data/lahat.xlsx" in body
    assert "reply_markup" in sent[-1]["kw"]


async def test_rekap_lahat_minimal_result(sent, monkeypatch):
    _patch_fn(
        monkeypatch,
        "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
        {"status": "success", "total_net": 0, "mandors": []},
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_rekap_lahat", 77, 42)

    body = sent[-1]["text"]
    assert "KU 24" not in body
    assert "Aksesoris FTTH" not in body


async def test_rekap_lahat_failure(sent, monkeypatch):
    _patch_fn(
        monkeypatch,
        "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
        {"status": "error", "message": "grup tidak ditemukan"},
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_rekap_lahat", 77, 42)
    assert "Gagal merekap material" in sent[-1]["text"]
    assert "grup tidak ditemukan" in sent[-1]["text"]


async def test_rekap_curup_full_breakdown(sent, monkeypatch):
    res = {
        "status": "success",
        "total_cable_m": 99,
        "accessories_breakdown": {
            "ACC-STOPING": 1,
            "ACC-DEADEND": 2,
            "ACC-FULCLAM": 3,
            "ACC-SUSPEN": 4,
            "ACC-HANGER": 5,
            "ACC-BUAYA": 6,
            "ACC-BELT": 7,
        },
        "breakdown": {"GESER": 2, "NOL": 0},
        "total_net": 8,
        "total_bruto": 9,
        "total_retur": 1,
        "mandors": ["Citra"],
        "excel_file": "/data/curup.xlsx",
    }
    reconcile = _patch_fn(
        monkeypatch, "alfa.tools.telecom_tools.reconcile_whatsapp_material_group", res
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_rekap_curup", 77, 42)

    reconcile.assert_called_once_with(
        group_name_or_id="Laporan pengambilan mandor curup",
        auto_launch_gridcraft=False,
    )
    body = sent[-1]["text"]
    assert "KU 24" in body
    for line in (
        "Stoping: 1 pcs",
        "Dead End: 2 pcs",
        "Full Clamp/Pole Clamp: 3 pcs",
        "Suspen: 4 pcs",
        "Slack Hanger: 5 pcs",
        "Clamp Buaya: 6 pcs",
        "Stainless Belt: 7 roll",
    ):
        assert line in body
    assert "(GESER: 2 btg)" in body and "NOL" not in body
    assert "reply_markup" in sent[-1]["kw"]


async def test_rekap_curup_minimal_and_zero_breakdown(sent, monkeypatch):
    _patch_fn(
        monkeypatch,
        "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
        {
            "status": "success",
            "total_net": 1,
            "breakdown": {"GESER": 0},
            "mandors": [],
        },
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_rekap_curup", 77, 42)

    body = sent[-1]["text"]
    assert "KU 24" not in body and "Aksesoris FTTH" not in body
    assert " (" not in body


async def test_rekap_curup_failure(sent, monkeypatch):
    _patch_fn(
        monkeypatch,
        "alfa.tools.telecom_tools.reconcile_whatsapp_material_group",
        {"status": "error", "message": "belum ada chat"},
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_rekap_curup", 77, 42)
    assert "Gagal merekap material" in sent[-1]["text"]
    assert "belum ada chat" in sent[-1]["text"]


# ── Executive daily briefing & ArtCraft hub ──────────────────────────────────
async def test_daily_briefing_success_and_failure(sent, monkeypatch):
    brief = _patch_fn(
        monkeypatch,
        "alfa.tools.telecom_tools.generate_daily_executive_briefing",
        {"status": "success", "briefing_card": "KARTU BRIEFING"},
    )
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_daily_briefing", 77, 42)
    brief.assert_called_once_with(shift="now", only_unreported=False)
    assert "KARTU BRIEFING" in sent[-1]["text"]

    brief.return_value = {"status": "error", "message": "data kosong"}
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_daily_briefing", 77, 42)
    assert "Gagal menyusun briefing" in sent[-1]["text"]
    assert "data kosong" in sent[-1]["text"]


async def test_btn_artcraft_renders_suite(sent):
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_artcraft", 77, 42)
    body = sent[-1]["text"]
    for app in ("GridCraft", "PdfCraft", "CadCraft", "PhotoCraft", "LightCraft", "DesignCraft"):
        assert app in body
    assert "reply_markup" in sent[-1]["kw"]


# ── Ekspor hasil rapat swarm ─────────────────────────────────────────────────
async def test_swarm_export_without_state(sent, monkeypatch):
    _patch_fn(monkeypatch, "alfa.swarm.deliberation.load_last_meeting_state", {})
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_swarm_export_last", 77, 42)
    assert "Belum ada riwayat rapat" in sent[-1]["text"]


async def test_swarm_export_sends_existing_files(sent, monkeypatch, tmp_path):
    report = tmp_path / "rapat.md"
    report.write_text("# rapat", encoding="utf-8")
    _patch_fn(
        monkeypatch,
        "alfa.swarm.deliberation.load_last_meeting_state",
        {"topic": "Rapat Mingguan", "report_files": {"md": str(report)}},
    )
    export = _patch_fn(monkeypatch, "alfa.swarm.deliberation.export_meeting_report_files", {})
    ctx = MagicMock()
    ctx.bot.send_document = AsyncMock()

    upd = MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_swarm_export_last", 77, 42)

    export.assert_not_called()
    ctx.bot.send_document.assert_awaited_once()
    kwargs = ctx.bot.send_document.await_args.kwargs
    assert kwargs["chat_id"] == 42 and kwargs["filename"] == "rapat.md"
    assert "Rapat Mingguan" in kwargs["caption"]
    assert sent == []


async def test_swarm_export_regenerates_missing_files(sent, monkeypatch, tmp_path):
    report = tmp_path / "rapat.pdf"
    report.write_bytes(b"%PDF")
    _patch_fn(
        monkeypatch,
        "alfa.swarm.deliberation.load_last_meeting_state",
        {"topic": "Rapat PDF", "report_files": {"pdf": str(tmp_path / "hilang.pdf")}},
    )
    export = _patch_fn(
        monkeypatch,
        "alfa.swarm.deliberation.export_meeting_report_files",
        {"pdf": str(report)},
    )
    ctx = MagicMock()
    ctx.bot.send_document = AsyncMock()

    await h._dispatch_menu_callback(MagicMock(), ctx, "btn_swarm_export_last", 77, 42)

    export.assert_called_once()
    ctx.bot.send_document.assert_awaited_once()
    assert sent == []


async def test_swarm_export_send_error_and_empty_export(sent, monkeypatch, tmp_path):
    report = tmp_path / "rapat.md"
    report.write_text("x", encoding="utf-8")
    _patch_fn(
        monkeypatch,
        "alfa.swarm.deliberation.load_last_meeting_state",
        {"topic": "", "report_files": {"md": str(report)}},
    )
    _patch_fn(monkeypatch, "alfa.swarm.deliberation.export_meeting_report_files", {})
    ctx = MagicMock()
    ctx.bot.send_document = AsyncMock(side_effect=RuntimeError("telegram down"))

    await h._dispatch_menu_callback(MagicMock(), ctx, "btn_swarm_export_last", 77, 42)
    assert "Gagal mengirim file laporan rapat" in sent[-1]["text"]

    # Tidak ada berkas sama sekali → export kosong → peringatan yang sama.
    _patch_fn(
        monkeypatch,
        "alfa.swarm.deliberation.load_last_meeting_state",
        {"topic": "Kosong", "report_files": {}},
    )
    sent.clear()
    await h._dispatch_menu_callback(MagicMock(), ctx, "btn_swarm_export_last", 77, 42)
    assert "Gagal mengirim file laporan rapat" in sent[-1]["text"]


# ── Eksekusi Action Plan rapat terakhir ──────────────────────────────────────
async def test_swarm_exec_without_topic(sent, monkeypatch):
    load = _patch_fn(monkeypatch, "alfa.swarm.deliberation.load_last_meeting_state", {})
    upd, ctx = MagicMock(), MagicMock()
    await h._dispatch_menu_callback(upd, ctx, "btn_swarm_exec_last", 77, 42)
    assert "Belum ada Action Plan" in sent[-1]["text"]

    load.return_value = {"topic": ""}
    await h._dispatch_menu_callback(upd, ctx, "btn_swarm_exec_last", 77, 42)
    assert "Belum ada Action Plan" in sent[-1]["text"]


async def test_swarm_exec_runs_plan_and_sends_docs(sent, monkeypatch, tmp_path):
    out_ok = tmp_path / "hasil.txt"
    out_ok.write_text("hasil", encoding="utf-8")
    out_ok2 = tmp_path / "hasil2.txt"
    out_ok2.write_text("hasil 2", encoding="utf-8")
    _patch_fn(
        monkeypatch,
        "alfa.swarm.deliberation.load_last_meeting_state",
        {
            "topic": "Optimalisasi Jaringan",
            "action_plan": "Langkah 1",
            "consensus": "Setuju",
        },
    )
    conduct = _patch_async(
        monkeypatch, "alfa.swarm.engine.conduct_multi_agent_meeting", {}
    )
    _patch_fn(
        monkeypatch,
        "alfa.bot.mode_commands.format_swarm_result",
        ("LANGKAH", "FINAL", [str(out_ok), str(out_ok2), str(tmp_path / "hilang.txt"), None]),
    )
    ctx = MagicMock()
    ctx.bot.send_document = AsyncMock(
        side_effect=[RuntimeError("gagal kirim"), None]
    )

    await h._dispatch_menu_callback(MagicMock(), ctx, "btn_swarm_exec_last", 77, 42)

    conduct.assert_awaited_once()
    assert conduct.await_args.kwargs["mode"] == "execute"
    assert "Eksekusi Action Plan" in conduct.await_args.kwargs["topic"]
    assert [m["text"] for m in sent] == [
        "⚡ **Mengeksekusi Action Plan Rapat Terakhir...**\n📌 _Optimalisasi Jaringan_",
        "LANGKAH",
        "FINAL",
    ]
    # Berkas hilang/None dilewati; dua berkas valid dicoba (satu gagal, satu sukses).
    assert ctx.bot.send_document.await_count == 2


# ── Fallback perintah menu via bot_module() ──────────────────────────────────
async def test_menu_commands_fallback_to_advanced_and_basic(sent, monkeypatch):
    monkeypatch.setattr(h, "_get_bot_module", lambda: None)
    targets = {
        "btn_keys": ("alfa.bot.advanced_commands", "keys_command"),
        "btn_cekagen": ("alfa.bot.basic_commands", "cekagen_command"),
        "btn_cron": ("alfa.bot.basic_commands", "cron_command"),
        "btn_proactive": ("alfa.bot.basic_commands", "proactive_command"),
        "btn_dashboard": ("alfa.bot.advanced_commands", "dashboard_command"),
        "btn_wa": ("alfa.bot.advanced_commands", "wa_command"),
        "btn_sites": ("alfa.bot.advanced_commands", "sites_command"),
        "btn_budget": ("alfa.bot.basic_commands", "budget_command"),
    }
    mocks = {}
    for data, (mod_name, attr) in targets.items():
        mod = __import__(mod_name, fromlist=[attr])
        m = AsyncMock()
        monkeypatch.setattr(mod, attr, m)
        mocks[data] = m

    for data, mock in mocks.items():
        upd, ctx = MagicMock(), MagicMock()
        await h._dispatch_menu_callback(upd, ctx, data, 77, 42)
        mock.assert_awaited_once_with(upd, ctx)


async def test_menu_command_fallback_missing_is_noop(sent, monkeypatch):
    monkeypatch.setattr(h, "_get_bot_module", lambda: None)
    import alfa.bot.advanced_commands as ac

    # ``basic_commands`` tidak punya ``keys_command`` — jalur getattr None.
    monkeypatch.setattr(ac, "keys_command", None)
    # Tidak ada handler callable → dispatch selesai tanpa error/pesan.
    await h._dispatch_menu_callback(MagicMock(), MagicMock(), "btn_keys", 77, 42)
    assert sent == []
