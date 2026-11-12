"""Tes `alfa/tools/telecom_tools/documents.py` — dokumen lapangan.

Cakupan: transkripsi voice note (Gemini + fallback faster-whisper offline),
parsing Surat Jalan / Delivery Order (teks digital, OCR vision, pencocokan BOQ),
dan inspeksi foto surat jalan (vision + fallback heuristik).

Semua hermetik: tidak ada panggilan jaringan. `faster_whisper`, `fitz`, Gemini
client, dan `pdfplumber` dipalsukan seperlunya.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import openpyxl
import pytest

from alfa.tools.telecom_tools import documents as td


class _DocError(RuntimeError):
    """Kegagalan tiruan pada pembacaan dokumen."""


class _PdfCtx:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _genai_client(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **_kw: SimpleNamespace(text=text)
        )
    )


@pytest.fixture()
def audio_file(tmp_path):
    f = tmp_path / "laporan.ogg"
    f.write_bytes(b"OggS-audio")
    return f


@pytest.fixture()
def no_local(monkeypatch):
    monkeypatch.setattr(td, "_resolve_local_whisper_fallback", lambda: (lambda *_a, **_k: None))


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setattr(
        "alfa.swarm.llm_client.get_agent_api_client",
        lambda _agent: ("gemini", "KEY", "gemini-test", None, 1),
    )


@pytest.fixture()
def no_key(monkeypatch):
    monkeypatch.setattr(
        "alfa.swarm.llm_client.get_agent_api_client",
        lambda _agent: ("gemini", "", "", None, None),
    )


# ── transkripsi voice note ─────────────────────────────────────────────────


class TestTranscribeVoiceNote:
    def test_missing_file_returns_error(self, tmp_path):
        res = td.transcribe_field_voice_note(str(tmp_path / "tidak-ada.ogg"))
        assert res["status"] == "error"
        assert "tidak ditemukan" in res["message"]

    def test_without_key_uses_local_fallback(self, audio_file, monkeypatch, no_key):
        monkeypatch.setattr(
            td,
            "_resolve_local_whisper_fallback",
            lambda: (lambda path, hint: {"status": "success", "transcript": "lokal", "extracted_data": {}}),
        )
        res = td.transcribe_field_voice_note(str(audio_file), "Lahat")
        assert res["status"] == "success"
        assert res["transcript"] == "lokal"

    def test_without_key_and_no_local_returns_error(self, audio_file, no_key, no_local):
        res = td.transcribe_field_voice_note(str(audio_file))
        assert res["status"] == "error"
        assert "Tidak ada Gemini API Key" in res["message"]

    def test_gemini_json_success_strips_fences(self, audio_file, monkeypatch, with_key):
        payload = {
            "transcript": "tarik kabel 1200 meter",
            "mandor": "Mugi",
            "cluster": "Lahat",
            "cables_meter": 1200.0,
            "poles_count": 0,
            "fat_count": 0,
            "kendala": "",
        }
        raw = "```json\n" + json.dumps(payload) + "\n```"
        monkeypatch.setattr("google.genai.Client", lambda **_kw: _genai_client(raw))
        res = td.transcribe_field_voice_note(str(audio_file), "Lahat")
        assert res["status"] == "success"
        assert res["extracted_data"]["mandor"] == "Mugi"
        assert res["transcript"] == "tarik kabel 1200 meter"

    def test_gemini_invalid_json_keeps_raw_transcript(
        self, audio_file, monkeypatch, with_key
    ):
        monkeypatch.setattr(
            "google.genai.Client", lambda **_kw: _genai_client("transkrip mentah")
        )
        res = td.transcribe_field_voice_note(str(audio_file))
        assert res["status"] == "success"
        assert res["transcript"] == "transkrip mentah"
        assert res["extracted_data"]["cables_meter"] == 0

    def test_gemini_error_uses_local_fallback(self, audio_file, monkeypatch, with_key):
        def boom(**_kw):
            raise _DocError()

        monkeypatch.setattr("google.genai.Client", lambda **_kw: SimpleNamespace(models=SimpleNamespace(generate_content=boom)))
        monkeypatch.setattr(
            td,
            "_resolve_local_whisper_fallback",
            lambda: (lambda path, hint: {"status": "success", "transcript": "dari lokal", "extracted_data": {}}),
        )
        res = td.transcribe_field_voice_note(str(audio_file))
        assert res["status"] == "success"
        assert res["transcript"] == "dari lokal"

    def test_gemini_error_and_no_local_returns_error(
        self, audio_file, monkeypatch, with_key, no_local
    ):
        def boom(**_kw):
            raise _DocError()

        monkeypatch.setattr("google.genai.Client", lambda **_kw: SimpleNamespace(models=SimpleNamespace(generate_content=boom)))
        res = td.transcribe_field_voice_note(str(audio_file))
        assert res["status"] == "error"
        assert "Transcribe voice note error" in res["message"]


# ── fallback faster-whisper lokal ──────────────────────────────────────────


class TestLocalWhisperFallback:
    def _install_model(self, monkeypatch, transcript: str):
        class _Model:
            def __init__(self, *_a, **_k):
                pass

            def transcribe(self, _path, language=None, beam_size=None):
                return [SimpleNamespace(text=transcript)], SimpleNamespace()

        monkeypatch.setitem(
            sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=_Model)
        )

    def test_extracts_field_entities(self, monkeypatch, tmp_path):
        audio = tmp_path / "a.ogg"
        audio.write_bytes(b"x")
        self._install_model(
            monkeypatch,
            "tarik kabel 1200 meter, tanam 25 tiang, pasang 3 fdt dan 4 fat, kendala: jalan rusak",
        )
        res = td._transcribe_local_whisper_fallback(str(audio), "Lahat")
        assert res is not None
        data = res["extracted_data"]
        assert data["cables_meter"] == 1200.0
        assert data["poles_count"] == 25
        assert data["fdt_count"] == 3
        assert data["fat_count"] == 4
        assert "kendala" in data["kendala"]
        assert data["cluster"] == "Lahat"

    def test_empty_transcript_returns_none(self, monkeypatch, tmp_path):
        audio = tmp_path / "a.ogg"
        audio.write_bytes(b"x")
        self._install_model(monkeypatch, "")
        assert td._transcribe_local_whisper_fallback(str(audio)) is None

    def test_model_failure_returns_none(self, monkeypatch, tmp_path):
        audio = tmp_path / "a.ogg"
        audio.write_bytes(b"x")

        def boom(*_a, **_k):
            raise _DocError()

        monkeypatch.setitem(
            sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=boom)
        )
        assert td._transcribe_local_whisper_fallback(str(audio)) is None


# ── Delivery Order ─────────────────────────────────────────────────────────

_DO_TEXT = """TO Number: DOEID26101705
Date: 17-10-2026
Destination: Lahat
1 Tiang 7m 3" PCS 94 Baik
2 Kabel KU24 METER 1200 Gulung
"""


class TestParseDeliveryOrder:
    def test_missing_file_returns_error(self, tmp_path):
        res = td.parse_delivery_order_document(str(tmp_path / "nope.pdf"))
        assert res["status"] == "error"
        assert "tidak ditemukan" in res["message"]

    def test_digital_pdf_extracts_header_and_items(self, tmp_path, monkeypatch):
        pdf_file = tmp_path / "DOEID26101705.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")
        page = SimpleNamespace(extract_text=lambda: _DO_TEXT)
        monkeypatch.setattr(
            "pdfplumber.open", lambda _path: _PdfCtx([page])
        )
        res = td.parse_delivery_order_document(str(pdf_file))
        assert res["status"] == "success"
        do = res["delivery_order"]
        assert do["number"] == "DOEID26101705"
        assert do["date"] == "17-10-2026"
        assert do["destination"] == "Lahat"
        assert len(do["items"]) == 2
        assert do["items"][0]["qty"] == 94.0
        assert do["items"][0]["unit"] == "PCS"
        assert do["items"][1]["unit"] == "METER"
        assert res["total_items_extracted"] == 2
        assert res["boq_comparison"] == {}

    def test_pdfplumber_error_falls_to_error_result(self, tmp_path, monkeypatch):
        pdf_file = tmp_path / "rusak.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")

        def boom(_path):
            raise OSError()

        monkeypatch.setattr("pdfplumber.open", boom)
        res = td.parse_delivery_order_document(str(pdf_file))
        assert res["status"] == "error"
        assert "Parse Delivery Order error" in res["message"]

    def test_vision_ocr_for_scanned_image(self, tmp_path, monkeypatch, with_key):
        img = tmp_path / "scan.png"
        img.write_bytes(b"PNGDATA")
        vision = {
            "number": "SJ-77",
            "date": "01-11-2026",
            "origin": "Gudang Lahat",
            "destination": "Cluster Lahat",
            "applicant": "Mugi",
            "pm": "Andi",
            "items": [
                {"no": 1, "description": "Tiang 7m", "unit": "PCS", "qty": 10, "remark": ""}
            ],
        }
        monkeypatch.setattr(
            "google.genai.Client", lambda **_kw: _genai_client(json.dumps(vision))
        )
        res = td.parse_delivery_order_document(str(img))
        assert res["status"] == "success"
        do = res["delivery_order"]
        assert do["number"] == "SJ-77"
        assert do["applicant"] == "Mugi"
        assert do["items"][0]["qty"] == 10
        assert res["total_items_extracted"] == 1

    def test_vision_without_key_returns_empty_items(
        self, tmp_path, monkeypatch, no_key
    ):
        img = tmp_path / "scan.png"
        img.write_bytes(b"PNGDATA")
        res = td.parse_delivery_order_document(str(img))
        assert res["status"] == "success"
        assert res["total_items_extracted"] == 0

    def test_vision_invalid_json_is_ignored(self, tmp_path, monkeypatch, with_key):
        img = tmp_path / "scan.png"
        img.write_bytes(b"PNGDATA")
        monkeypatch.setattr(
            "google.genai.Client", lambda **_kw: _genai_client("bukan json")
        )
        res = td.parse_delivery_order_document(str(img))
        assert res["status"] == "success"
        assert res["delivery_order"]["items"] == []

    def test_boq_cross_check_statuses(self, tmp_path, monkeypatch):
        pdf_file = tmp_path / "DO.pdf"
        pdf_file.write_bytes(b"%PDF-1.4")
        page = SimpleNamespace(extract_text=lambda: _DO_TEXT)
        monkeypatch.setattr("pdfplumber.open", lambda _path: _PdfCtx([page]))

        boq = tmp_path / "SMDT-Lahat.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "BOQ Lahat"
        ws.append(["Deskripsi", "Qty"])
        ws.append(['Tiang 7m 3"', 100])
        ws.append(["Kabel KU24", 1000])
        wb.save(boq)

        monkeypatch.setattr(td.glob, "glob", lambda _pattern: [str(boq)])
        res = td.parse_delivery_order_document(str(pdf_file), match_cluster_boq="Lahat")
        comp = res["boq_comparison"]
        assert comp["matched_boq_file"] == "SMDT-Lahat.xlsx"
        statuses = {c["item"]: c["status"] for c in comp["comparison"]}
        assert statuses['Tiang 7m 3"'] == "PARTIAL"  # 94 < 100
        assert statuses["Kabel KU24"] == "SUFFICIENT"  # 1200 >= 1000


# ── inspeksi surat jalan (vision) ──────────────────────────────────────────


class TestInspectSuratJalan:
    def test_missing_file(self, tmp_path):
        res = td.inspect_field_surat_jalan_image(str(tmp_path / "x.jpg"))
        assert res["status"] == "error"
        assert "tidak ditemukan" in res["message"]

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "catatan.txt"
        f.write_text("x", encoding="utf-8")
        res = td.inspect_field_surat_jalan_image(str(f))
        assert res["status"] == "error"
        assert "tidak didukung" in res["message"]

    def test_unreadable_file_returns_error(self, tmp_path):
        d = tmp_path / "aneh.png"
        d.mkdir()
        res = td.inspect_field_surat_jalan_image(str(d))
        assert res["status"] == "error"
        assert "Gagal membaca byte gambar" in res["message"]

    def test_vision_success(self, tmp_path, monkeypatch, with_key):
        img = tmp_path / "sj.jpg"
        img.write_bytes(b"JPGDATA")
        parsed = {
            "document_number": "SJ-99",
            "date": "01-11-2026",
            "cluster": "Lahat",
            "mandor_or_pic": "Mugi",
            "items": [{"code": "T73", "qty": 10}],
            "total_poles": 10,
        }
        monkeypatch.setattr(
            "google.genai.Client", lambda **_kw: _genai_client(json.dumps(parsed))
        )
        res = td.inspect_field_surat_jalan_image(str(img), "Lahat")
        assert res["status"] == "success"
        assert res["document_number"] == "SJ-99"
        assert res["source_file"].endswith("sj.jpg")

    def test_heuristic_fallback_without_key(self, tmp_path, no_key):
        img = tmp_path / "sj.png"
        img.write_bytes(b"PNGDATA")
        res = td.inspect_field_surat_jalan_image(str(img), "Curup")
        assert res["status"] == "success"
        assert res["mode"] == "heuristic_fallback"
        assert res["cluster"] == "Curup"
        assert res["total_poles"] == 31

    def test_heuristic_fallback_on_invalid_json(self, tmp_path, monkeypatch, with_key):
        img = tmp_path / "sj.png"
        img.write_bytes(b"PNGDATA")
        monkeypatch.setattr(
            "google.genai.Client", lambda **_kw: _genai_client("bukan json")
        )
        res = td.inspect_field_surat_jalan_image(str(img))
        assert res["status"] == "success"
        assert res["mode"] == "heuristic_fallback"

    def test_pdf_input_uses_fitz_and_vision(self, tmp_path, monkeypatch, with_key):
        pdf = tmp_path / "sj.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        fake_fitz = SimpleNamespace(
            open=lambda _p: [
                SimpleNamespace(
                    get_pixmap=lambda dpi: SimpleNamespace(tobytes=lambda fmt: b"PNG")
                )
            ]
        )
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
        monkeypatch.setattr(
            "google.genai.Client",
            lambda **_kw: _genai_client(json.dumps({"document_number": "SJ-PDF"})),
        )
        res = td.inspect_field_surat_jalan_image(str(pdf))
        assert res["status"] == "success"
        assert res["document_number"] == "SJ-PDF"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
