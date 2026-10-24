"""
Unit tests to ensure only WhatsApp chat sources from Pengambilan Material groups
are recorded to Google Sheets and GDrive backups.
"""

from unittest.mock import MagicMock, patch

from alfa.integrations.google_sheets import (
    is_pengambilan_material_group,
    is_whatsapp_source,
    parse_and_record_material_text,
    record_material_rows,
    sync_material_if_detected,
)
from alfa.tools.media.documents import record_material_to_sheets


def test_is_whatsapp_source_validation():
    """Verify is_whatsapp_source accepts WhatsApp sources and rejects everything else."""
    # Valid WhatsApp sources
    assert is_whatsapp_source("WhatsApp") is True
    assert is_whatsapp_source("whatsapp") is True
    assert is_whatsapp_source("WA: Grup Pengambilan Material A") is True
    assert is_whatsapp_source("WA: +628123456789") is True
    assert is_whatsapp_source("Grup WA Lapangan") is True
    assert is_whatsapp_source("WA (Chat Pribadi)") is True

    # Invalid non-WhatsApp sources (Must be rejected!)
    assert is_whatsapp_source("Telegram") is False
    assert is_whatsapp_source("Telegram (Chat)") is False
    assert is_whatsapp_source("Telegram (Foto)") is False
    assert is_whatsapp_source("Telegram (Dokumen)") is False
    assert is_whatsapp_source("Dokumen") is False
    assert is_whatsapp_source("Dokumen SMDT LAHAT.xlsx") is False
    assert is_whatsapp_source("Excel") is False
    assert is_whatsapp_source("PDF") is False
    assert is_whatsapp_source("Discord") is False
    assert is_whatsapp_source("Console") is False
    assert is_whatsapp_source("Manual Web Input") is False
    assert is_whatsapp_source("") is False
    assert is_whatsapp_source(None) is False


def test_is_pengambilan_material_group_validation():
    """Verify only groups containing 'pengambilan material' are accepted."""
    assert is_pengambilan_material_group("WA: Pengambilan Material") is True
    assert is_pengambilan_material_group("Pengambilan Material Cluster A") is True
    assert is_pengambilan_material_group("WA: Pengambilan Material Lahat") is True
    assert is_pengambilan_material_group("WA: Grup Proyek", group="Pengambilan Material Cluster B") is True

    # Reject other groups and document sources
    assert is_pengambilan_material_group("Grup Transfer Order") is False
    assert is_pengambilan_material_group("WA: Grup Transfer Order Subcon") is False
    assert is_pengambilan_material_group("Grup Umum") is False
    assert is_pengambilan_material_group("Chat Pribadi") is False
    assert is_pengambilan_material_group("Dokumen SMDT LAHAT.xlsx") is False
    assert is_pengambilan_material_group("Telegram (Chat)") is False


def test_record_material_rows_rejects_non_whatsapp():
    """record_material_rows must immediately reject non-WhatsApp sources."""
    sample_rows = [
        {"item_name": "KABEL DROPCORE 1C", "qty": 100, "unit": "MTR"}
    ]

    res_tg = record_material_rows(sample_rows, source="Telegram (Chat)")
    assert res_tg["status"] == "error"
    assert "bukan bersumber dari chat WhatsApp" in res_tg["message"]

    res_doc = record_material_rows(sample_rows, source="Dokumen SMDT LAHAT.xlsx")
    assert res_doc["status"] == "error"
    assert "bukan bersumber dari chat WhatsApp" in res_doc["message"]


def test_record_material_rows_rejects_non_pengambilan_material_group():
    """record_material_rows must reject WhatsApp messages from non-Pengambilan Material groups."""
    sample_rows = [
        {"item_name": "KABEL DROPCORE 1C", "qty": 100, "unit": "MTR"}
    ]

    res = record_material_rows(sample_rows, source="WA: Grup Transfer Order Subcon")
    assert res["status"] == "error"
    assert "bukan grup 'Pengambilan Material'" in res["message"]


def test_record_material_rows_accepts_pengambilan_material_group():
    """record_material_rows must allow genuine WhatsApp Pengambilan Material group messages."""
    sample_rows = [
        {"item_name": "KABEL DROPCORE 1C", "qty": 100, "unit": "MTR", "pic": "Pak Budi"}
    ]

    with patch("alfa.integrations.google_sheets.ensure_material_sheet_tab"), \
         patch("alfa.integrations.google_sheets.get_sheets_service") as mock_srv, \
         patch("alfa.integrations.google_sheets.get_spreadsheet_id", return_value="fake_sheet_id"), \
         patch("os.makedirs"), \
         patch("openpyxl.load_workbook"):
        mock_append = MagicMock()
        mock_append.execute.return_value = {"updates": {"updatedRows": 1}}
        mock_srv.return_value.spreadsheets.return_value.values.return_value.append.return_value = mock_append

        res = record_material_rows(sample_rows, source="WA: Pengambilan Material Cluster B", sender="Pak Budi")
        assert res["status"] == "success"
        assert res["total_items"] == 1
        assert res["cloud_synced"] is True


def test_parse_and_record_material_text_rejects_non_pengambilan_group():
    """parse_and_record_material_text must reject non-pengambilan groups without calling AI."""
    with patch("alfa.bot.config.resolve_main_gemini") as mock_ai:
        res = parse_and_record_material_text(
            text="Ambil dropcore 2 roll",
            source="WA: Grup Lain"
        )
        assert res["status"] == "error"
        assert "bukan grup 'Pengambilan Material'" in res["message"]
        mock_ai.assert_not_called()


def test_record_material_to_sheets_tool_rejects_document_sources():
    """record_material_to_sheets tool must reject document and non-WhatsApp callers."""
    res_default = record_material_to_sheets(
        material_text="Tiang 7m 10 btg",
        context="Rekap dokumen SMDT LAHAT.xlsx",
        source=""
    )
    assert res_default["status"] == "error"
    assert "HANYA mencatat otomatis dari chat WhatsApp grup yang memuat keterangan 'pengambilan material'" in res_default["message"]

    res_tg = record_material_to_sheets(
        material_text="Tiang 7m 10 btg",
        context="Dari obrolan Telegram",
        source="Telegram (Chat)"
    )
    assert res_tg["status"] == "error"
    assert "HANYA mencatat otomatis dari chat WhatsApp" in res_tg["message"]


def test_sync_material_if_detected_rejects_non_pengambilan_group():
    """sync_material_if_detected must return None for non-pengambilan groups."""
    res = sync_material_if_detected(
        text="Pengambilan material dropcore 100 pcs oleh Pak Budi",
        context="Grup Transfer Order",
        source="WA: Grup Transfer Order"
    )
    assert res is None
