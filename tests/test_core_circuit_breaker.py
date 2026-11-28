"""Unit tests untuk alfa.core.brain.circuit_breaker.

Mencakup: parsing retry-delay (format detik & format manusia), clamping
cooldown, perilaku cooldown per-model, pembersihan pasif saat kedaluwarsa,
filtering kandidat model, dan kontrak fail-open ketika SEMUA model sedang
didinginkan (sistem harus tetap berjalan, bukan macet total).
"""

import time

import pytest

from alfa.core.brain import circuit_breaker as cb


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore registry global agar tes terisolasi."""
    saved = dict(cb._COOLDOWN_REGISTRY)
    cb.reset_circuit_breaker()
    yield
    cb._COOLDOWN_REGISTRY.clear()
    cb._COOLDOWN_REGISTRY.update(saved)


class TestParseRetryDelay:
    def test_seconds_format(self):
        # 62514s > MAX_COOLDOWN (43200s) => dipotong ke plafon.
        assert cb.parse_retry_delay("'retryDelay': '62514s'") == cb.MAX_COOLDOWN_SECONDS

    def test_seconds_format_under_cap(self):
        assert cb.parse_retry_delay("'retryDelay': '3600s'") == 3600.0

    def test_fractional_seconds(self):
        assert cb.parse_retry_delay('retryDelay: "12.5s"') == 12.5

    def test_human_format_hms(self):
        # 17h21m54s = 62514 detik
        assert cb.parse_retry_delay("Quota exhausted. Please retry in 17h21m54s") == 62514.0

    def test_human_format_case_insensitive(self):
        assert cb.parse_retry_delay("please RETRY IN 1h0m0s") == 3600.0

    def test_caps_at_max_cooldown(self):
        huge = cb.parse_retry_delay("'retryDelay': '999999999s'")
        assert huge == cb.MAX_COOLDOWN_SECONDS

    def test_unknown_error_returns_default(self):
        assert cb.parse_retry_delay(RuntimeError("boom")) == cb.DEFAULT_COOLDOWN_SECONDS

    def test_empty_string_returns_default(self):
        assert cb.parse_retry_delay("") == cb.DEFAULT_COOLDOWN_SECONDS

    def test_none_input_does_not_raise(self):
        assert cb.parse_retry_delay(None) == cb.DEFAULT_COOLDOWN_SECONDS


class TestMarkAndAvailability:
    def test_marked_model_becomes_unavailable(self):
        cb.mark_model_exhausted("gemini-2.5-pro", cooldown_seconds=60, reason="429")
        assert cb.is_model_available("gemini-2.5-pro") is False

    def test_unmarked_model_available(self):
        assert cb.is_model_available("never-marked") is True

    def test_empty_model_name_never_registered(self):
        cb.mark_model_exhausted("", cooldown_seconds=60)
        assert "" not in cb._COOLDOWN_REGISTRY

    def test_empty_name_is_not_available(self):
        # Kontrak: nama kosong berarti tidak ada model untuk dipilih.
        assert cb.is_model_available("") is False

    def test_cooldown_floor_30s(self):
        cb.mark_model_exhausted("m-a", cooldown_seconds=1)
        until, _ = cb._COOLDOWN_REGISTRY["m-a"]
        assert until - time.monotonic() > 25  # dipaksa minimal 30s

    def test_cooldown_ceiling_12h(self):
        cb.mark_model_exhausted("m-b", cooldown_seconds=10**9)
        until, _ = cb._COOLDOWN_REGISTRY["m-b"]
        assert until - time.monotonic() <= cb.MAX_COOLDOWN_SECONDS + 1

    def test_default_reason_recorded(self):
        cb.mark_model_exhausted("m-c")
        _, reason = cb._COOLDOWN_REGISTRY["m-c"]
        assert reason == "quota/service exhausted"

    def test_expired_entry_purged_and_available(self):
        cb._COOLDOWN_REGISTRY["old-model"] = (time.monotonic() - 1, "expired")
        assert cb.is_model_available("old-model") is True
        assert "old-model" not in cb._COOLDOWN_REGISTRY  # dibersihkan pasif

    def test_reset_clears_everything(self):
        cb.mark_model_exhausted("x", cooldown_seconds=3600)
        cb.mark_model_exhausted("y", cooldown_seconds=3600)
        cb.reset_circuit_breaker()
        assert cb._COOLDOWN_REGISTRY == {}


class TestGetAvailableModels:
    def test_empty_candidates(self):
        assert cb.get_available_models([]) == []

    def test_all_fresh_preserved_in_order(self):
        models = ["a", "b", "c"]
        assert cb.get_available_models(models) == models

    def test_filters_out_cooling_models(self):
        cb.mark_model_exhausted("dead", cooldown_seconds=3600)
        result = cb.get_available_models(["dead", "alive"])
        assert result == ["alive"]

    def test_fail_open_when_all_cooling(self):
        # Kontrak kritis: jika semua kandidat didinginkan, registry di-reset
        # dan daftar penuh dikembalikan — sistem tidak boleh macet total.
        for m in ("m1", "m2"):
            cb.mark_model_exhausted(m, cooldown_seconds=3600)
        assert cb.get_available_models(["m1", "m2"]) == ["m1", "m2"]
        # Efek samping fail-open: cooldown benar-benar dibersihkan.
        assert cb.is_model_available("m1") is True
        assert cb.is_model_available("m2") is True

    def test_fail_open_scoped_to_candidates_only(self):
        cb.mark_model_exhausted("candidate", cooldown_seconds=3600)
        cb.mark_model_exhausted("bystander", cooldown_seconds=3600)
        cb.get_available_models(["candidate"])  # memicu fail-open
        assert "candidate" not in cb._COOLDOWN_REGISTRY
        assert "bystander" in cb._COOLDOWN_REGISTRY  # tidak ikut ter-reset
