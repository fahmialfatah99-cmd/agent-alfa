#!/usr/bin/env python3
"""Gerbang audit dependensi CI — gagal hanya untuk advisory yang punya fix.

``safety check`` warisan lama keluar dengan kode 64 untuk SETIAP advisory,
termasuk advisory tanpa versi perbaikan. Akibatnya job CI merah permanen
untuk paket transitif yang belum bisa dinaikkan. Skrip ini memindai
``requirements-lock.txt`` (bukan seluruh environment runner), menyimpan
artifact JSON yang bersih lewat ``--save-json`` (banner deprecation tidak
ikut), lalu:

- advisory dengan ``fixed_versions``  -> gagal (exit 1), harus di-upgrade;
- advisory tanpa fix yang tersedia     -> warning (tetap terlihat di log).

Dipakai oleh ``.github/workflows/code-quality.yml``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_REQUIREMENTS = "requirements-lock.txt"
DEFAULT_REPORT = "safety-report.json"
SCAN_TIMEOUT = 600


def collect_advisories(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalisasi advisory dari report safety, urut nama paket."""
    advisories: list[dict[str, Any]] = []
    raw = report.get("vulnerabilities")
    if not isinstance(raw, list):
        return advisories
    for item in raw:
        if not isinstance(item, dict):
            continue
        fixed_raw = item.get("fixed_versions")
        fixed = (
            [str(v).strip() for v in fixed_raw if str(v).strip()]
            if isinstance(fixed_raw, list)
            else []
        )
        advisories.append(
            {
                "package": str(item.get("package_name") or "?"),
                "version": str(item.get("analyzed_version") or "?"),
                "id": str(item.get("vulnerability_id") or "?"),
                "fixed_versions": fixed,
            }
        )
    advisories.sort(key=lambda v: (v["package"].lower(), v["version"], v["id"]))
    return advisories


def fixable_advisories(advisories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Advisory yang sudah punya versi perbaikan (wajib ditindaklanjuti)."""
    return [item for item in advisories if item["fixed_versions"]]


def _run_scan(
    safety_bin: str, requirements: Path, report: Path
) -> subprocess.CompletedProcess[str]:
    cmd = [
        safety_bin,
        "check",
        "-r",
        str(requirements),
        "--save-json",
        str(report),
        "--output",
        "screen",
    ]
    return subprocess.run(  # noqa: S603 — argumen berasal dari path lokal
        cmd,
        capture_output=True,
        text=True,
        timeout=SCAN_TIMEOUT,
        check=False,
    )


def _resolve_safety(value: str) -> str:
    found = shutil.which(value)
    if found:
        return found
    return value if Path(value).is_file() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument(
        "--safety",
        default=os.getenv("SAFETY_BIN", "safety"),
        help="Path/nama binary safety (default: env SAFETY_BIN atau 'safety')",
    )
    args = parser.parse_args(argv)

    requirements = Path(args.requirements)
    report = Path(args.report)
    safety_bin = _resolve_safety(args.safety)
    if not safety_bin:
        print("::error::'safety' tidak ditemukan (coba: pip install safety)", file=sys.stderr)
        return 2
    if not requirements.is_file():
        print(f"::error::File requirement tidak ada: {requirements}", file=sys.stderr)
        return 2
    if report.exists():
        report.unlink()

    try:
        proc = _run_scan(safety_bin, requirements, report)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"::error::Safety gagal dijalankan: {exc}", file=sys.stderr)
        return 2

    if not report.is_file():
        print("::error::Safety tidak menghasilkan report JSON.", file=sys.stderr)
        for line in (proc.stderr or proc.stdout or "").strip().splitlines()[-10:]:
            print(line, file=sys.stderr)
        return 2

    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::Report safety tidak valid: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("::error::Report safety bukan object JSON.", file=sys.stderr)
        return 2

    advisories = collect_advisories(data)
    print(f"Dependency audit: {len(advisories)} advisory di {requirements}")
    for item in advisories:
        fix = ", ".join(item["fixed_versions"]) if item["fixed_versions"] else "belum tersedia"
        print(f"  - {item['package']}=={item['version']}  {item['id']}  fix: {fix}")

    fixable = fixable_advisories(advisories)
    if fixable:
        print(
            f"::error::{len(fixable)} advisory punya versi perbaikan; "
            "upgrade dependensi terkait.",
            file=sys.stderr,
        )
        return 1
    if advisories:
        print(
            f"::warning::{len(advisories)} advisory belum punya versi perbaikan "
            "(dipantau, tidak menggagalkan CI)."
        )
    else:
        print("OK: tidak ada advisory dependensi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
