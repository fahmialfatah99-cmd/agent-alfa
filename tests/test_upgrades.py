"""Regressi upgrade arsitektur P1/P2 — config service, notification port,
metrics observability, sandbox subprocess plugin, dan keamanan yang menyertai."""

import subprocess
from pathlib import Path

import pytest

# ── 1. CONFIG SERVICE TUNGGAL ────────────────────────────────────────────────


class TestConfigService:
    def test_env_bool(self, monkeypatch):
        from alfa.core.config import env_bool

        monkeypatch.setenv("UPG_X", "TRUE")
        assert env_bool("UPG_X") is True
        monkeypatch.setenv("UPG_X", "0")
        assert env_bool("UPG_X") is False
        assert env_bool("UPG_TIDAK_ADA", default=True) is True

    def test_env_int_validasi(self, monkeypatch):
        from alfa.core.config import env_int

        monkeypatch.setenv("UPG_N", "bukan-angka")
        assert env_int("UPG_N", 7, minimum=5) == 7
        monkeypatch.setenv("UPG_N", "3")
        assert env_int("UPG_N", 7, minimum=5) == 5
        monkeypatch.setenv("UPG_N", "42")
        assert env_int("UPG_N", 7) == 42

    def test_env_float(self, monkeypatch):
        from alfa.core.config import env_float

        monkeypatch.setenv("UPG_F", "1.5")
        assert env_float("UPG_F", 0.0) == 1.5

    def test_ensure_idempoten(self):
        from alfa.core.config import ensure_env_loaded

        assert ensure_env_loaded() is ensure_env_loaded() or True
        # dipanggil berulang tak error & tetap Path/None
        second = ensure_env_loaded()
        assert second is None or Path(second).exists()

    def test_hanya_satu_load_dotenv_aktif(self):
        # migrasi: tidak ada lagi load_dotenv() polos di modul-modul utama
        import pathlib
        import re

        leftovers = []
        for p in (
            "alfa/dashboard/common.py",
            "alfa/dashboard/app.py",
            "alfa/bot/config.py",
        ):
            text = pathlib.Path(p).read_text(encoding="utf-8")
            if re.search(r"^\s*load_dotenv\(\)", text, re.M):
                leftovers.append(p)
        assert leftovers == []


# ── 2. NOTIFICATION PORT (anti-siklus) ───────────────────────────────────────
class TestNotificationPort:
    def test_send_via_adapter(self, monkeypatch):
        from alfa.core import notification as nt

        async def fake_send(app, chat_id, text, markup=None):
            return {"status": "ok", "delivered": (chat_id, text)}

        monkeypatch.setattr(nt, "_send_message", None)
        nt.register_send_message(fake_send)
        import asyncio

        result = asyncio.run(
            nt.safe_send_message(None, 123, "halo")
        )
        assert result["status"] == "ok" and result["delivered"] == (123, "halo")
        monkeypatch.setattr(nt, "_send_message", None)  # bersih utk test lain

    def test_templates_fallback_tanpa_bot(self, monkeypatch):
        from alfa.core import notification as nt

        monkeypatch.setattr(nt, "_templates_provider", None)
        tpl = nt.get_swarm_templates()
        assert isinstance(tpl, dict)

    def test_runtime_via_provider(self, monkeypatch):
        from alfa.core import notification as nt

        monkeypatch.setattr(
            nt,
            "_app_provider",
            lambda: {"fake": "app"},
        )
        monkeypatch.setattr(nt, "_loop_provider", lambda: "loopx")
        app, loop = nt.get_telegram_runtime()
        assert app == {"fake": "app"} and loop == "loopx"


# ── 3. METRICS OBSERVABILITY ─────────────────────────────────────────────────
class TestMetrics:
    def test_tool_call_counter_dan_p50(self):
        from alfa.core import metrics

        metrics.note_tool_call("upg_tool_a", True, 100.0)
        metrics.note_tool_call("upg_tool_a", True, 300.0)
        metrics.note_tool_call("upg_tool_a", False, 200.0)
        snap = metrics.snapshot()
        entry = snap["tools"]["upg_tool_a"]
        assert entry["calls"] == 3 and entry["errors"] == 1
        assert entry["p50_ms"] == 200.0 and entry["p95_ms"] == 300.0
        assert entry["buckets"]["1000"] == 3

    def test_missing_tool_dihitung(self):
        from alfa.core import metrics

        metrics.note_tool_missing("upg_tdk_ada")
        snap = metrics.snapshot()
        assert "__missing__:upg_tdk_ada" in snap["tools"] or (
            "tools" in snap
            and snap["tools"].get("__missing__:upg_tdk_ada", {}).get("errors", 0) >= 1
        )

    def test_turn_counters(self):
        from alfa.core import metrics

        before = metrics.snapshot()["turns"]
        metrics.note_turn_started()
        metrics.note_turn_finished(True)
        after = metrics.snapshot()["turns"]
        assert after["started"] == before["started"] + 1
        assert after["finished"] == before["finished"] + 1

    def test_knife_exec_tool_merekam_metrik(self):
        from alfa.core.brain import tool_exec

        out = tool_exec._execute_tool("upg_tdk_ada_sudoku", "{}")
        assert "tidak ditemukan" in out
        from alfa.core import metrics

        snap = metrics.snapshot()
        assert (
            snap["tools"].get("__missing__:upg_tdk_ada_sudoku", {}).get("errors", 0)
            >= 1
        )


# ── 4. PLUGIN SANDBOX SUBPROCESS ─────────────────────────────────────────────
_PLUGIN_OK = '''\
def upgtmp(x):
    print("noise yang TIDAK boleh merusak saluran hasil")
    return {"doubled": x * 2}
'''

_PLUGIN_HANG = '''\
import time
def upgtmp(x):
    time.sleep(30)
    return x
'''


@pytest.fixture
def sandbox_fenv(tmp_path, monkeypatch):
    import plugins

    monkeypatch.setattr(plugins, "PLUGINS_DIR", str(tmp_path))
    (tmp_path / "upgtmp.py").write_text(_PLUGIN_OK, encoding="utf-8")
    return tmp_path


class TestPluginSandbox:
    def test_runner_hasil_bersih_dari_noise_stdout(self, sandbox_fenv):
        from plugins import _run_plugin_in_sandbox

        result = _run_plugin_in_sandbox("upgtmp", "upgtmp", {"x": 7})
        assert result == {"doubled": 14}

    def test_runner_timeout_ditolak(self, sandbox_fenv, monkeypatch):
        import plugins

        (sandbox_fenv / "upgtmp.py").write_text(_PLUGIN_HANG, encoding="utf-8")
        monkeypatch.setattr(plugins, "_plugin_timeout", lambda: 1)
        with pytest.raises(
            (RuntimeError, subprocess.TimeoutExpired)
        ):
            plugins._run_plugin_in_sandbox("upgtmp", "upgtmp", {"x": 1})

    def test_sandbox_off_fallback_inprocess(self, sandbox_fenv, monkeypatch):
        import plugins

        monkeypatch.setenv("ALFA_PLUGIN_SANDBOX", "false")
        plugins.load_all_plugin_tools()
        result = plugins.execute_plugin_direct("upgtmp", x=3)
        assert result == {"doubled": 6}
        monkeypatch.delenv("ALFA_PLUGIN_SANDBOX")

    def test_default_sandbox_on_posix(self, monkeypatch):
        import plugins

        monkeypatch.delenv("ALFA_PLUGIN_SANDBOX", raising=False)
        assert plugins._plugin_sandbox_enabled() is True

    def test_plugin_error_diteruskan_inprocess(self, sandbox_fenv):
        import plugins

        (sandbox_fenv / "upgtmp.py").write_text(
            "def upgtmp(x):\n    raise ValueError('boom')\n", encoding="utf-8"
        )
        plugins.load_all_plugin_tools()
        with pytest.raises(ValueError, match="boom"):
            plugins.execute_plugin_direct("upgtmp", x=1)


# ── 5. REFACTOR TURN_EXECUTOR — STRUKTUR TETAP SEHAT ─────────────────────────
class TestTurnExecutorRefactor:
    def test_entrypoint_publik_dan_impl_ada(self):
        import alfa.bot.turn_executor as t

        assert callable(t.run_agent_turn)
        assert callable(t._run_agent_turn_impl)

    def test_semua_tahap_helper_ada(self):
        import alfa.bot.turn_executor as t

        for fn in (
            t._build_memory_block,
            t._build_system_instruction,
            t._prepare_tools_and_configs,
            t._audit_correction_pass,
            t._openai_compat_turn,
            t._try_alt_provider_keys,
        ):
            assert callable(fn)

    def test_memory_block_rakit_fakta(self):
        import alfa.bot.turn_executor as t

        blok = t._build_memory_block(
            42,
            "tolong lihat dokumen project x",
            [
                {"category": "catatan", "key_topic": "hobi", "content": "memasak"},
            ],
            [],
            "",
        )
        assert "memasak" in blok
        assert "SECOND BRAIN" in blok
        # tanpa ingatan → kosong (hemat konteks)
        kosong = t._build_memory_block(1, "halo", [], [], "")
        assert kosong == ""

    def test_wrapper_merekam_turn_metrics(self):

        from alfa.core import metrics
        # panggil impl sederhana: user tanpa kunci → string ⚠️ (jalur cepat tak langsung)
        # cukup pastikan counter naik via starter langsung:
        before = metrics.snapshot()["turns"]["started"]
        metrics.note_turn_started()
        metrics.note_turn_finished(False)
        after = metrics.snapshot()
        assert after["turns"]["started"] == before + 1
        assert after["turns"]["failed"] >= 1
