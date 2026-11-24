"""Phase 6 coverage: office documents, dataset charts, translation, sheets.

Hermetic: workbook dibuat di ``tmp_path``, matplotlib/pptx/Gemini di-fake.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def docs(monkeypatch, tmp_path):
    from alfa.tools.media import documents

    monkeypatch.setattr(documents, "SANDBOX_DIR", str(tmp_path))
    return documents


# ---------------------------------------------------------------------------
# Excel generation helpers
# ---------------------------------------------------------------------------


def test_generate_excel_variants(docs, tmp_path):
    out = docs.generate_excel_spreadsheet(
        "Laporan", ["Nama", "Qty"], json.dumps([["A", 1], {"Nama": "B", "qty": 2}])
    )
    assert out["status"] == "success"
    assert Path(out["file_path"]).exists()

    out = docs.generate_excel_spreadsheet(
        "CSV", "Nama,Qty", json.dumps([["A", 1]]), filename="lain"
    )
    assert Path(out["file_path"]).name == "lain.xlsx"

    out = docs.generate_excel_spreadsheet(
        "JSONHeader", json.dumps(["Nama", "Qty"]), json.dumps([["A", 1]])
    )
    assert out["status"] == "success"

    out = docs.generate_excel_spreadsheet("Dict", [], json.dumps([{"Nama": "A", "Qty": 1}]))
    assert out["status"] == "success"

    out = docs.generate_excel_spreadsheet("Scalar", [], json.dumps([1, 2]))
    assert out["status"] == "success"


def test_generate_excel_error(docs, monkeypatch):
    import openpyxl

    monkeypatch.setattr(
        openpyxl,
        "Workbook",
        lambda: (_ for _ in ()).throw(RuntimeError("excel rusak")),
    )
    out = docs.generate_excel_spreadsheet("X", ["A"], "[]")
    assert out["status"] == "error" and "Gagal membuat Excel" in out["message"]


def test_parse_helpers(docs):
    p = docs._parse_excel_headers
    assert p(None) == []
    assert p("  ") == []
    assert p('["A", "B"]') == ["A", "B"]
    assert p("A, B ,C") == ["A", "B", "C"]
    assert p(("A", "B")) == ["A", "B"]
    assert p("{rusak") == ["{rusak"]

    r = docs._parse_excel_rows
    assert r(None) == []
    assert r("   ") == []
    assert r('{"a": 1}') == [{"a": 1}]
    assert r([1, 2]) == [1, 2]
    with pytest.raises(TypeError):
        r(123)

    assert docs._normalize_excel_rows([{"A": 1}, ["x"], 5], ["A", "B"]) == [
        [1, ""],
        ["x"],
        [5],
    ]
    assert docs._xl_text(None) == "" and docs._xl_text(3) == "3"
    assert docs._xl_json_safe(SimpleNamespace(a=1)) .startswith("namespace")


def test_sha_and_snapshot(docs, tmp_path):
    missing = tmp_path / "nope.xlsx"
    assert docs._xl_sha256(missing) == ("", 0)

    good = tmp_path / "a.txt"
    good.write_text("abc", encoding="utf-8")
    digest, size = docs._xl_sha256(good)
    assert size == 3 and len(digest) == 64

    snap = docs._excel_snapshot(missing, "Sheet1")
    assert snap["exists"] is False

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Nama", "Qty"])
    ws.append(["A", 1])
    path = tmp_path / "b.xlsx"
    wb.save(path)
    wb.close()

    snap = docs._excel_snapshot(path, "Data")
    assert snap["sheet_exists"] is True
    assert snap["headers"] == ["Nama", "Qty"]
    assert snap["has_content"] is True

    snap = docs._excel_snapshot(path, "TidakAda")
    assert snap["sheet_exists"] is False


def test_build_excel_diff_actions(docs, tmp_path):
    path = tmp_path / "c.xlsx"
    path.write_text("x", encoding="utf-8")
    base = {"_path": str(path), "exists": True, "sheets": ["S"], "sheet_exists": True,
            "headers": ["A"], "rows": [["A"], [1]], "max_row": 2, "has_content": True}

    create = docs._build_excel_diff({**base, "sheet_exists": False}, "S", ["A"], [[1]], "upsert", "T")
    assert create["action"] == "create_sheet"
    assert "buat sheet baru" in create["summary"]

    append = docs._build_excel_diff(base, "S", ["A"], [[2]], "append", "")
    assert append["action"] == "append_rows" and append["rows_added"] == 1

    replace = docs._build_excel_diff(base, "S", ["A"], [], "upsert", "Judul")
    assert replace["action"] == "replace_sheet"
    assert replace["rows_removed"] == 1
    assert "baris judul" in replace["summary"]

    same = docs._build_excel_diff(base, "S", ["A"], [[1]], "upsert", "")
    assert same["changed"] is False
    assert "tidak ada perubahan" in same["summary"]

    preview = docs._build_excel_diff(
        {**base, "_path": "", "exists": False, "sheet_exists": False}, "S", ["A"], [[1]], "replace", ""
    )
    assert preview["changed"] is True and preview["file_sha256"] == ""


def test_verify_excel_sheet(docs, tmp_path):
    import openpyxl

    path = tmp_path / "d.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Nama", "Qty"])
    ws.append(["A", 1])
    wb.save(path)
    wb.close()

    ok, detail, sheets = docs._verify_excel_sheet(path, "Data", ["Nama", "Qty"], 1, 2)
    assert ok is True and detail == "ok" and sheets == ["Data"]

    ok, detail, _ = docs._verify_excel_sheet(path, "Hilang", [], 0, 0)
    assert ok is False and "tidak ditemukan" in detail

    ok, detail, _ = docs._verify_excel_sheet(path, "Data", ["Salah"], 1, 0)
    assert ok is False and "header tidak cocok" in detail

    ok, detail, _ = docs._verify_excel_sheet(path, "Data", [], 0, 99)
    assert ok is False and "jumlah baris kurang" in detail


# ---------------------------------------------------------------------------
# update_excel_sheet / restore_excel_backup
# ---------------------------------------------------------------------------


def test_update_excel_validation(docs, tmp_path):
    f = tmp_path / "x.xlsx"
    assert docs.update_excel_sheet(str(f), "")["status"] == "error"
    assert docs.update_excel_sheet(str(f), "S" * 32)["status"] == "error"
    assert docs.update_excel_sheet(str(f), "a[b")["status"] == "error"
    assert docs.update_excel_sheet(str(f), "S", mode="bad")["status"] == "error"
    assert docs.update_excel_sheet("", "S")["status"] == "error"
    assert docs.update_excel_sheet(str(tmp_path / "x.txt"), "S")["status"] == "error"
    assert docs.update_excel_sheet(str(tmp_path / "missing" / "x.xlsx"), "S")["status"] == "error"
    assert docs.update_excel_sheet(str(f), "S")["status"] == "error"
    assert docs.update_excel_sheet(str(f), "S", rows_json="rusak")["status"] == "error"


def test_update_excel_create_and_append(docs, tmp_path):
    f = tmp_path / "new.xlsx"
    out = docs.update_excel_sheet(
        str(f), "Data", ["Nama", "Qty"], json.dumps([["A", 1]]), title="Judul"
    )
    assert out["status"] == "success" and out["verified"] is True
    assert out["rows_written"] == 1

    out = docs.update_excel_sheet(str(f), "Data", rows_json=json.dumps([["B", 2]]), mode="append")
    assert out["status"] == "success"
    assert out["total_rows"] >= 4

    out = docs.update_excel_sheet(str(f), "Kedua", ["X"], json.dumps([[1]]), keep_backup=True)
    assert out["status"] == "success"
    assert out["backup_path"] and Path(out["backup_path"]).exists()

    out = docs.update_excel_sheet(str(f), "Kedua", ["X"], json.dumps([[2]]), mode="replace")
    assert out["status"] == "success"


def test_update_excel_dry_run(docs, tmp_path):
    f = tmp_path / "dry.xlsx"
    docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[1]]))
    out = docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[2]]), dry_run=True)
    assert out["status"] == "preview"
    assert out["diff"]["action"] == "replace_sheet"

    out = docs.update_excel_sheet(str(f), "Baru", ["A"], json.dumps([[1]]), dry_run=True)
    assert out["diff"]["action"] == "create_sheet"

    out = docs.update_excel_sheet(
        str(f), "Data", ["A"], json.dumps([[2]]), mode="append", dry_run=True
    )
    assert out["diff"]["action"] == "append_rows"


def test_update_excel_verify_failure_restores_backup(docs, tmp_path, monkeypatch):
    f = tmp_path / "v.xlsx"
    docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[1]]))
    monkeypatch.setattr(
        docs, "_verify_excel_sheet", lambda *a: (False, "gagal verifikasi", [])
    )
    out = docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[2]]))
    assert out["status"] == "error" and "Verifikasi gagal" in out["message"]

    g = tmp_path / "baru.xlsx"
    out = docs.update_excel_sheet(str(g), "Data", ["A"], json.dumps([[1]]))
    assert out["status"] == "error"
    assert not g.exists()


def test_update_excel_exception(docs, tmp_path, monkeypatch):
    f = tmp_path / "e.xlsx"
    docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[1]]))
    import openpyxl

    def boom(*a, **k):
        raise RuntimeError("load gagal")  # noqa: TRY003

    monkeypatch.setattr(openpyxl, "load_workbook", boom)
    out = docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[2]]))
    assert out["status"] == "error" and "Gagal update Excel" in out["message"]


def test_restore_excel_backup_validation(docs, tmp_path):
    assert docs.restore_excel_backup("")["status"] == "error"
    assert docs.restore_excel_backup(str(tmp_path / "x.txt"))["status"] == "error"
    assert docs.restore_excel_backup(str(tmp_path / "nope.xlsx"))["status"] == "error"

    f = tmp_path / "a.xlsx"
    f.write_text("x", encoding="utf-8")
    out = docs.restore_excel_backup(str(f))
    assert out["status"] == "error" and "Tidak ada backup" in out["message"]

    other = tmp_path / "b.bak-x"
    out = docs.restore_excel_backup(str(f), str(other))
    assert out["status"] == "error" and "tidak valid" in out["message"]


def test_restore_excel_backup_success_and_failure(docs, tmp_path):
    f = tmp_path / "r.xlsx"
    docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[1]]))
    out = docs.update_excel_sheet(
        str(f), "Data", ["A"], json.dumps([[2]]), keep_backup=True
    )
    backup = Path(out["backup_path"])
    out = docs.restore_excel_backup(str(f))
    assert out["status"] == "success" and out["verified"] is True
    assert "Data" in out["sheets"]
    assert backup.exists()

    out2 = docs.update_excel_sheet(
        str(f), "Data", ["A"], json.dumps([[2]]), keep_backup=True
    )
    backup2 = out2["backup_path"]
    out = docs.restore_excel_backup(str(f), backup2)
    assert out["status"] == "success"


def test_restore_excel_backup_empty_workbook(docs, tmp_path, monkeypatch):
    f = tmp_path / "s.xlsx"
    docs.update_excel_sheet(str(f), "Data", ["A"], json.dumps([[1]]))
    out = docs.update_excel_sheet(
        str(f), "Data", ["A"], json.dumps([[2]]), keep_backup=True
    )
    backup = out["backup_path"]
    import openpyxl

    real_load = openpyxl.load_workbook
    calls = {"n": 0}

    def fake_load(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_load(*a, **k)
        return SimpleNamespace(sheetnames=[], close=lambda: None)

    monkeypatch.setattr(openpyxl, "load_workbook", fake_load)
    out = docs.restore_excel_backup(str(f), backup)
    assert out["status"] == "error" and "Gagal restore Excel" in out["message"]


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


def test_generate_presentation(docs, monkeypatch):
    class Shape:
        def __init__(self):
            self.text = ""
            self.text_frame = SimpleNamespace(
                word_wrap=False,
                text="",
                add_paragraph=lambda: SimpleNamespace(text="", level=0),
            )

    class Placeholder(Shape):
        pass

    class Slide:
        def __init__(self):
            self.shapes = SimpleNamespace(title=Shape())
            self.placeholders = {1: Placeholder()}

    class Prs:
        def __init__(self):
            self.slide_layouts = [0, 1]
            self.slides = SimpleNamespace(add_slide=lambda layout: Slide())

        def save(self, path):
            Path(path).write_text("pptx", encoding="utf-8")

    fake = types.ModuleType("pptx")
    fake.Presentation = Prs
    monkeypatch.setitem(sys.modules, "pptx", fake)
    out = docs.generate_presentation_pptx(
        "Judul", "Sub", json.dumps([{"title": "S1", "points": ["a", "b"]}])
    )
    assert out["status"] == "success"

    out = docs.generate_presentation_pptx("J", "S", json.dumps({"title": "x"}))
    assert out["status"] == "success"

    out = docs.generate_presentation_pptx("J", "S", "bukan json")
    assert out["status"] == "error"


# ---------------------------------------------------------------------------
# Dataset analysis
# ---------------------------------------------------------------------------


class FakePyplot:
    def __init__(self):
        self.calls = []
        self.style = SimpleNamespace(available=["default"], use=lambda s: None)
        self.cm = SimpleNamespace(Paired=SimpleNamespace(colors=None))

    def figure(self, **k):
        self.calls.append(("figure", k))

    def bar(self, *a, **k):
        self.calls.append(("bar", a, k))

    def plot(self, *a, **k):
        self.calls.append(("plot", a, k))

    def scatter(self, *a, **k):
        self.calls.append(("scatter", a, k))

    def pie(self, *a, **k):
        self.calls.append(("pie", a, k))

    def title(self, *a, **k):
        pass

    def xlabel(self, *a, **k):
        pass

    def ylabel(self, *a, **k):
        pass

    def xticks(self, *a, **k):
        pass

    def tight_layout(self):
        pass

    def savefig(self, path, dpi=0):
        Path(path).write_text("png", encoding="utf-8")

    def close(self):
        pass


def _fake_matplotlib(monkeypatch, pyplot):
    matplotlib = types.ModuleType("matplotlib")
    matplotlib.use = lambda backend: None
    matplotlib.pyplot = pyplot
    monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", pyplot)


def test_analyze_dataset_paths(docs, monkeypatch, tmp_path):
    pyplot = FakePyplot()
    _fake_matplotlib(monkeypatch, pyplot)

    assert docs.analyze_dataset_csv_json(str(tmp_path / "nope.csv"))["status"] == "error"

    csv_path = tmp_path / "d.csv"
    csv_path.write_text("nama,qty\nA,1\nB,x\n", encoding="utf-8")
    out = docs.analyze_dataset_csv_json(str(csv_path))
    assert out["status"] == "success" and out["total_rows"] == 2
    assert any(c[0] == "bar" for c in pyplot.calls)

    out = docs.analyze_dataset_csv_json(str(csv_path), chart_type="line")
    assert any(c[0] == "plot" for c in pyplot.calls)

    out = docs.analyze_dataset_csv_json(str(csv_path), chart_type="scatter")
    assert any(c[0] == "scatter" for c in pyplot.calls)

    out = docs.analyze_dataset_csv_json(str(csv_path), chart_type="pie", title="Pie")
    assert any(c[0] == "pie" for c in pyplot.calls)

    json_path = tmp_path / "d.json"
    json_path.write_text(json.dumps([{"nama": "A", "qty": 1}]), encoding="utf-8")
    out = docs.analyze_dataset_csv_json(str(json_path), chart_type="pie")
    assert out["status"] == "success"

    json_path.write_text(json.dumps({"nama": "A", "qty": 1}), encoding="utf-8")
    out = docs.analyze_dataset_csv_json(str(json_path), x_column="nama", y_column="qty")
    assert out["status"] == "success"

    json_path.write_text("[]", encoding="utf-8")
    assert docs.analyze_dataset_csv_json(str(json_path))["status"] == "error"

    other = tmp_path / "d.txt"
    other.write_text("x", encoding="utf-8")
    assert docs.analyze_dataset_csv_json(str(other))["status"] == "error"


def test_analyze_dataset_error(docs, monkeypatch, tmp_path):
    csv_path = tmp_path / "d.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    pyplot = FakePyplot()

    def boom(*a, **k):
        raise RuntimeError("chart rusak")  # noqa: TRY003

    pyplot.savefig = boom
    _fake_matplotlib(monkeypatch, pyplot)
    out = docs.analyze_dataset_csv_json(str(csv_path))
    assert out["status"] == "error" and "Dataset analysis error" in out["message"]


# ---------------------------------------------------------------------------
# Translation and material sheets
# ---------------------------------------------------------------------------


def test_translate_text(docs, monkeypatch):
    import alfa.swarm.llm_client as llm

    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda cfg: ("gemini", "key", "model", "", "")
    )
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = lambda **k: SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=" hello "))
    )
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    out = docs.translate_text("halo")
    assert out["status"] == "success" and out["translated"] == "hello"

    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda cfg: ("gemini", "", "model", "", "")
    )
    assert docs.translate_text("x")["status"] == "error"

    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda cfg: ("gemini", "key", "model", "", "")
    )
    fake_genai.Client = lambda **k: SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=""))
    )
    assert docs.translate_text("x")["status"] == "error"

    def boom(**k):
        raise RuntimeError("api")

    monkeypatch.setattr(
        llm, "get_agent_api_client", lambda cfg: ("gemini", "key", "model", "", "")
    )
    fake_genai.Client = lambda **k: SimpleNamespace(
        models=SimpleNamespace(generate_content=boom)
    )
    assert docs.translate_text("x")["status"] == "error"


def test_record_material_to_sheets(docs, monkeypatch):
    from alfa.integrations import google_sheets as gs

    monkeypatch.setattr(gs, "is_whatsapp_source", lambda source: False)
    out = docs.record_material_to_sheets("isi", source="telegram")
    assert out["status"] == "error"

    monkeypatch.setattr(gs, "is_whatsapp_source", lambda source: True)
    monkeypatch.setattr(
        gs,
        "is_pengambilan_material_group",
        lambda source, context="": False,
    )
    assert docs.record_material_to_sheets("isi", source="wa")["status"] == "error"

    monkeypatch.setattr(
        gs,
        "is_pengambilan_material_group",
        lambda source, context="": True,
    )
    monkeypatch.setattr(
        gs,
        "parse_and_record_material_text",
        lambda text, context="", source="": {"status": "success", "text": text},
    )
    out = docs.record_material_to_sheets("isi", context="c", source="wa")
    assert out["status"] == "success" and out["text"] == "isi"
