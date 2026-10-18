"""Gate deep scraping di Swarm Step Executor.

Sesuai keluhan: agent riset TIDAK perlu menjalankan `universal_deep_scraper`
di setiap langkah bila langkah/intent tidak meminta data eksternal. Gate ini
menahan skrap berulang (maks. sekali per (topic, agent) untuk sinyal intent)
dan mengizinkan instruksi eksplisit menembus dedupe.
"""

from __future__ import annotations

import pytest  # noqa: F401 — pytest.fixture dipakai test lain file ini

from alfa.swarm.step_executor import (
    _reset_scrape_state,
)
from alfa.swarm.step_executor import (
    _step_needs_deep_scrape as needs,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_scrape_state()
    yield
    _reset_scrape_state()


def test_research_agent_tanpa_sinyal_data_lewat_jalur_agentic():
    """Agent Research + langkah 'tulis ringkasan' → TIDAK scrape."""
    perlu, alasan = needs(
        "Researcher Prime", "Analyst", "tulis ringkasan strategi pemasaran", {}
    )
    assert perlu is False
    assert alasan  # alasan skip diisi supaya terlog


def test_task_eksplisit_scrape_dijalankan():
    perlu, alasan = needs(
        "Researcher Prime",
        "Analyst",
        "buatkan csv 20 produk terlaris di shopee",
        {},
    )
    assert perlu is True
    assert alasan == ""


def test_intel_role_dengan_ambil_data():
    perlu, alasan = needs(
        "Scout-1", "Intel Agent", "ambil data supplier berbagai kota", {}
    )
    assert perlu is True
    assert alasan == ""


def test_agent_non_riset_tetap_tidak_scrape():
    perlu, alasan = needs("Coder-1", "Developer", "collect datany aja dulu", {})
    assert perlu is False
    assert alasan == ""  # non-riset: tanpa alasan khusus (bukan jalurnya)


def test_intent_scrape_hanya_langkah_pertama_yang_scrape():
    intent = {
        "is_scrape": True,
        "clean_query": "produk terlaris bulan ini",
        "category": "all_marketplace",
    }
    # langkah 1: boleh scrape
    perlu1, _ = needs("Prime Research", "Research", "kumpulkan facia", intent)
    assert perlu1 is True
    # langkah 2 (intent masih hidup, tapi tak ada sinyal task) → skip
    perlu2, alasan2 = needs(
        "Prime Research", "Research", "rangkum hasil risetnya", intent
    )
    assert perlu2 is False
    assert "sudah" in alasan2


def test_task_eksplisit_menembus_dedupe():
    intent = {"is_scrape": True, "clean_query": "produk terlaris"}
    perlu1, _ = needs("Prime", "Research", "kumpulkan data helpdesk", intent)
    perlu2, _ = needs(
        "Prime", "Research", "scrape ulang komplimenn hrga baru", intent
    )
    assert (perlu1, perlu2) == (True, True)


def test_intent_scrape_tanpa_agent_riset_tidak_scrape():
    perlu, _ = needs("Finance-1", "Accountant", "cek neraca", {
        "is_scrape": True, "clean_query": "x",
    })
    assert perlu is False
