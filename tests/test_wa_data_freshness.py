"""Guard kesegaran data rekap material WhatsApp.

Rekap yang disusun dari arsip basi harus diberi peringatan eksplisit —
rekap yang terlihat "mutakhir" padahal berumur 11 hari adalah kegagalan data
yang lebih berbahaya daripada error.
"""

from __future__ import annotations

import time

from alfa.tools.telecom_tools import whatsapp as wa_mod


def test_stale_archive_is_flagged(monkeypatch):
    monkeypatch.setattr(
        wa_mod, "_wa_bridge_status", lambda: {"client_status": "INITIALIZING", "is_ready": False}
    )
    result = wa_mod._data_freshness([{"ts": int(time.time()) - 72 * 3600}], live_api_used=False)
    assert result["stale"] is True
    assert result["live_api_used"] is False
    assert result["bridge_ready"] is False
    assert result["age_hours"] and result["age_hours"] >= 71
    assert any("arsip lokal" in r for r in result["reasons"])
    assert any("berumur" in r for r in result["reasons"])


def test_fresh_live_data_is_not_flagged(monkeypatch):
    monkeypatch.setattr(
        wa_mod, "_wa_bridge_status", lambda: {"client_status": "READY", "is_ready": True}
    )
    result = wa_mod._data_freshness([{"ts": int(time.time())}], live_api_used=True)
    assert result["stale"] is False
    assert result["reasons"] == []
    assert result["newest_message_at"]


def test_no_messages_at_all_is_stale(monkeypatch):
    monkeypatch.setattr(
        wa_mod, "_wa_bridge_status", lambda: {"client_status": "READY", "is_ready": True}
    )
    result = wa_mod._data_freshness([], live_api_used=True)
    assert result["stale"] is True
    assert any("tidak ada pesan" in r for r in result["reasons"])


def test_bridge_unreachable_is_stale(monkeypatch):
    monkeypatch.setattr(wa_mod, "_wa_bridge_status", dict)
    result = wa_mod._data_freshness([{"ts": int(time.time())}], live_api_used=False)
    assert result["stale"] is True
    assert result["client_status"] == "UNKNOWN"
