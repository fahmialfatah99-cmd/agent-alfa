"""Regression tests untuk kontrak schema tool.

Parsing tool harus menghasilkan tipe parameter yang benar (integer/boolean),
bukan string. Modul yang dipecah menjadi paket tidak boleh mengubah
anotasi fungsi sehingga schema OpenAI ikut berubah.
"""

from __future__ import annotations

from alfa.tools.registry import TOOL_REGISTRY


def _props(tool_name: str) -> dict:
    entry = TOOL_REGISTRY[tool_name]
    return entry["schema"]["openai_spec"]["function"]["parameters"]["properties"]


def test_integrations_password_schema_keeps_scalar_types():
    props = _props("generate_secure_password")
    assert props["length"]["type"] == "integer"
    assert props["include_uppercase"]["type"] == "boolean"
    assert props["include_digits"]["type"] == "boolean"
    assert props["include_special"]["type"] == "boolean"
    assert props["count"]["type"] == "integer"


def test_integrations_wa_schema_keeps_types():
    props = _props("wa_get_messages")
    assert props["limit"]["type"] == "integer"
    props = _props("wa_send_message")
    assert props["to"]["type"] == "string"
    assert props["message"]["type"] == "string"


def test_telecom_schema_keeps_types():
    props = _props("boq_consolidate_master_workbook")
    assert props["file_paths"]["type"] == "string"
    assert props["project_title"]["type"] == "string"
    # Anotasi string (PEP 563) harus tetap menghasilkan tipe numerik/boolean.
    props = _props("schedule_daily_briefing_task")
    assert props["morning_hour"]["type"] == "integer"
    assert props["evening_minute"]["type"] == "integer"
    assert props["enabled"]["type"] == "boolean"
