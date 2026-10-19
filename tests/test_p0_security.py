"""Regresi keamanan P0 — gard yang sebelumnya bisa dilewati.

Tiap kelas di file ini memverifikasi satu item P0 dari audit keamanan:
sandbox containment, fail-closed python sandbox, trust per-tier, risk tier
default, deny-by-default approval gate, dashboard auth fail-closed, dan
API keamanan `alfa.security` yang sebelumnya hanya stub.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_GATE_BOOM_MSG = "gate meledak"


# ── P0-1: sandbox working_dir containment ────────────────────────────────────


class TestSandboxContainment:
    def test_working_dir_root_ditolak(self, tmp_path, monkeypatch):
        """Regresi: working_dir='/' → mount `-v /:/workspace -v /:/`."""
        from alfa.tools.system.constants import resolve_sandbox_working_dir

        monkeypatch.setenv("ALFA_SANDBOX_ROOT", str(tmp_path))
        for bad in ("/", "/etc", "/usr", "/root"):
            path, err = resolve_sandbox_working_dir(bad)
            assert path == "", bad
            assert err, bad

    def test_working_dir_di_dalam_root_diterima(self, tmp_path, monkeypatch):
        from alfa.tools.system.constants import resolve_sandbox_working_dir

        monkeypatch.setenv("ALFA_SANDBOX_ROOT", str(tmp_path))
        sub = tmp_path / "proj"
        sub.mkdir()
        path, err = resolve_sandbox_working_dir(str(sub))
        assert err == ""
        assert path == os.path.realpath(str(sub))

    def test_path_prefix_sibling_bukan_contained(self, tmp_path, monkeypatch):
        """/tmp/root2 bukan bagian dari /tmp/root (bug prefix matching)."""
        from alfa.tools.system.constants import resolve_sandbox_working_dir

        root = tmp_path / "root"
        sibling = tmp_path / "root2"
        root.mkdir()
        sibling.mkdir()
        monkeypatch.setenv("ALFA_SANDBOX_ROOT", str(root))
        path, err = resolve_sandbox_working_dir(str(sibling))
        assert path == ""
        assert err

    def test_home_tidak_boleh_jadi_root(self, monkeypatch):
        """Root yang memuat $HOME membocorkan ~/.ssh & ~/.env."""
        from alfa.tools.system.constants import sandbox_allowed_roots

        monkeypatch.setenv("ALFA_SANDBOX_ROOT", os.path.expanduser("~"))
        roots = sandbox_allowed_roots()
        assert os.path.realpath(os.path.expanduser("~")) not in roots
        assert "/" not in roots

    def test_tidak_ada_mount_host_path_ke_root(self, tmp_path, monkeypatch):
        """Command docker tidak boleh mem-mount host path di luar root."""
        from alfa.tools.system import execution as ex

        captured: dict = {}

        class _FakeSub:
            @staticmethod
            def run(cmd, **kwargs):  # noqa: ANN001, ANN003
                captured["cmd"] = cmd
                raise SystemExit(0)  # stop sebelum eksekusi sungguhan

        monkeypatch.setattr(ex, "_get_subprocess", lambda: _FakeSub)
        monkeypatch.setattr(ex, "_check_docker_available", lambda: True)
        monkeypatch.setattr(ex, "_ensure_sandbox_image", lambda: True)
        monkeypatch.setenv("ALFA_SANDBOX_ROOT", str(tmp_path))
        monkeypatch.setenv("ALFA_UNRESTRICTED", "false")
        monkeypatch.setenv("ALFA_BASH_BACKEND", "docker")

        try:
            ex.execute_bash_command("echo hi", working_dir=str(tmp_path))
        except SystemExit:
            pass

        cmd = captured.get("cmd") or []
        from alfa.tools.system.constants import SANDBOX_DIR, sandbox_allowed_roots

        allowed = {SANDBOX_DIR, *sandbox_allowed_roots()}
        for i, arg in enumerate(cmd):
            if arg == "-v" and i + 1 < len(cmd):
                src = cmd[i + 1].split(":")[0]
                assert src in allowed or src.startswith(str(tmp_path)), cmd
                # Tidak boleh ada mount `host:host` (path host yang sama
                # di dalam container) — itulah vektor escape-nya.
                assert cmd[i + 1].count(":") >= 1
                src_path, _, dst_path = cmd[i + 1].partition(":")
                if src_path == dst_path:
                    assert src_path.startswith(str(tmp_path)), cmd


# ── P0-2: python sandbox fail-closed ────────────────────────────────────────


class TestPythonSandboxFailClosed:
    def test_tanpa_docker_tidak_jatuh_ke_host(self, monkeypatch):
        """Regresi: execute_python_sandbox diam-diam jalan di host."""
        from alfa.tools.system import execution as ex

        monkeypatch.setattr(ex, "_check_docker_available", lambda: False)
        monkeypatch.setattr(ex, "is_unrestricted", lambda: False)
        monkeypatch.setenv("ALFA_UNRESTRICTED", "false")
        monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "false")
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")

        res = ex.execute_python_sandbox("print('halo')")
        assert res["status"] == "error"
        assert res["isolation"] == "blocked"
        assert "diblokir" in (res.get("stderr") or "").lower()

    def test_bash_dan_python_konsisten(self, monkeypatch):
        """Kedua sandbox punya aturan yang sama: tanpa izin → diblokir."""
        from alfa.tools.system import execution as ex

        monkeypatch.setattr(ex, "_check_docker_available", lambda: False)
        monkeypatch.setattr(ex, "is_unrestricted", lambda: False)
        monkeypatch.setenv("ALFA_UNRESTRICTED", "false")
        monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "false")
        monkeypatch.setenv("SANDBOX_BACKEND", "auto")
        monkeypatch.setenv("ALFA_BASH_BACKEND", "auto")

        py_res = ex.execute_python_sandbox("print(1)")
        bash_res = ex.execute_bash_command("echo 1")
        assert py_res["isolation"] == "blocked"
        assert bash_res["isolation"] == "blocked"

    def test_script_tidak_tertinggal_di_disk(self, monkeypatch):
        """Kode yang diblokir tidak boleh meninggalkan file di SANDBOX_DIR."""
        from alfa.tools.system import execution as ex
        from alfa.tools.system.constants import SANDBOX_DIR

        monkeypatch.setattr(ex, "_check_docker_available", lambda: False)
        monkeypatch.setattr(ex, "is_unrestricted", lambda: False)
        monkeypatch.setenv("ALFA_UNRESTRICTED", "false")
        monkeypatch.setenv("ALFA_ALLOW_HOST_EXEC", "false")

        before = set(os.listdir(SANDBOX_DIR)) if os.path.isdir(SANDBOX_DIR) else set()
        ex.execute_python_sandbox("x = 1\nprint(x)")
        after = set(os.listdir(SANDBOX_DIR)) if os.path.isdir(SANDBOX_DIR) else set()
        leaked = {f for f in (after - before) if f.endswith(".py")}
        assert not leaked, leaked


# ── P0-3: trust per tier ─────────────────────────────────────────────────────


class TestTrustPerTier:
    def test_approval_low_tidak_membuka_tier_critical(self, tmp_path, monkeypatch):
        from alfa.core.perm import gate as g
        from alfa.core.perm.store import get_tier_trust, update_tier_trust

        db_file = str(tmp_path / "trust.db")
        monkeypatch.setenv("ALFA_DB_PATH", db_file)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        update_tier_trust(1, "low", was_safe=True, response_time=0.1)
        assert get_tier_trust(1, "low")[0] >= 0.9
        assert get_tier_trust(1, "critical") == (0.0, 0)
        ok, _ = g.should_auto_approve(1, "ssh_execute_command")
        assert ok is False
        ok, _ = g.should_auto_approve(1, "clean_system_storage")
        assert ok is False

    def test_auto_approved_tidak_menambah_trust(self, tmp_path, monkeypatch):
        from alfa.core.perm import gate as g
        from alfa.core.perm.store import get_tier_trust

        db_file = str(tmp_path / "trust2.db")
        monkeypatch.setenv("ALFA_DB_PATH", db_file)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        tier = g.get_tool_tier("read_local_file")
        g._record(2, "read_local_file", tier, "auto_approved", "{}", 0.0)
        assert get_tier_trust(2, tier.value) == (0.0, 0)

    def test_eksplisit_menambah_trust_per_tier(self, tmp_path, monkeypatch):
        from alfa.core.perm import gate as g
        from alfa.core.perm.store import get_tier_trust

        db_file = str(tmp_path / "trust3.db")
        monkeypatch.setenv("ALFA_DB_PATH", db_file)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        tier = g.get_tool_tier("read_local_file")
        g._record(3, "read_local_file", tier, "once", "{}", 1.0)
        trust, count = get_tier_trust(3, tier.value)
        assert count == 1
        assert trust > 0.5


# ── P0-4: risk tier default & klasifikasi lengkap ───────────────────────────


class TestRiskTiers:
    def test_default_tier_fail_closed(self):
        from alfa.core.perm.constants import DEFAULT_TIER, RiskTier

        assert DEFAULT_TIER is RiskTier.HIGH

    def test_vault_tools_terklasifikasi(self):
        from alfa.core.perm import gate as g

        assert g.get_tool_tier("vault_delete_secret").value == "critical"
        assert g.get_tool_tier("vault_get_secret").value == "high"
        assert g.get_tool_tier("vault_store_secret").value == "high"

    def test_python_sandbox_klasifikasi(self):
        from alfa.core.perm import gate as g

        assert g.get_tool_tier("execute_python_sandbox").value == "high"
        assert g.get_tool_tier("execute_bash_command").value == "high"

    def test_semua_tool_terdaftar_terklasifikasi(self):
        """Tidak boleh ada tool yang diam-diam jatuh ke DEFAULT_TIER."""
        from alfa.core.perm.constants import TOOL_CLASSIFICATION
        from alfa.tools import AVAILABLE_TOOLS

        names = {f.__name__ for f in AVAILABLE_TOOLS if hasattr(f, "__name__")}
        missing = sorted(names - set(TOOL_CLASSIFICATION))
        assert not missing, f"tool tanpa klasifikasi risk tier: {missing}"


# ── P0-5: deny-by-default approval gate ─────────────────────────────────────


class TestDenyByDefaultGate:
    async def test_brain_menolak_tool_tanpa_gate(self, monkeypatch):
        from alfa.core.brain import agentic as ag

        executed: list = []
        monkeypatch.setattr(ag, "_execute_tool", lambda n, a: executed.append(n) or "OK")

        out = await ag._resolve_tool_outcome(None, "execute_bash_command", "{}")
        assert "DITOLAK" in out
        assert not executed

    async def test_gate_error_menolak_tool(self, monkeypatch):
        from alfa.core.brain import agentic as ag

        executed: list = []
        monkeypatch.setattr(ag, "_execute_tool", lambda n, a: executed.append(n) or "OK")

        async def _boom(_name, _args=""):
            raise RuntimeError(_GATE_BOOM_MSG)

        out = await ag._resolve_tool_outcome(_boom, "execute_bash_command", "{}")
        assert "DITOLAK" in out
        assert not executed

    async def test_gate_izin_menjalankan_tool(self, monkeypatch):
        from alfa.core.brain import agentic as ag

        executed: list = []
        monkeypatch.setattr(ag, "_execute_tool", lambda n, a: executed.append(n) or "OK")

        async def _allow(_name, _args=""):
            return None

        out = await ag._resolve_tool_outcome(_allow, "execute_bash_command", "{}")
        assert out == "OK"
        assert executed == ["execute_bash_command"]

    def test_reflection_tidak_punya_tools(self):
        """Job background ekstraksi memori tidak boleh punya akses tool."""
        import inspect

        from alfa.memory import reflection as refl

        src = inspect.getsource(refl)
        assert "tools_schema=[]" in src

    def test_fallback_provider_meneruskan_gate(self):
        import inspect

        from alfa.bot.pipeline import provider_adapter as pa

        sig = inspect.signature(pa.try_alt_provider_keys)
        assert "approval_gate" in sig.parameters
        src = inspect.getsource(pa.try_alt_provider_keys)
        assert "approval_gate=approval_gate" in src

    def test_swarm_pakai_headless_gate(self):
        import inspect

        from alfa.swarm import llm_client as lc

        assert hasattr(lc, "swarm_headless_gate")
        src = inspect.getsource(lc.generate_agent_response)
        assert "approval_gate=swarm_headless_gate" in src

    def test_allow_all_gate_terdaftar(self):
        from alfa.core.perm import gate as g

        assert callable(g.ALLOW_ALL_GATE)
        assert g.gate_is_interactive(None) is False
        assert g.gate_is_interactive(g.ALLOW_ALL_GATE) is False

        async def _interactive(_n, _a=""):
            return None

        assert g.gate_is_interactive(_interactive) is True


# ── P0-6: dashboard auth fail-closed ─────────────────────────────────────────


class TestDashboardFailClosed:
    def test_api_tanpa_token_ditolak(self, monkeypatch):
        """Regresi: DASHBOARD_AUTH_TOKEN kosong → SELURUH /api/* terbuka."""
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
        monkeypatch.setenv("ALFA_INSECURE_LOCAL", "false")
        client = TestClient(pkg_app)
        res = client.get("/api/tools")
        assert res.status_code == 401, res.text

    def test_escape_hatch_lokal_berfungsi(self, monkeypatch):
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "")
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
        monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
        client = TestClient(pkg_app)
        res = client.get("/api/tools")
        assert res.status_code == 200, res.text

    def test_escape_hatch_nonaktif_saat_token_ada(self, monkeypatch):
        from fastapi.testclient import TestClient

        from alfa.dashboard import app as pkg_app
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok123")
        monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "tok123")
        monkeypatch.setenv("ALFA_INSECURE_LOCAL", "true")
        client = TestClient(pkg_app)
        res = client.get("/api/tools")
        assert res.status_code == 401, res.text

    def test_passkey_login_ceremony_publik(self, monkeypatch):
        """Passkey login harus bisa diakses tanpa session (belum login)."""
        from alfa.dashboard.routes import auth as auth_mod

        monkeypatch.setattr(auth_mod, "DASHBOARD_AUTH_TOKEN", "tok123")
        src = Path(auth_mod.__file__).read_text(encoding="utf-8")
        assert "/api/auth/webauthn/login/options" in src
        assert "/api/auth/webauthn/login/verify" in src


# ── P0-7: alfa.security bukan lagi stub ─────────────────────────────────────


class TestSecurityApiTidakPalsu:
    def test_encrypt_api_key_benkut_asli(self):
        """Regresi: encrypt_api_key dulu mengembalikan plaintext."""
        import alfa.security as sec

        token = sec.encrypt_api_key("rahasia-super")
        assert token.startswith("enc1:")
        assert "rahasia-super" not in token
        assert sec.decrypt_api_key(token) == "rahasia-super"

    def test_is_command_blocked_dihormati(self):
        import alfa.security as sec

        assert sec.is_command_blocked("rm -rf /") is True
        assert sec.get_block_reason("rm -rf /")
        assert sec.is_command_blocked("echo halo") is False

    def test_encrypt_key_gagal_kuat_jika_kripto_tidak_ada(self, monkeypatch):
        """encrypt_key tidak boleh degrade diam-diam ke plaintext."""
        from alfa.core.db import crypto as c

        monkeypatch.setattr(c, "_get_aesgcm", lambda: None)
        with pytest.raises(c.CryptoUnavailableError):
            c.encrypt_key("rahasia")
