"""Tes renderer UI `alfa/bot/cloud_menu.py` (Sheets & Drive).

Semua hermetik: Telegram, Google Sheets, dan Drive di-mock. Fokus pada
*perilaku* yang dilihat pengguna — teks, tombol, fallback, dan router
callback — bukan detail implementasi.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, RetryAfter

from alfa.bot import cloud_menu as cm


class _ServiceError(OSError):
    """Kegagalan layanan tiruan (pesan ada di dalam kelas exception)."""


class _NetworkDownError(_ServiceError):
    def __init__(self) -> None:
        super().__init__("jaringan mati")


class _DriveDownError(_ServiceError):
    def __init__(self) -> None:
        super().__init__("drive down")


class _DiskFullError(_ServiceError):
    def __init__(self) -> None:
        super().__init__("disk penuh")


def _update(cb_data: str = "", user_id: int = 42) -> SimpleNamespace:
    # Tanpa cb_data -> update gaya perintah (tanpa callback query), sehingga
    # render memakai safe_send_message. Dengan cb_data -> update callback.
    query = (
        SimpleNamespace(data=cb_data, answer=AsyncMock(), edit_message_text=AsyncMock())
        if cb_data
        else None
    )
    return SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=1000),
        effective_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(chat_id=1000),
    )


def _context() -> SimpleNamespace:
    return SimpleNamespace(bot=AsyncMock())


class _Sent:
    """Rekam panggilan safe_send_message."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, context, chat_id, text, reply_to_message_id=None, reply_markup=None):
        self.calls.append(
            {"chat_id": chat_id, "text": text, "markup": reply_markup}
        )
        return SimpleNamespace(message_id=1)

    @property
    def last_text(self) -> str:
        return self.calls[-1]["text"]


@pytest.fixture()
def sent(monkeypatch):
    rec = _Sent()
    monkeypatch.setattr(cm, "safe_send_message", rec)
    cm._CACHE.clear()
    yield rec
    cm._CACHE.clear()


@pytest.fixture()
def authed(monkeypatch):
    monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)


def _button_texts(markup) -> list[str]:
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def _callback_data(markup) -> list[str]:
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def test_file_icon_variants():
    from alfa.bot import cloud_menu as cm

    assert cm._get_file_icon("", name="lagu.mp3") == "🎵"
    assert cm._get_file_icon("audio/ogg") == "🎵"
    assert cm._get_file_icon("", name="film.mp4") == "🎥"
    assert cm._get_file_icon("video/webm") == "🎥"
    assert cm._get_file_icon("", name="arsip.zip") == "📦"
    assert cm._get_file_icon("application/x-7z", name="x.7z") == "📄"


# ── _edit_or_send ──────────────────────────────────────────────────────────


def _query(data: str = "cx|hub") -> SimpleNamespace:
    return SimpleNamespace(
        data=data, answer=AsyncMock(), edit_message_text=AsyncMock()
    )


class TestEditOrSend:
    async def test_uses_query_edit_when_available(self, sent):
        query = _query()
        await cm._edit_or_send(query, _context(), 5, "halo")
        query.edit_message_text.assert_awaited_once()
        assert sent.calls == []

    async def test_no_query_falls_back_to_send(self, sent):
        await cm._edit_or_send(None, _context(), 5, "halo")
        assert sent.last_text == "halo"

    async def test_not_modified_is_silent(self, sent):
        query = _query()
        query.edit_message_text.side_effect = BadRequest("Message is not modified")
        await cm._edit_or_send(query, _context(), 5, "halo")
        assert sent.calls == []

    async def test_retry_after_is_silent(self, sent):
        query = _query()
        query.edit_message_text.side_effect = RetryAfter(3)
        await cm._edit_or_send(query, _context(), 5, "halo")
        assert sent.calls == []

    async def test_unexpected_error_falls_back(self, sent):
        query = _query()
        query.edit_message_text.side_effect = RuntimeError("boom")
        await cm._edit_or_send(query, _context(), 5, "halo")
        assert sent.last_text == "halo"


# ── Cloud Hub ──────────────────────────────────────────────────────────────


class TestCloudHub:
    async def test_hub_connected_with_metadata(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID123456789012345")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_spreadsheet_metadata",
            lambda sid: {"status": "success", "title": "Rekap ALFA", "total_tabs": 4},
        )
        monkeypatch.setattr(
            cm,
            "gdrive_status",
            lambda: {
                "status": "success",
                "connected": True,
                "user": {"displayName": "Fahmi"},
            },
        )
        await cm.render_cloud_hub(_update(), _context())
        assert "Rekap ALFA" in sent.last_text
        assert "4 tab" in sent.last_text
        assert "Fahmi" in sent.last_text
        assert "Terhubung" in sent.last_text

    async def test_hub_survives_service_errors(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID")

        def boom(_sid):
            raise _NetworkDownError()

        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_metadata", boom)

        def boom_status():
            raise _DriveDownError()

        monkeypatch.setattr(cm, "gdrive_status", boom_status)
        await cm.render_cloud_hub(_update(), _context())
        assert "Tidak Terhubung" in sent.last_text
        assert "Mati" in sent.last_text

    async def test_hub_without_sheet_id(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "")
        monkeypatch.setattr(cm, "gdrive_status", lambda: {"status": "error"})
        await cm.render_cloud_hub(_update(), _context())
        assert "Tidak Terhubung" in sent.last_text


# ── Sheets ─────────────────────────────────────────────────────────────────


class TestSheetsHome:
    async def test_no_spreadsheet_id(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "")
        await cm.render_sheets_home(_update(), _context())
        assert "Belum Terhubung" in sent.last_text
        assert "/setsheet" in sent.last_text

    async def test_metadata_failure(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_spreadsheet_metadata",
            lambda sid: {"status": "error", "message": "403 Forbidden"},
        )
        await cm.render_sheets_home(_update(), _context())
        assert "Gagal Mengakses" in sent.last_text
        assert "403 Forbidden" in sent.last_text

    async def test_lists_tabs_and_caches(self, sent, monkeypatch):
        tabs = [{"title": f"Tab {i}"} for i in range(10)]
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_spreadsheet_metadata",
            lambda sid: {
                "status": "success",
                "title": "Buku Kerja",
                "tabs": tabs,
                "url": "https://docs.google.com/spreadsheets/d/SID/edit",
            },
        )
        upd = _update(user_id=77)
        await cm.render_sheets_home(upd, _context())
        assert "Buku Kerja" in sent.last_text
        assert "10 lembar kerja" in sent.last_text
        # 8 tab halaman 1 + navigasi + tombol lain
        assert "📋 Tab 0" in " ".join(_button_texts(sent.calls[-1]["markup"]))
        assert any(d and d.startswith("cx|sh|h|1") for d in _callback_data(sent.calls[-1]["markup"]))
        # cache terisi untuk callback berikutnya
        assert cm._cache_get(77, "sheet_tabs") == tabs
        assert cm._cache_get(77, "current_sid") == "SID"

    async def test_last_page_clamps(self, sent, monkeypatch):
        tabs = [{"title": f"Tab {i}"} for i in range(3)]
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_spreadsheet_metadata",
            lambda sid: {"status": "success", "title": "T", "tabs": tabs},
        )
        await cm.render_sheets_home(_update(), _context(), page=99)
        assert "1/1" not in sent.last_text  # nav tidak dirender saat 1 halaman
        assert "📋 Tab 2" in " ".join(_button_texts(sent.calls[-1]["markup"]))


class TestTabDetail:
    async def _setup(self, monkeypatch, preview=None):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID")
        cm._cache_put(42, "sheet_tabs", [{"title": "Material"}])
        cm._cache_put(42, "current_sid", "SID")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_tab_preview",
            lambda **kw: preview
            or {
                "status": "success",
                "spreadsheet_title": "Rekap",
                "total_rows": 12,
                "data_rows_count": 11,
                "headers": [f"K{i}" for i in range(9)],
                "recent_rows": [["T73", "94", "Lahat"], [], ["A", "B"]],
                "sheet_id": 7,
            },
        )

    async def test_no_cache_falls_back_to_home(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "SID")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_spreadsheet_metadata",
            lambda sid: {"status": "success", "title": "X", "tabs": []},
        )
        await cm.render_tab_detail(_update(), _context(), 3)
        assert "Google Sheets Agent" in sent.last_text

    async def test_preview_error_shows_message(self, sent, monkeypatch):
        await self._setup(monkeypatch, preview={"status": "error", "message": "Tab hilang"})
        await cm.render_tab_detail(_update(), _context(), 0)
        assert "Tab hilang" in sent.last_text

    async def test_preview_success_formats_headers_and_rows(self, sent, monkeypatch):
        await self._setup(monkeypatch)
        await cm.render_tab_detail(_update(), _context(), 0)
        text = sent.last_text
        assert "Tab Sheets: Material" in text
        assert "12" in text and "11" in text
        assert "+3 kolom" in text  # 9 header, tampil 6
        assert "T73 • 94 • Lahat" in text
        assert "Belum ada baris data" not in text
        assert any(
            "Buka Tab Ini" in b for b in _button_texts(sent.calls[-1]["markup"])
        )

    async def test_long_entry_is_truncated(self, sent, monkeypatch):
        long_val = "X" * 150
        await self._setup(
            monkeypatch,
            preview={
                "status": "success",
                "spreadsheet_title": "R",
                "total_rows": 2,
                "data_rows_count": 1,
                "headers": ["H"],
                "recent_rows": [[long_val]],
            },
        )
        await cm.render_tab_detail(_update(), _context(), 0)
        assert "..." in sent.last_text
        assert long_val not in sent.last_text

    async def test_empty_rows_placeholder(self, sent, monkeypatch):
        await self._setup(
            monkeypatch,
            preview={
                "status": "success",
                "spreadsheet_title": "R",
                "total_rows": 1,
                "data_rows_count": 0,
                "headers": [],
                "recent_rows": [],
            },
        )
        await cm.render_tab_detail(_update(), _context(), 0)
        assert "Belum ada baris data" in sent.last_text


class TestAllSheets:
    async def test_empty_list(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "list_accessible_spreadsheets", lambda: [])
        await cm.render_all_sheets(_update(), _context())
        assert "Tidak ada file spreadsheet" in sent.last_text

    async def test_paginated_list_with_tags(self, sent, monkeypatch):
        items = [
            {"title": "Aktif", "id": "1", "is_active": True, "source": "Drive"},
            {"title": "Lokal", "id": "2", "is_active": False, "source": "local"},
            {"title": "Lain", "id": "3", "is_active": False, "source": "Drive"},
        ] + [{"title": f"X{i}", "id": str(i), "source": "Drive"} for i in range(8)]
        monkeypatch.setattr(cm.google_sheets, "list_accessible_spreadsheets", lambda: items)
        upd = _update(user_id=88)
        await cm.render_all_sheets(upd, _context(), page=1)
        labels = " ".join(_button_texts(sent.calls[-1]["markup"]))
        assert "11 file" in sent.last_text
        assert cm._cache_get(88, "all_sheets") == items
        assert any("▶️" in t or "◀️" in t for t in _button_texts(sent.calls[-1]["markup"]))
        assert labels  # ada tombol

    async def test_page_clamped(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm.google_sheets,
            "list_accessible_spreadsheets",
            lambda: [{"title": "S", "id": "1", "source": "Drive"}],
        )
        await cm.render_all_sheets(_update(), _context(), page=9)
        assert "1/1" not in _button_texts(sent.calls[-1]["markup"])


class TestSheetSelection:
    async def test_invalid_index_falls_back(self, sent, monkeypatch):
        monkeypatch.setattr(cm.google_sheets, "list_accessible_spreadsheets", lambda: [])
        await cm.render_sheet_selection(_update(), _context(), 5)
        assert "Tidak ada file spreadsheet" in sent.last_text

    async def test_active_sheet_has_no_set_button(self, sent, monkeypatch):
        item = {
            "title": "Rekap",
            "id": "SID-1234567890123456",
            "is_active": True,
            "source": "Drive",
            "url": "https://docs.google.com/spreadsheets/d/X",
        }
        cm._cache_put(42, "all_sheets", [item])
        await cm.render_sheet_selection(_update(), _context(), 0)
        text = sent.last_text
        assert "Aktif Digunakan Agent" in text
        assert "Jadikan Sheet Aktif" not in _button_texts(sent.calls[-1]["markup"])

    async def test_inactive_drive_sheet_offers_activation(self, sent, monkeypatch):
        item = {
            "title": "Kandidat",
            "id": "SID-1234567890123456",
            "is_active": False,
            "source": "Drive",
            "url": "https://docs.google.com/spreadsheets/d/Y",
        }
        cm._cache_put(42, "all_sheets", [item])
        await cm.render_sheet_selection(_update(), _context(), 0)
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert any("Jadikan Sheet Aktif" in b for b in buttons)
        assert any("Buka di Google Sheets" in b for b in buttons)

    async def test_local_sheet_hides_web_button(self, sent, monkeypatch):
        item = {
            "title": "Lokal",
            "id": "lokal",
            "is_active": False,
            "source": "local",
            "is_local": True,
            "url": "file:///x",
        }
        cm._cache_put(42, "all_sheets", [item])
        await cm.render_sheet_selection(_update(), _context(), 0)
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert not any("Buka di Google Sheets" in b for b in buttons)
        assert not any("Jadikan Sheet Aktif" in b for b in buttons)


# ── Drive ──────────────────────────────────────────────────────────────────


class TestDriveHome:
    async def test_connected_with_mounts_and_folder_url(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm,
            "gdrive_status",
            lambda: {
                "status": "success",
                "connected": True,
                "user": {"emailAddress": "alfa@example.com"},
                "auth_mode": "oauth",
                "default_folder_name": "alfa agent",
                "default_folder_url": "https://drive.google.com/drive/folders/XYZ",
                "mounted_drives": [
                    {"name": "GDrive1", "active": True, "items_count": 12},
                    {"name": "GDrive2", "active": False, "items_count": 0},
                ],
            },
        )
        await cm.render_drive_home(_update(), _context())
        text = sent.last_text
        assert "Terhubung" in text
        assert "alfa@example.com" in text
        assert "oauth" in text
        assert "GDrive1" in text and "12 item" in text
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert any("Buka Folder" in b for b in buttons)

    async def test_disconnected_defaults(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "gdrive_status", lambda: {"status": "error"})
        await cm.render_drive_home(_update(), _context())
        text = sent.last_text
        assert "Belum Terhubung" in text
        assert "Service Account" in text
        assert "Tidak ada folder lokal ter-mount" in text


class TestCloudFiles:
    async def test_error_response(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm,
            "gdrive_list_files",
            lambda **kw: {"status": "error", "message": "Kuota habis"},
        )
        await cm.render_cloud_files(_update(), _context())
        assert "Kuota habis" in sent.last_text

    async def test_empty_folder_with_back_button(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm, "gdrive_list_files", lambda **kw: {"status": "success", "files": []}
        )
        await cm.render_cloud_files(_update(), _context(), folder_ref="123")
        assert "Folder kosong" in sent.last_text
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert any("Folder Atas" in b for b in buttons)

    async def test_lists_folders_and_files_with_cache(self, sent, monkeypatch):
        files = [
            {"id": "F1", "name": "Folder Satu", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "D1", "name": "rekap.xlsx", "mimeType": "application/vnd.ms-excel"},
        ]
        monkeypatch.setattr(
            cm, "gdrive_list_files", lambda **kw: {"status": "success", "files": files}
        )
        upd = _update(user_id=9)
        await cm.render_cloud_files(upd, _context())
        assert "2 item" in sent.last_text
        datas = _callback_data(sent.calls[-1]["markup"])
        assert any(d and d.startswith("cx|dr|c|") for d in datas)
        assert any(d and d.startswith("cx|dr|f|") for d in datas)
        folder_cache = cm._cache_get(9, "folder_cache", {})
        assert any(v.get("id") == "F1" for v in folder_cache.values())

    async def test_numeric_folder_ref_resolves_to_id(self, sent, monkeypatch):
        seen: dict = {}

        def fake_list(folder_id: str = "", limit: int = 50):
            seen["folder_id"] = folder_id
            return {"status": "success", "files": [{"id": "x", "name": "a.txt", "mimeType": ""}]}

        monkeypatch.setattr(cm, "gdrive_list_files", fake_list)
        cm._cache_put(42, "folder_cache", {0: {"id": "REAL-ID", "name": "Sub"}})
        await cm.render_cloud_files(_update(), _context(), folder_ref="0")
        assert seen["folder_id"] == "REAL-ID"
        assert "Sub" in sent.last_text

    async def test_pagination_extra_carries_folder_ref(self, sent, monkeypatch):
        files = [
            {"id": str(i), "name": f"f{i}.txt", "mimeType": "text/plain"}
            for i in range(9)
        ]
        monkeypatch.setattr(
            cm, "gdrive_list_files", lambda **kw: {"status": "success", "files": files}
        )
        await cm.render_cloud_files(_update(), _context(), page=0, folder_ref="77")
        datas = _callback_data(sent.calls[-1]["markup"])
        assert any(d and d.startswith("cx|dr|c|1|77") for d in datas)


class TestCloudFileDetail:
    async def test_invalid_index_falls_back(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm, "gdrive_list_files", lambda **kw: {"status": "success", "files": []}
        )
        await cm.render_cloud_file_detail(_update(), _context(), 3)
        assert "Folder kosong" in sent.last_text or "Google Drive" in sent.last_text

    async def test_spreadsheet_offers_sheets_viewer(self, sent, monkeypatch):
        files = [
            {
                "id": "S1",
                "name": "Rekap",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "size": "2048",
                "modifiedTime": "2026-10-20T19:01:24.957Z",
                "webViewLink": "https://docs.google.com/spreadsheets/d/S1",
            }
        ]
        cm._cache_put(42, "cloud_files", files)
        cm._cache_put(42, "current_cloud_folder_ref", "all")
        await cm.render_cloud_file_detail(_update(), _context(), 0)
        text = sent.last_text
        assert "Detail File Cloud" in text
        assert "2.0 KB" in text
        assert "20/10/26 19:01" in text
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert any("Buka di Google Sheets Viewer" in b or "Sheets Viewer" in b for b in buttons)
        assert any("Buka di Google Drive" in b for b in buttons)

    async def test_generic_file_without_url(self, sent, monkeypatch):
        files = [{"id": "G1", "name": "catatan.txt", "mimeType": "text/plain"}]
        cm._cache_put(42, "cloud_files", files)
        await cm.render_cloud_file_detail(_update(), _context(), 0)
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert not any("Buka di Google Drive" in b for b in buttons)
        assert any("Kembali ke File" in b for b in buttons)


# ── Mounted Drive ──────────────────────────────────────────────────────────


class TestMountedDriveFiles:
    async def test_error_response(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "error", "message": "Mount tidak ada"},
        )
        await cm.render_mounted_drive_files(_update(), _context())
        assert "Mount tidak ada" in sent.last_text

    async def test_empty_root_has_no_parent_button(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "success", "files": []},
        )
        await cm.render_mounted_drive_files(_update(), _context(), drive_idx=1)
        assert "Folder kosong" in sent.last_text
        buttons = _button_texts(sent.calls[-1]["markup"])
        assert not any("Folder Atas" in b for b in buttons)

    async def test_empty_subpath_offers_parent(self, sent, monkeypatch):
        cm._cache_put(42, "mount_cache_2", {0: "sub/dir"})
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "success", "files": []},
        )
        await cm.render_mounted_drive_files(_update(), _context(), drive_idx=2, subpath_idx=0)
        assert "sub/dir" in sent.last_text
        assert any("Folder Atas" in b for b in _button_texts(sent.calls[-1]["markup"]))

    async def test_lists_dirs_and_files(self, sent, monkeypatch):
        files = [
            {"name": "Sub", "is_dir": True},
            {"name": "laporan.pdf", "is_dir": False, "size": 4096, "path": "/x/laporan.pdf"},
        ]
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "success", "files": files},
        )
        upd = _update(user_id=5)
        await cm.render_mounted_drive_files(upd, _context(), drive_idx=1)
        datas = _callback_data(sent.calls[-1]["markup"])
        assert any(d and d.startswith("cx|dr|m|1|") for d in datas)
        assert any(d and d.startswith("cx|dr|mf|1|") for d in datas)
        cache = cm._cache_get(5, "mount_cache_1", {})
        assert "Sub" in cache.values()
        assert cm._cache_get(5, "mounted_files_1") == files


class TestMountedPagination:
    async def test_many_files_and_subpath_parent_button(self, sent, monkeypatch):
        files = [
            {"name": f"f{i}.txt", "is_dir": False, "size": 10} for i in range(8)
        ]
        cm._cache_put(42, "mount_cache_1", {0: "sub/dir"})
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "success", "files": files},
        )
        upd = _update(user_id=42)
        await cm.render_mounted_drive_files(upd, _context(), drive_idx=1, subpath_idx=0, page=0)
        datas = _callback_data(sent.calls[-1]["markup"])
        # navigasi halaman membawa drive/subpath
        assert any(d and d.startswith("cx|dr|m|1|0|1") for d in datas)
        # tombol "Folder Atas" di nav bawah
        assert any("Folder Atas" in b for b in _button_texts(sent.calls[-1]["markup"]))
        # cache subfolder induk disimpan (sticky)
        cache = cm._cache_get(42, "mount_cache_1", {})
        assert "sub" in cache.values()


class TestMountedFileDetail:
    async def test_invalid_index_falls_back(self, sent, monkeypatch):
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "success", "files": []},
        )
        await cm.render_mounted_file_detail(_update(), _context(), 1, 9)
        assert "Folder kosong" in sent.last_text

    async def test_success_shows_path_and_size(self, sent, monkeypatch):
        cm._cache_put(
            42,
            "mounted_files_1",
            [{"name": "foto.jpg", "path": "/home/u/GDrive1/foto.jpg", "size": 1024}],
        )
        await cm.render_mounted_file_detail(_update(), _context(), 1, 0)
        text = sent.last_text
        assert "foto.jpg" in text
        assert "/home/u/GDrive1/foto.jpg" in text
        assert "1.0 KB" in text


# ── Router callback ────────────────────────────────────────────────────────


class TestHandleCallback:
    async def test_not_a_cloud_callback(self, sent):
        assert await cm.handle_cloud_callback(_update("btn_menu"), _context()) is False

    async def test_no_query(self, sent):
        upd = SimpleNamespace(callback_query=None, effective_user=None, effective_chat=None)
        assert await cm.handle_cloud_callback(upd, _context()) is False

    async def test_unauthenticated_is_rejected(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: False)
        upd = _update("cx|hub")
        assert await cm.handle_cloud_callback(upd, _context()) is True
        upd.callback_query.answer.assert_awaited_once()
        assert sent.calls == []

    async def test_hub_route(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "")
        monkeypatch.setattr(cm, "gdrive_status", lambda: {"status": "error"})
        upd = _update("cx|hub")
        assert await cm.handle_cloud_callback(upd, _context()) is True
        upd.callback_query.edit_message_text.assert_awaited()

    async def test_sheets_routes(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "")
        for data in ("cx|sh|home", "cx|sh|h|2", "cx|sh|t|0", "cx|sh|all|0", "cx|sh|sel|0"):
            upd = _update(data)
            assert await cm.handle_cloud_callback(upd, _context()) is True
            upd.callback_query.edit_message_text.assert_awaited()

    async def test_sheets_set_activates_spreadsheet(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        cm._cache_put(42, "all_sheets", [{"id": "NEW-ID", "title": "Baru"}])
        calls: list[str] = []
        monkeypatch.setattr(cm.google_sheets, "set_spreadsheet_id", lambda x: calls.append(x))
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "OLD")
        monkeypatch.setattr(
            cm.google_sheets,
            "get_spreadsheet_metadata",
            lambda sid: {"status": "success", "title": "Baru", "tabs": []},
        )
        assert await cm.handle_cloud_callback(_update("cx|sh|set|0"), _context()) is True
        assert calls == ["NEW-ID"]

    async def test_sheets_set_with_invalid_index_is_noop(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        cm._cache_put(42, "all_sheets", [])
        calls: list[str] = []
        monkeypatch.setattr(cm.google_sheets, "set_spreadsheet_id", lambda x: calls.append(x))
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "")
        assert await cm.handle_cloud_callback(_update("cx|sh|set|5"), _context()) is True
        assert calls == []

    async def test_drive_routes(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        monkeypatch.setattr(cm, "gdrive_status", lambda: {"status": "error"})
        monkeypatch.setattr(
            cm, "gdrive_list_files", lambda **kw: {"status": "success", "files": []}
        )
        monkeypatch.setattr(
            cm,
            "gdrive_list_mounted_files",
            lambda **kw: {"status": "success", "files": []},
        )
        for data in ("cx|dr|home", "cx|dr|c|0|all", "cx|dr|f|0", "cx|dr|m|1|0|0", "cx|dr|mf|1|0"):
            upd = _update(data)
            assert await cm.handle_cloud_callback(upd, _context()) is True
            upd.callback_query.edit_message_text.assert_awaited()

    async def test_noop_and_unknown_domain(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        for data in ("cx|noop", "cx|zzz"):
            sent.calls.clear()
            assert await cm.handle_cloud_callback(_update(data), _context()) is True
        # "cx" saja bukan callback cloud (tanpa pemisah domain)
        assert await cm.handle_cloud_callback(_update("cx"), _context()) is False

    async def test_render_error_is_logged_not_raised(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)

        async def boom(*_a, **_k):
            raise _DiskFullError()

        monkeypatch.setattr(cm, "render_cloud_hub", boom)
        upd = _update("cx|hub")
        assert await cm.handle_cloud_callback(upd, _context()) is True  # tidak melempar
        upd.callback_query.answer.assert_awaited_once()


# ── Slash commands ─────────────────────────────────────────────────────────


class TestCommands:
    async def test_unauthorized_commands_do_nothing(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: False)
        await cm.sheets_command(_update(), _context())
        await cm.drive_command(_update(), _context())
        await cm.cloud_command(_update(), _context())
        assert sent.calls == []

    async def test_authorized_commands_render(self, sent, monkeypatch):
        monkeypatch.setattr(cm, "is_authorized", lambda _uid: True)
        monkeypatch.setattr(cm.google_sheets, "get_spreadsheet_id", lambda: "")
        monkeypatch.setattr(cm, "gdrive_status", lambda: {"status": "error"})

        await cm.sheets_command(_update(), _context())
        assert "Belum Terhubung" in sent.last_text

        await cm.drive_command(_update(), _context())
        assert "Google Drive Agent Explorer" in sent.last_text

        await cm.cloud_command(_update(), _context())
        assert "Google Cloud Services" in sent.last_text


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
