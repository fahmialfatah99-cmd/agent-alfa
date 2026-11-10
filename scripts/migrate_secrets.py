#!/usr/bin/env python3
"""Migrasikan secret dari `.env` repository ke file privat di luar repo.

Default: **dry-run** (hanya menampilkan rencana). Gunakan ``--apply`` untuk
menulis file privat, dan ``--strip`` untuk membersihkan `.env` repository
(selalu membuat backup `.env.bak-<timestamp>` lebih dulu).

Contoh:
    python scripts/migrate_secrets.py                     # rencana saja
    python scripts/migrate_secrets.py --apply             # tulis ~/.config/alfa/secrets.env
    python scripts/migrate_secrets.py --apply --strip     # sekaligus bersihkan .env
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"
DEFAULT_TARGET = Path("~/.config/alfa/secrets.env").expanduser()


def parse_env(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (baris non-kunci, daftar (key, nilai))."""
    if not path.exists():
        return [], []
    plain: list[str] = []
    pairs: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            plain.append(raw)
            continue
        key, _, value = stripped.partition("=")
        pairs.append((key.strip(), value.strip()))
        plain.append(raw)
    return plain, pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Tulis file secret privat (default: dry-run)",
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Hapus kunci yang dimigrasi dari .env repository (butuh --apply)",
    )
    parser.add_argument(
        "--target",
        default=str(DEFAULT_TARGET),
        help="Lokasi file secret privat (default: ~/.config/alfa/secrets.env)",
    )
    args = parser.parse_args(argv)

    if args.strip and not args.apply:
        print("--strip hanya boleh dipakai bersama --apply", file=sys.stderr)
        return 2

    target = Path(args.target).expanduser()
    if not ENV_PATH.exists():
        print(f"Tidak ada .env di {ENV_PATH} — tidak ada yang dimigrasi.")
        return 0

    _, pairs = parse_env(ENV_PATH)
    if not pairs:
        print("Tidak ada pasangan KEY=VALUE di .env — tidak ada yang dimigrasi.")
        return 0

    print(f"Sumber : {ENV_PATH}")
    print(f"Tujuan : {target}")
    print(f"Kunci  : {len(pairs)}")
    for key, _ in pairs:
        print(f"  - {key}")

    if not args.apply:
        print("\nDry-run. Jalankan ulang dengan --apply untuk menulis file.")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    body = "# Secret privat ALFA — dimuat sebelum .env repository.\n"
    body += "# File ini TIDAK boleh masuk git. chmod 600.\n"
    body += "".join(f"{key}={value}\n" for key, value in pairs)
    target.write_text(body, encoding="utf-8")
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    print(f"\nDitulis: {target} (mode 600)")

    if args.strip:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        # Backup disimpan DI LUAR repo (rahasia tidak boleh menumpuk di working tree).
        backup_dir = target.parent
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"env-backup-{stamp}.bak"
        shutil.copy2(ENV_PATH, backup)
        os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
        moved = {key for key, _ in pairs}
        kept = [
            line
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip().partition("=")[0].strip() not in moved
        ]
        ENV_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.chmod(ENV_PATH, stat.S_IRUSR | stat.S_IWUSR)
        print(f"Backup .env : {backup}")
        print(f"`.env` dibersihkan; {len(moved)} kunci pindah ke file privat.")

    print(
        "\nRestart WAJIB agar env termuat ulang:\n"
        "  systemctl --user restart telegram-ai-bot.service alfa-dashboard.service\n"
        "  (JANGAN restart wa-sheets-bot.service)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
