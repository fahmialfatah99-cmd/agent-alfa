"""Hermetic unit tests for Phase 4 Coverage Boost:
Covers integrations tools, GDrive operations, WA digest, and TTS engine.
"""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alfa.bot.wa_digest import (
    _esc,
    _parse_ts,
    _set_setting,
    build_digest_text,
    collect_records,
    digest_enabled,
    digest_hours,
    send_digest,
    summarize_records,
)
from alfa.integrations.gdrive.operations import (
    gdrive_create_folder,
    gdrive_download_file,
    gdrive_list_files,
    gdrive_sync_to_second_brain,
    gdrive_upload_file,
)
from alfa.media.tts_engine import (
    clean_markdown_for_tts,
    text_to_speech_ogg,
)
from alfa.swarm.engine import (
    _budget_exceeded,
    _provider_dead_streak,
    _swarm_budget,
    conduct_multi_agent_meeting,
)
from alfa.tools.system.integrations import (
    _wa_api,
    generate_secure_password,
    list_wa_drive_uploads,
    manage_wa_sheets_bot,
    query_database,
    schedule_reminder,
    scrcpy_android_control,
    start_focus_session,
    wa_add_format,
    wa_delete_format,
    wa_get_chats,
    wa_get_incoming,
    wa_get_me,
    wa_get_messages,
    wa_get_records,
    wa_list_formats,
    wa_search_messages,
    wa_send_message,
    wa_toggle_format,
)

# ==============================================================================
# 1. Tests for alfa.tools.system.integrations
# ==============================================================================

class TestIntegrationsTools:
    def test_schedule_reminder(self):
        with patch("alfa.tools.system.integrations.database.add_reminder_sync", return_value=42):
            res = schedule_reminder("2026-10-20T10:00:00", "Beli kopi")
            assert res["status"] == "success"
            assert res["reminder_id"] == 42
            assert "Pengingat #42" in res["message"]

        with patch("alfa.tools.system.integrations.database.add_reminder_sync", side_effect=ValueError("bad time")):
            res = schedule_reminder("invalid", "pesan")
            assert res["status"] == "error"
            assert "bad time" in res["message"]

    def test_generate_secure_password(self):
        res1 = generate_secure_password(length=16, count=1)
        assert res1["status"] == "success"
        assert len(res1["passwords"][0]) == 16

        res_multi = generate_secure_password(length=12, count=3)
        assert res_multi["status"] == "success"
        assert len(res_multi["passwords"]) == 3
        for p in res_multi["passwords"]:
            assert len(p) == 12

        # Test flags
        res_no_special = generate_secure_password(length=10, include_special=False)
        assert res_no_special["status"] == "success"

    def test_start_focus_session(self):
        with patch("alfa.tools.system.integrations.get_current_user_id", return_value=None):
            res = start_focus_session("Coding")
            assert res["status"] == "error"
            assert "User context tidak ditemukan" in res["message"]

        with (
            patch("alfa.tools.system.integrations.get_current_user_id", return_value=123),
            patch("alfa.tools.system.integrations.get_current_chat_id", return_value=456),
            patch(
                "alfa.tools.system.integrations.database.start_focus_session_sync",
                return_value={"id": 1, "end_time": "12:00"},
            ),
        ):
            res = start_focus_session("Coding", duration_minutes=30)
            assert res["status"] == "success"
            assert "Coding" in res["message"]

    def test_wa_api_success(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "success", "data": "ok"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = _wa_api("GET", "/api/chats", params={"limit": 5})
            assert res["status"] == "success"
            assert res["data"] == "ok"

    def test_wa_api_error_response(self):
        mock_err = MagicMock()
        mock_err.read.return_value = json.dumps({"status": "error", "message": "Gagal baca", "code": "WA_ERROR"}).encode("utf-8")
        mock_err_instance = Exception("HTTP 500")
        mock_err_instance.read = mock_err.read

        with patch("urllib.request.urlopen", side_effect=mock_err_instance):
            res = _wa_api("POST", "/api/send", body={"to": "123", "message": "hi"})
            assert res["status"] == "error"
            assert res["message"] == "Gagal baca"

    def test_wa_api_unreachable(self):
        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            res = _wa_api("GET", "/api/me")
            assert res["status"] == "error"
            assert "tak terjangkau" in res["message"]

    def test_wa_helpers(self):
        with patch("alfa.tools.system.integrations._wa_api", return_value={"status": "success"}) as mock_api:
            wa_get_chats(10, only_unread=True)
            mock_api.assert_called_with("GET", "/api/chats", {"limit": 10, "unread": "1"})

            wa_get_messages("0812345", 25)
            mock_api.assert_called_with("GET", "/api/messages", {"chat": "0812345", "limit": 25})

            wa_search_messages("invoice")
            mock_api.assert_called_with("GET", "/api/search", {"q": "invoice"})

            wa_get_incoming(15)
            mock_api.assert_called_with("GET", "/api/incoming", {"limit": 15})

            wa_get_me()
            mock_api.assert_called_with("GET", "/api/me")

            wa_send_message("0812345", "Tes kirim")
            mock_api.assert_called_with("POST", "/api/send", body={"to": "0812345", "message": "Tes kirim"})

            wa_list_formats()
            mock_api.assert_called_with("GET", "/api/formats")

            wa_toggle_format("Stok", True)
            mock_api.assert_called_with("POST", "/api/formats/toggle", body={"name": "Stok", "enabled": True})

            wa_add_format("Laporan", "lapor, info", "TabLaporan")
            mock_api.assert_called_with("POST", "/api/formats", body={"name": "Laporan", "keywords": ["lapor", "info"], "tab": "TabLaporan"})

            wa_delete_format("Laporan")
            mock_api.assert_called_with("DELETE", "/api/formats", body={"name": "Laporan"})

            wa_get_records("Stok", 20)
            mock_api.assert_called_with("GET", "/api/records", {"format": "Stok", "limit": 20})

    def test_manage_wa_sheets_bot(self):
        with patch("subprocess.run") as mock_sub:
            # Status action
            mock_sub.side_effect = [
                MagicMock(stdout="active\n"),
                MagicMock(stdout="enabled\n"),
                MagicMock(stdout="Running details...\n"),
            ]
            res = manage_wa_sheets_bot(action="status")
            assert res["status"] == "success"
            assert res["is_running"] is True

            # Start action
            mock_sub.side_effect = [
                MagicMock(returncode=0),
                MagicMock(stdout="active\n"),
            ]
            with patch("time.sleep"):
                res_start = manage_wa_sheets_bot(action="start")
                assert res_start["status"] == "success"
                assert "berhasil di-start" in res_start["message"]

            # Logs action
            mock_sub.side_effect = [
                MagicMock(stdout="Log line 1\nLog line 2"),
            ]
            res_logs = manage_wa_sheets_bot(action="logs")
            assert res_logs["status"] == "success"
            assert "Log line 1" in res_logs["logs"]

            # Unknown action
            res_unk = manage_wa_sheets_bot(action="destroy")
            assert res_unk["status"] == "error"

    def test_list_wa_drive_uploads(self, tmp_path):
        fake_file = tmp_path / "drive_uploads.json"
        with patch("os.path.expanduser", return_value=str(fake_file)):
            # When file does not exist
            res_none = list_wa_drive_uploads()
            assert res_none["total"] == 0

            # When file exists with entries
            fake_file.write_text(json.dumps({
                "uploads": [
                    {"ts": "2026-10-19", "file_name": "foto.jpg", "folder": "Uploads", "sender": "Budi", "group": "Grup A", "web_link": "https://drive..."}
                ]
            }))
            res_exist = list_wa_drive_uploads(limit=5)
            assert res_exist["status"] == "success"
            assert res_exist["total"] == 1
            assert res_exist["uploads"][0]["nama_file"] == "foto.jpg"

    def test_scrcpy_android_control(self):
        with patch("shutil.which", return_value="/usr/bin/adb"):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(stdout="device1  device\n")
                res = scrcpy_android_control(action="status")
                assert res["status"] == "success"
                assert "device1" in res["raw_devices_output"]

                # mirror
                with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                    with patch("subprocess.Popen") as mock_popen:
                        res_mirror = scrcpy_android_control(action="mirror")
                        assert res_mirror["status"] == "success"
                        assert mock_popen.called

                # unknown
                res_unk = scrcpy_android_control(action="explode")
                assert res_unk["status"] == "error"

    def test_query_database(self, tmp_path):
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users (name) VALUES ('Alice'), ('Bob')")
        conn.commit()
        conn.close()

        # Non-existent DB
        res_err = query_database(str(tmp_path / "nonexistent.db"), "SELECT 1")
        assert res_err["status"] == "error"

        # Dangerous query
        res_dang = query_database(str(db_file), "DROP TABLE users")
        assert res_dang["status"] == "error"
        assert "DROP" in res_dang["message"]

        # Valid SELECT
        res_sel = query_database(str(db_file), "SELECT * FROM users ORDER BY id")
        assert res_sel["status"] == "success"
        assert res_sel["row_count"] == 2
        assert res_sel["data"][0]["name"] == "Alice"

        # Valid INSERT / UPDATE
        res_upd = query_database(str(db_file), "UPDATE users SET name = 'Charlie' WHERE id = 1")
        assert res_upd["status"] == "success"
        assert "1 baris terpengaruh" in res_upd["message"]


# ==============================================================================
# 2. Tests for alfa.integrations.gdrive.operations
# ==============================================================================

class TestGDriveOperations:
    def test_gdrive_list_files(self):
        mock_service = MagicMock()
        mock_files = [
            {"id": "f1", "name": "doc.pdf", "mimeType": "application/pdf"}
        ]
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": mock_files
        }

        with patch("alfa.integrations.gdrive.operations._get_gdrive_service", return_value=mock_service):
            res = gdrive_list_files(folder_id="root", query="doc")
            assert res["status"] == "success"
            assert res["total_found"] == 1
            assert res["files"][0]["name"] == "doc.pdf"

        # Error handling
        with patch("alfa.integrations.gdrive.operations._get_gdrive_service", side_effect=RuntimeError("Auth expired")):
            res_err = gdrive_list_files()
            assert res_err["status"] == "error"
            assert "Auth expired" in res_err["message"]

    def test_gdrive_upload_file(self, tmp_path):
        sample_file = tmp_path / "test.txt"
        sample_file.write_text("Hello GDrive")

        mock_service = MagicMock()
        mock_service.files.return_value.create.return_value.execute.return_value = {
            "id": "new_id_123",
            "name": "test.txt",
            "webViewLink": "https://drive.google.com/test",
        }

        with (
            patch("alfa.integrations.gdrive.operations._get_gdrive_service", return_value=mock_service),
            patch("googleapiclient.http.MediaFileUpload"),
        ):
            res = gdrive_upload_file(filepath=str(sample_file), custom_filename="test.txt")
            assert res["status"] == "success"
            assert res["file_id"] == "new_id_123"

        # File not found
        res_missing = gdrive_upload_file(filepath=str(tmp_path / "not_there.txt"))
        assert res_missing["status"] == "error"

    def test_gdrive_download_file(self, tmp_path):
        mock_service = MagicMock()
        mock_service.files.return_value.get.return_value.execute.return_value = {
            "name": "downloaded.txt"
        }

        with (
            patch("alfa.integrations.gdrive.operations._get_gdrive_service", return_value=mock_service),
            patch("alfa.integrations.gdrive.operations.SANDBOX_DIR", str(tmp_path)),
            patch("googleapiclient.http.MediaIoBaseDownload") as mock_downloader,
        ):
            mock_downloader.return_value.next_chunk.return_value = (None, True)
            res = gdrive_download_file(file_id="fid_123", save_filename="out.txt")
            assert res["status"] == "success"
            assert "out.txt" in res["saved_path"]

    def test_gdrive_create_folder(self):
        mock_service = MagicMock()
        mock_service.files.return_value.create.return_value.execute.return_value = {
            "id": "folder_999",
            "name": "NewFolder",
            "webViewLink": "https://drive.google.com/folder",
        }

        with patch("alfa.integrations.gdrive.operations._get_gdrive_service", return_value=mock_service):
            res = gdrive_create_folder(folder_name="NewFolder")
            assert res["status"] == "success"
            assert res["folder_id"] == "folder_999"

    def test_gdrive_sync_to_second_brain(self):
        mock_service = MagicMock()
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "doc.txt", "mimeType": "text/plain"}]
        }

        with (
            patch("alfa.integrations.gdrive.operations._get_gdrive_service", return_value=mock_service),
            patch("alfa.integrations.gdrive.operations.gdrive_download_file", return_value={"status": "success", "saved_path": "/tmp/doc.txt"}),
            patch("alfa.memory.vector.ingest_document", return_value={"status": "success", "chunks": 2}),
        ):
            res = gdrive_sync_to_second_brain(folder_id="fld_1", limit=2)
            assert res["status"] == "success"
            assert res["total_ingested"] >= 1


# ==============================================================================
# 3. Tests for alfa.bot.wa_digest
# ==============================================================================

class TestWADigest:
    def test_setting_and_hours(self):
        with patch("alfa.core.database.get_sync_db") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_conn

            # Setting exists
            mock_conn.execute.return_value.fetchone.return_value = {"value": "08:00,17:00"}
            hours = digest_hours()
            assert hours == ["08:00", "17:00"]

            # Setting not exists (default)
            mock_conn.execute.return_value.fetchone.return_value = None
            assert digest_enabled() is True

            # Set setting
            _set_setting("wa_digest_enabled", "1")
            assert mock_conn.execute.called

    def test_parse_ts(self):
        assert _parse_ts("19/10/2026, 10.30.00") is not None
        assert _parse_ts("19/10/2026 10.30.00") is not None
        assert _parse_ts("19/10/2026, 10:30:00") is not None
        assert _parse_ts("invalid date") is None
        assert _parse_ts("") is None

    def test_collect_records(self):
        with patch("alfa.tools.wa_get_records") as mock_wa:
            mock_wa.return_value = {
                "status": "success",
                "records": [
                    {"timestamp": "19/10/2026, 08.00.00", "body": "Pesan hari ini", "format_name": "Stok"},
                    {"timestamp": "01/01/2020, 08.00.00", "body": "Pesan lama", "format_name": "Stok"},
                ],
            }
            recs = collect_records("Stok", limit=10)
            assert len(recs) == 2
            assert recs[0]["body"] == "Pesan hari ini"

    def test_esc(self):
        assert _esc("test `code` *bold* [link]") == "test 'code' ·bold· (link)"

    @pytest.mark.asyncio
    async def test_summarize_records(self):
        # Empty records
        assert await summarize_records([]) == ""

        # With records
        with patch("alfa.bot.turn_executor.run_agent_turn", new_callable=AsyncMock) as mock_turn:
            mock_turn.return_value = "Ringkasan: Semua aman terkendali."
            res = await summarize_records([{"body": "Update stok aman", "format_name": "Stok"}])
            assert "Semua aman" in res

    @pytest.mark.asyncio
    async def test_build_digest_text(self):
        # Empty
        with patch("alfa.bot.wa_digest.collect_records", return_value=[]):
            text_empty = await build_digest_text()
            assert "belum ada catatan terekam" in text_empty

        # With items
        sample_records = [
            {"format_name": "Stok", "timestamp": "19/10/2026", "sender": "Budi", "body": "Barang masuk"},
            {"format_name": "Kas", "timestamp": "19/10/2026", "sender": "Siti", "body": "Uang masuk"},
        ]
        with (
            patch("alfa.bot.wa_digest.collect_records", return_value=sample_records),
            patch("alfa.bot.wa_digest.summarize_records", new_callable=AsyncMock, return_value="AI: Stok bertambah"),
        ):
            text = await build_digest_text()
            assert "Digest Cerdas WA" in text
            assert "Stok" in text
            assert "Kas" in text
            assert "AI: Stok bertambah" in text

    @pytest.mark.asyncio
    async def test_send_digest(self):
        mock_ctx = MagicMock()
        with (
            patch("alfa.bot.wa_digest.build_digest_text", new_callable=AsyncMock, return_value="Teks Digest"),
            patch("alfa.bot.helpers.safe_send_message", new_callable=AsyncMock) as mock_send,
        ):
            res = await send_digest(mock_ctx, 12345)
            assert res is True
            mock_send.assert_called_with(mock_ctx, 12345, "Teks Digest")


# ==============================================================================
# 4. Tests for alfa.media.tts_engine
# ==============================================================================

class TestTTSEngine:
    def test_clean_markdown_for_tts(self):
        text = "Halo ```python\nprint(1)\n``` ini [Google](https://google.com) *tebal* dan `inline`."
        cleaned = clean_markdown_for_tts(text)
        assert "```" not in cleaned
        assert "https://" not in cleaned
        assert "Google" in cleaned
        assert "inline" not in cleaned
        assert "tebal" in cleaned

    @pytest.mark.asyncio
    async def test_text_to_speech_ogg_edge_tts(self):
        mock_communicate = MagicMock()
        mock_communicate.save = AsyncMock()

        mock_mod = MagicMock()
        mock_mod.Communicate.return_value = mock_communicate

        with patch("alfa.media.tts_engine._get_edge_tts", return_value=mock_mod):
            with patch("os.path.getsize", return_value=200):
                path = await text_to_speech_ogg("Halo ini pengujian suara")
                assert path.endswith(".mp3")
                assert os.path.exists(path)
                try:
                    os.remove(path)
                except OSError:
                    pass

    @pytest.mark.asyncio
    async def test_text_to_speech_ogg_gtts_fallback(self):
        mock_gtts = MagicMock()

        with (
            patch("alfa.media.tts_engine._get_edge_tts", return_value=None),
            patch.dict("sys.modules", {"gtts": mock_gtts}),
            patch("os.path.getsize", return_value=250),
        ):
            path = await text_to_speech_ogg("Halo fallback gtts")
            assert path.endswith(".mp3")
            try:
                os.remove(path)
            except OSError:
                pass


# ==============================================================================
# 5. Tests for alfa.swarm.engine
# ==============================================================================


class TestSwarmEngine:
    def test_swarm_budget(self, monkeypatch):
        monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "45")
        monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "10")
        t, s = _swarm_budget()
        assert t == 45.0
        assert s == 10

        # Default-nya AKTIF (P1): timeout & batas langkah tidak boleh 0
        # (misi tanpa payung bisa berjalan selamanya & membakar kuota).
        monkeypatch.delenv("ALFA_SWARM_TASK_TIMEOUT", raising=False)
        monkeypatch.delenv("ALFA_SWARM_MAX_STEPS", raising=False)
        t_default, s_default = _swarm_budget()
        assert t_default > 0
        assert s_default > 0

        # Nilai tidak valid → jatuh ke default, bukan 0 (nonaktif).
        monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "invalid")
        monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "invalid")
        t, s = _swarm_budget()
        assert t == 1800.0
        assert s == 40

    def test_provider_dead_streak(self):
        # Empty or short
        assert _provider_dead_streak([]) == ""
        assert _provider_dead_streak([{"status": "error"}]) == ""

        # Streak of 3 matching errors
        dead_steps = [
            {"status": "error", "tool_output": "SEMUA provider gagal coba lagi", "execution_summary": ""},
            {"status": "error", "tool_output": "", "execution_summary": "SEMUA provider gagal total"},
            {"status": "error", "tool_output": "SEMUA provider gagal", "execution_summary": ""},
        ]
        msg = _provider_dead_streak(dead_steps)
        assert "provider mati" in msg

        # Not matching
        alive_steps = [
            {"status": "success", "tool_output": "ok"},
            {"status": "error", "tool_output": "SEMUA provider gagal"},
            {"status": "error", "tool_output": "SEMUA provider gagal"},
        ]
        assert _provider_dead_streak(alive_steps) == ""

    def test_budget_exceeded(self, monkeypatch):
        # Steps exceeded
        monkeypatch.setenv("ALFA_SWARM_MAX_STEPS", "2")
        monkeypatch.setenv("ALFA_SWARM_TASK_TIMEOUT", "0")
        assert "batas 2 langkah" in _budget_exceeded([{}, {}])
        assert _budget_exceeded([{}]) == ""

    def test_cancel_flag(self):
        from alfa.swarm import workspace_hygiene as wh

        # State sesi kini per-session (bukan global MEETING_RUNNING).
        wh.register_session("uji_phase4")
        try:
            wh._clear_cancel_flag("uji_phase4")
            assert wh._cancel_requested("uji_phase4") is False
            assert wh.request_cancel_swarm("uji_phase4") is True
            assert wh._cancel_requested("uji_phase4") is True
            wh._clear_cancel_flag("uji_phase4")
            assert wh._cancel_requested("uji_phase4") is False
        finally:
            wh.unregister_session("uji_phase4")

    @pytest.mark.asyncio
    async def test_conduct_multi_agent_meeting_fast(self):
        fake_agent = {
            "name": "DevAgent",
            "role": "Developer",
            "model": "test-model",
            "is_enabled": 1,
            "system_prompt": "You are a developer.",
        }
        step_dict = {
            "step_num": 1,
            "agent_name": "DevAgent",
            "role": "Developer",
            "tool_used": "run_command",
            "duration_ms": 120,
            "status": "success",
            "execution_summary": "Langkah 1 selesai",
            "deliverable_file": None,
        }
        with (
            patch("alfa.core.database.list_custom_agents_sync", return_value=[fake_agent]),
            patch("alfa.swarm.engine._execute_agent_step", new_callable=AsyncMock) as mock_step,
            patch("alfa.swarm.engine._cancel_requested", return_value=False),
            patch("alfa.swarm.engine.generate_agent_response", new_callable=AsyncMock, return_value="KONSENSUS UTAMA\nACTION PLAN 1"),
            patch("alfa.swarm.engine.log_live"),
            patch("alfa.swarm.engine._harvest_new_sandbox_projects", return_value=[]),
        ):
            mock_step.return_value = (step_dict, True, "QA passed")
            res = await conduct_multi_agent_meeting(
                topic="Buat skrip tes",
                mode="execute",
                participant_names=["DevAgent"],
            )
            assert res["status"] == "success"
            assert "DevAgent" in res["participants"]
            assert res["mode"] == "execute"

