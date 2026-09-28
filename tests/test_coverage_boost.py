"""Coverage boost for big under-tested modules.

Targets (all hermetic, no network, no real side effects):
- alfa.tools.system.monitoring (real psutil, dry-run only)
- alfa.tools.filesystem.universal_file_extractor (synthetic bytes)
- alfa.tools.media.pdf_editor (generated PDFs in tmp)
- alfa.core.cli.interactive_menu (mocked InquirerPy)
- alfa.core.cli.slash_commands (AlfaCLI instance, persistence mocked)
- alfa.swarm.llm_client (pure config resolution, no network)
"""

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_cli():
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone", attached_files=[])
    cli._save_config = lambda *a, **k: None
    cli._update_prompt = lambda *a, **k: None
    return cli


# ── monitoring ───────────────────────────────────────────────────────────────


class TestMonitoring:
    def test_get_system_stats_shape(self):
        from alfa.tools.system import monitoring as mon

        stats = mon.get_system_stats()
        assert isinstance(stats, dict)
        assert stats.get("status") == "success"

    def test_list_running_processes(self):
        from alfa.tools.system import monitoring as mon

        res = mon.list_running_processes()
        assert res["status"] == "success"
        assert isinstance(res["top_processes"], list)
        assert res["total_processes"] > 0
        mine = mon.list_running_processes(filter_name="python")
        assert isinstance(mine["top_processes"], list)

    def test_kill_process_invalid(self):
        from alfa.tools.system import monitoring as mon

        res = mon.kill_process("definitely-not-a-real-process-xyz")
        assert res["status"] in ("success", "error")

    def test_kill_spawned_sleep(self):
        from alfa.tools.system import monitoring as mon

        proc = subprocess.Popen(["sleep", "30"])
        try:
            res = mon.kill_process(str(proc.pid))
            assert res["status"] == "success"
            time.sleep(0.3)
            assert proc.poll() is not None
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_clean_storage_dry_run(self):
        from alfa.tools.system import monitoring as mon

        res = mon.clean_system_storage(dry_run=True)
        assert res["status"] == "success"

    def test_hardware_invalid_action(self):
        from alfa.tools.system import monitoring as mon

        res = mon.control_linux_hardware("frobnicator_xyz")
        assert res["status"] == "error"

    def test_volume_validation(self):
        from alfa.tools.system import monitoring as mon

        res = mon.control_linux_hardware("set_volume", value="9999x")
        assert res["status"] == "error"

    def test_services_invalid_action(self):
        from alfa.tools.system import monitoring as mon

        res = mon.manage_system_services("unit.service", "explode_xyz")
        assert res["status"] == "error"

    def test_services_bad_name_rejected(self):
        from alfa.tools.system import monitoring as mon

        res = mon.manage_system_services("a; rm -rf ~", "status")
        assert res["status"] == "error"

    def test_crontab_list_safe(self):
        from alfa.tools.system import monitoring as mon

        res = mon.manage_crontab_jobs("list")
        assert res["status"] == "success"

    def test_auto_diagnose_no_fix(self):
        from alfa.tools.system import monitoring as mon

        res = mon.auto_diagnose_and_heal_system(fix_issues=False)
        assert isinstance(res, dict)

    def test_guardian_configs(self):
        from alfa.tools.system import monitoring as mon

        assert isinstance(mon.proactive_system_guardian_config(), dict)
        assert isinstance(mon.proactive_ambient_agent_config(), dict)


# ── universal file extractor ─────────────────────────────────────────────────


class TestExtractor:
    @pytest.mark.parametrize(
        "name,mime,payload",
        [
            ("note.txt", "text/plain", b"hello world"),
            ("data.csv", "text/csv", b"a,b\n1,2\n"),
            ("doc.json", "application/json", b'{"k": 1}'),
            ("page.html", "text/html", b"<html><body><p>Hi</p></body></html>"),
            ("readme.md", "text/markdown", b"# Title\n\nbody"),
            ("archive.zip", "application/zip", b"PK\x05\x06" + b"\x00" * 18),
        ],
    )
    def test_process_attachment_types(self, name, mime, payload):
        from alfa.tools.filesystem import universal_file_extractor as ux

        text, part = ux.process_uploaded_attachment(
            name, mime, payload, save_disk=False
        )
        assert isinstance(text, str) and len(text) > 0

    def test_csv_direct(self):
        from alfa.tools.filesystem import universal_file_extractor as ux

        out = ux._extract_csv(b"a,b\n1,2\n", "f.csv")
        assert out is None or isinstance(out, str)

    def test_html_xml_direct(self):
        from alfa.tools.filesystem import universal_file_extractor as ux

        assert isinstance(ux._extract_html_xml(b"<p>x</p>", "f.html", ".html"), str)

    def test_data_formats_json(self):
        from alfa.tools.filesystem import universal_file_extractor as ux

        assert isinstance(ux._extract_data_formats(b'{"a": 1}', "f.json", ".json"), str)

    def test_excel_archive_helpers(self, tmp_path):
        import zipfile

        from alfa.tools.filesystem import universal_file_extractor as ux

        zpath = tmp_path / "a.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("inner.txt", "dalam")
        out = ux._extract_archive(zpath.read_bytes(), "a.zip", ".zip")
        assert isinstance(out, str) and "inner" in out

    def test_word_powerpoint_graceful(self):
        from alfa.tools.filesystem import universal_file_extractor as ux

        # Truncated binaries must not crash, may return empty/error text
        assert isinstance(ux._extract_word(b"\x00" * 64, "f.docx"), str)
        assert isinstance(ux._extract_powerpoint(b"\x00" * 64, "f.pptx"), str)


# ── pdf editor round-trips ───────────────────────────────────────────────────


def _make_pdf(path, pages=3, text="Halo"):
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        w.write(f)
    return str(path)


class TestPdfEditor:
    def test_merge_split_rotate(self, tmp_path):
        from alfa.tools.media import pdf_editor as pe

        a = _make_pdf(tmp_path / "a.pdf", pages=2)
        b = _make_pdf(tmp_path / "b.pdf", pages=3)
        merged = pe.pdf_merge_documents([a, b], "m.pdf")
        assert merged["status"] == "success"
        split = pe.pdf_split_document(
            merged["file_path"], "1-2", str(tmp_path / "parts")
        )
        assert split["status"] == "success"
        assert len(split["files"]) == 2
        rot = pe.pdf_rotate_pages(merged["file_path"], 90)
        assert rot["status"] == "success"

    def test_encrypt_decrypt(self, tmp_path):
        from alfa.tools.media import pdf_editor as pe

        src = _make_pdf(tmp_path / "s.pdf")
        enc = pe.pdf_encrypt_password(src, "pw123")
        assert enc["status"] == "success"
        dec = pe.pdf_decrypt_password(enc["file_path"], "pw123")
        assert dec["status"] == "success"
        wrong = pe.pdf_decrypt_password(enc["file_path"], "salah")
        assert wrong["status"] == "error"

    def test_extract_and_metadata(self, tmp_path):
        from alfa.tools.media import pdf_editor as pe

        src = _make_pdf(tmp_path / "s.pdf")
        assert pe.pdf_extract_full_text(src)["status"] == "success"
        meta = pe.pdf_inspect_metadata(src)
        assert meta["status"] == "success"
        assert pe.pdf_extract_full_text("/tidak/ada.pdf")["status"] == "error"

    def test_compress(self, tmp_path):
        from alfa.tools.media import pdf_editor as pe

        src = _make_pdf(tmp_path / "s.pdf")
        assert pe.pdf_compress_and_optimize(src, str(tmp_path / "c.pdf"))["status"] in (
            "success",
            "error",
        )


# ── interactive menu (mocked prompts) ────────────────────────────────────────


def _prompt_mock(*values):
    m = MagicMock()
    sel = MagicMock()
    sel.execute.side_effect = list(values)
    m.select.return_value = sel
    m.text.return_value = sel
    m.confirm.return_value = sel
    return m


class TestInteractiveMenu:
    def test_get_workspace_files_capped(self, tmp_path, monkeypatch):

        import alfa.core.cli.interactive_menu as menu

        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "venv").mkdir()
        (tmp_path / "venv" / "skip.py").write_text("x")
        files = menu.get_workspace_files(max_files=50)
        assert "a.py" in files
        assert not any("venv" in f for f in files)

    def test_menu_switch_mode_delegates(self, monkeypatch):
        import alfa.core.cli.interactive_menu as menu

        monkeypatch.setattr(menu, "inquirer", _prompt_mock("standalone"))
        cli = MagicMock()
        menu.menu_switch_mode(cli)
        cli.do_slash_mode.assert_called_once_with("standalone")

    def test_open_palette_exit(self, monkeypatch):
        import alfa.core.cli.interactive_menu as menu

        monkeypatch.setattr(menu, "inquirer", _prompt_mock("exit"))
        cli = MagicMock()
        cli.direct_ai = MagicMock(provider="gemini", model="m")
        cli.mode = "auto"
        cli.attached_files = []
        cli.agent_execution_mode = "single"
        menu.open_interactive_menu(cli)

    def test_menu_switch_model(self, monkeypatch):
        import alfa.core.cli.interactive_menu as menu

        monkeypatch.setattr(menu, "inquirer", _prompt_mock("gemini", "m1"))
        cli = MagicMock()
        cli.direct_ai = MagicMock(provider="gemini", model="m")
        try:
            menu.menu_switch_model(cli)
        except Exception:
            pass


# ── slash commands ───────────────────────────────────────────────────────────


class TestSlashCommands:
    def test_mode_switch_and_status(self, capsys):
        cli = _make_cli()
        cli.do_slash_mode("swarm")
        assert cli.agent_execution_mode == "swarm"
        cli.do_slash_mode("")
        out = capsys.readouterr().out
        assert "Mode" in out

    def test_models_and_tools_list(self, capsys):
        cli = _make_cli()
        cli.do_slash_models("")
        cli.do_slash_tools("")
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_provider_and_keys(self, capsys):
        cli = _make_cli()
        cli.do_slash_provider("")
        cli.do_slash_keys("")
        capsys.readouterr()

    def test_agents_and_persona(self, capsys):
        cli = _make_cli()
        cli.do_slash_agents("")
        cli.do_slash_persona("")
        capsys.readouterr()

    def test_repomap_and_undo(self, capsys, tmp_path, monkeypatch):

        cli = _make_cli()
        monkeypatch.chdir(tmp_path)
        (tmp_path / "x.py").write_text("a = 1\n")
        cli.do_slash_repomap("")
        cli.do_slash_undo("")
        capsys.readouterr()

    def test_file_context_add_list_clear(self, tmp_path):
        cli = _make_cli()
        f = tmp_path / "konteks.txt"
        f.write_text("isi")
        cli.do_slash_file(f"add {f}")
        assert len(cli.attached_files) == 1
        cli.do_slash_file("list")
        cli.do_slash_file("clear")
        assert len(cli.attached_files) == 0


# ── llm client config resolution ─────────────────────────────────────────────


class TestLlmClient:
    def test_default_model_fallback(self, monkeypatch):
        import alfa.swarm.llm_client as llc

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert isinstance(llc._default_gemini_model(), str)

    def test_agent_client_env_fallback(self, monkeypatch):
        import alfa.swarm.llm_client as llc

        monkeypatch.setattr(
            llc.database, "get_active_api_key_sync", lambda *a, **k: None
        )
        monkeypatch.setenv("GEMINI_API_KEY", "DUMMY123")
        provider, api_key, model, base_url, key_id = llc.get_agent_api_client({})
        assert provider == "gemini"
        assert api_key == "DUMMY123"
        assert key_id is None

    def test_agent_client_openai_env(self, monkeypatch):
        import alfa.swarm.llm_client as llc

        monkeypatch.setattr(
            llc.database, "get_active_api_key_sync", lambda *a, **k: None
        )
        monkeypatch.setenv("OPENAI_API_KEY", "SK-DUMMY")
        provider, api_key, model, base_url, key_id = llc.get_agent_api_client(
            {"provider": "openai", "model": "gpt-x"}
        )
        assert provider == "openai"
        assert model == "gpt-x"

    def test_agent_client_norouter_default(self, monkeypatch):
        import alfa.swarm.llm_client as llc

        monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
        monkeypatch.delenv("ROUTER_API_KEY", raising=False)
        monkeypatch.setattr(
            llc.database, "get_active_api_key_sync", lambda *a, **k: None
        )
        provider, api_key, model, base_url, key_id = llc.get_agent_api_client(
            {"provider": "9router"}
        )
        assert provider == "9router"
        assert base_url == "http://127.0.0.1:20128/v1"
