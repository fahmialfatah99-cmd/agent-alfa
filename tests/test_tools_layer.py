"""Tool layer yang belum teruji: situs, manajemen, PDF builder, scraper, CLI chat.

Modul-modul ini adalah lapisan "plumbing" yang jarang disentuh test, padahal
banyak berisi keputusan penting (deteksi stack, pemilihan folder frontend,
penjadwalan task, pembuatan PDF, parsing hasil scrape).
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Deteksi stack & registry situs ───────────────────────────────────────────


class TestSiteStackDetection:
    def test_deteksi_backend_fastapi(self, tmp_path):
        from alfa.tools.system.sites import _detect_stack

        (tmp_path / "app.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
        )
        info = _detect_stack(str(tmp_path))
        assert info["has_backend"] is True

    def test_deteksi_frontend_next(self, tmp_path):
        from alfa.tools.system.sites import _detect_stack

        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"next": "14.0.0"}}), encoding="utf-8"
        )
        info = _detect_stack(str(tmp_path))
        assert info["has_frontend"] is True

    def test_deteksi_php_artisan(self, tmp_path):
        from alfa.tools.system.sites import _detect_stack

        (tmp_path / "artisan").write_text("#!/usr/bin/env php", encoding="utf-8")
        info = _detect_stack(str(tmp_path))
        assert info["has_php"] is True

    def test_deteksi_static_dari_html(self, tmp_path):
        from alfa.tools.system.sites import _detect_stack

        (tmp_path / "index.html").write_text(
            "<html><head><title>Judul Situs</title></head></html>", encoding="utf-8"
        )
        info = _detect_stack(str(tmp_path))
        assert info["has_static"] is True
        assert info["title"] == "Judul Situs"

    def test_folder_kosong(self, tmp_path):
        from alfa.tools.system.sites import _detect_stack

        info = _detect_stack(str(tmp_path))
        assert info["has_backend"] is False
        assert info["has_frontend"] is False

    def test_pick_frontend_dir_memilih_next(self, tmp_path):
        from alfa.tools.system.sites import _pick_frontend_dir

        fe = tmp_path / "frontend"
        fe.mkdir()
        (fe / "package.json").write_text(
            json.dumps({"dependencies": {"next": "14"}, "scripts": {"start": "next start"}}),
            encoding="utf-8",
        )
        assert _pick_frontend_dir(str(tmp_path)) == str(fe)

    def test_pick_frontend_dir_fallback(self, tmp_path):
        from alfa.tools.system.sites import _pick_frontend_dir

        assert _pick_frontend_dir(str(tmp_path)) == str(tmp_path)

    def test_free_port_melewati_yang_terpakai(self):
        from alfa.tools.system.sites import _free_port

        port = _free_port(8000, {8000, 8001})
        assert port not in (8000, 8001)

    def test_registry_load_save(self, tmp_path, monkeypatch):
        from alfa.tools.system import sites

        reg_file = tmp_path / "sites.json"
        monkeypatch.setattr(sites, "REGISTRY_FILE", str(reg_file))
        monkeypatch.setattr(sites, "STATE_DIR", str(tmp_path))
        sites._save_registry({"a": {"slug": "a"}})
        assert reg_file.exists()
        assert "a" in sites._load_registry()

    def test_registry_rusak_tidak_crash(self, tmp_path, monkeypatch):
        from alfa.tools.system import sites

        bad = tmp_path / "sites.json"
        bad.write_text("{rusak", encoding="utf-8")
        monkeypatch.setattr(sites, "REGISTRY_FILE", str(bad))
        monkeypatch.setattr(sites, "STATE_DIR", str(tmp_path))
        assert isinstance(sites._load_registry(), dict)

    def test_stop_site_slug_tak_dikenal(self, monkeypatch):
        from alfa.tools.system import sites

        monkeypatch.setattr(sites, "_load_registry", lambda: {})
        res = sites.stop_site("tidak-ada")
        assert res.get("status") == "error"

    def test_site_status_kosong(self, monkeypatch):
        from alfa.tools.system import sites

        monkeypatch.setattr(sites, "refresh_registry", lambda: {})
        assert sites.site_status() == []


# ── Manajemen: recurring task, API key, plugin dinamis ───────────────────────


class TestManagement:
    def test_add_recurring_task(self, monkeypatch):
        from alfa.tools import system as _sys  # noqa: F401
        from alfa.tools.system import management

        captured = {}

        def _fake_add(**kwargs):
            captured.update(kwargs)
            return 7

        import alfa.core.database as database

        monkeypatch.setattr(database, "add_cron_job_sync", _fake_add)
        res = management.add_recurring_task("Judul", "instruksi", 30, "single")
        assert res["status"] == "success"
        assert res["job_id"] == 7
        assert captured["interval_minutes"] == 30

    def test_add_recurring_task_interval_dibatasi(self, monkeypatch):
        from alfa.tools.system import management

        captured = {}

        def _fake_add(**kwargs):
            captured.update(kwargs)
            return 1

        import alfa.core.database as database

        monkeypatch.setattr(database, "add_cron_job_sync", _fake_add)
        management.add_recurring_task("J", "i", 0, "single")
        assert captured["interval_minutes"] == 1

    def test_list_recurring_tasks(self, monkeypatch):
        import alfa.core.database as database
        from alfa.tools.system import management

        monkeypatch.setattr(
            database, "list_cron_jobs_sync", lambda uid: [{"id": 1, "title": "J"}]
        )
        res = management.list_recurring_tasks()
        assert res["status"] == "success"
        assert res["total_jobs"] == 1
        assert res["tasks"][0]["id"] == 1

    def test_cancel_recurring_task_tak_ada(self, monkeypatch):
        import alfa.core.database as database
        from alfa.tools.system import management

        monkeypatch.setattr(database, "delete_cron_job_sync", lambda jid: False)
        res = management.cancel_recurring_task(999)
        assert res["status"] == "error"

    def test_manage_api_keys_validasi_action(self, monkeypatch):
        from alfa.tools.system import management

        res = management.manage_api_keys("aksi-ngawur")
        assert res["status"] == "error"

    def test_manage_api_keys_tanpa_api_key_ditolak(self, monkeypatch):
        from alfa.tools.system import management

        res = management.manage_api_keys(
            "add", name="Nameless", provider="gemini", api_key=""
        )
        assert res["status"] == "error"
        assert "api_key" in res.get("message", "")

    def test_manage_api_keys_activate_tanpa_key_id_ditolak(self):
        from alfa.tools.system import management

        res = management.manage_api_keys("activate")
        assert res["status"] == "error"

    def test_manage_api_keys_delete_tanpa_key_id_ditolak(self):
        from alfa.tools.system import management

        res = management.manage_api_keys("delete")
        assert res["status"] == "error"

    def test_list_dynamic_plugins(self, monkeypatch):
        from alfa.tools.system import management

        res = management.list_dynamic_plugins()
        assert res["status"] == "success"
        assert "plugins" in res

    def test_delete_dynamic_plugin_tak_ada(self, monkeypatch):
        from alfa.tools.system import management

        res = management.delete_dynamic_plugin("plugin-hantu-xyz")
        assert res["status"] in ("error", "success")

    def test_check_subagent_status_tak_ada(self, monkeypatch):
        from alfa.tools.system import management

        res = management.check_subagent_status("tidak-ada")
        assert res["status"] == "error"

    def test_query_token_usage(self, monkeypatch):
        from alfa.tools.system import management

        res = management.query_token_usage(24)
        assert res["status"] == "success"
        assert "per_key" in res
        assert "window_hours" in res


# ── PDF builder ──────────────────────────────────────────────────────────────


class TestPdfBuilder:
    def test_output_dir_dibuat(self, tmp_path, monkeypatch):
        from alfa.tools.media import pdf_builder

        monkeypatch.setenv("HOME", str(tmp_path))
        out = pdf_builder.get_pdf_output_dir("Laporan")
        assert os.path.isdir(out)
        assert "ALFA_PDF_TOOLS" in out

    def test_generate_pdf_report_tanpa_isi(self, tmp_path, monkeypatch):
        from alfa.tools.media import pdf_builder

        monkeypatch.setenv("HOME", str(tmp_path))
        res = pdf_builder.generate_pdf_report("Judul", "")
        assert res["status"] in ("error", "success")
        if res["status"] == "error":
            assert "kosong" in (res.get("message") or "").lower()

    def test_apply_watermark_file_tidak_ada(self, tmp_path, monkeypatch):
        from alfa.tools.media import pdf_builder

        monkeypatch.setenv("HOME", str(tmp_path))
        res = pdf_builder.pdf_apply_watermark_text(
            str(tmp_path / "hilang.pdf"), "TEXAS"
        )
        assert res["status"] == "error"

    def test_insert_page_numbers_file_tidak_ada(self, tmp_path, monkeypatch):
        from alfa.tools.media import pdf_builder

        monkeypatch.setenv("HOME", str(tmp_path))
        res = pdf_builder.pdf_insert_page_numbers(str(tmp_path / "hilang.pdf"))
        assert res["status"] == "error"

    def test_images_convert_to_pdf_tanpa_gambar(self, tmp_path, monkeypatch):
        from alfa.tools.media import pdf_builder

        monkeypatch.setenv("HOME", str(tmp_path))
        res = pdf_builder.images_convert_to_pdf([])
        assert res["status"] == "error"

    def test_convert_to_images_file_tidak_ada(self, tmp_path, monkeypatch):
        from alfa.tools.media import pdf_builder

        monkeypatch.setenv("HOME", str(tmp_path))
        res = pdf_builder.pdf_convert_to_images(str(tmp_path / "hilang.pdf"))
        assert res["status"] == "error"


# ── Scraper: parsing hasil ───────────────────────────────────────────────────


class TestFastScraperParsing:
    def test_attr_str_menangani_none(self):
        from alfa.scrapers.fast import _attr_str

        assert _attr_str(None) == ""
        assert _attr_str("teks") == "teks"
        assert _attr_str(123) == ""

    def test_extract_product_fields_dari_soup(self):
        bs4 = pytest.importorskip("bs4")
        from alfa.scrapers.fast import extract_product_fields_from_soup

        html = """
        <div class="product">
          <h1 class="title">Produk Bagus</h1>
          <span class="price">Rp150.000</span>
          <a class="link" href="https://tokopedia.com/p/1">link</a>
        </div>
        """
        soup = bs4.BeautifulSoup(html, "html.parser")
        out = extract_product_fields_from_soup(soup, "https://tokopedia.com/p/1")
        assert isinstance(out, dict)

    def test_run_batch_scrape_dengan_url_tidak_valid(self, monkeypatch):
        from alfa.scrapers import fast

        monkeypatch.setattr(
            fast, "scrape_with_fast_tls", lambda url: {"status": "error", "error": "x"}
        )
        res = fast.run_batch_scrape(["https://contoh.test/a"])
        assert isinstance(res, dict)


# ── CLI chat ─────────────────────────────────────────────────────────────────


class TestCliChat:
    def test_deteksi_tool_call(self):
        from alfa.core.cli.chat import _contains_tool_call

        assert _contains_tool_call('{"tool": "x"}') is True
        assert _contains_tool_call("teks biasa") is False
        assert _contains_tool_call("```tool_call\n{}") is True
        assert _contains_tool_call("") is False
