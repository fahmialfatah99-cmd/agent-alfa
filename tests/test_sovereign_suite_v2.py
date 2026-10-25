"""Unit tests for ALFA Sovereign Superpower Tools v2.

Tests:
1. sanitize_pii_and_secrets
2. compare_documents_semantic_diff
3. media_generate_subtitles_srt
4. query_sqlite_database_readonly
5. inspect_api_endpoint_health
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.tools import (
    compare_documents_semantic_diff,
    inspect_api_endpoint_health,
    media_generate_subtitles_srt,
    query_sqlite_database_readonly,
    sanitize_pii_and_secrets,
)


class TestSanitizePiiAndSecrets:
    def test_sanitize_raw_text_comprehensive(self):
        sample_text = (
            "Halo admin, ini data klien:\n"
            "NIK: 3201234567890001\n"
            "No HP: +6281234567890 atau 085712345678\n"
            "Email: direktur.utama@perusahaan.co.id\n"
            "Gemini Key: AIzaSyD3xAmP1eKeyExAmp1e1234567890abcdef\n"
            "OpenAI Key: sk-abcdef1234567890abcdef1234567890\n"
            "GitHub Token: ghp_1234567890abcdefghijklmnopqrstuvwxyz\n"
            "password: 'rahasianegara123'\n"
        )

        res = sanitize_pii_and_secrets(text_or_file_path=sample_text)
        assert res["status"] == "success"
        assert res["total_redacted"] >= 6
        output = res["sanitized_output"]

        # Assert no sensitive values leak
        assert "3201234567890001" not in output
        assert "+6281234567890" not in output
        assert "direktur.utama@perusahaan.co.id" not in output
        assert "AIzaSyD3xAmP1eKeyExAmp1e1234567890abcdef" not in output
        assert "sk-abcdef1234567890abcdef1234567890" not in output
        assert "rahasianegara123" not in output

        # Assert redacted markers present
        assert "[REDACTED_NIK:" in output
        assert "[REDACTED_PHONE:" in output
        assert "[REDACTED_EMAIL:" in output
        assert "[REDACTED_API_KEY]" in output
        assert "[REDACTED_SECRET]" in output

    def test_sanitize_file_save(self, tmp_path):
        src_file = tmp_path / "sensitive_log.txt"
        out_file = tmp_path / "cleaned_log.txt"
        src_file.write_text("Kontak darurat: 081234567890, email: admin@alfa.id, secret: 'supersecret'")

        res = sanitize_pii_and_secrets(text_or_file_path=str(src_file), save_output_path=str(out_file))
        assert res["status"] == "success"
        assert res["is_file"] is True
        assert out_file.exists()

        content = out_file.read_text(encoding="utf-8")
        assert "081234567890" not in content
        assert "admin@alfa.id" not in content
        assert "supersecret" not in content


class TestCompareDocumentsSemanticDiff:
    def test_compare_text_files_diff(self, tmp_path):
        file_a = tmp_path / "kontrak_v1.txt"
        file_b = tmp_path / "kontrak_v2.txt"

        file_a.write_text(
            "Pasal 1: Ketentuan Umum.\n"
            "Pasal 2: Biaya langganan sebesar Rp 500.000 per bulan.\n"
            "Pasal 3: Masa berlaku 12 bulan.\n"
            "Pasal 4: Ketentuan lama yang akan dihapus.\n"
        )

        file_b.write_text(
            "Pasal 1: Ketentuan Umum.\n"
            "Pasal 2: Biaya langganan sebesar Rp 750.000 per bulan.\n"
            "Pasal 3: Masa berlaku 12 bulan.\n"
            "Pasal 5: Klausul proteksi data baru ditambahkan.\n"
            "Pasal 6: Lampiran tambahan integrasi API.\n"
        )

        res = compare_documents_semantic_diff(str(file_a), str(file_b))
        assert res["status"] == "success"
        assert "markdown_report" in res
        assert res["similarity_percentage"] > 0

        # Check modifications and additions
        assert any("Pasal 6" in item for item in res["added_items"])
        assert len(res["modified_items"]) >= 1

        mod = res["modified_items"][0]
        assert "500.000" in mod["before"]
        assert "750.000" in mod["after"]
        assert mod["numeric_changes"] is not None

    def test_compare_missing_file_error(self):
        res = compare_documents_semantic_diff("non_existent_a.txt", "non_existent_b.txt")
        assert res["status"] == "error"
        assert "tidak ditemukan" in res["message"]


class TestMediaGenerateSubtitlesSrt:
    def test_missing_media_file_error(self):
        res = media_generate_subtitles_srt("/invalid/path/audio.mp3")
        assert res["status"] == "error"
        assert "tidak ditemukan" in res["message"]

    def test_mocked_transcription_srt_and_vtt(self, tmp_path):
        dummy_audio = tmp_path / "meeting_record.wav"
        dummy_audio.write_bytes(b"RIFFdummywavdata")

        # Mock segment objects returned by faster_whisper
        class MockSegment:
            def __init__(self, start, end, text):
                self.start = start
                self.end = end
                self.text = text

        segments = [
            MockSegment(0.0, 2.5, "Halo selamat pagi semua rekan kerja."),
            MockSegment(2.5, 6.2, "Hari ini kita membahas deployment ALFA OS."),
        ]

        mock_whisper = MagicMock()
        mock_whisper.transcribe.return_value = (segments, MagicMock(language="id"))

        with patch("faster_whisper.WhisperModel", return_value=mock_whisper):
            # Test SRT
            res_srt = media_generate_subtitles_srt(str(dummy_audio), output_format="srt", language="id")
            assert res_srt["status"] == "success"
            assert res_srt["format"] == "srt"
            assert res_srt["total_segments"] == 2
            srt_path = Path(res_srt["subtitle_file"])
            assert srt_path.exists()
            srt_text = srt_path.read_text(encoding="utf-8")
            assert "00:00:00,000 --> 00:00:02,500" in srt_text
            assert "Halo selamat pagi semua rekan kerja." in srt_text

            # Test VTT
            res_vtt = media_generate_subtitles_srt(str(dummy_audio), output_format="vtt", language="id")
            assert res_vtt["status"] == "success"
            assert res_vtt["format"] == "vtt"
            vtt_path = Path(res_vtt["subtitle_file"])
            assert vtt_path.exists()
            vtt_text = vtt_path.read_text(encoding="utf-8")
            assert vtt_text.startswith("WEBVTT")
            assert "00:00:00.000 --> 00:00:02.500" in vtt_text


class TestQuerySqliteDatabaseReadonly:
    def test_query_select_success(self, tmp_path):
        db_path = tmp_path / "inventory.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, sku TEXT, qty INTEGER)")
        conn.execute("INSERT INTO items VALUES (1, 'FIBER-OTB-24', 50)")
        conn.execute("INSERT INTO items VALUES (2, 'PATCH-CORD-SC', 120)")
        conn.commit()
        conn.close()

        res = query_sqlite_database_readonly(str(db_path), "SELECT id, sku, qty FROM items ORDER BY id ASC")
        assert res["status"] == "success"
        assert res["row_count"] == 2
        assert "items" in res["message"] or "baris" in res["message"]
        assert len(res["columns"]) == 3
        assert "FIBER-OTB-24" in res["markdown_table"]

    def test_query_mutation_rejection(self, tmp_path):
        db_path = tmp_path / "guard_test.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE secrets (id INT, val TEXT)")
        conn.commit()
        conn.close()

        # Test DELETE rejection
        res_del = query_sqlite_database_readonly(str(db_path), "DELETE FROM secrets WHERE id=1")
        assert res_del["status"] == "error"
        assert "ditolak" in res_del["message"].lower() or "read-only" in res_del["message"].lower()

        # Test DROP rejection
        res_drop = query_sqlite_database_readonly(str(db_path), "DROP TABLE secrets")
        assert res_drop["status"] == "error"
        assert "ditolak" in res_drop["message"].lower()

        # Test INSERT rejection
        res_ins = query_sqlite_database_readonly(str(db_path), "INSERT INTO secrets VALUES (1, 'hack')")
        assert res_ins["status"] == "error"

    def test_query_missing_db(self):
        res = query_sqlite_database_readonly("/non/existent/db.sqlite", "SELECT 1")
        assert res["status"] == "error"
        assert "tidak ditemukan" in res["message"]


class TestInspectApiEndpointHealth:
    def test_inspect_healthy_endpoint_mock(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.content = b'{"status": "ok", "service": "alfa-gateway"}'
        mock_resp.json.return_value = {"status": "ok", "service": "alfa-gateway"}

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        with patch("httpx.Client", return_value=mock_client):
            res = inspect_api_endpoint_health("https://api.alfa.local/health", expected_status=200, check_ssl=False)
            assert res["status"] == "success"
            assert res["is_healthy"] is True
            assert res["http_status"] == 200
            assert "api.alfa.local" in res["url"]

    def test_inspect_endpoint_connection_failure(self):
        with patch("httpx.Client", side_effect=Exception("Connection refused")):
            res = inspect_api_endpoint_health("https://offline.service.internal:9999", timeout_sec=1.0)
            assert res["status"] == "error"
            assert res["details"]["is_healthy"] is False
            assert "tidak dapat dihubungi" in res["message"]
