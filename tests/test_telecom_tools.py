"""
Unit tests for Telecommunication & Fiber Optic (NRO / FTTH) Operations Suite.
"""

import os

import openpyxl

from alfa.tools.telecom_tools import (
    _classify_telecom_material,
    boq_check_project_anomalies,
    boq_compare_and_diff,
    boq_consolidate_master_workbook,
    boq_reconcile_with_field_reports,
    render_cluster_kml_map,
)


def test_classify_telecom_material():
    assert _classify_telecom_material("Kabel ADSS 24 Core") == "CABLE"
    assert _classify_telecom_material("Steel Pole 7 meter 3 inch") == "POLE"
    assert _classify_telecom_material("FAT 16 Port Pole Mounted") == "DISTRIBUTION_BOX"
    assert _classify_telecom_material("Suspension Clamp Plastic") == "ACCESSORIES"
    assert _classify_telecom_material("Protection Sleeve 60mm") == "OPTICAL_PASSIVE"
    assert _classify_telecom_material("Random Item ABC") == "OTHER"


def test_render_cluster_kml_map(tmp_path):
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>Pole 7m 01</name>
          <description>Tiang awal cluster</description>
          <Point>
            <coordinates>102.54914,-3.45673,0</coordinates>
          </Point>
        </Placemark>
        <Placemark>
          <name>FAT 01</name>
          <description>FAT 16 port</description>
          <Point>
            <coordinates>102.54950,-3.45690,0</coordinates>
          </Point>
        </Placemark>
        <Placemark>
          <name>Rute Kabel Feeder</name>
          <LineString>
            <coordinates>
              102.54914,-3.45673,0 102.54950,-3.45690,0
            </coordinates>
          </LineString>
        </Placemark>
      </Document>
    </kml>
    """
    kml_file = tmp_path / "test_cluster.kml"
    kml_file.write_text(kml_content, encoding="utf-8")

    out_html = "test_cluster_map.html"
    res = render_cluster_kml_map(str(kml_file), output_html_filename=out_html)

    assert res["status"] == "success"
    assert res["total_points"] == 2
    assert res["total_cable_routes"] == 1
    assert os.path.exists(res["output_html_file"])


def test_boq_consolidate_master_workbook(tmp_path):
    # Buat Workbook 1 (Cluster A)
    wb1 = openpyxl.Workbook()
    ws1 = wb1.active
    ws1.title = "BoQ NRO Cluster"
    ws1.append(["No", "Description", "Unit", "Qty"])
    ws1.append([1, "Kabel ADSS 24C", "Meter", 1200])
    ws1.append([2, "Steel Pole 7m", "Pcs", 20])
    wb1_path = tmp_path / "BOQ - Cluster A.xlsx"
    wb1.save(str(wb1_path))

    # Buat Workbook 2 (Cluster B)
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.title = "BoQ NRO Cluster"
    ws2.append(["No", "Description", "Unit", "Qty"])
    ws2.append([1, "Kabel ADSS 24C", "Meter", 800])
    ws2.append([2, "Steel Pole 7m", "Pcs", 15])
    ws2.append([3, "FAT 16 Core", "Box", 4])
    wb2_path = tmp_path / "BOQ - Cluster B.xlsx"
    wb2.save(str(wb2_path))

    res = boq_consolidate_master_workbook(
        file_paths=[str(wb1_path), str(wb2_path)],
        output_filename="TEST_MASTER_CONSOLIDATED.xlsx",
        project_title="TEST PROJECT KONSOLIDASI",
    )

    assert res["status"] == "success"
    assert res["total_clusters"] == 2
    assert res["grand_totals"]["cable_meters"] == 2000.0
    assert res["grand_totals"]["poles_pcs"] == 35
    assert res["grand_totals"]["fat_fdt_pcs"] == 4
    assert os.path.exists(res["output_file"])


def test_boq_compare_and_diff(tmp_path):
    wb_old = openpyxl.Workbook()
    ws_old = wb_old.active
    ws_old.append(["Item", "Qty", "Unit"])
    ws_old.append(["Kabel ADSS 24C", 1000, "Meter"])
    ws_old.append(["Tiang 7m", 25, "Pcs"])
    ws_old.append(["FAT 8 Core", 5, "Pcs"])
    old_path = tmp_path / "BOQ_Rev0.xlsx"
    wb_old.save(str(old_path))

    wb_new = openpyxl.Workbook()
    ws_new = wb_new.active
    ws_new.append(["Item", "Qty", "Unit"])
    ws_new.append(["Kabel ADSS 24C", 1250, "Meter"])  # Modified (+250)
    ws_new.append(["Tiang 7m", 25, "Pcs"])            # Unchanged
    # FAT 8 Core removed
    ws_new.append(["FAT 16 Core", 3, "Pcs"])          # Added
    new_path = tmp_path / "BOQ_Rev1.xlsx"
    wb_new.save(str(new_path))

    res = boq_compare_and_diff(str(old_path), str(new_path), output_diff_filename="TEST_DIFF.xlsx")

    assert res["status"] == "success"
    stats = res["statistics"]
    assert stats["items_added"] == 1
    assert stats["items_removed"] == 1
    assert stats["items_modified"] == 1
    assert stats["items_unchanged"] == 1
    assert os.path.exists(res["output_diff_file"])


def test_boq_reconcile_and_anomalies():
    res_rec = boq_reconcile_with_field_reports("Curup", days_back=7)
    assert res_rec["status"] == "success"
    assert "reconciliation_summary" in res_rec

    res_anom = boq_check_project_anomalies(project_keyword="FTTH")
    assert res_anom["status"] == "success"
    assert "health_status" in res_anom


def test_generate_daily_executive_briefing():
    from alfa.tools.telecom_tools import generate_daily_executive_briefing
    res = generate_daily_executive_briefing(shift="morning", days_back=2)
    assert res["status"] == "success"
    assert "briefing_card" in res
    assert "DAILY EXECUTIVE BRIEFING" in res["briefing_card"]


def test_parse_delivery_order_document():
    from alfa.tools.telecom_tools import parse_delivery_order_document
    # Test on existing sample TOSBI file if exists
    sample_file = "/home/fahmial/Unduhan/TOSBI260425001.pdf"
    if os.path.exists(sample_file):
        res = parse_delivery_order_document(sample_file)
        assert res["status"] == "success"
        assert res["total_items_extracted"] >= 1
        assert res["delivery_order"]["number"] == "TOSBI260425001"


def test_wa_relay_send_from_telegram_validation():
    from alfa.tools.telecom_tools import wa_relay_send_from_telegram
    res = wa_relay_send_from_telegram("", "")
    assert res["status"] == "error"
    assert "tidak boleh kosong" in res["message"]


def test_dashboard_map_viewer_endpoints():
    from fastapi.testclient import TestClient

    from alfa.dashboard.app import create_app

    client = TestClient(create_app())
    res_map = client.get("/map")
    assert res_map.status_code == 200
    assert "ALFA FTTH Cluster Map Center" in res_map.text


def test_calculate_material_return_and_scrap():
    from alfa.tools.telecom_tools import calculate_material_return_and_scrap
    res = calculate_material_return_and_scrap(
        cluster_name="Curup",
        total_cable_issued_m=3000.0,
        total_poles_issued_pcs=40.0,
        cable_scrap_allowance_pct=3.0,
    )
    assert res["status"] == "success"
    assert "audit_card" in res
    assert "calculations" in res
    assert res["calculations"]["cable"]["allowed_scrap_m"] >= 0


def test_consolidate_delivery_orders_to_stock_ledger():
    from alfa.tools.telecom_tools import consolidate_delivery_orders_to_stock_ledger
    sample = "/home/fahmial/Unduhan/TOSBI260425001.pdf"
    if os.path.exists(sample):
        res = consolidate_delivery_orders_to_stock_ledger(file_paths=sample, output_filename="TEST_STOCK_LEDGER.xlsx")
        assert res["status"] == "success"
        assert res["total_material_types"] >= 1
        assert os.path.exists(res["output_file"])


def test_schedule_daily_briefing_task():
    from alfa.tools.telecom_tools import schedule_daily_briefing_task
    res = schedule_daily_briefing_task(enabled=True)
    assert res["status"] == "success"
    assert "job_id" in res


