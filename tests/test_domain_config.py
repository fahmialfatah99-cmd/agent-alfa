"""Regression tests untuk `alfa.config.domain` (data domain terpusat)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from alfa.config.domain import (
    DEFAULT_CLUSTER,
    MANDOR_NAME_MAP,
    SUMMARY_CLUSTERS,
    SYMBOLIC_LOGISTICS_CONSTRAINTS,
    TRACKED_CLUSTERS,
    detect_cluster,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_default_tracked_clusters_and_summary():
    assert DEFAULT_CLUSTER == "LAHAT"
    assert "LAHAT" in TRACKED_CLUSTERS
    assert SUMMARY_CLUSTERS[0] == "LAHAT"
    assert set(SUMMARY_CLUSTERS).issubset(set(TRACKED_CLUSTERS))


def test_detect_cluster_prefers_tracked_match():
    assert detect_cluster("pengambilan di cluster curup") == "CURUP"
    assert detect_cluster("tidak ada cluster") == DEFAULT_CLUSTER
    assert detect_cluster("cluster lubuklinggau") == "LUBUKLINGGAU"


def test_symbolic_constraints_are_internally_consistent():
    for cluster, c in SYMBOLIC_LOGISTICS_CONSTRAINTS.items():
        assert c["mugi_bruto"] - c["mugi_retur"] == c["mugi_net"], cluster
        assert c["mugi_net"] + c["aqe_net"] == c["total_net"], cluster
        assert sum(c["items"].values()) == c["total_net"], cluster


def test_mandor_map_has_both_raw_and_plus_variants():
    for key, name in MANDOR_NAME_MAP.items():
        if key.startswith("+"):
            raw = key[1:]
        else:
            raw = key
        assert MANDOR_NAME_MAP[raw] == name
        assert MANDOR_NAME_MAP[f"+{raw}"] == name


def test_env_override_tracked_clusters():
    out = _run_probe(
        "from alfa.config.domain import TRACKED_CLUSTERS; print(','.join(TRACKED_CLUSTERS))",
        {"ALFA_TRACKED_CLUSTERS": "alpha,beta"},
    )
    assert out == "ALPHA,BETA"


def test_env_override_constraints():
    payload = json.dumps(
        {
            "ALFA": {
                "cluster": "CLUSTER_ALFA",
                "mugi_bruto": 10,
                "mugi_retur": 2,
                "mugi_net": 8,
                "aqe_net": 5,
                "total_net": 13,
                "items": {"T72": 13},
            }
        }
    )
    out = _run_probe(
        "from alfa.config.domain import SYMBOLIC_LOGISTICS_CONSTRAINTS as c;"
        " print(c['ALFA']['total_net'])",
        {"ALFA_DOMAIN_CONSTRAINTS_JSON": payload},
    )
    assert out == "13"


def test_invalid_constraints_json_falls_back_to_defaults():
    out = _run_probe(
        "from alfa.config.domain import SYMBOLIC_LOGISTICS_CONSTRAINTS as c;"
        " print(sorted(c.keys()))",
        {"ALFA_DOMAIN_CONSTRAINTS_JSON": "{invalid json"},
    )
    assert out == "['LAHAT']"
