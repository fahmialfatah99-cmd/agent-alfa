"""Unit test parser seksi output AI (web_dashboard._parse_ai_sections)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web_dashboard  # noqa: E402


class TestParseAiSections:
    def test_format_baku(self):
        teks = "===TIKTOK_SCRIPT===\nisi script\n===TELEGRAM_CARD===\nisi kartu"
        out = web_dashboard._parse_ai_sections(teks)
        assert out["tiktok_script"] == "isi script"
        assert out["telegram_card"] == "isi kartu"

    def test_kunci_lowercase(self):
        out = web_dashboard._parse_ai_sections("===WA_BROADCAST===\npesan")
        assert "wa_broadcast" in out

    def test_teks_sebelum_seksi_pertama_diabaikan(self):
        out = web_dashboard._parse_ai_sections(
            "catatan pembuka acak\n===A===\nkonten a"
        )
        assert out["a"] == "konten a"
        assert "catatan" not in out

    def test_tanpa_marker_menghasilkan_kosong(self):
        assert web_dashboard._parse_ai_sections("teks polos tanpa marker") == {}
        assert web_dashboard._parse_ai_sections("") == {}
        assert web_dashboard._parse_ai_sections(None) == {}

    def test_isi_multibaris_utuh(self):
        isi = "baris1\nbaris2\nbaris3"
        out = web_dashboard._parse_ai_sections(f"===X===\n{isi}")
        assert out["x"] == isi

    def test_marker_dengan_jumlah_sama_sama_lebih(self):
        out = web_dashboard._parse_ai_sections("====NAMA====\nisi")
        assert out.get("nama") == "isi"
