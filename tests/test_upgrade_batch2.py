"""Upgrade coverage batch 2: network, visual tester, dataset analysis.

All hermetic: pure helpers, error paths, localhost-only operations, and
mocked external services. No network, no system mutation.
"""

import sys


class TestNetwork:
    def test_cert_pairs(self):
        from alfa.tools.system.network import _cert_pairs

        assert _cert_pairs([("CN", "x"), ["O", "y"], "junk", None]) == {"CN": "x", "O": "y"}
        assert _cert_pairs(None) == {}
        assert _cert_pairs([]) == {}

    def test_scan_local(self):
        from alfa.tools.system.network import scan_local_network

        res = scan_local_network()
        assert isinstance(res, dict)

    def test_audit_localhost(self):
        from alfa.tools.system.network import audit_network_security

        res = audit_network_security(target_host="127.0.0.1", scan_type="quick_ports")
        assert isinstance(res, dict)
        assert res.get("status") == "success"

    def test_download_refused(self):
        from alfa.tools.system.network import download_file_from_url

        res = download_file_from_url("http://127.0.0.1:9/nope.bin")
        assert isinstance(res, dict)
        assert res.get("status") == "error"

    def test_send_email_no_creds(self, monkeypatch):
        import smtplib

        import alfa.tools.system.network as net

        monkeypatch.delenv("SMTP_EMAIL", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)

        def boom(*a, **k):
            raise ConnectionError("offline")

        monkeypatch.setattr(smtplib, "SMTP", boom)
        res = net.send_email(to="a@b.c", subject="s", body="b")
        assert isinstance(res, dict)


class TestVisualTester:
    def test_no_engine(self, monkeypatch):
        import alfa.tools.web.visual_tester as vt

        monkeypatch.setitem(sys.modules, "camoufox.sync_api", None)
        res = vt.browser_visual_test_page("http://127.0.0.1:9/")
        assert res["status"] == "error"
        assert "Camoufox" in res["message"]


class TestDataset:
    def test_missing_file(self):
        from alfa.tools.media.documents import analyze_dataset_csv_json

        res = analyze_dataset_csv_json("/tidak/ada/data_xyz.csv")
        assert res["status"] == "error"

    def test_small_csv(self, tmp_path):
        from alfa.tools.media.documents import analyze_dataset_csv_json

        f = tmp_path / "d.csv"
        f.write_text("nama,nilai\na,10\nb,20\nc,30\n", encoding="utf-8")
        res = analyze_dataset_csv_json(str(f), x_column="nama", y_column="nilai")
        assert isinstance(res, dict)
