"""Phase 6 coverage: LibreOffice/MarkItDown office conversion tools.

Hermetic: subprocess LibreOffice, MarkItDown, openpyxl, dan filesystem output
di-mock. Tidak ada aplikasi office atau jaringan yang dijalankan.
"""

from __future__ import annotations

import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def oc(monkeypatch, tmp_path):
    from alfa.tools.filesystem import office_convert as mod

    monkeypatch.setattr(mod, "SANDBOX_DIR", str(tmp_path))
    return mod


def _fake_run_factory(created: list[Path] | None = None):
    def fake_run(cmd, **kwargs):
        if created is not None:
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            fmt = cmd[cmd.index("--convert-to") + 1]
            src = Path(cmd[cmd.index("--convert-to") + 2])
            path = outdir / f"{src.stem}.{fmt}"
            path.write_text("output", encoding="utf-8")
            created.append(path)
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    return fake_run


# ---------------------------------------------------------------------------
# MarkItDown
# ---------------------------------------------------------------------------


def test_markitdown_success_without_save(oc, monkeypatch):
    class Result:
        text_content = "a" * 2500
        title = ""

    fake = types.ModuleType("markitdown")
    fake.MarkItDown = lambda: SimpleNamespace(convert=lambda target: Result())
    monkeypatch.setitem(sys.modules, "markitdown", fake)

    out = oc.markitdown_convert_document("/tmp/dokumen.docx")
    assert out["status"] == "success"
    assert out["content_length"] == 2500
    assert out["is_truncated"] is True
    assert len(out["markdown_snippet"]) == 2000
    assert out["saved_file"] is None


def test_markitdown_success_with_save(oc, monkeypatch, tmp_path):
    class Result:
        text_content = "isi markdown"
        title = "Judul"

    fake = types.ModuleType("markitdown")
    fake.MarkItDown = lambda: SimpleNamespace(convert=lambda target: Result())
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    monkeypatch.setattr(oc.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))

    out = oc.markitdown_convert_document("http://x", "hasil")
    assert out["status"] == "success"
    assert out["title"] == "Judul"
    assert out["is_truncated"] is False
    saved = tmp_path / "Dokumen" / "ALFA_SWARM_OUTPUTS" / "hasil.md"
    assert saved.read_text(encoding="utf-8") == "isi markdown"


def test_markitdown_error(oc, monkeypatch):
    fake = types.ModuleType("markitdown")

    class Boom:
        def __init__(self):
            raise ValueError("gagal")

    fake.MarkItDown = Boom
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    out = oc.markitdown_convert_document("x")
    assert out["status"] == "error" and "MarkItDown" in out["message"]


# ---------------------------------------------------------------------------
# LibreOffice conversion
# ---------------------------------------------------------------------------


def test_libreoffice_convert_missing_and_success(oc, tmp_path, monkeypatch):
    out = oc.libreoffice_convert_document(str(tmp_path / "tidak-ada.docx"))
    assert out["status"] == "error"

    src = tmp_path / "laporan.docx"
    src.write_text("x", encoding="utf-8")
    created: list[Path] = []
    monkeypatch.setattr(oc.subprocess, "run", _fake_run_factory(created))
    out = oc.libreoffice_convert_document(str(src), ".PDF")
    assert out["status"] == "success"
    assert out["output_format"] == "pdf"
    assert Path(out["file_path"]).name == "laporan.pdf"


def test_libreoffice_convert_glob_fallback(oc, tmp_path, monkeypatch):
    src = tmp_path / "input.odt"
    src.write_text("x", encoding="utf-8")
    other = tmp_path / "lain.pdf"
    other.write_text("isi", encoding="utf-8")
    monkeypatch.setattr(
        oc.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", stderr="")
    )
    out = oc.libreoffice_convert_document(str(src), "pdf")
    assert out["status"] == "success"
    assert Path(out["file_path"]).name == "lain.pdf"


def test_libreoffice_convert_failure_and_exception(oc, tmp_path, monkeypatch):
    src = tmp_path / "input.odt"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        oc.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="", stderr="gagal konversi"),
    )
    out = oc.libreoffice_convert_document(str(src))
    assert out["status"] == "error" and "gagal konversi" in out["message"]

    def boom(*a, **k):
        raise OSError("libreoffice hilang")  # noqa: TRY003

    monkeypatch.setattr(oc.subprocess, "run", boom)
    out = oc.libreoffice_convert_document(str(src))
    assert out["status"] == "error" and "error" in out["message"].lower()


# ---------------------------------------------------------------------------
# Page previews
# ---------------------------------------------------------------------------


def test_render_previews_missing_pdf_and_no_images(oc, tmp_path, monkeypatch):
    out = oc.libreoffice_render_page_previews(str(tmp_path / "x.pdf"))
    assert out["status"] == "error"

    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x", encoding="utf-8")
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: SimpleNamespace(stderr="err"))
    monkeypatch.setattr(oc.glob, "glob", lambda pattern: [])
    out = oc.libreoffice_render_page_previews(str(pdf), max_pages=99)
    assert out["status"] == "error" and "err" in out["message"]


def test_render_previews_success(oc, tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x", encoding="utf-8")
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=""))
    monkeypatch.setattr(
        oc.glob,
        "glob",
        lambda pattern: [str(tmp_path / "preview_doc-1.png"), str(tmp_path / "preview_doc-2.png")],
    )
    out = oc.libreoffice_render_page_previews(str(pdf), max_pages=20, dpi=200)
    assert out["status"] == "success"
    assert out["rendered_pages"] == 2
    assert out["images"] == ["preview_doc-1.png", "preview_doc-2.png"]


def test_render_previews_non_pdf_conversion(oc, tmp_path, monkeypatch):
    name = f"alfa_preview_{uuid.uuid4().hex}"
    src = tmp_path / f"{name}.docx"
    src.write_text("x", encoding="utf-8")
    temp_pdf = Path("/tmp") / f"{name}.pdf"  # noqa: S108 - mengikuti path produksi
    try:
        monkeypatch.setattr(
            oc.subprocess, "run", lambda *a, **k: SimpleNamespace(stderr="")
        )
        out = oc.libreoffice_render_page_previews(str(src), max_pages=0)
        assert out["status"] == "error"

        def make_pdf(*a, **k):
            temp_pdf.write_text("pdf", encoding="utf-8")
            return SimpleNamespace(stderr="")

        monkeypatch.setattr(oc.subprocess, "run", make_pdf)
        monkeypatch.setattr(oc.glob, "glob", lambda pattern: [])
        out = oc.libreoffice_render_page_previews(str(src), max_pages=0)
        assert out["status"] == "error"
        assert not temp_pdf.exists()
    finally:
        temp_pdf.unlink(missing_ok=True)


def test_render_previews_exception(oc, tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_text("x", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("pdftoppm")

    monkeypatch.setattr(oc.subprocess, "run", boom)
    out = oc.libreoffice_render_page_previews(str(pdf))
    assert out["status"] == "error" and "render preview error" in out["message"]


# ---------------------------------------------------------------------------
# Create document
# ---------------------------------------------------------------------------


def test_create_document_success_and_filename_cleanup(oc, tmp_path, monkeypatch):
    monkeypatch.setattr(oc.subprocess, "run", _fake_run_factory([]))
    out = oc.libreoffice_create_document(
        "writer", "Laporan Bulanan!", "<h1>Isi</h1>", export_format="PDF"
    )
    assert out["status"] == "success"
    assert out["format"] == "pdf"
    assert out["doc_type"] == "writer"
    assert Path(out["file_path"]).exists()

    out = oc.libreoffice_create_document(
        "calc", "Data", "<p>x</p>", filename="rekap.final", export_format="xlsx"
    )
    assert Path(out["file_path"]).name == "rekap.xlsx"


def test_create_document_failure(oc, monkeypatch):
    monkeypatch.setattr(
        oc.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", stderr="gagal")
    )
    out = oc.libreoffice_create_document("impress", "Slide", "<h1>x</h1>")
    assert out["status"] == "error" and "gagal" in out["message"]

    def boom(*a, **k):
        raise OSError("libreoffice")

    monkeypatch.setattr(oc.subprocess, "run", boom)
    out = oc.libreoffice_create_document("writer", "X", "isi")
    assert out["status"] == "error" and "error" in out["message"].lower()


# ---------------------------------------------------------------------------
# Extract text
# ---------------------------------------------------------------------------


def test_extract_document_text_missing_and_success(oc, tmp_path, monkeypatch):
    out = oc.libreoffice_extract_document_text(str(tmp_path / "hilang.docx"))
    assert out["status"] == "error"

    src = tmp_path / "dokumen.docx"
    src.write_text("x", encoding="utf-8")
    txt = tmp_path / "hasil.txt"
    txt.write_text("halo dunia alfa", encoding="utf-8")
    monkeypatch.setattr(oc.os, "getpid", lambda: 987654321)
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(oc.glob, "glob", lambda pattern: [str(txt)])
    out = oc.libreoffice_extract_document_text(str(src))
    assert out["status"] == "success"
    assert out["character_count"] == 15
    assert out["word_count"] == 3
    assert out["document"] == "dokumen.docx"


def test_extract_document_text_no_output(oc, tmp_path, monkeypatch):
    src = tmp_path / "dokumen.docx"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(oc.os, "getpid", lambda: 987654322)
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(oc.glob, "glob", lambda pattern: [])
    out = oc.libreoffice_extract_document_text(str(src))
    assert out["status"] == "error"

    def boom(*a, **k):
        raise OSError("libreoffice")

    monkeypatch.setattr(oc.subprocess, "run", boom)
    out = oc.libreoffice_extract_document_text(str(src))
    assert out["status"] == "error" and "extract text error" in out["message"]


# ---------------------------------------------------------------------------
# Smart Excel inspector
# ---------------------------------------------------------------------------


def _fake_openpyxl(monkeypatch, sheets):
    class Ws:
        def __init__(self, rows):
            self._rows = rows

        def iter_rows(self, values_only=True):
            return iter(self._rows)

    class Wb:
        sheetnames = list(sheets)

        def __getitem__(self, name):
            return Ws(sheets[name])

    fake = types.ModuleType("openpyxl")
    fake.load_workbook = lambda *a, **k: Wb()
    monkeypatch.setitem(sys.modules, "openpyxl", fake)


def test_smart_excel_inspector_missing_and_success(oc, tmp_path, monkeypatch):
    out = oc.smart_excel_inspector(str(tmp_path / "tidak-ada.xlsx"))
    assert out["status"] == "error"

    path = tmp_path / "data.xlsx"
    path.write_text("x", encoding="utf-8")
    sheets = {
        "Material": [
            ["No", "Material Description", "Qty", "Unit"],
            [1, "Kabel Fiber", 10, "meter"],
            [2, "Tiang Beton", 0, "unit"],
            [3, None, None, None],
            [4, "FAT 1:8", 5, "pcs"],
        ],
        "Kosong": [],
    }
    _fake_openpyxl(monkeypatch, sheets)
    out = oc.smart_excel_inspector(str(path))
    assert out["status"] == "success"
    assert out["total_items"] == 3
    assert out["sheets_data"]["Material"]["header_row"] == 1
    assert out["sheets_data"]["Material"]["items"][0]["qty"] == 10
    assert out["sheets_data"]["Material"]["items"][0]["unit"] == "meter"


def test_smart_excel_inspector_filters(oc, tmp_path, monkeypatch):
    path = tmp_path / "data.xlsx"
    path.write_text("x", encoding="utf-8")
    sheets = {
        "A": [
            ["Material Qty", "Desc", "Qty", "Unit"],
            ["x", "Kabel", 10, "m"],
            ["y", "Tiang", 20, "unit"],
        ],
        "B": [["Description", "Qty"], ["Kabel B", 1]],
    }
    _fake_openpyxl(monkeypatch, sheets)
    out = oc.smart_excel_inspector(str(path), search_keyword="kabel")
    assert out["total_items"] == 2

    out = oc.smart_excel_inspector(str(path), min_qty=15)
    assert out["total_items"] == 1
    assert out["sheets_data"]["A"]["items"][0]["item"] == "Tiang"

    out = oc.smart_excel_inspector(str(path), max_rows=1, sheet_name="A")
    assert out["total_items"] == 1

    out = oc.smart_excel_inspector(str(path), sheet_name="Tidak Ada")
    assert out["total_items"] == 3


def test_smart_excel_inspector_error(oc, tmp_path, monkeypatch):
    path = tmp_path / "data.xlsx"
    path.write_text("x", encoding="utf-8")
    fake = types.ModuleType("openpyxl")

    def boom(*a, **k):
        raise RuntimeError("corrupt")

    fake.load_workbook = boom
    monkeypatch.setitem(sys.modules, "openpyxl", fake)
    out = oc.smart_excel_inspector(str(path))
    assert out["status"] == "error" and "corrupt" in out["message"]


# ---------------------------------------------------------------------------
# Semantic diff
# ---------------------------------------------------------------------------


def test_compare_documents_missing(oc, tmp_path):
    out = oc.compare_documents_semantic_diff(str(tmp_path / "a"), str(tmp_path / "b"))
    assert out["status"] == "error" and "A" in out["message"]

    b = tmp_path / "b.txt"
    b.write_text("b", encoding="utf-8")
    out = oc.compare_documents_semantic_diff(str(tmp_path / "a"), str(b))
    assert out["status"] == "error" and "B" in out["message"]


def test_compare_documents_success(oc, tmp_path, monkeypatch):
    from alfa.memory import doc_parser

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    text_a = "satu\ndua 10\nhapus\ntiga"
    text_b = "satu\ndua 20\ntiga\nbaru"
    monkeypatch.setattr(
        doc_parser, "extract_document_content", lambda path: (text_a if path == str(a.resolve()) else text_b, "txt")
    )
    out = oc.compare_documents_semantic_diff(str(a), str(b), max_diff_items=1)
    assert out["status"] == "success"
    assert out["counts"]["added"] >= 1
    assert out["counts"]["removed"] >= 1
    assert out["counts"]["modified"] >= 1
    assert out["similarity_percentage"] > 0
    assert "Laporan Perbandingan Dokumen" in out["markdown_report"]
    assert len(out["added_items"]) <= 1


def test_compare_documents_error(oc, tmp_path, monkeypatch):
    from alfa.memory import doc_parser

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    def boom(path):
        raise RuntimeError("parser")

    monkeypatch.setattr(doc_parser, "extract_document_content", boom)
    out = oc.compare_documents_semantic_diff(str(a), str(b))
    assert out["status"] == "error" and "comparison error" in out["message"]
