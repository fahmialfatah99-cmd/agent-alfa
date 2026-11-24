"""Phase 6 coverage: universal file & multimodal attachment extractor.

Hermetic: parsing libraries di-fake, semua byte berada di memori, dan folder
upload diarahkan ke ``tmp_path``.
"""

from __future__ import annotations

import io
import sys
import tarfile
import types
import zipfile
from types import SimpleNamespace

import pytest


@pytest.fixture
def ufe(monkeypatch, tmp_path):
    from alfa.tools.filesystem import universal_file_extractor as mod

    monkeypatch.setattr(mod, "UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    return mod


# ---------------------------------------------------------------------------
# Dispatching
# ---------------------------------------------------------------------------


def _fake_google_genai(monkeypatch, fail: bool = False):
    class Part:
        @staticmethod
        def from_bytes(data, mime_type):
            if fail:
                raise RuntimeError("part")
            return ("part", data, mime_type)

    fake_types = types.ModuleType("google.genai.types")
    fake_types.Part = Part
    fake_genai = types.ModuleType("google.genai")
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)


def test_process_image_and_audio(ufe, monkeypatch):
    _fake_google_genai(monkeypatch)
    text, part = ufe.process_uploaded_attachment("foto.JPG", "", b"img")
    assert "[LAMPIRAN GAMBAR/FOTO: foto.JPG]" in text
    assert part[2] == "image/jpeg"
    assert "FILE TERSIMPAN DI DISK" in text
    from pathlib import Path

    assert Path(ufe.UPLOAD_DIR).exists()

    text, part = ufe.process_uploaded_attachment("rekaman.mp3", "", b"aud")
    assert "[LAMPIRAN AUDIO/SUARA: rekaman.mp3]" in text
    assert part[2] == "audio/mp3"


def test_process_image_part_and_save_failure(ufe, monkeypatch, tmp_path):
    _fake_google_genai(monkeypatch, fail=True)
    text, part = ufe.process_uploaded_attachment("x.png", "image/png", b"x")
    assert part is None and "LAMPIRAN GAMBAR" in text

    from pathlib import Path

    for saved in Path(ufe.UPLOAD_DIR).iterdir():
        saved.unlink()

    def boom(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr("builtins.open", boom)
    text, part = ufe.process_uploaded_attachment("y.png", "image/png", b"y")
    assert text and not list(Path(ufe.UPLOAD_DIR).iterdir())


def test_process_pdf_and_word(ufe, monkeypatch):
    _fake_google_genai(monkeypatch)
    monkeypatch.setattr(ufe, "_extract_pdf", lambda raw, name: "isi pdf")
    text, part = ufe.process_uploaded_attachment("a.pdf", "", b"pdf")
    assert "[DOKUMEN PDF: a.pdf]" in text and "isi pdf" in text
    assert part[2] == "application/pdf"

    monkeypatch.setattr(ufe, "_extract_word", lambda raw, name: "isi word")
    text, part = ufe.process_uploaded_attachment("a.docx", "", b"doc")
    assert "[DOKUMEN WORD: a.docx]" in text and part is None


def test_process_ppt_excel_csv(ufe, monkeypatch):
    monkeypatch.setattr(ufe, "_extract_powerpoint", lambda raw, name: "slide")
    text, part = ufe.process_uploaded_attachment("a.pptx", "", b"ppt")
    assert "[PRESENTASI PPTX: a.pptx]" in text and part is None

    monkeypatch.setattr(ufe, "_extract_excel", lambda raw, name, ext: "sheet")
    text, _ = ufe.process_uploaded_attachment("a.xlsx", "", b"xls")
    assert "[SPREADSHEET EXCEL: a.xlsx]" in text

    monkeypatch.setattr(ufe, "_extract_csv", lambda raw, name: "a,b\n1,2")
    text, _ = ufe.process_uploaded_attachment("data.csv", "", b"a,b\n1,2")
    assert "[DATA TABEL CSV: data.csv]" in text

    monkeypatch.setattr(ufe, "_extract_csv", lambda raw, name: None)
    text, _ = ufe.process_uploaded_attachment("data.csv", "", b"a,b\n1,2")
    assert "[BERKAS TEKS: data.csv]" in text


def test_process_archive_html_data_and_code(ufe, monkeypatch):
    monkeypatch.setattr(ufe, "_extract_archive", lambda raw, name, ext: "arsip")
    text, _ = ufe.process_uploaded_attachment("a.zip", "", b"zip")
    assert "[ARSIP TERKOMPRESI: a.zip]" in text

    monkeypatch.setattr(ufe, "_extract_html_xml", lambda raw, name, ext: "html")
    text, _ = ufe.process_uploaded_attachment("a.html", "", b"<html/>")
    assert "[KODE WEB / STRUKTUR: a.html]" in text

    monkeypatch.setattr(ufe, "_extract_data_formats", lambda raw, name, ext: "data")
    text, _ = ufe.process_uploaded_attachment("a.yaml", "", b"a: 1")
    assert "[DATA KONFIGURASI: a.yaml]" in text

    code = b"print(1)\nprint(2)\n"
    text, _ = ufe.process_uploaded_attachment("script.py", "", code)
    assert "[KODE SUMBER: script.py]" in text
    assert "```python" in text and "1 | print(1)" in text

    long_code = "\n".join(str(i) for i in range(1005)).encode()
    text, _ = ufe.process_uploaded_attachment("long.py", "", long_code)
    assert "Menampilkan 1000 dari total 1005 baris" in text


def test_process_fallback_and_binary(ufe):
    text, _ = ufe.process_uploaded_attachment("catatan.unknown", "", b"halo")
    assert "[BERKAS TEKS: catatan.unknown]" in text and "halo" in text

    class BadBytes(bytes):
        def decode(self, *a, **k):
            raise ValueError("x")  # noqa: TRY003

    text, _ = ufe.process_uploaded_attachment(
        "x.bin", "application/x-bin", BadBytes(b"xx"), save_disk=False
    )
    assert "[BERKAS BINER: x.bin (2 bytes)]" in text


# ---------------------------------------------------------------------------
# Document extractors
# ---------------------------------------------------------------------------


def test_extract_pdf_fitz_primary_and_pypdf_fallback(ufe, monkeypatch):
    class Page:
        def __init__(self, text):
            self._text = text

        def get_text(self, mode):
            return self._text

    class Doc:
        def __iter__(self):
            return iter([Page("satu"), Page("  "), Page("dua")])

        def __len__(self):
            return 3

    fake_fitz = types.ModuleType("fitz")
    fake_fitz.open = lambda **kwargs: Doc()
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    out = ufe._extract_pdf(b"pdf", "a.pdf")
    assert "Total 3 halaman" in out
    assert "Halaman 1" in out and "Halaman 3" in out

    class BoomFitz(types.ModuleType):
        def open(self, **kwargs):
            raise RuntimeError("fitz")

    monkeypatch.setitem(sys.modules, "fitz", BoomFitz("fitz"))

    class PdfPage:
        def extract_text(self):
            return "teks"

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = lambda stream: SimpleNamespace(pages=[PdfPage(), PdfPage()])
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    out = ufe._extract_pdf(b"pdf", "a.pdf")
    assert "Total 2 halaman" in out and "teks" in out

    class PdfBoom(types.ModuleType):
        def PdfReader(self, stream):  # noqa: N802
            raise ValueError("bad")

    monkeypatch.setitem(sys.modules, "pypdf", PdfBoom("pypdf"))
    assert "Gagal membaca teks" in ufe._extract_pdf(b"pdf", "a.pdf")


def test_extract_word_and_powerpoint(ufe, monkeypatch):
    class Style:
        name = "Heading 1"

    fake_docx = types.ModuleType("docx")
    fake_docx.Document = lambda stream: SimpleNamespace(
        paragraphs=[
            SimpleNamespace(text="Judul", style=Style()),
            SimpleNamespace(text="  ", style=None),
            SimpleNamespace(text="Isi", style=SimpleNamespace(name="Normal")),
        ],
        tables=[
            SimpleNamespace(
                rows=[
                    SimpleNamespace(
                        cells=[SimpleNamespace(text="A"), SimpleNamespace(text="B")]
                    ),
                    SimpleNamespace(
                        cells=[
                            SimpleNamespace(text="1\nx"),
                            SimpleNamespace(text="2"),
                        ]
                    ),
                ]
            )
        ],
    )
    monkeypatch.setitem(sys.modules, "docx", fake_docx)
    out = ufe._extract_word(b"doc", "a.docx")
    assert "### Judul" in out and "#### Tabel 1" in out and "| 1 x | 2 |" in out

    class BoomDocx(types.ModuleType):
        def Document(self, stream):  # noqa: N802
            raise RuntimeError("docx")

    monkeypatch.setitem(sys.modules, "docx", BoomDocx("docx"))
    assert "Gagal membaca dokumen Word" in ufe._extract_word(b"doc", "a.docx")

    notes = SimpleNamespace(notes_text_frame=SimpleNamespace(text="catatan"))
    slide = SimpleNamespace(
        shapes=[
            SimpleNamespace(text="Judul"),
            SimpleNamespace(text="  "),
            SimpleNamespace(splat=1),
        ],
        has_notes_slide=True,
        notes_slide=notes,
    )
    fake_pptx = types.ModuleType("pptx")
    fake_pptx.Presentation = lambda stream: SimpleNamespace(slides=[slide])
    monkeypatch.setitem(sys.modules, "pptx", fake_pptx)
    out = ufe._extract_powerpoint(b"ppt", "a.pptx")
    assert "Total 1 Slide" in out and "Catatan Presenter" in out

    class BoomPptx(types.ModuleType):
        def Presentation(self, stream):  # noqa: N802
            raise RuntimeError("ppt")

    monkeypatch.setitem(sys.modules, "pptx", BoomPptx("pptx"))
    assert "Gagal membaca presentasi" in ufe._extract_powerpoint(b"ppt", "a.pptx")


# ---------------------------------------------------------------------------
# Sheet aggregation helpers
# ---------------------------------------------------------------------------


def test_pre_aggregation_empty_and_numeric(ufe):
    assert ufe._build_full_sheet_pre_aggregation([], []) == ""
    headers = ["Qty", "Biaya", "Kategori", "Tanggal", "ID"]
    rows = [
        [1, 10.5, "A", "2024-01-01", "x1"],
        [2, 20.5, "A", "2024-01-02", "x2"],
        [3, 30.5, "B", "2024-01-03", "x3"],
        [4, None, "", "", "x4"],
        [5, "", "C", "2024-01-04", "x5"],
        [6, 40.5, "C", "2024-01-05", "x6"],
        [7, 50.5, "C", "2024-01-06", "x7"],
        [8, 60.5, "B", "2024-01-07", "x8"],
        [9, 70.5, "A", "2024-01-08", "x9"],
        [10, 80.5, "A", "2024-01-09", "x10"],
    ]
    out = ufe._build_full_sheet_pre_aggregation(headers, rows)
    assert "REKAPITULASI EKSAK 100%" in out
    assert "SUM" in out and "Biaya" in out
    assert "Tanggal" not in out
    assert "ID" not in out


def test_pre_aggregation_string_numbers_bools_and_blank_header(ufe):
    headers = ["", "Nilai", "Flag"]
    rows = [
        ["x", "1,5", True],
        ["y", "2.5", False],
        ["z", "-3", True],
    ]
    out = ufe._build_full_sheet_pre_aggregation(headers, rows)
    assert "Nilai" in out
    assert "Flag" in out
    assert "True" in out


def test_prepare_sheet_headers_empty_and_simple(ufe):
    assert ufe._prepare_sheet_headers_and_rows([]) == ([], [], 0)
    headers, rows, raw_cols = ufe._prepare_sheet_headers_and_rows(
        [["Nama", "Qty"], ["a", 1]]
    )
    assert headers == ["Nama", "Qty"] and rows == [["a", 1]] and raw_cols == 2


def test_prepare_sheet_headers_anchor_and_summary_row(ufe):
    rows = [
        ["Laporan", None, None, None],
        ["Material Code", "Material Description", "Qty", "Gap"],
        ["M1", "Kabel", 10, 100],
        ["M2", "Tiang", 20, 200],
    ]
    rows[1].extend([1.0, 2.0, 3.0])
    rows[0].extend([None, None, None])
    # Anchor dengan angka ringkasan di kolom kanan -> dipertahankan sebagai baris total.
    headers, data_rows, raw_cols = ufe._prepare_sheet_headers_and_rows(rows)
    assert any(h.startswith("Material") for h in headers)
    assert data_rows[0][0] == "TOTAL / RINGKASAN"
    assert raw_cols == 7


def test_prepare_sheet_headers_footer_pruning(ufe):
    rows = [
        ["Laporan Material"],
        ["Material Code", "Material Description", "Qty"],
        ["M1", "Kabel", 1],
        ["", "", None],
        ["catatan.pdf", "", None],
        ["M2", "Tiang", 2],
    ]
    headers, data_rows, _ = ufe._prepare_sheet_headers_and_rows(rows)
    assert len(data_rows) == 2
    assert headers[0].lower() == "material code"


def test_prepare_sheet_headers_wide_pruning(ufe):
    header = [f"Kolom {i}" for i in range(20)]
    header[0] = "Material Code"
    header[1] = "Material Description"
    header[2] = "Type"
    header[3] = "Unit"
    for i in range(4, 20):
        header[i] = f"Daily {i}"
    rows = [header] + [[f"v{i}" for i in range(20)] for _ in range(3)]
    headers, data_rows, raw_cols = ufe._prepare_sheet_headers_and_rows(rows)
    assert raw_cols == 20
    assert len(headers) <= 15
    assert len(data_rows[0]) == len(headers)


def test_cross_sheet_rollup(ufe):
    assert ufe._build_cross_sheet_material_rollup([]) == ""

    records = [
        {
            "name": "Summary",
            "headers": ["Material Description", "Total Material Provided"],
            "rows": [["x", 1]],
        },
        {
            "name": "Pati",
            "headers": [
                "Type",
                "Material Description",
                "Unit",
                "Total Material Provided",
                "Usage Qty",
                "Remaining Qty",
                "Actual Stock",
            ],
            "rows": [
                ["Kabel", 'Kabel  “A” 2,5"', "m", 10, "2,5", 7, 8],
                [None, "Kabel  “A” 2,5\"", "", 5, 1, 4, 4],
                ["Tiang", "Tiang Beton", "btg", "3", None, 3, 3],
                [None, None, None, None, None, None, None],
                [None, "material description", None, 99, 99, 99, 99],
            ],
        },
        {
            "name": "Jepara",
            "headers": [
                "Material Description",
                "Total Material Provided",
                "Usage Qty",
                "Remaining Qty",
                "Actual Stock",
            ],
            "rows": [["Tiang Beton", 2, 1, 1, 1]],
        },
        {
            "name": "Lain",
            "headers": ["Foo"],
            "rows": [["bar"]],
        },
    ]
    out = ufe._build_cross_sheet_material_rollup(records)
    assert "REKAPITULASI GABUNGAN LINTAS SHEET" in out
    assert "Pati" in out and "Jepara" in out
    assert "Kabel" in out and "Tiang Beton" in out

    only_one = [records[1], records[3]]
    assert ufe._build_cross_sheet_material_rollup(only_one) == ""


# ---------------------------------------------------------------------------
# Excel / CSV
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


def test_extract_excel_multi_sheet_with_rollup(ufe, monkeypatch):
    header = [
        "Material Description",
        "Unit",
        "Total Material Provided",
        "Usage Qty",
        "Remaining Qty",
        "Actual Stock",
    ]
    sheets = {
        "Pati": [header, ["Kabel", "m", 10, 2, 8, 8], [None] * 6],
        "Jepara": [header, ["Kabel", "m", 5, 1, 4, 4]],
        "Kosong": [[None, None]],
    }
    _fake_openpyxl(monkeypatch, sheets)
    out = ufe._extract_excel(b"xlsx", "a.xlsx", ".xlsx")
    assert "REKAPITULASI GABUNGAN" in out
    assert "Sheet: Pati" in out and "Sheet: Jepara" in out
    assert "Sheet: Kosong" not in out


def test_extract_excel_single_sheet_many_rows(ufe, monkeypatch):
    header = ["Nama", "Qty"]
    rows = [header] + [[f"item{i}", i] for i in range(90)]
    _fake_openpyxl(monkeypatch, {"Satu": rows})
    out = ufe._extract_excel(b"xlsx", "a.xlsx", ".xlsx")
    assert "30 Sampel Pertama dari 90" in out
    assert "90 baris data" in out


def test_extract_excel_openpyxl_error_then_pandas(ufe, monkeypatch):
    class Boom(types.ModuleType):
        def load_workbook(self, *a, **k):
            raise RuntimeError("openpyxl")

    monkeypatch.setitem(sys.modules, "openpyxl", Boom("openpyxl"))

    class Df:
        columns = ["Nama", "Qty"]
        shape = (2, 2)

        def __len__(self):
            return 2

        @property
        def values(self):
            return SimpleNamespace(tolist=lambda: [["a", 1], ["b", 2]])

        def head(self, n):
            return self

        def to_markdown(self, index=False):
            return "| Nama | Qty |"

    fake_pd = types.ModuleType("pandas")
    fake_pd.read_excel = lambda *a, **k: Df()
    monkeypatch.setitem(sys.modules, "pandas", fake_pd)

    out = ufe._extract_excel(b"xlsx", "a.xlsx", ".xlsx")
    assert "Data Spreadsheet: a.xlsx (2 baris x 2 kolom)" in out
    assert "REKAPITULASI" in out

    out = ufe._extract_excel(b"ods", "a.ods", ".ods")
    assert "Data Spreadsheet: a.ods" in out

    fake_pd.read_excel = lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    assert "Gagal membaca spreadsheet" in ufe._extract_excel(b"x", "a.xlsx", ".xlsx")


def test_extract_csv_success_and_fallback(ufe, monkeypatch):
    out = ufe._extract_csv(b"nama,qty\na,1\nb,2\nc,3\n", "a.csv")
    assert "Data Tabel" in out and "delimiter" in out
    assert "nama" in out

    import pandas as pd

    monkeypatch.setattr(
        pd, "read_csv", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )
    out = ufe._extract_csv(b"a,b\n1,2\n", "a.csv")
    assert out.startswith("```csv") and "a,b" in out


# ---------------------------------------------------------------------------
# Archive / HTML / data formats
# ---------------------------------------------------------------------------


def test_extract_archive_zip_and_tar(ufe):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("folder/", "")
        zf.writestr("folder/a.txt", "isi teks")
        zf.writestr("folder/b.py", "print(1)")
    out = ufe._extract_archive(buf.getvalue(), "a.zip", ".zip")
    assert "Total 3 item" in out
    assert "Pratinjau Isi" in out and "isi teks" in out

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        data = b"hello"
        info = tarfile.TarInfo("a.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    out = ufe._extract_archive(buf.getvalue(), "a.tar", ".tar")
    assert "Total 1 item" in out and "a.txt" in out

    assert "Gagal membaca arsip" in ufe._extract_archive(b"bukan arsip", "x.zip", ".zip")


def test_extract_html_xml_and_fallback(ufe, monkeypatch):
    html = b"<html><script>x</script><nav>n</nav><body>Halo <b>Dunia</b></body></html>"
    out = ufe._extract_html_xml(html, "a.html", ".html")
    assert "Konten Web/Struktur a.html" in out
    assert "Halo" in out and "Dunia" in out

    class Boom(types.ModuleType):
        def __getattr__(self, name):
            raise RuntimeError("bs4")

    monkeypatch.setitem(sys.modules, "bs4", None)
    out = ufe._extract_html_xml(b"<p>x</p>", "a.html", ".html")
    assert "<p>x</p>" in out


def test_extract_data_formats(ufe):
    out = ufe._extract_data_formats(b'{"a": 1}', "a.json", ".json")
    assert "```json" in out and '"a": 1' in out

    out = ufe._extract_data_formats(b'{"a": 1}\n{"b": 2}\n', "a.jsonl", ".jsonl")
    assert "Total 2 baris JSONL" in out

    out = ufe._extract_data_formats(b"a: 1\nb: [1, 2]\n", "a.yaml", ".yaml")
    assert "```yaml" in out and "a: 1" in out

    out = ufe._extract_data_formats(b"x = 1\n", "a.toml", ".toml")
    assert out.startswith("```") and "x = 1" in out

    out = ufe._extract_data_formats(b"{rusak", "a.json", ".json")
    assert out.startswith("{rusak")
