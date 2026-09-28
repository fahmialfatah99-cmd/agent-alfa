"""Coverage batch 9: WhatsApp dashboard route helpers and validators.

Hermetic: WA_DRIVE_UPLOADS_FILE redirected to tmp, Drive API mocked.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def wa(tmp_path, monkeypatch):
    import alfa.dashboard.routes.system.whatsapp as wam

    monkeypatch.setattr(
        wam, "WA_DRIVE_UPLOADS_FILE", str(tmp_path / "drive_uploads.json")
    )
    return wam


def _svc(existing_ids=None, created_id="NEW_ID"):
    """Fake Drive service: list() returns existing_ids, create() returns created_id."""
    svc = MagicMock()
    files = MagicMock()
    files.list.return_value.execute.return_value = {
        "files": [{"id": i, "name": "n"} for i in (existing_ids or [])]
    }
    files.create.return_value.execute.return_value = {"id": created_id}
    svc.files.return_value = files
    return svc


# ── media rules validation ───────────────────────────────────────────────────


class TestValidateMediaRules:
    def test_requires_list(self, wa):
        errs = wa._validate_media_rules({"a": 1})
        assert len(errs) == 1
        assert "harus berupa array" in errs[0]

    def test_caps_at_30(self, wa):
        rules = [{"name": f"r{i}", "types": ["foto"], "naming": "x"} for i in range(31)]
        assert wa._validate_media_rules(rules) == ["Maksimal 30 aturan."]

    def test_accepts_valid(self, wa):
        rules = [{"name": "invoice", "types": ["foto", "pdf"], "naming": "INV-*"}]
        assert wa._validate_media_rules(rules) == []

    def test_rejects_non_dict_entry(self, wa):
        errs = wa._validate_media_rules(["bukan objek"])
        assert any("bukan objek" in e for e in errs)

    def test_rejects_empty_name(self, wa):
        errs = wa._validate_media_rules([{"name": "  ", "types": ["foto"]}])
        assert any("nama kosong" in e for e in errs)

    def test_rejects_duplicate_name_case_insensitive(self, wa):
        rules = [
            {"name": "Inv", "types": ["foto"], "naming": "a"},
            {"name": "inv", "types": ["foto"], "naming": "b"},
        ]
        errs = wa._validate_media_rules(rules)
        assert any("duplikat" in e for e in errs)

    def test_rejects_empty_types(self, wa):
        errs = wa._validate_media_rules([{"name": "a", "types": [], "naming": "x"}])
        assert any("minimal satu jenis file" in e for e in errs)

    def test_rejects_unknown_type(self, wa):
        errs = wa._validate_media_rules(
            [{"name": "a", "types": ["exe"], "naming": "x"}]
        )
        assert any("minimal satu jenis file" in e for e in errs)

    def test_rejects_non_list_types(self, wa):
        errs = wa._validate_media_rules([{"name": "a", "types": "foto", "naming": "x"}])
        assert any("minimal satu jenis file" in e for e in errs)

    def test_rejects_empty_naming(self, wa):
        errs = wa._validate_media_rules([{"name": "a", "types": ["foto"]}])
        assert any("pola nama file kosong" in e for e in errs)


# ── sheet format validation ──────────────────────────────────────────────────


class TestValidateFormats:
    def test_requires_list(self, wa):
        errs = wa._validate_wa_formats("bukan array")
        assert len(errs) == 1 and "harus berupa array" in errs[0]

    def test_caps_at_50(self, wa):
        fmts = [
            {
                "name": f"f{i}",
                "tab": f"t{i}",
                "keywords": ["x"],
                "columns": [{"title": "a", "source": "b"}],
            }
            for i in range(51)
        ]
        assert wa._validate_wa_formats(fmts) == ["Maksimal 50 format."]

    def test_accepts_valid(self, wa):
        fmts = [
            {
                "name": "Order",
                "tab": "Order",
                "keywords": ["order"],
                "columns": [{"title": "No", "source": "no"}],
            }
        ]
        assert wa._validate_wa_formats(fmts) == []

    def test_rejects_non_dict_entry(self, wa):
        assert any("bukan objek" in e for e in wa._validate_wa_formats([42]))

    def test_rejects_empty_name(self, wa):
        fmts = [
            {
                "name": " ",
                "tab": "T",
                "keywords": ["k"],
                "columns": [{"title": "a", "source": "b"}],
            }
        ]
        assert any("nama kosong" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_duplicate_name(self, wa):
        col = [{"title": "a", "source": "b"}]
        fmts = [
            {"name": "X", "tab": "T1", "keywords": ["k"], "columns": col},
            {"name": "x", "tab": "T2", "keywords": ["k"], "columns": col},
        ]
        assert any("duplikat" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_empty_tab(self, wa):
        fmts = [
            {
                "name": "X",
                "tab": "",
                "keywords": ["k"],
                "columns": [{"title": "a", "source": "b"}],
            }
        ]
        assert any("tab Sheets kosong" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_duplicate_tab(self, wa):
        col = [{"title": "a", "source": "b"}]
        fmts = [
            {"name": "A", "tab": "S", "keywords": ["k"], "columns": col},
            {"name": "B", "tab": "S", "keywords": ["k"], "columns": col},
        ]
        assert any("lebih dari satu format" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_missing_keywords(self, wa):
        fmts = [
            {
                "name": "X",
                "tab": "T",
                "keywords": [],
                "columns": [{"title": "a", "source": "b"}],
            }
        ]
        assert any("keywords wajib" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_blank_keyword(self, wa):
        fmts = [
            {
                "name": "X",
                "tab": "T",
                "keywords": ["  "],
                "columns": [{"title": "a", "source": "b"}],
            }
        ]
        assert any("keywords wajib" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_empty_columns(self, wa):
        fmts = [{"name": "X", "tab": "T", "keywords": ["k"], "columns": []}]
        assert any("minimal 1 kolom" in e for e in wa._validate_wa_formats(fmts))

    def test_caps_columns_at_30(self, wa):
        cols = [{"title": f"c{i}", "source": "s"} for i in range(31)]
        fmts = [{"name": "X", "tab": "T", "keywords": ["k"], "columns": cols}]
        assert any("maksimal 30 kolom" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_column_empty_title(self, wa):
        fmts = [
            {
                "name": "X",
                "tab": "T",
                "keywords": ["k"],
                "columns": [{"title": "", "source": "s"}],
            }
        ]
        assert any("judul kosong" in e for e in wa._validate_wa_formats(fmts))

    def test_rejects_column_empty_source(self, wa):
        fmts = [
            {
                "name": "X",
                "tab": "T",
                "keywords": ["k"],
                "columns": [{"title": "A", "source": ""}],
            }
        ]
        assert any("sumber kosong" in e for e in wa._validate_wa_formats(fmts))

    def test_column_source_falls_back_to_value(self, wa):
        fmts = [
            {
                "name": "X",
                "tab": "T",
                "keywords": ["k"],
                "columns": [{"title": "A", "value": "B"}],
            }
        ]
        assert wa._validate_wa_formats(fmts) == []


# ── gdrive subfolder ─────────────────────────────────────────────────────────


class TestGdriveSubfolder:
    def test_returns_existing(self, wa, monkeypatch):
        monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "PARENT")
        monkeypatch.setattr(wa.tools, "_get_gdrive_service", lambda: _svc(["EXISTING"]))
        assert wa._gdrive_ensure_subfolder("WaInvoice") == "EXISTING"

    def test_creates_when_missing(self, wa, monkeypatch):
        monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "PARENT")
        svc = _svc([], created_id="CREATED")
        monkeypatch.setattr(wa.tools, "_get_gdrive_service", lambda: svc)
        assert wa._gdrive_ensure_subfolder("WaInvoice") == "CREATED"
        body = svc.files.return_value.create.call_args.kwargs["body"]
        assert body["name"] == "WaInvoice"
        assert body["parents"] == ["PARENT"]

    def test_creates_without_parent(self, wa, monkeypatch):
        monkeypatch.setattr(wa.tools, "_get_default_gdrive_folder_id", lambda: "")
        svc = _svc([], created_id="CREATED2")
        monkeypatch.setattr(wa.tools, "_get_gdrive_service", lambda: svc)
        assert wa._gdrive_ensure_subfolder("WaInvoice") == "CREATED2"
        body = svc.files.return_value.create.call_args.kwargs["body"]
        assert "parents" not in body


# ── upload log ───────────────────────────────────────────────────────────────


class TestUploadLog:
    def test_first_write_creates_file(self, wa):
        wa._log_wa_drive_upload({"file": "a.pdf"})
        data = json.loads(Path(wa.WA_DRIVE_UPLOADS_FILE).read_text())
        assert data["uploads"][0] == {"file": "a.pdf"}

    def test_prepends_newest_first(self, wa):
        wa._log_wa_drive_upload({"n": 1})
        wa._log_wa_drive_upload({"n": 2})
        data = json.loads(Path(wa.WA_DRIVE_UPLOADS_FILE).read_text())
        assert [u["n"] for u in data["uploads"]] == [2, 1]

    def test_caps_at_200(self, wa):
        wa._log_wa_drive_upload({"n": 0})
        for i in range(1, 250):
            wa._log_wa_drive_upload({"n": i})
        data = json.loads(Path(wa.WA_DRIVE_UPLOADS_FILE).read_text())
        assert len(data["uploads"]) == 200
        assert data["uploads"][0]["n"] == 249

    def test_tolerates_corrupt_file(self, wa):
        Path(wa.WA_DRIVE_UPLOADS_FILE).write_text("{{{rusak", encoding="utf-8")
        wa._log_wa_drive_upload({"n": 7})
        data = json.loads(Path(wa.WA_DRIVE_UPLOADS_FILE).read_text())
        assert data["uploads"][0]["n"] == 7

    def test_never_raises(self, wa, monkeypatch):
        monkeypatch.setattr(
            wa.os,
            "replace",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        wa._log_wa_drive_upload({"n": 1})  # must swallow
