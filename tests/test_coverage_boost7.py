"""Coverage batch 7: antigravity_login (OAuth device-flow + instance mgmt).

Hermetic: urlopen/subprocess/shutil.which di-mock, BASE diarahkan ke tmp.
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def ag(tmp_path, monkeypatch):
    """Import module with BASE redirected into tmp, isolated pending state."""
    import alfa.integrations.antigravity_login as agl

    monkeypatch.setattr(agl, "BASE", str(tmp_path))
    monkeypatch.setattr(agl, "_pending", {})
    monkeypatch.setattr(agl, "_pending_lock", __import__("threading").Lock())
    return agl


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ── instance registry ────────────────────────────────────────────────────────


class TestInstanceRegistry:
    def test_load_missing_returns_empty(self, ag):
        assert ag._load_instances() == {}

    def test_load_corrupt_returns_empty(self, ag):
        p = Path(ag._instances_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{{{bukan json", encoding="utf-8")
        assert ag._load_instances() == {}

    def test_load_non_dict_returns_empty(self, ag):
        p = Path(ag._instances_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[1,2,3]", encoding="utf-8")
        assert ag._load_instances() == {}

    def test_save_then_load_roundtrip(self, ag):
        payload = {"instances": {"a": {"port": 8888}}}
        ag._save_instances(payload)
        assert ag._load_instances() == payload

    def test_next_free_port_skips_used(self, ag):
        # 8877 is always reserved; no instances -> 8878
        assert ag.next_free_instance_port() == 8878
        ag._save_instances({"instances": {"x": {"port": 8878}, "y": {"port": 8879}}})
        assert ag.next_free_instance_port() == 8880

    def test_next_free_port_tolerates_bad_entry(self, ag):
        ag._save_instances({"instances": {"bad": {"port": "bukan-angka"}}})
        assert ag.next_free_instance_port() == 8878

    def test_list_accounts_empty(self, ag):
        assert ag.list_accounts() == []

    def test_list_accounts_reads_email(self, ag):
        acc = Path(ag.BASE) / "accounts" / "user1"
        acc.mkdir(parents=True)
        (acc / "antigravity-oauth-token").write_text(
            json.dumps({"email": "a@b.c"}), encoding="utf-8"
        )
        # account without token file
        (Path(ag.BASE) / "accounts" / "user2").mkdir(parents=True)
        ag._save_instances({"instances": {"user1": {"port": 8888}}})
        rows = {r["name"]: r for r in ag.list_accounts()}
        assert rows["user1"]["email"] == "a@b.c"
        assert rows["user1"]["port"] == 8888
        assert rows["user2"]["email"] == ""


# ── token helpers ────────────────────────────────────────────────────────────


class TestTokenHelpers:
    def test_rfc3339_shape(self, ag):
        out = ag._rfc3339_in(3600)
        assert out.endswith("Z") and "T" in out
        # must parse back as a real timestamp
        assert datetime.strptime(out, "%Y-%m-%dT%H:%M:%S.%fZ")

    def test_rfc3339_is_future(self, ag):
        out = ag._rfc3339_in(600)
        parsed = datetime.strptime(out, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        assert (parsed - datetime.now(timezone.utc)).total_seconds() > 500

    def test_exchange_code_success(self, ag, monkeypatch):
        seen = {}

        def _fake_urlopen(req, timeout=30):
            seen["url"] = req.full_url
            seen["body"] = req.data
            return _Resp({"access_token": "AT", "refresh_token": "RT"})

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        out = ag._exchange_code("CODE123", "http://localhost:8899/callback")
        assert out["access_token"] == "AT"
        assert out["refresh_token"] == "RT"
        assert out["token_type"] == "Bearer"
        assert b"CODE123" in seen["body"]

    def test_exchange_code_defaults(self, ag, monkeypatch):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda r, timeout=30: _Resp({"access_token": "A"}),
        )
        out = ag._exchange_code("C", "http://x")
        assert out["refresh_token"] == ""
        assert out["token_type"] == "Bearer"

    def test_exchange_code_without_token_raises(self, ag, monkeypatch):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda r, timeout=30: _Resp({"error": "bad"})
        )
        with pytest.raises(RuntimeError, match="Token exchange gagal"):
            ag._exchange_code("C", "http://x")

    def test_fetch_email_success(self, ag, monkeypatch):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda r, timeout=15: _Resp({"email": "u@x.io"})
        )
        assert ag._fetch_email("AT") == "u@x.io"

    def test_fetch_email_failure_returns_empty(self, ag, monkeypatch):
        def _boom(req, timeout=15):
            raise OSError("jaringan mati")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        assert ag._fetch_email("AT") == ""


# ── systemd unit registration ────────────────────────────────────────────────


class TestSystemdUnits:
    def test_register_skipped_without_systemd(self, ag, monkeypatch):
        monkeypatch.setattr(ag.shutil, "which", lambda n: None)
        ag._register_instance("acc", "/home/u", 8888)  # no-op, must not raise

    def test_register_writes_unit_and_enables(self, ag, monkeypatch, tmp_path):
        monkeypatch.setattr(ag.shutil, "which", lambda n: "/usr/bin/systemctl")
        calls = []
        monkeypatch.setattr(
            ag.subprocess, "run", lambda *a, **k: calls.append(a) or MagicMock()
        )
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        unit_dir = tmp_path / "home" / ".config" / "systemd" / "user"
        ag._register_instance("acc", "/home/u", 8888)
        units = list(unit_dir.glob("antigravity-proxy-*.service"))
        assert units, "unit file harus ditulis"
        body = units[0].read_text()
        assert "--port 8888" in body
        assert "Environment=HOME=/home/u" in body
        # daemon-reload + enable --now
        assert any("daemon-reload" in str(c) for c in calls)
        assert any("enable" in str(c) for c in calls)

    def test_unregister_is_safe_when_missing(self, ag, monkeypatch, tmp_path):
        monkeypatch.setattr(ag.shutil, "which", lambda n: None)
        ag._unregister_instance("acc")  # no systemd -> early return

    def test_unregister_removes_unit(self, ag, monkeypatch, tmp_path):
        monkeypatch.setattr(ag.shutil, "which", lambda n: "/usr/bin/systemctl")
        monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: MagicMock())
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        unit_dir = tmp_path / "home" / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit = unit_dir / "antigravity-proxy-acc.service"
        unit.write_text("x", encoding="utf-8")
        ag._unregister_instance("acc")
        assert not unit.exists()


# ── login session state machine ─────────────────────────────────────────────


class TestLoginState:
    def test_login_status_idle(self, ag):
        assert ag.login_status("nobody") == {"status": "idle"}

    def test_login_status_reflects_pending(self, ag):
        ag._pending[("acc")] = {"status": "waiting", "email": "", "error": ""}
        assert ag.login_status("acc")["status"] == "waiting"

    def test_login_status_normalises_case(self, ag):
        ag._pending[("acc")] = {"status": "waiting"}
        assert ag.login_status("  ACC  ")["status"] == "waiting"

    def test_start_login_rejects_bad_name(self, ag):
        out = ag.start_login("Bad Name!")
        assert out["status"] == "error"
        assert "huruf kecil" in out["message"]

    def test_start_login_rejects_empty(self, ag):
        assert ag.start_login("")["status"] == "error"

    def test_start_login_builds_auth_url(self, ag, monkeypatch):
        started = {}

        def _fake_thread(target=None, args=(), kwargs=None, daemon=None):
            started["called"] = True

            def _noop(*a, **k):
                return None

            return MagicMock(target=_noop, start=lambda: None)

        monkeypatch.setattr(ag.threading, "Thread", _fake_thread)
        out = ag.start_login("myacc")
        assert out["status"] == "success"
        assert out["name"] == "myacc"
        assert "accounts.google.com" in out["auth_url"]
        assert "access_type=offline" in out["auth_url"]
        assert started.get("called") is True
        # the session is recorded as waiting until the browser callback lands
        assert ag.login_status("myacc")["status"] == "waiting"

    def test_start_login_blocks_concurrent(self, ag, monkeypatch):
        ag._pending[("other")] = {"status": "waiting"}
        out = ag.start_login("myacc")
        assert out["status"] == "error"
        assert "berjalan" in out["message"]


# ── account removal ─────────────────────────────────────────────────────────


class TestRemoveAccount:
    def test_remove_requires_name(self, ag):
        assert ag.remove_account("  ")["status"] == "error"

    def test_remove_deletes_dirs_and_entry(self, ag, monkeypatch):
        monkeypatch.setattr(ag, "_unregister_instance", lambda n: None)
        acc = Path(ag.BASE) / "accounts" / "acc"
        acc.mkdir(parents=True)
        home = Path(ag.BASE) / "home_acc"
        home.mkdir(parents=True)
        ag._save_instances({"instances": {"acc": {"port": 8888}}})
        out = ag.remove_account("ACC")
        assert out["status"] == "success"
        assert out["removed"] == 2
        assert not acc.exists() and not home.exists()
        assert "acc" not in ag._load_instances().get("instances", {})

    def test_remove_unknown_is_still_success(self, ag, monkeypatch):
        monkeypatch.setattr(ag, "_unregister_instance", lambda n: None)
        out = ag.remove_account("ghost")
        assert out["status"] == "success"
        assert out["removed"] == 0
