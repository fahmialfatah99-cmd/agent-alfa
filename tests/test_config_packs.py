"""Regression tests untuk config pack (`alfa/config/packs/`)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from alfa.config.packs import DEFAULT_PACK, available_packs, load_pack, pack_data

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKS_DIR = REPO_ROOT / "alfa" / "config" / "packs"


def _run_probe(script: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def test_available_packs_contains_default_and_demo():
    packs = available_packs()
    assert DEFAULT_PACK in packs
    assert "demo" in packs


def test_pack_files_have_expected_shape():
    for name in available_packs():
        data = json.loads((PACKS_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert data.get("name") == name
        assert isinstance(data.get("clusters"), list) and data["clusters"]
        assert isinstance(data.get("constraints"), dict)
        assert isinstance(data.get("mandor_names"), dict)


def test_default_pack_matches_builtin_domain():
    from alfa.config.domain import (
        MANDOR_NAME_MAP,
        SUMMARY_CLUSTERS,
        SYMBOLIC_LOGISTICS_CONSTRAINTS,
        TRACKED_CLUSTERS,
    )

    pack = pack_data()
    assert tuple(pack["clusters"]) == TRACKED_CLUSTERS
    assert tuple(pack["summary_clusters"]) == SUMMARY_CLUSTERS
    assert pack["mandor_names"] == MANDOR_NAME_MAP
    assert SYMBOLIC_LOGISTICS_CONSTRAINTS["LAHAT"]["total_net"] == 160


def test_demo_pack_switches_domain_data():
    out = _run_probe(
        "from alfa.config.domain import DEFAULT_CLUSTER, MANDOR_NAME_MAP, TRACKED_CLUSTERS;"
        " print(DEFAULT_CLUSTER, ','.join(TRACKED_CLUSTERS), len(MANDOR_NAME_MAP))",
        {"ALFA_CONFIG_PACK": "demo"},
    )
    cluster, clusters, mandors = out.split()
    assert cluster == "ALFA"
    assert clusters == "ALFA,BETA"
    assert mandors == "2"


def test_unknown_pack_falls_back_to_default():
    out = _run_probe(
        "from alfa.config.domain import DEFAULT_CLUSTER; print(DEFAULT_CLUSTER)",
        {"ALFA_CONFIG_PACK": "pack-yang-tidak-ada"},
    )
    assert out == "LAHAT"


def test_load_pack_accepts_explicit_name():
    demo = load_pack("demo")
    assert demo["name"] == "demo"
    assert "ALFA" in demo["clusters"]
