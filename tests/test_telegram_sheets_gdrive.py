"""Unit and integration tests for Telegram Google Sheets & Google Drive viewer UI."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alfa.bot.basic_commands import _main_menu_markup
from alfa.bot.cloud_menu import (
    _esc,
    _fmt_size,
    _fmt_time,
    cloud_command,
    drive_command,
    handle_cloud_callback,
    render_cloud_hub,
    render_drive_home,
    render_sheets_home,
    sheets_command,
)
from alfa.integrations import google_sheets


def test_main_menu_markup_contains_sheets_and_drive():
    """Verify that _main_menu_markup includes Sheets and Drive buttons."""
    markup = _main_menu_markup()
    button_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "btn_sheets" in button_datas
    assert "btn_gdrive" in button_datas
    assert "btn_wa" in button_datas


def test_fmt_size_and_time():
    """Test format size and time helpers."""
    assert _fmt_size(0) == "0 B"
    assert _fmt_size(500) == "500 B"
    assert _fmt_size(1500) == "1.5 KB"
    assert _fmt_size(1048576) == "1.0 MB"

    assert _fmt_time("") == "-"
    assert _fmt_time("2026-10-20T19:01:24.957Z") == "20/10/26 19:01"


def test_esc():
    """Test markdown escaper."""
    assert _esc("test_file*name.xlsx") == "test\\_file\\*name.xlsx"


def test_google_sheets_metadata_and_preview_mocked():
    """Test get_spreadsheet_metadata and get_tab_preview logic with mock."""
    with patch("alfa.integrations.google_sheets.get_sheets_service") as mock_svc_factory:
        mock_svc = MagicMock()
        mock_svc_factory.return_value = mock_svc

        # Mock metadata
        mock_meta_get = MagicMock()
        mock_meta_get.execute.return_value = {
            "properties": {"title": "TEST SPREADSHEET"},
            "sheets": [
                {
                    "properties": {
                        "sheetId": 12345,
                        "title": "Data Utama",
                        "index": 0,
                        "gridProperties": {"rowCount": 100, "columnCount": 10},
                    }
                }
            ],
        }
        mock_svc.spreadsheets().get.return_value = mock_meta_get

        # Test metadata
        meta = google_sheets.get_spreadsheet_metadata("test_sid")
        assert meta["status"] == "success"
        assert meta["title"] == "TEST SPREADSHEET"
        assert meta["total_tabs"] == 1
        assert meta["tabs"][0]["title"] == "Data Utama"

        # Mock values get for preview
        mock_val_get = MagicMock()
        mock_val_get.execute.return_value = {
            "values": [
                ["Waktu", "Material", "QTY", "PIC"],
                ["20/10/2026", "Tiang 7m", "10", "Mandor A"],
                ["20/10/2026", "Kabel", "50", "Mandor B"],
            ]
        }
        mock_svc.spreadsheets().values().get.return_value = mock_val_get

        preview = google_sheets.get_tab_preview(
            spreadsheet_id="test_sid", tab_name="Data Utama", limit=5
        )
        assert preview["status"] == "success"
        assert preview["total_rows"] == 3
        assert preview["data_rows_count"] == 2
        assert preview["headers"] == ["Waktu", "Material", "QTY", "PIC"]
        assert len(preview["recent_rows"]) == 2


@pytest.mark.asyncio
async def test_render_cloud_hub():
    """Test rendering cloud hub menu."""
    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_user.id = 999
    update.callback_query = MagicMock()
    context = MagicMock()

    with patch("alfa.bot.cloud_menu._edit_or_send", new_callable=AsyncMock) as mock_edit:
        await render_cloud_hub(update, context)
        mock_edit.assert_called_once()
        text_arg = mock_edit.call_args[0][3]
        assert "Google Cloud Services Agent" in text_arg


@pytest.mark.asyncio
async def test_render_sheets_home():
    """Test rendering sheets home with worksheets list."""
    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_user.id = 999
    update.callback_query = MagicMock()
    context = MagicMock()

    mock_meta = {
        "status": "success",
        "title": "BOT LAPORAN",
        "url": "https://docs.google.com/test",
        "total_tabs": 2,
        "tabs": [
            {"sheet_id": 1, "title": "Tab 1"},
            {"sheet_id": 2, "title": "Tab 2"},
        ],
    }

    with patch("alfa.integrations.google_sheets.get_spreadsheet_id", return_value="test_id_123"), \
         patch("alfa.integrations.google_sheets.get_spreadsheet_metadata", return_value=mock_meta), \
         patch("alfa.bot.cloud_menu._edit_or_send", new_callable=AsyncMock) as mock_edit:
        await render_sheets_home(update, context, 0)
        mock_edit.assert_called_once()
        text_arg = mock_edit.call_args[0][3]
        assert "BOT LAPORAN" in text_arg
        markup = mock_edit.call_args[0][4]
        btn_labels = [b.text for row in markup.inline_keyboard for b in row]
        assert any("Tab 1" in b for b in btn_labels)
        assert any("Tab 2" in b for b in btn_labels)


@pytest.mark.asyncio
async def test_render_drive_home():
    """Test rendering Google Drive home."""
    update = MagicMock()
    update.effective_chat.id = 123
    update.effective_user.id = 999
    update.callback_query = MagicMock()
    context = MagicMock()

    mock_st = {
        "status": "success",
        "connected": True,
        "user": {"emailAddress": "sa@google.com"},
        "auth_mode": "service_account",
        "default_folder_name": "Test Folder",
        "default_folder_url": "https://drive.google.com",
        "mounted_drives": [{"name": "GDrive1", "active": True, "items_count": 50}],
    }

    with patch("alfa.bot.cloud_menu.gdrive_status", return_value=mock_st), \
         patch("alfa.bot.cloud_menu._edit_or_send", new_callable=AsyncMock) as mock_edit:
        await render_drive_home(update, context)
        mock_edit.assert_called_once()
        text_arg = mock_edit.call_args[0][3]
        assert "Google Drive Agent Explorer" in text_arg
        assert "GDrive1" in text_arg


@pytest.mark.asyncio
async def test_handle_cloud_callback_router():
    """Test handle_cloud_callback routing."""
    update = MagicMock()
    update.effective_user.id = 123
    update.effective_chat.id = 456
    context = MagicMock()

    query = MagicMock()
    query.answer = AsyncMock()
    update.callback_query = query

    with patch("alfa.bot.cloud_menu.is_authorized", return_value=True), \
         patch("alfa.bot.cloud_menu.render_cloud_hub", new_callable=AsyncMock) as mock_hub, \
         patch("alfa.bot.cloud_menu.render_sheets_home", new_callable=AsyncMock) as mock_sh, \
         patch("alfa.bot.cloud_menu.render_drive_home", new_callable=AsyncMock) as mock_dr:

        # Test non-cx callback
        query.data = "wx|home"
        assert await handle_cloud_callback(update, context) is False

        # Test cx|hub
        query.data = "cx|hub"
        assert await handle_cloud_callback(update, context) is True
        mock_hub.assert_called_once()

        # Test cx|sh|home
        query.data = "cx|sh|home"
        assert await handle_cloud_callback(update, context) is True
        mock_sh.assert_called_once()

        # Test cx|dr|home
        query.data = "cx|dr|home"
        assert await handle_cloud_callback(update, context) is True
        mock_dr.assert_called_once()


@pytest.mark.asyncio
async def test_slash_commands():
    """Test slash commands entrypoints."""
    update = MagicMock()
    update.effective_user.id = 123
    context = MagicMock()

    with patch("alfa.bot.cloud_menu.is_authorized", return_value=True), \
         patch("alfa.bot.cloud_menu.render_sheets_home", new_callable=AsyncMock) as mock_sh, \
         patch("alfa.bot.cloud_menu.render_drive_home", new_callable=AsyncMock) as mock_dr, \
         patch("alfa.bot.cloud_menu.render_cloud_hub", new_callable=AsyncMock) as mock_hub:

        await sheets_command(update, context)
        mock_sh.assert_called_once()

        await drive_command(update, context)
        mock_dr.assert_called_once()

        await cloud_command(update, context)
        mock_hub.assert_called_once()
