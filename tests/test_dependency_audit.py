"""Tests for scripts/check_dependency_audit.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_dependency_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("alfa_check_dependency_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_advisories_normalizes_and_sorts():
    module = _load_module()
    report = {
        "vulnerabilities": [
            {
                "package_name": "zeta",
                "analyzed_version": "2.0",
                "vulnerability_id": "B",
                "fixed_versions": ["2.1"],
            },
            {
                "package_name": "alpha",
                "analyzed_version": "1.0",
                "vulnerability_id": "A",
                "fixed_versions": [],
            },
            "bukan-dict",
        ]
    }

    rows = module.collect_advisories(report)

    assert [row["package"] for row in rows] == ["alpha", "zeta"]
    assert rows[0]["fixed_versions"] == []
    assert rows[1]["fixed_versions"] == ["2.1"]


def test_fixable_advisories_only_returns_rows_with_fix():
    module = _load_module()
    rows = [
        {"package": "a", "version": "1", "id": "A", "fixed_versions": []},
        {"package": "b", "version": "2", "id": "B", "fixed_versions": ["2.1"]},
    ]

    assert [row["package"] for row in module.fixable_advisories(rows)] == ["b"]


def test_collect_advisories_handles_missing_or_invalid_payload():
    module = _load_module()

    assert module.collect_advisories({}) == []
    assert module.collect_advisories({"vulnerabilities": "nope"}) == []
