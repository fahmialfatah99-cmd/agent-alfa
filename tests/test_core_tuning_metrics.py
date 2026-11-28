"""Unit tests for alfa.core.tuning dan alfa.core.metrics.

Kedua modul ini sebelumnya belum punya test langsung. tuning.py adalah
"satu sumber kebenaran" untuk timeout/temperature/pemotongan output tool,
dan metrics.py adalah penghitung observability thread-safe yang dipakai
agent loop dan /api/metrics.

Semua test bersifat hermetik: env di-mock per-test (monkeypatch) dan state
global metrics di-snapshot/pulihkan lewat fixture autouse.
"""

import threading
import time

import pytest

from alfa.core import metrics, tuning


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Hapus semua env knob yang dibaca tuning agar tidak bocor dari .env/shell."""
    for var in (
        "ALFA_UNRESTRICTED",
        "ALFA_HOST_TIMEOUT",
        "ALFA_TOOL_TIMEOUT",
        "ALFA_MAX_TOOL_OUTPUT",
        "ALFA_TEMPERATURE",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def _reset_metrics():
    """Snapshot & pulihkan state global metrics.py supaya test terisolasi."""
    saved = {
        "calls": dict(metrics._tool_calls),
        "errors": dict(metrics._tool_errors),
        "durations": dict(metrics._tool_durations_ms),
        "buckets": dict(metrics._duration_buckets),
        "started": metrics._turns_started,
        "finished": metrics._turns_finished,
        "failed": metrics._turns_failed,
        "recent": list(metrics._recent_turns),
    }
    yield
    metrics._tool_calls.clear()
    metrics._tool_calls.update(saved["calls"])
    metrics._tool_errors.clear()
    metrics._tool_errors.update(saved["errors"])
    metrics._tool_durations_ms.clear()
    metrics._tool_durations_ms.update(saved["durations"])
    metrics._duration_buckets.clear()
    metrics._duration_buckets.update(saved["buckets"])
    metrics._turns_started = saved["started"]
    metrics._turns_finished = saved["finished"]
    metrics._turns_failed = saved["failed"]
    metrics._recent_turns.clear()
    metrics._recent_turns.extend(saved["recent"])


# ---------------------------------------------------------------------------
# tuning._env_int
# ---------------------------------------------------------------------------

class TestEnvInt:
    def test_valid_int(self, monkeypatch):
        monkeypatch.setenv("ALFA_X", "42")
        assert tuning._env_int("ALFA_X", 7) == 42

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("ALFA_X", "  13\n")
        assert tuning._env_int("ALFA_X", 7) == 13

    def test_invalid_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ALFA_X", "bukan-angka")
        assert tuning._env_int("ALFA_X", 7) == 7

    def test_missing_var_returns_default(self):
        assert tuning._env_int("ALFA_YANG_TIDAK_ADA", 99) == 99


# ---------------------------------------------------------------------------
# tuning._unrestricted
# ---------------------------------------------------------------------------

class TestUnrestricted:
    @pytest.mark.parametrize("raw", ["true", "TRUE", "True", " true ", "TrUe"])
    def test_true_variants(self, monkeypatch, raw):
        monkeypatch.setenv("ALFA_UNRESTRICTED", raw)
        assert tuning._unrestricted() is True

    @pytest.mark.parametrize("raw", ["false", "", "yes", "1", "no"])
    def test_non_true_values_are_false(self, monkeypatch, raw):
        monkeypatch.setenv("ALFA_UNRESTRICTED", raw)
        assert tuning._unrestricted() is False

    def test_default_is_false(self):
        assert tuning._unrestricted() is False


# ---------------------------------------------------------------------------
# tuning.host_exec_timeout / tool_exec_timeout
# ---------------------------------------------------------------------------

class TestTimeouts:
    def test_restricted_default(self):
        assert tuning.host_exec_timeout(unrestricted=False) == 45

    def test_unrestricted_default(self):
        assert tuning.host_exec_timeout(unrestricted=True) == 600

    def test_custom_restricted_default(self):
        assert tuning.host_exec_timeout(unrestricted=False, default_restricted=10) == 10

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("ALFA_HOST_TIMEOUT", "120")
        assert tuning.host_exec_timeout(unrestricted=False) == 120
        assert tuning.host_exec_timeout(unrestricted=True) == 120

    def test_auto_detect_unrestricted_from_env(self, monkeypatch):
        monkeypatch.setenv("ALFA_UNRESTRICTED", "true")
        assert tuning.host_exec_timeout() == 600

    def test_tool_timeout_floor_without_explicit(self):
        # host default restricted = 45 -> max(300, 75) = 300
        assert tuning.tool_exec_timeout() == 300

    def test_tool_timeout_follows_large_host_timeout(self, monkeypatch):
        monkeypatch.setenv("ALFA_HOST_TIMEOUT", "500")
        assert tuning.tool_exec_timeout() == 530

    def test_tool_timeout_always_exceeds_host(self, monkeypatch):
        monkeypatch.setenv("ALFA_HOST_TIMEOUT", "100000")
        assert tuning.tool_exec_timeout() > tuning.host_exec_timeout()

    def test_explicit_tool_timeout_override(self, monkeypatch):
        monkeypatch.setenv("ALFA_TOOL_TIMEOUT", "77")
        assert tuning.tool_exec_timeout() == 77


# ---------------------------------------------------------------------------
# tuning.max_tool_output
# ---------------------------------------------------------------------------

class TestMaxToolOutput:
    def test_default(self):
        assert tuning.max_tool_output() == 12000

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ALFA_MAX_TOOL_OUTPUT", "5000")
        assert tuning.max_tool_output() == 5000

    def test_floor_1000(self, monkeypatch):
        monkeypatch.setenv("ALFA_MAX_TOOL_OUTPUT", "10")
        assert tuning.max_tool_output() == 1000


# ---------------------------------------------------------------------------
# tuning.truncate_middle
# ---------------------------------------------------------------------------

class TestTruncateMiddle:
    def test_short_text_untouched(self):
        assert tuning.truncate_middle("hello", 100) == "hello"

    def test_exact_limit_untouched(self):
        text = "x" * 50
        assert tuning.truncate_middle(text, 50) == text

    def test_none_becomes_empty_string(self):
        assert tuning.truncate_middle(None, 10) == ""

    def test_non_str_is_coerced(self):
        assert tuning.truncate_middle(123456, 10) == "123456"

    def test_limit_zero_or_negative_returns_full(self):
        text = "abcdefghij" * 10
        assert tuning.truncate_middle(text, 0) == text
        assert tuning.truncate_middle(text, -5) == text

    def test_head_and_tail_preserved(self):
        text = "H" * 100 + "M" * 400 + "T" * 100
        out = tuning.truncate_middle(text, 120)
        assert len(out) <= 120
        assert out.startswith("H")
        assert out.endswith("T")
        assert "dipotong" in out
        # Kepala lebih banyak daripada ekor (head_ratio default 0.6)
        head_part = out.split("...[")[0]
        tail_part = out.split("]...\n")[-1]
        assert len(head_part) >= len(tail_part)

    def test_marker_reports_removed_count(self):
        text = "a" * 1000
        out = tuning.truncate_middle(text, 100)
        assert "...[900 karakter dipotong]..." in out

    def test_result_length_never_exceeds_limit(self):
        text = "z" * 5000
        for limit in (120, 300, 1000):
            assert len(tuning.truncate_middle(text, limit)) <= limit

    def test_head_ratio_extremes(self):
        text = "a" * 1000
        full_head = tuning.truncate_middle(text, 200, head_ratio=1.0)
        assert full_head.endswith("dipotong]...\n") or full_head.endswith("\n")
        full_tail = tuning.truncate_middle(text, 200, head_ratio=0.0)
        assert full_tail.startswith("\n...[")


# ---------------------------------------------------------------------------
# tuning.tool_temperature
# ---------------------------------------------------------------------------

class TestToolTemperature:
    def test_env_override_wins_for_all_models(self, monkeypatch):
        monkeypatch.setenv("ALFA_TEMPERATURE", "0.9")
        assert tuning.tool_temperature("gemini-3-pro") == 0.9
        assert tuning.tool_temperature("gpt-4o") == 0.9

    def test_invalid_env_falls_through(self, monkeypatch):
        monkeypatch.setenv("ALFA_TEMPERATURE", "panas")
        assert tuning.tool_temperature("gpt-4o") == 0.3

    @pytest.mark.parametrize(
        "model",
        ["gemini-3-pro", "models/gemini-3-flash", "GEMINI-3.0-Ultra"],
    )
    def test_gemini3_returns_none(self, model):
        assert tuning.tool_temperature(model) is None

    @pytest.mark.parametrize("model", ["gemini-2.5-pro", "gpt-4o", "llama3", ""])
    def test_other_models_get_03(self, model):
        assert tuning.tool_temperature(model) == 0.3

    def test_untrimmed_padded_model_not_gemini3(self):
        # Kontrak saat ini: nama model tidak di-strip, jadi spasi membuat
        # model tidak terdeteksi sebagai gemini-3 (dokumentasi perilaku).
        assert tuning.tool_temperature(" gemini-3-x ") == 0.3


# ---------------------------------------------------------------------------
# metrics — tool call counters
# ---------------------------------------------------------------------------

class TestMetricsToolCalls:
    def test_note_tool_call_success(self, _reset_metrics):
        metrics.note_tool_call("bash", ok=True, duration_ms=100)
        snap = metrics.snapshot()
        t = snap["tools"]["bash"]
        assert t["calls"] == 1
        assert t["errors"] == 0
        assert t["count"] == 1

    def test_note_tool_call_error_counted(self, _reset_metrics):
        metrics.note_tool_call("python", ok=False, duration_ms=50)
        t = metrics.snapshot()["tools"]["python"]
        assert t["calls"] == 1
        assert t["errors"] == 1

    def test_multiple_calls_accumulate(self, _reset_metrics):
        for _ in range(3):
            metrics.note_tool_call("grep", ok=True, duration_ms=10)
        metrics.note_tool_call("grep", ok=False, duration_ms=20)
        t = metrics.snapshot()["tools"]["grep"]
        assert t["calls"] == 4
        assert t["errors"] == 1

    def test_duration_buckets(self, _reset_metrics):
        metrics.note_tool_call("fast", ok=True, duration_ms=10)     # <=50
        metrics.note_tool_call("slow", ok=True, duration_ms=99999)  # hanya +Inf
        snap = metrics.snapshot()
        assert snap["tools"]["fast"]["buckets"]["50"] == 1
        assert snap["tools"]["slow"]["buckets"]["+Inf"] == 1
        assert snap["tools"]["slow"]["buckets"]["50"] == 0

    def test_percentiles(self, _reset_metrics):
        for d in [10, 20, 30, 40, 50]:
            metrics.note_tool_call("p", ok=True, duration_ms=d)
        t = metrics.snapshot()["tools"]["p"]
        assert t["p50_ms"] in (30, 40)
        assert t["p95_ms"] == 50

    def test_note_tool_missing(self, _reset_metrics):
        metrics.note_tool_missing("nonexistent_tool")
        metrics.note_tool_missing("nonexistent_tool")
        t = metrics.snapshot()["tools"]["__missing__:nonexistent_tool"]
        assert t["errors"] == 2
        assert t["calls"] == 0

    def test_snapshot_is_a_copy(self, _reset_metrics):
        metrics.note_tool_call("c", ok=True, duration_ms=1)
        snap = metrics.snapshot()
        snap["tools"]["c"]["calls"] = 999
        assert metrics.snapshot()["tools"]["c"]["calls"] == 1

    def test_bad_input_does_not_raise(self, _reset_metrics):
        # Anti-throwing: metrik tidak boleh mengganggu jalur utama.
        metrics.note_tool_call(None, ok=True, duration_ms="bukan-angka")
        metrics.note_tool_missing(None)
        metrics.note_turn_started()
        metrics.note_turn_finished(True)


# ---------------------------------------------------------------------------
# metrics — turn counters
# ---------------------------------------------------------------------------

class TestMetricsTurns:
    def test_turn_counters(self, _reset_metrics):
        before = metrics.snapshot()["turns"]
        metrics.note_turn_started()
        metrics.note_turn_finished(True)
        metrics.note_turn_started()
        metrics.note_turn_finished(False)
        after = metrics.snapshot()["turns"]
        assert after["started"] == before["started"] + 2
        assert after["finished"] == before["finished"] + 1
        assert after["failed"] == before["failed"] + 1

    def test_recent_turns_recorded(self, _reset_metrics):
        metrics.note_turn_started()
        metrics.note_turn_finished(True)
        recent = metrics.snapshot()["recent_turns"]
        assert recent[-1]["event"] == "finished"
        assert recent[-1]["ok"] is True
        assert recent[-2]["event"] == "started"
        assert isinstance(recent[-1]["ts"], float)

    def test_recent_turns_capped_at_50_in_snapshot(self, _reset_metrics):
        for _ in range(80):
            metrics.note_turn_started()
        assert len(metrics.snapshot()["recent_turns"]) <= 50

    def test_uptime_monotonic(self, _reset_metrics):
        u1 = metrics.snapshot()["uptime_seconds"]
        time.sleep(0.01)
        assert metrics.snapshot()["uptime_seconds"] >= u1


# ---------------------------------------------------------------------------
# metrics — thread safety
# ---------------------------------------------------------------------------

class TestMetricsThreadSafety:
    def test_concurrent_updates_no_lost_counts(self, _reset_metrics):
        errors_seen = []

        def worker():
            try:
                for _ in range(100):
                    metrics.note_tool_call("race", ok=True, duration_ms=5)
            except Exception as e:  # pragma: no cover - hanya jika bug
                errors_seen.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors_seen
        snap = metrics.snapshot()
        assert snap["tools"]["race"]["calls"] == 800
        # Deque durations dibatasi maxlen, tapi tidak boleh melebihi batas itu
        assert snap["tools"]["race"]["count"] <= 200
