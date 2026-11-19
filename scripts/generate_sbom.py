#!/usr/bin/env python3
"""Generate CycloneDX 1.5 SBOM dari requirements-lock.txt tanpa dependensi baru.

Hanya baris ``nama==versi`` yang dipakai; komentar, opsi pip, dan hash diabaikan.
Output deterministik (komponen diurutkan) agar artifact CI bisa dibandingkan
antar build.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)")


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: Path) -> list[dict[str, str]]:
    """Ambil komponen name/version dari lockfile (deterministik, tanpa I/O net)."""
    components: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        match = _REQ_RE.match(clean)
        if not match:
            continue
        name, version = match.group(1), match.group(2)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{_normalize_name(name)}@{quote(version, safe='._-+')}",
            }
        )
    components.sort(key=lambda item: (item["name"].lower(), item["version"]))
    return components


def build_sbom(components: list[dict[str, str]], version: str) -> dict:
    """Bangun dokumen CycloneDX 1.5 minimal yang valid."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "alfa-generate-sbom",
                        "version": "1.0.0",
                    }
                ]
            },
            "component": {
                "type": "application",
                "name": "alfa-agent",
                "version": version,
            },
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", default="requirements-lock.txt")
    parser.add_argument("--output", default="sbom.cdx.json")
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args(argv)

    requirements = Path(args.requirements)
    if not requirements.is_file():
        print(f"::error::File requirement tidak ada: {requirements}", file=sys.stderr)
        return 2

    from alfa import __version__

    document = build_sbom(parse_requirements(requirements), __version__)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.stdout:
        sys.stdout.write(payload)
        return 0

    output = Path(args.output)
    output.write_text(payload, encoding="utf-8")
    print(
        f"SBOM CycloneDX: {len(document['components'])} komponen "
        f"-> {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
