"""Telecom & FTTH operations suite for ALFA.

Pecah dari modul monolitik ``telecom_tools.py`` menjadi sub-modul per
tanggung jawab. **Import path publik tidak berubah** — semua simbol tetap
di-import dari ``alfa.tools.telecom_tools``.

Sub-modul:
- ``_common``   : konstanta & parser bersama (klasifikasi material, klasifikasi grup).
- ``boq``       : konsolidasi/diff/rekonsiliasi/anomali BOQ.
- ``maps``      : render peta cluster KML/KMZ.
- ``briefing``  : briefing eksekutif harian + penjadwal.
- ``documents`` : understanding dokumen lapangan (voice note, DO, surat jalan).
- ``ledger``    : konsolidasi ledger stok + hitung retur/scrap.
- ``relay``     : relay ke Telegram + alert anomali instan.
- ``whatsapp``  : rekonsiliasi material grup WhatsApp.
"""

from alfa.tools.telecom_tools._common import (
    FIELD_CONSOLIDATION_ENABLED,
    PLAN_OR_SPECULATIVE_WORDS,
    _classify_telecom_material,
    _extract_telecom_quantities_from_text,
    _parse_single_boq_workbook,
    is_project_or_pengambilan,
    is_to_group,
)
from alfa.tools.telecom_tools.boq import (
    boq_check_project_anomalies,
    boq_compare_and_diff,
    boq_consolidate_master_workbook,
    boq_reconcile_with_field_reports,
)
from alfa.tools.telecom_tools.briefing import (
    generate_daily_executive_briefing,
    schedule_daily_briefing_task,
)
from alfa.tools.telecom_tools.documents import (
    _transcribe_local_whisper_fallback,
    inspect_field_surat_jalan_image,
    parse_delivery_order_document,
    transcribe_field_voice_note,
)
from alfa.tools.telecom_tools.ledger import (
    calculate_material_return_and_scrap,
    consolidate_delivery_orders_to_stock_ledger,
)
from alfa.tools.telecom_tools.maps import render_cluster_kml_map
from alfa.tools.telecom_tools.relay import (
    dispatch_instant_material_anomaly_alert,
    wa_relay_send_from_telegram,
)
from alfa.tools.telecom_tools.whatsapp import reconcile_whatsapp_material_group

__all__ = [
    "FIELD_CONSOLIDATION_ENABLED",
    "PLAN_OR_SPECULATIVE_WORDS",
    "_classify_telecom_material",
    "_extract_telecom_quantities_from_text",
    "_parse_single_boq_workbook",
    "_transcribe_local_whisper_fallback",
    "boq_check_project_anomalies",
    "boq_compare_and_diff",
    "boq_consolidate_master_workbook",
    "boq_reconcile_with_field_reports",
    "calculate_material_return_and_scrap",
    "consolidate_delivery_orders_to_stock_ledger",
    "dispatch_instant_material_anomaly_alert",
    "generate_daily_executive_briefing",
    "inspect_field_surat_jalan_image",
    "is_project_or_pengambilan",
    "is_to_group",
    "parse_delivery_order_document",
    "reconcile_whatsapp_material_group",
    "render_cluster_kml_map",
    "schedule_daily_briefing_task",
    "transcribe_field_voice_note",
    "wa_relay_send_from_telegram",
]
