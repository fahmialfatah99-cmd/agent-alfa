"""Phase 5 coverage: Google Sheets validation, parsing, and sync helpers.

Hermetic: Google API, LLM, dan subprocess di-mock. ``subprocess.run`` di-patch
autouse agar tes tidak pernah me-restart ``wa-sheets-bot.service``.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from alfa.integrations import google_sheets as gs


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    wa_dir = tmp_path / "wa"
    wa_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("MATERIAL_SPREADSHEET_ID", raising=False)
    monkeypatch.setattr(gs, "WA_BOT_DIR", str(wa_dir))
    monkeypatch.setattr(gs, "WA_KEY_FILE", str(wa_dir / "service-account.json"))
    monkeypatch.setattr(gs, "GDRIVE_KEY_FILE", str(tmp_path / "gdrive_credentials.json"))
    monkeypatch.setattr(
        gs.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    return SimpleNamespace(tmp=tmp_path, home=home, wa=wa_dir)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "sheets.db"
    monkeypatch.setenv("ALFA_DB_PATH", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from alfa.core.db import connection

    connection.init_db_sync()
    return path


def _set_setting(key: str, value: str) -> None:
    from alfa.core import database

    with database.get_sync_db() as conn:
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


# ── spreadsheet id ───────────────────────────────────────────────────────────


def test_get_spreadsheet_id_priority(db, _isolated, monkeypatch):
    assert gs.get_spreadsheet_id().startswith("1d9Mr")

    _set_setting("material_spreadsheet_id", "dari-database")
    assert gs.get_spreadsheet_id() == "dari-database"

    with gs.database.get_sync_db() as conn:
        conn.execute("DELETE FROM system_settings")
        conn.commit()
    monkeypatch.setenv("SPREADSHEET_ID", "dari-env")
    assert gs.get_spreadsheet_id() == "dari-env"
    monkeypatch.delenv("SPREADSHEET_ID")

    monkeypatch.setenv("MATERIAL_SPREADSHEET_ID", "dari-env-material")
    assert gs.get_spreadsheet_id() == "dari-env-material"
    monkeypatch.delenv("MATERIAL_SPREADSHEET_ID")

    (_isolated.wa / ".env").write_text(
        'SPREADSHEET_ID="dari-wa-env"\n', encoding="utf-8"
    )
    assert gs.get_spreadsheet_id() == "dari-wa-env"


def test_get_spreadsheet_id_survives_db_error(monkeypatch):
    def boom(*args, **kwargs):
        msg = "db rusak"
        raise sqlite3.Error(msg)

    monkeypatch.setattr(gs.database, "get_sync_db", boom)
    assert gs.get_spreadsheet_id().startswith("1d9Mr")


def test_set_spreadsheet_id_rejects_short_id():
    out = gs.set_spreadsheet_id("pendek")
    assert out["status"] == "error"
    assert "tidak valid" in out["message"]


def test_set_spreadsheet_id_success_updates_db_and_env(db, _isolated, monkeypatch):
    env_file = _isolated.wa / ".env"
    env_file.write_text("SPREADSHEET_ID=lama\nLAIN=1\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        gs,
        "ensure_material_sheet_tab",
        lambda **kwargs: {"status": "success", "title": "Rekap"},
    )
    monkeypatch.setattr(
        gs.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )

    url = "https://docs.google.com/spreadsheets/d/abc1234567890XYZ/edit#gid=0"
    out = gs.set_spreadsheet_id(url)
    assert out["status"] == "success"
    assert out["spreadsheet_id"] == "abc1234567890XYZ"
    assert out["spreadsheet_title"] == "Rekap"
    text = env_file.read_text(encoding="utf-8")
    assert "SPREADSHEET_ID=abc1234567890XYZ" in text
    assert "LAIN=1" in text
    assert calls == [["systemctl", "--user", "restart", "wa-sheets-bot.service"]]

    from alfa.core import database

    with database.get_sync_db() as conn:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM system_settings WHERE key LIKE '%spreadsheet_id'"
            ).fetchall()
        )
    assert rows["material_spreadsheet_id"] == "abc1234567890XYZ"
    assert rows["wa_spreadsheet_id"] == "abc1234567890XYZ"


def test_set_spreadsheet_id_appends_env_and_warns_on_api_error(db, _isolated, monkeypatch):
    env_file = _isolated.wa / ".env"
    env_file.write_text("LAIN=1\n", encoding="utf-8")
    monkeypatch.setattr(
        gs,
        "ensure_material_sheet_tab",
        lambda **kwargs: {"status": "error", "message": "403"},
    )
    out = gs.set_spreadsheet_id("abc1234567890XYZ")
    assert out["status"] == "warning"
    assert "Share" in out["message"]
    assert "SPREADSHEET_ID=abc1234567890XYZ" in env_file.read_text(encoding="utf-8")


def test_set_spreadsheet_id_survives_db_error(_isolated, monkeypatch):
    def boom(*args, **kwargs):
        msg = "db mati"
        raise sqlite3.Error(msg)

    monkeypatch.setattr(gs.database, "get_sync_db", boom)
    monkeypatch.setattr(
        gs,
        "ensure_material_sheet_tab",
        lambda **kwargs: {"status": "error", "message": "x"},
    )
    out = gs.set_spreadsheet_id("abc1234567890XYZ")
    assert out["status"] == "warning"


# ── sheet tab initialization ─────────────────────────────────────────────────


class _Exec:
    def __init__(self, value=None):
        self.value = value

    def execute(self):
        return self.value


class _FakeSheets:
    def __init__(self, owner):
        self.owner = owner

    def get(self, **kwargs):
        self.owner.calls.append(("get", kwargs))
        if self.owner.error:
            raise self.owner.error
        return _Exec(self.owner.meta)

    def batchUpdate(self, **kwargs):  # noqa: N802 - mengikuti nama API Google
        self.owner.calls.append(("batchUpdate", kwargs))
        return _Exec({})

    def values(self):
        return _FakeValues(self.owner)


class _FakeValues:
    def __init__(self, owner):
        self.owner = owner

    def get(self, **kwargs):
        self.owner.calls.append(("values.get", kwargs))
        if self.owner.error:
            raise self.owner.error
        return _Exec({"values": self.owner.rows})

    def update(self, **kwargs):
        self.owner.calls.append(("values.update", kwargs))
        return _Exec({})

    def append(self, **kwargs):
        self.owner.calls.append(("values.append", kwargs))
        if self.owner.error:
            raise self.owner.error
        return _Exec({"updates": {"updatedRows": len(kwargs["body"]["values"])}})


class _FakeService:
    def __init__(self, meta=None, rows=None, error=None):
        self.meta = meta or {}
        self.rows = rows or []
        self.error = error
        self.calls = []

    def spreadsheets(self):
        return _FakeSheets(self)


def _meta(tabs):
    return {
        "properties": {"title": "Rekap Material"},
        "sheets": [{"properties": {"title": tab}} for tab in tabs],
    }


def test_ensure_tab_requires_id(monkeypatch):
    monkeypatch.setattr(gs, "get_spreadsheet_id", lambda: "")
    out = gs.ensure_material_sheet_tab()
    assert out["status"] == "error"


def test_ensure_tab_creates_missing_tab_and_headers(monkeypatch):
    svc = _FakeService(meta=_meta([]), rows=[])
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    out = gs.ensure_material_sheet_tab("abc1234567890XYZ")
    assert out["status"] == "success"
    assert out["tab_name"] == "Pengambilan Material"
    names = [c[0] for c in svc.calls]
    assert "batchUpdate" in names
    assert "values.update" in names


def test_ensure_tab_existing_tab_with_headers(monkeypatch):
    headers = gs.PENGAMBILAN_HEADERS
    svc = _FakeService(meta=_meta(["Pengambilan Material"]), rows=[headers])
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    out = gs.ensure_material_sheet_tab("abc1234567890XYZ")
    assert out["status"] == "success"
    names = [c[0] for c in svc.calls]
    assert "batchUpdate" not in names
    assert "values.update" not in names


def test_ensure_tab_custom_tab_name_headers(monkeypatch):
    svc = _FakeService(meta=_meta([]), rows=[["x"]])
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    out = gs.ensure_material_sheet_tab("abc1234567890XYZ", tab_name="Arsip")
    assert out["status"] == "success"
    update = next(c for c in svc.calls if c[0] == "values.update")
    assert update[1]["body"]["values"] == [gs.TRANSFER_ORDER_HEADERS]


def test_ensure_tab_permission_error_is_actionable(monkeypatch):
    msg = "The caller does not have permission"
    svc = _FakeService(error=OSError(msg))
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    out = gs.ensure_material_sheet_tab("abc1234567890XYZ")
    assert out["status"] == "error"
    assert "Service Account" in out["message"]


# ── source validation ────────────────────────────────────────────────────────


def test_is_whatsapp_source():
    assert gs.is_whatsapp_source("") is False
    assert gs.is_whatsapp_source("WA: Grup") is True
    assert gs.is_whatsapp_source("grup wa pengambilan") is True
    assert gs.is_whatsapp_source("whatsapp") is True
    assert gs.is_whatsapp_source("WhatsApp Grup") is True
    assert gs.is_whatsapp_source("Telegram") is False
    assert gs.is_whatsapp_source("file.xlsx") is False
    assert gs.is_whatsapp_source("WA: Grup", context="dari Telegram") is False
    assert gs.is_whatsapp_source("manual input") is False
    assert gs.is_whatsapp_source("hasil web") is False


def test_is_pengambilan_material_group():
    assert gs.is_pengambilan_material_group("") is False
    assert (
        gs.is_pengambilan_material_group("WA: Grup Pengambilan Material") is True
    )
    assert gs.is_pengambilan_material_group("WA: Grup", group="Pengambilan Material") is True
    assert (
        gs.is_pengambilan_material_group(
            "WA: Grup", context="grup: Pengambilan Material Curup, anggota 5"
        )
        is True
    )
    assert gs.is_pengambilan_material_group("WA: Pengambilan Curup") is True
    assert (
        gs.is_pengambilan_material_group(
            "WA: Transfer Order", group="Pengambilan Material Transfer Order"
        )
        is False
    )
    assert gs.is_pengambilan_material_group("WA: Pengambilan Material", context="Telegram") is False
    assert gs.is_pengambilan_material_group("WA: Grup Lain") is False
    assert (
        gs.is_pengambilan_material_group(
            "WA: Grup Lain", group="Pengambilan Material Subcon"
        )
        is False
    )


# ── record rows ──────────────────────────────────────────────────────────────


def _valid_source():
    return "WA: Grup Pengambilan Material"


def test_record_material_rows_rejects_empty_and_wrong_source(db):
    assert gs.record_material_rows([])["status"] == "error"
    out = gs.record_material_rows([{"item_name": "Kabel", "qty": 2}], source="Telegram")
    assert out["status"] == "error"
    out = gs.record_material_rows(
        [{"item_name": "Kabel", "qty": 2}], source="WA: Grup Lain"
    )
    assert out["status"] == "error"
    out = gs.record_material_rows([{"item_name": "-", "qty": 0}], source=_valid_source())
    assert out["status"] == "error"


def test_record_material_rows_cloud_and_local_success(db, _isolated, monkeypatch):
    svc = _FakeService()
    monkeypatch.setattr(gs, "ensure_material_sheet_tab", lambda **kwargs: {"status": "success"})
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    rows = [
        {
            "waktu": "19/11/2026",
            "no_doc": "FORM-1",
            "cluster": "Curup",
            "item_name": "Kabel Dropcore",
            "qty": 100,
            "unit": "MTR",
            "pic": "-",
            "sender": "62812@lid",
            "notes": "tarikan",
        }
    ]
    out = gs.record_material_rows(rows, source=_valid_source(), spreadsheet_id="abc1234567890XYZ")
    assert out["status"] == "success"
    assert out["cloud_synced"] is True
    assert out["local_synced"] is True
    assert out["total_items"] == 1
    assert out["local_path"].endswith("Rekap_Pengambilan_Material.xlsx")

    import openpyxl

    wb = openpyxl.load_workbook(out["local_path"])
    ws = wb["Pengambilan Material"]
    values = list(ws.values)
    assert values[0] == tuple(gs.PENGAMBILAN_HEADERS)
    assert values[1][3] == "Kabel Dropcore"
    assert "62812" in values[1][6]

    # Panggilan kedua memuat workbook yang sudah ada.
    out2 = gs.record_material_rows(rows, source=_valid_source(), spreadsheet_id="abc1234567890XYZ")
    assert out2["status"] == "success"
    assert out2["cloud_synced"] is True


def test_record_material_rows_cloud_failure_local_success(db, _isolated, monkeypatch):
    def boom():
        msg = "google mati"
        raise OSError(msg)

    monkeypatch.setattr(gs, "ensure_material_sheet_tab", lambda **kwargs: {"status": "error"})
    monkeypatch.setattr(gs, "get_sheets_service", boom)
    out = gs.record_material_rows(
        [{"item_name": "ODP", "qty": 1, "sender": "Budi"}],
        source=_valid_source(),
        spreadsheet_id="abc1234567890XYZ",
    )
    assert out["status"] == "success"
    assert out["cloud_synced"] is False
    assert "google mati" in out["cloud_error"]


def test_record_material_rows_all_targets_fail(db, _isolated, monkeypatch):
    def boom():
        msg = "google mati"
        raise OSError(msg)

    def local_boom(*args, **kwargs):
        msg = "disk penuh"
        raise OSError(msg)

    monkeypatch.setattr(gs, "ensure_material_sheet_tab", lambda **kwargs: {"status": "error"})
    monkeypatch.setattr(gs, "get_sheets_service", boom)
    monkeypatch.setattr(gs.os, "makedirs", local_boom)
    out = gs.record_material_rows(
        [{"item_name": "ODP", "qty": 1}],
        source=_valid_source(),
        spreadsheet_id="abc1234567890XYZ",
    )
    assert out["status"] == "error"
    assert out["cloud_synced"] is False
    assert out["local_synced"] is False


# ── AI parsing ───────────────────────────────────────────────────────────────


class _LLM:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents):
        self.calls.append(model)
        value = self.texts.pop(0) if self.texts else ""
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(text=value)


def _patch_llm(monkeypatch, llm, model="m"):
    from alfa.bot import config as bot_config

    monkeypatch.setattr(bot_config, "resolve_main_gemini", lambda: (llm, 1, "Gemini"))
    monkeypatch.setattr(bot_config, "_main_brain_gemini_model", lambda: model)


def test_parse_material_rejects_empty_and_wrong_source(db):
    assert gs.parse_and_record_material_text("")["status"] == "error"
    assert gs.parse_and_record_material_text("x", source="Telegram")["status"] == "error"
    assert (
        gs.parse_and_record_material_text("x", source="WA: Grup Lain")["status"]
        == "error"
    )


def test_parse_material_without_client(db, monkeypatch):
    from alfa.bot import config as bot_config
    from alfa.swarm import llm_client

    def no_config():
        msg = "tidak ada"
        raise ImportError(msg)

    def no_agent(agent):
        msg = "tidak ada"
        raise ImportError(msg)

    monkeypatch.setattr(bot_config, "resolve_main_gemini", no_config)
    monkeypatch.setattr(llm_client, "get_agent_api_client", no_agent)
    out = gs.parse_and_record_material_text("Kabel 10", source=_valid_source())
    assert out["status"] == "error"
    assert "tidak tersedia" in out["message"]


def test_parse_material_success_and_tab_names(db, monkeypatch):
    payload = json.dumps(
        [{"no_doc": "-", "cluster": "Curup", "item_name": "Kabel", "qty": 10,
          "unit": "MTR", "pic": "A", "notes": "x"}]
    )
    llm = _LLM([payload, payload, payload])
    _patch_llm(monkeypatch, llm)
    recorded = {}

    def fake_record(**kwargs):
        recorded.update(kwargs)
        return {"status": "success", "total_items": 1}

    monkeypatch.setattr(gs, "record_material_rows", fake_record)
    out = gs.parse_and_record_material_text("Kabel 10", source="WA: Pengambilan Material Curup")
    assert out["status"] == "success"
    assert recorded["tab_name"] == "Pengambilan Material Curup"
    assert out["parsed_items"][0]["item_name"] == "Kabel"

    gs.parse_and_record_material_text("Kabel 10", source="WA: Pengambilan Material Lahat")
    assert recorded["tab_name"] == "Pengambilan Material Lahat"

    gs.parse_and_record_material_text("Kabel 10", source="WA: Grup Pengambilan Material")
    assert recorded["tab_name"] == "Grup Pengambilan Material"


def test_parse_material_handles_fenced_json(db, monkeypatch):
    for fenced in (
        "```json\n[]\n```",
        "```\n[]\n```",
        "  ```json\n[]\n```  ",
    ):
        llm = _LLM([fenced])
        _patch_llm(monkeypatch, llm)
        monkeypatch.setattr(
            gs,
            "record_material_rows",
            lambda **kwargs: {"status": "success", "total_items": 0},
        )
        out = gs.parse_and_record_material_text("x", source=_valid_source())
        assert out["status"] == "success"
        assert out["parsed_items"] == []


def test_parse_material_invalid_json_and_non_list(db, monkeypatch):
    llm = _LLM(["bukan json"])
    _patch_llm(monkeypatch, llm)
    out = gs.parse_and_record_material_text("x", source=_valid_source())
    assert out["status"] == "error"
    assert "Gagal membaca" in out["message"]

    llm = _LLM(['{"bukan": "list"}'])
    _patch_llm(monkeypatch, llm)
    out = gs.parse_and_record_material_text("x", source=_valid_source())
    assert out["status"] == "error"
    assert "bukan berupa JSON array" in out["message"]


def test_parse_material_retries_next_model(db, monkeypatch):
    llm = _LLM([RuntimeError("503"), "[]"])
    _patch_llm(monkeypatch, llm)
    monkeypatch.setattr(
        gs, "record_material_rows", lambda **kwargs: {"status": "success", "total_items": 0}
    )
    out = gs.parse_and_record_material_text("x", source=_valid_source())
    assert out["status"] == "success"
    assert len(llm.calls) == 2


def test_parse_material_all_models_fail(db, monkeypatch):
    llm = _LLM([RuntimeError("503")] * 6)
    _patch_llm(monkeypatch, llm)
    out = gs.parse_and_record_material_text("x", source=_valid_source())
    assert out["status"] == "error"
    assert "Semua model AI gagal" in out["message"]


# ── auto detection ───────────────────────────────────────────────────────────


def test_sync_material_if_detected(monkeypatch):
    assert gs.sync_material_if_detected("") is None
    assert gs.sync_material_if_detected("Kabel 10", source="Telegram") is None
    assert gs.sync_material_if_detected("halo semua", source=_valid_source()) is None
    assert gs.sync_material_if_detected("pengambilan material", source=_valid_source()) is None

    monkeypatch.setattr(
        gs,
        "parse_and_record_material_text",
        lambda **kwargs: {"status": "success", "total_items": 2},
    )
    out = gs.sync_material_if_detected(
        "pengambilan material: kabel 10 mtr", source=_valid_source()
    )
    assert out["total_items"] == 2

    monkeypatch.setattr(
        gs, "parse_and_record_material_text", lambda **kwargs: {"status": "error"}
    )
    assert gs.sync_material_if_detected(
        "pengambilan material: kabel 10 mtr", source=_valid_source()
    ) is None

    def boom(**kwargs):
        msg = "api mati"
        raise OSError(msg)

    monkeypatch.setattr(gs, "parse_and_record_material_text", boom)
    assert gs.sync_material_if_detected(
        "pengambilan material: kabel 10 mtr", source=_valid_source()
    ) is None


# ── metadata, preview, listing ───────────────────────────────────────────────


def test_get_spreadsheet_metadata(monkeypatch):
    monkeypatch.setattr(gs, "get_spreadsheet_id", lambda: "")
    assert gs.get_spreadsheet_metadata()["status"] == "error"

    svc = _FakeService(
        meta={
            "properties": {"title": "Rekap", "locale": "id_ID", "timeZone": "Asia/Jakarta"},
            "sheets": [
                {
                    "properties": {
                        "sheetId": 7,
                        "title": "Pengambilan Material",
                        "index": 0,
                        "gridProperties": {"rowCount": 100, "columnCount": 9},
                    }
                }
            ],
        }
    )
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    out = gs.get_spreadsheet_metadata("abc1234567890XYZ")
    assert out["status"] == "success"
    assert out["total_tabs"] == 1
    assert out["tabs"][0]["sheet_id"] == 7
    assert out["url"].endswith("/edit")

    msg = "gagal"
    error_svc = _FakeService(error=OSError(msg))
    monkeypatch.setattr(gs, "get_sheets_service", lambda: error_svc)
    assert gs.get_spreadsheet_metadata("abc1234567890XYZ")["status"] == "error"


def test_get_tab_preview(monkeypatch):
    monkeypatch.setattr(gs, "get_spreadsheet_id", lambda: "")
    assert gs.get_tab_preview()["status"] == "error"

    monkeypatch.setattr(gs, "get_spreadsheet_id", lambda: "abc1234567890XYZ")
    monkeypatch.setattr(
        gs, "get_spreadsheet_metadata", lambda sid: {"status": "error", "message": "x"}
    )
    assert gs.get_tab_preview()["status"] == "error"

    monkeypatch.setattr(
        gs, "get_spreadsheet_metadata", lambda sid: {"status": "success", "title": "R", "tabs": []}
    )
    assert gs.get_tab_preview()["status"] == "error"

    tabs = [
        {"title": "Pengambilan Material", "sheet_id": 7},
        {"title": "Arsip", "sheet_id": 8},
    ]
    svc = _FakeService(
        rows=[list(gs.PENGAMBILAN_HEADERS), ["a"], ["b"], ["c"], ["d"]]
    )
    monkeypatch.setattr(
        gs,
        "get_spreadsheet_metadata",
        lambda sid: {"status": "success", "title": "R", "tabs": tabs},
    )
    monkeypatch.setattr(gs, "get_sheets_service", lambda: svc)
    out = gs.get_tab_preview("abc1234567890XYZ", "arsip", limit=2)
    assert out["status"] == "success"
    assert out["tab_name"] == "Arsip"
    assert out["sheet_id"] == 8
    assert out["recent_rows"] == [["c"], ["d"]]

    out = gs.get_tab_preview("abc1234567890XYZ")
    assert out["tab_name"] == "Pengambilan Material"

    msg = "gagal baca"
    error_svc = _FakeService(error=OSError(msg))
    monkeypatch.setattr(gs, "get_sheets_service", lambda: error_svc)
    assert gs.get_tab_preview("abc1234567890XYZ")["status"] == "error"


def test_list_accessible_spreadsheets(monkeypatch, _isolated):
    monkeypatch.setattr(gs, "get_spreadsheet_id", lambda: "active-id")
    monkeypatch.setattr(
        gs,
        "get_spreadsheet_metadata",
        lambda sid: {"status": "success", "title": "Aktif", "total_tabs": 2, "url": "u"},
    )
    from alfa.integrations.gdrive import auth

    class DriveFiles:
        def list(self, **kwargs):
            return _Exec(
                {
                    "files": [
                        {"id": "drive-id", "name": "Drive Sheet", "webViewLink": "v"},
                        {"id": "active-id", "name": "Duplikat"},
                    ]
                }
            )

    drive = SimpleNamespace(files=lambda: DriveFiles())
    monkeypatch.setattr(auth, "_get_gdrive_service", lambda: drive)

    ( _isolated.home / "GDrive1").mkdir(parents=True)
    (_isolated.home / "GDrive1" / "lokal.xlsx").write_bytes(b"x")
    (_isolated.home / "GDrive2").mkdir(parents=True)
    (_isolated.home / "GDrive2" / "data.csv").write_text("a", encoding="utf-8")

    rows = gs.list_accessible_spreadsheets()
    ids = [r["id"] for r in rows]
    assert "active-id" in ids
    assert "drive-id" in ids
    assert any(r.get("is_local") for r in rows)
    assert len([r for r in rows if r["id"] == "active-id"]) == 1


def test_list_accessible_spreadsheets_handles_errors(monkeypatch, _isolated):
    monkeypatch.setattr(gs, "get_spreadsheet_id", lambda: "active-id")
    monkeypatch.setattr(
        gs, "get_spreadsheet_metadata", lambda sid: {"status": "error", "message": "x"}
    )
    from alfa.integrations.gdrive import auth

    def boom():
        msg = "drive mati"
        raise OSError(msg)

    monkeypatch.setattr(auth, "_get_gdrive_service", boom)
    assert gs.list_accessible_spreadsheets() == []


# ── service factory ──────────────────────────────────────────────────────────


def test_get_sheets_service_requires_credentials(_isolated):
    with pytest.raises(ValueError, match="Kredensial"):
        gs.get_sheets_service()


def test_get_sheets_service_loads_wa_key(_isolated, monkeypatch):
    (_isolated.wa / "service-account.json").write_text(
        json.dumps({"type": "service_account"}), encoding="utf-8"
    )
    from google.oauth2 import service_account
    from googleapiclient import discovery

    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        staticmethod(lambda info, scopes: "creds"),
    )
    monkeypatch.setattr(discovery, "build", lambda *a, **k: "service")
    assert gs.get_sheets_service() == "service"


def test_get_sheets_service_skips_broken_files(_isolated, monkeypatch):
    (_isolated.wa / "service-account.json").write_text("{rusak", encoding="utf-8")
    _isolated.tmp.joinpath("gdrive_credentials.json").write_text("{rusak", encoding="utf-8")
    with pytest.raises(ValueError, match="Kredensial"):
        gs.get_sheets_service()


def test_get_sheets_service_loads_gdrive_key(_isolated, monkeypatch):
    gdrive = _isolated.tmp / "gdrive_credentials.json"
    gdrive.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    from google.oauth2 import service_account
    from googleapiclient import discovery

    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        staticmethod(lambda info, scopes: "creds"),
    )
    monkeypatch.setattr(discovery, "build", lambda *a, **k: "service2")
    assert gs.get_sheets_service() == "service2"
