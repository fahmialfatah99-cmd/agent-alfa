"""Tes untuk jalur ekstraksi dokumen & analyzer dataset (risiko tinggi, coverage rendah).

- `alfa/tools/filesystem/universal_file_extractor.py` — lampiran yang diunggah
  bot (teks, gambar, Excel, CSV, ZIP, HTML) + agregasi material.
- `alfa/tools/media/documents.py` — pembuatan spreadsheet/presentasi & analisis
  dataset dengan chart.

Semua hermetik: berkas dibuat di `tmp_path`, tidak ada jaringan, tidak ada
Telegram API.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── universal_file_extractor ───────────────────────────────────────────────


class TestProcessUploadedAttachment:
    def test_text_file_returns_context(self, tmp_path, monkeypatch):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        monkeypatch.setattr(ufe, "UPLOAD_DIR", str(tmp_path))
        text_ctx, part = ufe.process_uploaded_attachment(
            "catatan.txt", "text/plain", b"isi catatan penting", save_disk=True
        )
        assert text_ctx is not None
        assert "catatan.txt" in text_ctx
        assert part is None
        # berkas benar-benar tersimpan di disk & disebut di konteks
        saved = list(tmp_path.iterdir())
        assert saved, "berkas tidak tersimpan"
        assert str(saved[0]) in text_ctx

    def test_save_disk_false_writes_nothing(self, tmp_path, monkeypatch):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        monkeypatch.setattr(ufe, "UPLOAD_DIR", str(tmp_path))
        text_ctx, _ = ufe.process_uploaded_attachment(
            "x.txt", "text/plain", b"abc", save_disk=False
        )
        assert text_ctx is not None
        assert not list(tmp_path.iterdir())

    def test_image_returns_multimodal_part(self, tmp_path, monkeypatch):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        monkeypatch.setattr(ufe, "UPLOAD_DIR", str(tmp_path))
        # PNG 1x1 valid
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
            b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
            b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        text_ctx, part = ufe.process_uploaded_attachment(
            "foto.png", "image/png", png, save_disk=False
        )
        assert text_ctx is not None
        assert "LAMPIRAN GAMBAR" in text_ctx
        assert part is not None

    def test_unsafe_filename_is_sanitised(self, tmp_path, monkeypatch):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        monkeypatch.setattr(ufe, "UPLOAD_DIR", str(tmp_path))
        ufe.process_uploaded_attachment(
            "../../etc/passwd.txt", "text/plain", b"x", save_disk=True
        )
        for saved in tmp_path.iterdir():
            assert "/" not in saved.name
            assert ".." not in saved.name


class TestExcelCsvExtraction:
    def _xlsx_bytes(self) -> bytes:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Material"
        ws.append(["Item", "Qty", "Cluster"])
        ws.append(["T73", 94, "Lahat"])
        ws.append(["Kabel KU24", 120, "Curup"])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_extract_excel_returns_table(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        out = ufe._extract_excel(self._xlsx_bytes(), "rekap.xlsx", ".xlsx")
        assert "Material" in out
        assert "T73" in out
        assert "Lahat" in out

    def test_extract_csv_returns_table(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        text_buf = io.StringIO()
        w = csv.writer(text_buf)
        w.writerow(["Item", "Qty"])
        w.writerow(["T73", 94])
        out = ufe._extract_csv(text_buf.getvalue().encode("utf-8"), "rekap.csv")
        assert out is not None
        assert "T73" in out

    def test_pre_aggregation_computes_numeric_summary(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        headers = ["Item", "Qty"]
        rows = [["T73", 94], ["Kabel", 120], ["T72", 86]]
        agg = ufe._build_full_sheet_pre_aggregation(headers, rows)
        assert agg
        assert "300" in agg or "Qty" in agg

    def test_pre_aggregation_empty_returns_empty(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        assert ufe._build_full_sheet_pre_aggregation([], []) == ""

    def test_cross_sheet_rollup_mentions_all_sheets(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        headers = [
            "Material Description",
            "Unit",
            "Total Material Provided",
            "Usage Qty",
            "Remaining Qty",
        ]
        records = [
            {"name": "Lahat", "headers": headers, "rows": [["T73", "btg", 94, 10, 84]]},
            {"name": "Curup", "headers": headers, "rows": [["T72", "btg", 30, 5, 25]]},
        ]
        rollup = ufe._build_cross_sheet_material_rollup(records)
        assert "Lahat" in rollup
        assert "Curup" in rollup

    def test_prepare_headers_and_rows(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        rows: list[list[Any]] = [["Item", "Qty"], ["T73", 94]]
        headers, data_rows, raw_cols = ufe._prepare_sheet_headers_and_rows(rows)
        assert headers
        assert data_rows
        assert raw_cols >= len(headers)


class TestOtherExtractors:
    def test_html_extraction(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        html = b"<html><body><h1>Judul</h1><p>Isi paragraf</p></body></html>"
        out = ufe._extract_html_xml(html, "h.html", ".html")
        assert out
        assert "Judul" in out

    def test_archive_lists_members(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.txt", "isi a")
            zf.writestr("b.txt", "isi b")
        out = ufe._extract_archive(buf.getvalue(), "arsip.zip", ".zip")
        assert out
        assert "a.txt" in out

    def test_unknown_extension_returns_readable_text(self):
        from alfa.tools.filesystem import universal_file_extractor as ufe

        out = ufe._extract_data_formats(b"data mentah", "file.bin", ".bin")
        assert out


# ── media/documents ───────────────────────────────────────────────────────


class TestMediaDocuments:
    def test_generate_excel_spreadsheet(self, tmp_path, monkeypatch):
        from alfa.tools.media import documents as md

        monkeypatch.setattr(md, "SANDBOX_DIR", str(tmp_path))
        rows = json.dumps([["T73", 94], ["Kabel", 120]])
        res = md.generate_excel_spreadsheet(
            "Material", ["Item", "Qty"], rows, filename="rekap_material.xlsx"
        )
        assert res.get("status") == "success"
        assert (tmp_path / "rekap_material.xlsx").exists()

    def test_analyze_dataset_missing_file(self, tmp_path):
        from alfa.tools.media import documents as md

        res = md.analyze_dataset_csv_json(str(tmp_path / "nope.csv"))
        assert res.get("status") == "error"
        assert "tidak ditemukan" in res.get("message", "")

    def test_analyze_dataset_csv_creates_chart(self, tmp_path):
        from alfa.tools.media import documents as md

        csv_path = tmp_path / "data.csv"
        csv_path.write_text("Item,Qty\nT73,94\nT72,86\n", encoding="utf-8")
        res = md.analyze_dataset_csv_json(
            str(csv_path), chart_type="bar", x_column="Item", y_column="Qty"
        )
        assert res.get("status") == "success"
        assert res.get("chart_generated")
        assert res.get("total_rows") == 2

    def test_translate_text_uses_model(self, monkeypatch):
        """Terjemahkan memakai Gemini; model dikendalikan (tanpa jaringan)."""
        from alfa.tools.media import documents as md

        class _FakeModels:
            def generate_content(self, model=None, contents=None):
                return MagicMock(text="halo dunia")

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                self.models = _FakeModels()

        monkeypatch.setattr(
            "alfa.swarm.llm_client.get_agent_api_client",
            lambda cfg: ("gemini", "key-test", "gemini-3.5-pro", "", None),
        )
        with patch("google.genai.Client", _FakeClient):
            res = md.translate_text("hello", target_lang="en")
        assert res.get("status") == "success"
        assert res.get("translated") == "halo dunia"

    def test_translate_text_without_api_key(self, monkeypatch):
        from alfa.tools.media import documents as md

        monkeypatch.setattr(
            "alfa.swarm.llm_client.get_agent_api_client",
            lambda cfg: ("gemini", "", "", "", None),
        )
        res = md.translate_text("hello", target_lang="en")
        assert res.get("status") == "error"
        assert "API key" in res.get("message", "")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
