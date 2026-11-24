"""Phase 6 coverage: parser bersama suite telecom (BOQ, kuantitas chat, grup).

Hermetic: workbook Excel di-fake sebagai objek ringan, tidak ada file produksi.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def tc():
    from alfa.tools.telecom_tools import _common

    return _common


# ---------------------------------------------------------------------------
# Klasifikasi material
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("desc", "category"),
    [
        ("Label Tiang 100", "ACCESSORIES"),
        ("Pengecatan Tiang", "ACCESSORIES"),
        ("Pondasi Tiang Beton", "ACCESSORIES"),
        ("Clamp ADSS 12", "ACCESSORIES"),
        ("Dead End Grip", "ACCESSORIES"),
        ("FAT 16 Port Outdoor", "DISTRIBUTION_BOX"),
        ("FDT 48 Port", "DISTRIBUTION_BOX"),
        ("Joint Closure 24 Core", "DISTRIBUTION_BOX"),
        ("ODC 12 Core", "DISTRIBUTION_BOX"),
        ("Media Converter 8 port outdoor", "DISTRIBUTION_BOX"),
        ("Kabel ADSS 12C", "CABLE"),
        ("Drop Core 2", "CABLE"),
        ("Fig 8 Messenger", "CABLE"),
        ("Tiang Beton 7m", "POLE"),
        ("Pole 9 Meter", "POLE"),
        ("Tiang Mounted Bracket", "ACCESSORIES"),
        ("Splitter 1:8", "OPTICAL_PASSIVE"),
        ("Pigtail SC", "OPTICAL_PASSIVE"),
        ("Adapter SC/APC", "OPTICAL_PASSIVE"),
        ("Sleeve Proteksi", "OPTICAL_PASSIVE"),
        ("Barang Misterius", "OTHER"),
        ("", "OTHER"),
    ],
)
def test_classify_telecom_material(tc, desc, category):
    assert tc._classify_telecom_material(desc) == category


def test_classify_pole_excludes_labels_and_foundation(tc):
    assert tc._classify_telecom_material("Tiang Label Balok") == "ACCESSORIES"
    assert tc._classify_telecom_material("Tiang Pondasi Kecil") == "ACCESSORIES"
    assert tc._classify_telecom_material("  POLE 9M  ") == "POLE"
    # Klaim "mounted" mengecualikan POLE dan tidak cocok kategori lain.
    assert tc._classify_telecom_material("Pole Mounted Unit") == "OTHER"


# ---------------------------------------------------------------------------
# Workbook BOQ
# ---------------------------------------------------------------------------


class FakeWs:
    def __init__(self, rows):
        self._rows = rows

    def iter_rows(self, values_only=True):
        return iter(self._rows)


class FakeWb:
    def __init__(self, sheets: dict[str, list[tuple]]):
        self._sheets = sheets
        self.sheetnames = list(sheets)

    def __getitem__(self, name):
        return FakeWs(self._sheets[name])


HEADER = (None, "Description", "Unit", "Material Qty", "Service Qty")


def test_boq_prefers_cluster_with_material(tc):
    wb = FakeWb(
        {
            "BoQ NRO Cluster": [
                HEADER,
                (None, "Kabel ADSS 12C", "Meter", 120, None),
                (None, "FAT 16 Port", "Pcs", 4, None),
            ],
            "BoQ NRO All Feeder": [
                HEADER,
                (None, "Kabel Feeder", "Meter", 500, None),
            ],
        }
    )
    sheet, scope, items = tc._parse_single_boq_workbook(wb)
    assert sheet == "BoQ NRO Cluster"
    assert scope == "CLUSTER_DISTRIBUTION"
    assert [i["desc"] for i in items] == ["Kabel ADSS 12C", "FAT 16 Port"]
    assert items[0]["qty"] == 120.0 and items[0]["category"] == "CABLE"
    assert items[0]["unit"] == "Meter"
    assert items[1]["unit"] == "Pcs"
    assert items[1]["is_service"] is False


def test_boq_falls_back_to_feeder_when_cluster_empty(tc):
    wb = FakeWb(
        {
            "BoQ NRO Cluster": [
                HEADER,
                (None, "Rencana Nol", "Pcs", 0, None),
                (None, "Total", "Pcs", 1000000000, None),
            ],
            "BoQ NRO All Feeder": [
                HEADER,
                (None, "Kabel Feeder", "Meter", 500, None),
            ],
        }
    )
    sheet, scope, items = tc._parse_single_boq_workbook(wb)
    assert sheet == "BoQ NRO All Feeder" and scope == "SUB_FEEDER"
    assert len(items) == 1


def test_boq_feeder_only(tc):
    wb = FakeWb(
        {"BoQ NRO All Feeder": [HEADER, (None, "Drop Core", "Meter", 30, None)]}
    )
    sheet, scope, items = tc._parse_single_boq_workbook(wb)
    assert sheet == "BoQ NRO All Feeder" and scope == "SUB_FEEDER"
    assert items[0]["unit"] == "Meter"


def test_boq_generic_skips_summary_and_cover(tc):
    wb = FakeWb(
        {
            "Summary": [HEADER, (None, "Kabel", "Meter", 1, None)],
            "Permit DKK": [HEADER, (None, "Izin", "Pcs", 1, None)],
            "BoM Utama": [HEADER, (None, "Bolt", "Pcs", 1, None)],
            "Cover": [HEADER, (None, "Judul", "-", 1, None)],
            "Daftar Isi": [HEADER, (None, "Isi", "-", 1, None)],
            "Detail Pekerjaan": [
                HEADER,
                (None, "Tiang Beton", "Batang", 12, None),
            ],
        }
    )
    sheet, scope, items = tc._parse_single_boq_workbook(wb)
    assert sheet == "Detail Pekerjaan" and scope == "GENERIC"
    assert items[0]["desc"] == "Tiang Beton"
    assert items[0]["unit"] == "Batang"


def test_boq_all_sheets_ignored_uses_first(tc):
    wb = FakeWb(
        {
            "Summary": [HEADER, (None, "Kabel", "Meter", 1, None)],
            "Cover": [HEADER, (None, "Judul", "-", 1, None)],
        }
    )
    sheet, scope, items = tc._parse_single_boq_workbook(wb)
    assert sheet == "Summary" and scope == "GENERIC"
    assert items[0]["desc"] == "Kabel"


def test_boq_empty_sheet(tc):
    wb = FakeWb({"Data": []})
    sheet, scope, items = tc._parse_single_boq_workbook(wb)
    assert (sheet, scope, items) == ("Data", "GENERIC", [])


def test_boq_no_header_uses_default_columns(tc):
    wb = FakeWb(
        {
            "Data": [
                (None, "Kabel ADSS", "Meter", 42, None),
                (None, "X", None, None, None),
                (None, None, None, None, None),
            ]
        }
    )
    _, _, items = tc._parse_single_boq_workbook(wb)
    assert len(items) == 1
    assert items[0]["qty"] == 42.0


def test_boq_header_variants_and_row_filters(tc):
    rows = [
        ("Uraian", "Satuan", "Volume", None, None, "Qty Jasa"),
        ("Kabel ADSS", "Meter", 25, None, None, None),
        ("Sub Total", "", 99, None, None, None),
        ("Grand Total Kabel", "", 99, None, None, None),
        ("", "", None, None, None, None),
        ("A", "", None, None, None, None),
        (None, "", None, None, None, None),
        ("Splicing 24 Core", "Titik", None, None, None, 7),
        ("Testcomm OLT", "Titik", None, None, None, 3),
        ("Adapter SC", "Pcs", 0, None, None, 5),
    ]
    wb = FakeWb({"BOQ Vendor": rows})
    _, scope, items = tc._parse_single_boq_workbook(wb)
    assert scope == "GENERIC"
    by_desc = {i["desc"]: i for i in items}
    assert "Kabel ADSS" in by_desc
    assert by_desc["Kabel ADSS"]["qty"] == 25.0
    assert "Sub Total" not in by_desc
    assert "Grand Total Kabel" not in by_desc
    assert by_desc["Splicing 24 Core"]["is_service"] is True
    assert by_desc["Splicing 24 Core"]["qty"] == 7.0
    assert by_desc["Testcomm OLT"]["is_service"] is True
    # Qty material 0 tidak dihitung, tapi qty jasa non-nol tetap diabaikan
    # karena desc tidak termasuk kata layanan -> item tidak muncul.
    assert "Adapter SC" not in by_desc


def test_boq_material_qty_and_service_columns(tc):
    rows = [
        (None, "Item", "Unit", "Material Qty", "Service Qty"),
        (None, "Tiang Beton", "Pcs", 5, 2),
        (None, "OTDR Test", "Titik", None, 4),
        (None, "O PM Check", "Titik", None, 0),
    ]
    wb = FakeWb({"BOQ": rows})
    _, _, items = tc._parse_single_boq_workbook(wb)
    by_desc = {i["desc"]: i for i in items}
    assert by_desc["Tiang Beton"]["qty"] == 5.0
    assert by_desc["Tiang Beton"]["is_service"] is False
    assert by_desc["OTDR Test"]["qty"] == 4.0
    assert by_desc["OTDR Test"]["is_service"] is True
    assert "O PM Check" not in by_desc


def test_boq_default_unit_rules(tc):
    rows = [
        (None, "Item", None, "Qty"),
        (None, "Kabel Drop Core", None, 10),
        (None, "Bolt Plat", None, 3),
    ]
    wb = FakeWb({"Data": rows})
    _, _, items = tc._parse_single_boq_workbook(wb)
    units = {i["desc"]: i["unit"] for i in items}
    assert units["Kabel Drop Core"] == "Meter"
    assert units["Bolt Plat"] == "Pcs"


# ---------------------------------------------------------------------------
# Ekstraksi kuantitas chat
# ---------------------------------------------------------------------------


def test_quantities_ignore_plan_and_identity_numbers(tc):
    assert tc._extract_telecom_quantities_from_text("") == {
        "cables": 0.0,
        "poles": 0.0,
        "fats": 0.0,
        "fdts": 0.0,
    }
    assert tc._extract_telecom_quantities_from_text(
        "besok kita tarik kabel 100 meter"
    )["cables"] == 0.0
    assert tc._extract_telecom_quantities_from_text("FDT 2")["fdts"] == 0.0
    assert tc._extract_telecom_quantities_from_text("fat 16 port")["fats"] == 0.0
    assert tc._extract_telecom_quantities_from_text("tiang 7m")["poles"] == 0.0


def test_quantities_poles_patterns(tc):
    assert tc._extract_telecom_quantities_from_text("T72: 10 btg")["poles"] == 10.0
    assert (
        tc._extract_telecom_quantities_from_text("tiang 7m: 10 btg")["poles"] == 10.0
    )
    assert tc._extract_telecom_quantities_from_text("15 btg tiang")["poles"] == 15.0
    assert (
        tc._extract_telecom_quantities_from_text("tanam tiang 7m 3 batang")["poles"]
        == 3.0
    )
    assert (
        tc._extract_telecom_quantities_from_text("T7.3.-15.btng.")["poles"] == 15.0
    )
    assert (
        tc._extract_telecom_quantities_from_text("tiang 9 meter: 5 batang")["poles"]
        == 5.0
    )


def test_quantities_cables_context_required(tc):
    out = tc._extract_telecom_quantities_from_text(
        "tarik kabel 100 meter\nkabel 10 meter\nlebar jalan 20 meter"
    )
    assert out["cables"] == 100.0
    assert out["poles"] == 0.0


def test_quantities_cable_short_and_pole_context(tc):
    assert (
        tc._extract_telecom_quantities_from_text("kabel 10 meter hari ini")["cables"]
        == 0.0
    )
    assert (
        tc._extract_telecom_quantities_from_text("kabel ke tiang 50 meter")["cables"]
        == 0.0
    )
    assert (
        tc._extract_telecom_quantities_from_text(
            "penarikan adss 120 m dan fig8 60m"
        )["cables"]
        == 180.0
    )


def test_quantities_fat_and_fdt_units(tc):
    out = tc._extract_telecom_quantities_from_text(
        "\n".join(
            [
                "fat 2 box",
                "3 unit fat",
                "odp 1 pcs",
                "fdt 1 unit",
                "2 box fdt",
                "odc 3 pcs",
            ]
        )
    )
    assert out["fats"] == 6.0
    assert out["fdts"] == 6.0


def test_quantities_spec_plan_and_invalid_numbers(tc):
    # Baris rencana diabaikan sepenuhnya.
    out = tc._extract_telecom_quantities_from_text(
        "\n".join(["rencana pasang fat 4 box", "nanti kita tanam tiang 6 btg"])
    )
    assert out == {"cables": 0.0, "poles": 0.0, "fats": 0.0, "fdts": 0.0}

    # Format angka tidak valid diabaikan tanpa exception.
    assert (
        tc._extract_telecom_quantities_from_text("kabel abc meter")["cables"] == 0.0
    )


# ---------------------------------------------------------------------------
# Deteksi grup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "TO Proyek A",
        "to-rekon",
        "Grup TO",
        "Transfer Order Cluster 3",
        "Tim & To Lapangan",
        "laporan/to",
        "projek-to-utama",
        "  TO 12  ",
    ],
)
def test_is_to_group_positive(tc, name):
    assert tc.is_to_group(name) is True


@pytest.mark.parametrize(
    "name",
    ["", "   ", "Grup FTTH Pati", "Projek Recon Indosat", "TO"],
)
def test_is_to_group_negative(tc, name):
    assert tc.is_to_group(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "IMT Cluster Pati",
        "YOFC Recon 1",
        "Grup Pengambilan Material",
        "FTTH ODN Ronggo",
        "Proyek Tol Laut",
        "Recon Lapangan",
    ],
)
def test_is_project_positive(tc, name):
    assert tc.is_project_or_pengambilan(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "TO Proyek A",
        "+6281234567890",
        "081234567890",
        "chat pribadi",
        "Telegram (Chat)",
        "Test Verification",
        "WA: Grup Test",
        "Grup Random",
    ],
)
def test_is_project_negative(tc, name):
    assert tc.is_project_or_pengambilan(name) is False


def test_field_consolidation_flag_is_boolean(tc):
    assert isinstance(tc.FIELD_CONSOLIDATION_ENABLED, bool)
    assert isinstance(tc.PLAN_OR_SPECULATIVE_WORDS, tuple)
    assert "besok" in tc.PLAN_OR_SPECULATIVE_WORDS


def test_empty_and_none_descriptions(tc):
    assert tc._classify_telecom_material(None) == "OTHER"
    assert tc.is_to_group(None) is False
    assert tc.is_project_or_pengambilan(None) is False
