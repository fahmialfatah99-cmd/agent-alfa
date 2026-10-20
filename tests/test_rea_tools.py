"""Unit tests for REA (Reverse Engineer Anything) tools integration."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from alfa.tools.system.reverse_engineering import (
    _run_rea_command,
    rea_inspect_android_package,
    rea_inspect_binary_or_wasm,
    rea_inspect_js_app,
    rea_inspect_sqlite_database,
    rea_recover_js_sources,
    rea_run_command,
)


def test_run_rea_command_file_not_found(monkeypatch):
    monkeypatch.setattr(
        "alfa.tools.system.reverse_engineering._REA_EXECUTABLE",
        "/path/that/does/not/exist/rea",
    )
    res = _run_rea_command(["test"])
    assert res["status"] == "error"
    assert "tidak ditemukan" in res["message"]


def test_run_rea_command_timeout(monkeypatch):
    def mock_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="rea", timeout=5)

    monkeypatch.setattr(subprocess, "run", mock_run)
    res = _run_rea_command(["test"])
    assert res["status"] == "error"
    assert "melebihi batas waktu" in res["message"]


def test_run_rea_command_non_zero_exit(monkeypatch):
    mock_proc = MagicMock(returncode=1, stdout="", stderr="Error: target not found")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)
    res = _run_rea_command(["test"])
    assert res["status"] == "error"
    assert res["returncode"] == 1
    assert "Error: target not found" in res["error"]


def test_run_rea_command_success_json(monkeypatch):
    payload = {
        "operation": "inspect_sqlite_database",
        "confidence": "observed",
        "normalized_result": {"schema": {"tables": [{"name": "users"}]}},
        "raw_result": None,
        "limitations": [],
    }
    mock_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)
    res = _run_rea_command(["inspect-sqlite-database", "dummy.db"])
    assert res["status"] == "success"
    assert res["operation"] == "inspect_sqlite_database"
    assert "schema" in res["normalized"]


def test_rea_inspect_android_package(tmp_path, monkeypatch):
    apk_file = tmp_path / "app.apk"
    apk_file.write_bytes(b"PK\x03\x04mock")

    # Missing file
    res_missing = rea_inspect_android_package(str(tmp_path / "absent.apk"))
    assert res_missing["status"] == "error"

    # Present file
    with patch(
        "alfa.tools.system.reverse_engineering._run_rea_command",
        return_value={"status": "success", "package": "com.example.app"},
    ) as mock_cmd:
        res = rea_inspect_android_package(str(apk_file))
        assert res["status"] == "success"
        mock_cmd.assert_called_once()


def test_rea_inspect_js_app(tmp_path):
    asar_file = tmp_path / "app.asar"
    asar_file.write_bytes(b"mock_asar")

    res_missing = rea_inspect_js_app(str(tmp_path / "missing.asar"))
    assert res_missing["status"] == "error"

    with patch(
        "alfa.tools.system.reverse_engineering._run_rea_command",
        return_value={"status": "success", "graph": {}},
    ):
        res = rea_inspect_js_app(str(asar_file))
        assert res["status"] == "success"


def test_rea_recover_js_sources(tmp_path):
    bundle_file = tmp_path / "bundle.js"
    bundle_file.write_text("console.log('hi');")
    out_dir = str(tmp_path / "out_src")

    res_missing = rea_recover_js_sources(str(tmp_path / "missing.js"))
    assert res_missing["status"] == "error"

    with patch(
        "alfa.tools.system.reverse_engineering._run_rea_command",
        return_value={"status": "success", "files": 5},
    ):
        res = rea_recover_js_sources(str(bundle_file), output_dir=out_dir)
        assert res["status"] == "success"


def test_rea_inspect_sqlite_database(tmp_path):
    db_file = tmp_path / "test.db"
    db_file.write_bytes(b"SQLite format 3\x00")

    res_missing = rea_inspect_sqlite_database(str(tmp_path / "missing.db"))
    assert res_missing["status"] == "error"

    with patch(
        "alfa.tools.system.reverse_engineering._run_rea_command",
        return_value={"status": "success", "schema": {}},
    ) as mock_cmd:
        res = rea_inspect_sqlite_database(str(db_file), table="users", row_limit=10)
        assert res["status"] == "success"
        call_args = mock_cmd.call_args[0][0]
        assert "--table" in call_args
        assert "users" in call_args


def test_rea_inspect_binary_or_wasm(tmp_path):
    wasm_file = tmp_path / "test.wasm"
    wasm_file.write_bytes(b"\x00asm")
    bin_file = tmp_path / "test.so"
    bin_file.write_bytes(b"\x7fELF")

    with patch(
        "alfa.tools.system.reverse_engineering._run_rea_command",
        return_value={"status": "success"},
    ) as mock_cmd:
        res_wasm = rea_inspect_binary_or_wasm(str(wasm_file))
        assert res_wasm["status"] == "success"
        assert "inspect-wasm-artifact" in mock_cmd.call_args_list[0][0][0]

        res_bin = rea_inspect_binary_or_wasm(str(bin_file))
        assert res_bin["status"] == "success"
        call_args = mock_cmd.call_args_list[1][0][0]
        assert "inspect-with-objdump" in call_args
        assert "file_headers" in call_args


def test_rea_run_command_validation():
    # Empty or invalid subcommand
    assert rea_run_command("")["status"] == "error"
    assert rea_run_command("-invalid")["status"] == "error"

    with patch(
        "alfa.tools.system.reverse_engineering._run_rea_command",
        return_value={"status": "success"},
    ) as mock_cmd:
        res = rea_run_command("instructions", args_json='["--target", "main"]')
        assert res["status"] == "success"
        call_args = mock_cmd.call_args[0][0]
        assert call_args == ["instructions", "--target", "main"]
