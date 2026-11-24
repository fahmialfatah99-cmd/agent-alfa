"""Phase 6 coverage: document parser + contextual chunker untuk vector brain.

Hermetic: parser dokumen (fitz/pypdf/docx/pandas/pptx) di-fake, semua berkas
hanya di ``tmp_path``.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def dp():
    from alfa.memory import doc_parser

    return doc_parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_extract_non_string_and_raw_text(dp, tmp_path):
    assert dp.extract_document_content(None) == ("", "unknown")
    assert dp.extract_document_content(123) == ("", "unknown")

    assert dp.extract_document_content("  halo dunia  ") == ("halo dunia", "text")
    assert dp.extract_document_content("\n teks\n") == ("teks", "text")


def test_extract_plain_text_file_fallback(dp, tmp_path):
    py = tmp_path / "script.py"
    py.write_text("print(1)\n", encoding="utf-8")
    text, kind = dp.extract_document_content(str(py))
    assert text == "print(1)\n" and kind == "py"

    md = tmp_path / "README.md"
    md.write_text("# Judul\n", encoding="utf-8")
    text, kind = dp.extract_document_content(str(md))
    assert text.startswith("# Judul") and kind == "md"

    txt = tmp_path / "notes"
    txt.write_text("tanpa ekstensi", encoding="utf-8")
    text, kind = dp.extract_document_content(str(txt))
    assert text == "tanpa ekstensi" and kind == "text"


def test_extract_dispatch_to_helpers(dp, tmp_path, monkeypatch):
    cases = {
        "pdf": ("pdf", "_extract_pdf_file"),
        "docx": ("docx", "_extract_docx_file"),
        "xlsx": ("excel", "_extract_excel_file"),
        "csv": ("csv", "_extract_csv_file"),
        "tsv": ("tsv", "_extract_csv_file"),
        "pptx": ("pptx", "_extract_pptx_file"),
    }
    for ext, (kind, helper) in cases.items():
        path = tmp_path / f"dokumen.{ext}"
        path.write_bytes(b"x")
        monkeypatch.setattr(
            dp, helper, lambda *a, _h=helper, **k: f"isi-{_h}"
        )
        text, source = dp.extract_document_content(str(path))
        assert source == kind, ext
        assert text == f"isi-{helper}"


def test_extract_read_error_returns_marker(dp, tmp_path, monkeypatch):
    import builtins

    path = tmp_path / "rusak.txt"
    path.write_text("isi", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk penuh")  # noqa: TRY003

    monkeypatch.setattr(builtins, "open", boom)
    text, kind = dp.extract_document_content(str(path))
    assert text.startswith("[Gagal membaca berkas rusak.txt")
    assert kind == "txt"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_fitz_primary(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"pdf")

    class Page:
        def __init__(self, text):
            self._text = text

        def get_text(self, mode):
            return self._text

    class Doc:
        def __iter__(self):
            return iter([Page("halaman satu"), Page("   "), Page("halaman dua")])

        def close(self):
            self.closed = True

    fake = types.ModuleType("fitz")
    fake.open = lambda target: Doc()
    monkeypatch.setitem(sys.modules, "fitz", fake)

    out = dp._extract_pdf_file(str(path))
    assert "## --- Halaman 1 ---" in out
    assert "halaman dua" in out
    assert "Halaman 2 ---" not in out


def test_pdf_fitz_failure_pypdf_fallback(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"pdf")

    class Boom(types.ModuleType):
        def open(self, target):
            raise RuntimeError("fitz rusak")  # noqa: TRY003

    monkeypatch.setitem(sys.modules, "fitz", Boom("fitz"))

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = lambda target: SimpleNamespace(
        pages=[
            SimpleNamespace(extract_text=lambda: " dari pypdf "),
            SimpleNamespace(extract_text=lambda: None),
        ]
    )
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    out = dp._extract_pdf_file(str(path))
    assert "dari pypdf" in out and "Halaman 1" in out


def test_pdf_all_parsers_fail(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"pdf")

    class BoomFitz(types.ModuleType):
        def open(self, target):
            raise RuntimeError("fitz")  # noqa: TRY003

    class BoomPdf(types.ModuleType):
        def PdfReader(self, target):  # noqa: N802 - mengikuti API pypdf
            raise ValueError("pypdf")  # noqa: TRY003

    monkeypatch.setitem(sys.modules, "fitz", BoomFitz("fitz"))
    monkeypatch.setitem(sys.modules, "pypdf", BoomPdf("pypdf"))
    out = dp._extract_pdf_file(str(path))
    assert "Teks tidak dapat diekstrak" in out


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def test_docx_headings_and_tables(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.docx"
    path.write_bytes(b"docx")

    def para(text, style):
        return SimpleNamespace(text=text, style=SimpleNamespace(name=style))

    table = SimpleNamespace(
        rows=[
            SimpleNamespace(
                cells=[SimpleNamespace(text="Kolom A"), SimpleNamespace(text="Kolom B")]
            ),
            SimpleNamespace(
                cells=[SimpleNamespace(text="1"), SimpleNamespace(text="2")]
            ),
            SimpleNamespace(
                cells=[SimpleNamespace(text="satu\ndua")]
            ),
        ]
    )
    fake = types.ModuleType("docx")
    fake.Document = lambda target: SimpleNamespace(
        paragraphs=[
            para("Judul Besar", "Heading 1"),
            para("Sub", "Heading 2"),
            para("Subsub", "Heading 3"),
            para("Normal", "Normal"),
            para("   ", "Normal"),
            para("TanpaStyle", None),
        ],
        tables=[table],
    )
    monkeypatch.setitem(sys.modules, "docx", fake)

    out = dp._extract_docx_file(str(path))
    assert "# Judul Besar" in out
    assert "## Sub" in out
    assert "### Subsub" in out
    assert "| Kolom A | Kolom B |" in out
    assert "| --- | --- |" in out
    assert "| 1 | 2 |" in out
    assert "| satu dua |  |" in out


def test_docx_error(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.docx"
    path.write_bytes(b"docx")

    class Boom(types.ModuleType):
        def Document(self, target):  # noqa: N802 - mengikuti API python-docx
            raise RuntimeError("docx corrupt")  # noqa: TRY003

    monkeypatch.setitem(sys.modules, "docx", Boom("docx"))
    assert "Gagal membaca file docx" in dp._extract_docx_file(str(path))


# ---------------------------------------------------------------------------
# Excel / CSV
# ---------------------------------------------------------------------------


def test_excel_sheets_and_error(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"xlsx")

    class Sheet:
        def __init__(self, empty=False, rows=1):
            self.empty = empty
            self._rows = rows

        def head(self, n):
            return self

        def fillna(self, value):
            return self

        def to_markdown(self, index=False):
            return "| kolom |\n| --- |"

        def __len__(self):
            return self._rows

    sheets = {
        "Data": Sheet(rows=250),
        "Kosong": Sheet(empty=True),
    }
    fake = types.ModuleType("pandas")
    fake.ExcelFile = lambda target: SimpleNamespace(
        sheet_names=list(sheets), parse=lambda name: sheets[name]
    )
    monkeypatch.setitem(sys.modules, "pandas", fake)

    out = dp._extract_excel_file(str(path))
    assert "## Sheet: Data" in out
    assert "*(Sheet kosong)*" in out
    assert "Total 250 baris" in out

    def boom(*a, **k):
        raise ValueError("xlsx rusak")  # noqa: TRY003

    fake.ExcelFile = boom
    assert "Gagal membaca file excel" in dp._extract_excel_file(str(path))


def test_csv_and_tsv_extraction(dp, tmp_path, monkeypatch):
    csv_path = tmp_path / "a.csv"
    csv_path.write_bytes(b"csv")

    calls = {}

    class Df:
        def __init__(self, empty=False):
            self.empty = empty

        def fillna(self, value):
            return self

        def to_markdown(self, index=False):
            return "| a |"

    def fake_read_csv(target, sep=",", nrows=0, on_bad_lines="skip"):
        calls["sep"] = sep
        calls["nrows"] = nrows
        return Df()

    fake = types.ModuleType("pandas")
    fake.read_csv = fake_read_csv
    monkeypatch.setitem(sys.modules, "pandas", fake)

    out = dp._extract_csv_file(str(csv_path), "csv")
    assert calls["sep"] == "," and calls["nrows"] == 300
    assert "## Data Tabel: a.csv" in out and "| a |" in out

    tsv_path = tmp_path / "b.tsv"
    tsv_path.write_bytes(b"tsv")
    out = dp._extract_csv_file(str(tsv_path), "tsv")
    assert calls["sep"] == "\t"

    fake.read_csv = lambda *a, **k: Df(empty=True)
    assert "*(Tabel kosong)*" in dp._extract_csv_file(str(csv_path))

    def boom(*a, **k):
        raise RuntimeError("csv gagal")  # noqa: TRY003

    fake.read_csv = boom
    assert "Gagal membaca CSV" in dp._extract_csv_file(str(csv_path))


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------


def test_pptx_slides_and_error(dp, tmp_path, monkeypatch):
    path = tmp_path / "a.pptx"
    path.write_bytes(b"pptx")

    def slide(paragraphs, has_text=True):
        return SimpleNamespace(
            shapes=[
                SimpleNamespace(
                    has_text_frame=has_text,
                    text_frame=SimpleNamespace(
                        paragraphs=[
                            SimpleNamespace(text=p) for p in paragraphs
                        ]
                    ),
                ),
                SimpleNamespace(has_text_frame=False),
            ]
        )

    fake = types.ModuleType("pptx")
    fake.Presentation = lambda target: SimpleNamespace(
        slides=[
            slide(["Judul Slide", "Poin 1", "Poin 2", "  "]),
            slide([], has_text=False),
        ]
    )
    monkeypatch.setitem(sys.modules, "pptx", fake)

    out = dp._extract_pptx_file(str(path))
    assert "## Slide 1: Judul Slide" in out
    assert "• Poin 1" in out
    assert "Slide 2" not in out

    class Boom(types.ModuleType):
        def Presentation(self, target):  # noqa: N802 - mengikuti API python-pptx
            raise RuntimeError("pptx rusak")  # noqa: TRY003

    monkeypatch.setitem(sys.modules, "pptx", Boom("pptx"))
    assert "Gagal membaca PPTX" in dp._extract_pptx_file(str(path))


# ---------------------------------------------------------------------------
# Contextual chunker
# ---------------------------------------------------------------------------


def test_chunk_empty_input(dp):
    assert dp.chunk_document_contextual("") == []
    assert dp.chunk_document_contextual("   \n ") == []


def test_chunk_single_chunk_with_default_heading(dp):
    out = dp.chunk_document_contextual("baris pendek", doc_title="Panduan")
    assert len(out) == 1
    assert out[0].startswith("[Dokumen: Panduan | Bagian: Pendahuluan]")


def test_chunk_headings_and_page_markers(dp):
    text = "\n".join(
        [
            "# Bagian A",
            "pendahuluan bagian a",
            "--- Halaman 2 ---",
            "isi halaman dua",
            "### Bagian C",
            "isi c",
        ]
    )
    out = dp.chunk_document_contextual(text, doc_title="Dok", chunk_size=60, overlap=0)
    assert out
    assert any("Bagian A" in chunk for chunk in out)
    assert any("Pendahuluan" not in chunk for chunk in out)


def test_chunk_split_with_overlap_and_tables(dp):
    lines = ["# Bab " + "x" * 20]
    lines += [f"baris data ke-{i} " + "y" * 30 for i in range(12)]
    lines += ["| a | b |", "| --- | --- |", "| 1 | 2 |"]
    text = "\n".join(lines)
    out = dp.chunk_document_contextual(text, doc_title="Tabel", chunk_size=200, overlap=60)
    assert len(out) > 1
    assert all(chunk.startswith("[Dokumen: Tabel | Bagian:") for chunk in out)
    assert any("| 1 | 2 |" in chunk for chunk in out)

    no_overlap = dp.chunk_document_contextual(text, chunk_size=200, overlap=0)
    assert len(no_overlap) >= 1


def test_chunk_keeps_short_tail(dp, tmp_path):
    text = "\n".join(["x" * 40 for _ in range(10)])
    out = dp.chunk_document_contextual(text, chunk_size=100, overlap=60)
    assert len(out) > 1
    assert out[-1].splitlines()[-1].strip() != ""


def test_extract_read_error_marker_without_monkeypatch(dp, tmp_path):
    path = tmp_path / "berkas-bertipe-direktori"
    path.mkdir()
    # Path adalah direktori sehingga os.path.isfile() False -> perlakuan teks mentah.
    text, kind = dp.extract_document_content(str(path))
    assert kind == "text" and Path(path).name in text
