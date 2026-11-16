#!/usr/bin/env python3
"""Backup operasional DB ALFA: snapshot terverifikasi, retensi, offsite, drill.

Perintah
--------
``run`` (default)
    Buat snapshot hot-safe, verifikasi isi terhadap DB sumber, tulis sidecar
    jumlah tabel/baris, simpan salinan mingguan, lalu sinkronkan offsite bila
    ``ALFA_BACKUP_OFFSITE_REMOTE`` diisi.

``verify <archive>``
    Verifikasi integritas arsip: ``PRAGMA quick_check``, SHA-256 manifest,
    dan (bila sidecar tersedia) jumlah tabel/baris harus sama persis.

``restore-drill``
    Restore snapshot terbaru ke DB sementara, lalu bandingkan dengan sidecar.
    Tidak pernah menulis ke DB produksi.

Semua kegagalan verifikasi menghasilkan exit code 1 agar systemd menandai
unit gagal. Kegagalan offsite tidak menggagalkan backup lokal (hanya warning).

Environment
-----------
``ALFA_BACKUP_DIR``              direktori snapshot (default ``~/.alfa/backups``)
``ALFA_BACKUP_DAILY_KEEP``       jumlah snapshot harian (default 7)
``ALFA_BACKUP_WEEKLY_KEEP``      jumlah snapshot mingguan (default 4)
``ALFA_BACKUP_OFFSITE_REMOTE``   remote rclone, mis. ``gdrive1:alfa-backups``
``ALFA_BACKUP_RCLONE_TIMEOUT``   detik timeout sinkron offsite (default 300)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alfa.core.config import ensure_env_loaded  # noqa: E402
from alfa.core.db.backup_manager import (  # noqa: E402
    create_verified_db_snapshot,
    list_db_snapshots,
    restore_db_snapshot,
)

DEFAULT_BACKUP_DIR = Path.home() / ".alfa" / "backups"
SIDECAR_SUFFIX = ".counts.json"


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _backup_dir(value: str | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path(
        os.getenv("ALFA_BACKUP_DIR", str(DEFAULT_BACKUP_DIR))
    ).expanduser().resolve()


def _source_db() -> Path:
    """Path DB sumber, mengikuti resolusi env yang sama dengan aplikasi."""
    env_db = os.getenv("ALFA_DB_PATH", "").strip()
    if env_db:
        return Path(env_db).expanduser().resolve()
    return (ROOT / "agent_data.db").resolve()


def _sidecar_path(archive: Path) -> Path:
    return archive.with_name(archive.name + SIDECAR_SUFFIX)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    # Tabel virtual vss0 hanya bisa dihitung bila ekstensi tersedia. Muat
    # bila ada; bila tidak, inspect_db mencatatnya sebagai skipped.
    try:
        conn.enable_load_extension(True)
        import sqlite_vss

        sqlite_vss.load(conn)
    except (ImportError, OSError, sqlite3.Error):
        pass
    finally:
        try:
            conn.enable_load_extension(False)
        except sqlite3.Error:
            pass
    return conn


def inspect_db(path: Path) -> dict[str, Any]:
    """Baca integritas + jumlah baris semua tabel (read-only)."""
    if not path.exists():
        raise FileNotFoundError(f"DB tidak ditemukan: {path}")  # noqa: TRY003
    conn = _connect_ro(path)
    try:
        quick = conn.execute("PRAGMA quick_check").fetchall()
        healthy = len(quick) == 1 and str(quick[0][0]).lower() == "ok"
        names = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts: dict[str, int] = {}
        skipped: list[str] = []
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            try:
                # nosec B608 - identifier berasal dari sqlite_master, bukan input.
                row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()  # nosec B608
            except sqlite3.Error:
                # Virtual table (mis. vss0) tanpa ekstensi: catat, jangan gagal.
                skipped.append(name)
                continue
            counts[name] = int(row[0]) if row else 0
        return {
            "healthy": healthy,
            "quick_check": quick,
            "table_total": len(names),
            "tables": counts,
            "skipped": skipped,
        }
    finally:
        conn.close()


@contextmanager
def _open_archive(archive: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Ekstrak ``agent_data.db`` + manifest ke direktori sementara."""
    with tempfile.TemporaryDirectory(prefix="alfa_verify_") as tmp_dir:
        try:
            with tarfile.open(archive, "r:gz") as tar:
                member = tar.getmember("agent_data.db")
                tar.extract(member, path=tmp_dir, filter="data")
                manifest: dict[str, Any] = {}
                try:
                    manifest_member = tar.getmember("manifest.json")
                    stream = tar.extractfile(manifest_member)
                    if stream is not None:
                        manifest = json.loads(stream.read().decode("utf-8"))
                except (KeyError, json.JSONDecodeError, UnicodeDecodeError):
                    manifest = {}
        except (KeyError, tarfile.TarError, OSError) as exc:
            raise ValueError(  # noqa: TRY003
                f"Arsip tidak valid: {archive} ({exc})"
            ) from exc
        yield Path(tmp_dir) / "agent_data.db", manifest


def _load_sidecar(archive: Path) -> dict[str, Any]:
    sidecar = _sidecar_path(archive)
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _compare_counts(
    info: dict[str, Any],
    expected: dict[str, Any],
    *,
    exact: bool,
) -> list[str]:
    """Bandingkan hasil inspeksi dengan ekspektasi (monoton atau persis)."""
    problems: list[str] = []
    expected_tables = int(expected.get("table_total") or 0)
    if exact and expected_tables and info["table_total"] != expected_tables:
        problems.append(
            f"jumlah tabel {info['table_total']} != {expected_tables}"
        )
    if not exact and expected_tables and info["table_total"] < expected_tables:
        problems.append(
            f"jumlah tabel {info['table_total']} < {expected_tables}"
        )
    expected_rows = expected.get("tables") or {}
    if not isinstance(expected_rows, dict):
        return problems
    skipped = {str(item) for item in (info.get("skipped") or [])}
    skipped |= {str(item) for item in (expected.get("skipped") or [])}
    for name, expected_count in expected_rows.items():
        if str(name) in skipped:
            continue
        actual = info["tables"].get(str(name))
        if actual is None:
            problems.append(f"tabel '{name}' hilang")
            continue
        want = int(expected_count or 0)
        if exact and int(actual) != want:
            problems.append(f"baris '{name}' {actual} != {want}")
        if not exact and int(actual) < want:
            problems.append(f"baris '{name}' {actual} < {want}")
    return problems


def verify_archive(
    archive: Path,
    *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verifikasi arsip. ``expected`` memakai aturan monoton (sumber sebelum backup)."""
    problems: list[str] = []
    try:
        with _open_archive(archive) as (db_path, manifest):
            info = inspect_db(db_path)
            sha = _sha256(db_path)
    except (ValueError, sqlite3.Error, OSError) as exc:
        return {"status": "error", "problems": [str(exc)], "archive": str(archive)}

    if not info["healthy"]:
        problems.append(f"quick_check: {info['quick_check']}")
    manifest_sha = str(manifest.get("db_sha256") or "")
    if manifest_sha and manifest_sha != sha:
        problems.append("SHA-256 arsip tidak cocok dengan manifest")
    if info["table_total"] <= 0:
        problems.append("arsip tidak memuat tabel")

    sidecar = _load_sidecar(archive)
    if sidecar:
        problems.extend(_compare_counts(info, sidecar, exact=True))
    if expected is not None:
        problems.extend(_compare_counts(info, expected, exact=False))

    return {
        "status": "ok" if not problems else "error",
        "archive": str(archive),
        "sha256": sha,
        "sha256_manifest": manifest_sha,
        "table_total": info["table_total"],
        "tables": info["tables"],
        "skipped": info.get("skipped") or [],
        "sidecar": bool(sidecar),
        "problems": problems,
    }


def _write_sidecar(archive: Path, info: dict[str, Any]) -> None:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "archive": archive.name,
        "table_total": info["table_total"],
        "tables": info["tables"],
        "skipped": info.get("skipped") or [],
    }
    _sidecar_path(archive).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _prune_weekly(weekly_dir: Path, keep: int) -> list[str]:
    files = sorted(
        weekly_dir.glob("alfa_weekly_*.tar.gz"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for old in files[keep:]:
        try:
            old.unlink()
            _sidecar_path(old).unlink(missing_ok=True)
            removed.append(old.name)
        except OSError:
            continue
    return removed


def _copy_weekly(
    archive: Path,
    backup_dir: Path,
    keep: int,
    info: dict[str, Any],
) -> dict[str, Any]:
    stamp = datetime.now()
    week_key = f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"
    weekly_dir = backup_dir / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    target = weekly_dir / f"alfa_weekly_{week_key}.tar.gz"
    copied = False
    try:
        if not target.exists():
            shutil.copy2(archive, target)
            _write_sidecar(target, info)
            copied = True
        removed = _prune_weekly(weekly_dir, keep)
    except OSError as exc:
        return {"status": "error", "message": str(exc), "target": str(target)}
    return {
        "status": "ok",
        "target": str(target),
        "copied": copied,
        "rotated_out": removed,
    }


def _prune_orphan_sidecars(backup_dir: Path) -> int:
    removed = 0
    for sidecar in backup_dir.glob(f"alfa_snapshot_*.tar.gz{SIDECAR_SUFFIX}"):
        archive = sidecar.with_name(sidecar.name[: -len(SIDECAR_SUFFIX)])
        if not archive.exists():
            try:
                sidecar.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def sync_offsite(
    backup_dir: Path, remote: str, timeout: int
) -> dict[str, Any]:
    """Sinkronkan direktori backup ke remote rclone (fail-soft)."""
    if not remote:
        return {"status": "skipped", "reason": "remote kosong"}
    exe = shutil.which("rclone")
    if not exe:
        return {"status": "skipped", "reason": "rclone tidak ditemukan"}
    command = [
        exe,
        "sync",
        str(backup_dir),
        remote,
        "--transfers",
        "2",
        "--checkers",
        "4",
        "--timeout",
        "5m",
        "--stats",
        "0",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - argumen list, tanpa shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": str(exc)}
    if proc.returncode == 0:
        return {"status": "ok", "remote": remote}
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return {
        "status": "error",
        "remote": remote,
        "code": proc.returncode,
        "message": detail[-1] if detail else "rclone gagal",
    }


def run_backup(
    *,
    backup_dir: Path | None = None,
    daily_keep: int | None = None,
    weekly_keep: int | None = None,
    offsite_remote: str | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Buat + verifikasi snapshot, simpan mingguan, sinkron offsite."""
    ensure_env_loaded()
    out_dir = (backup_dir or _backup_dir()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    daily_keep = daily_keep or _int_env("ALFA_BACKUP_DAILY_KEEP", 7)
    weekly_keep = weekly_keep or _int_env("ALFA_BACKUP_WEEKLY_KEEP", 4)
    remote = (
        offsite_remote
        if offsite_remote is not None
        else os.getenv("ALFA_BACKUP_OFFSITE_REMOTE", "").strip()
    )
    timeout = timeout or _int_env("ALFA_BACKUP_RCLONE_TIMEOUT", 300)

    source = _source_db()
    try:
        before = inspect_db(source)
    except (sqlite3.Error, OSError) as exc:
        return {"status": "error", "stage": "source", "message": str(exc)}

    snapshot = create_verified_db_snapshot(
        db_path=str(source), backup_dir=str(out_dir), max_backups=daily_keep
    )
    if snapshot.get("status") != "success":
        return {"status": "error", "stage": "snapshot", "detail": snapshot}

    archive = Path(str(snapshot["snapshot_path"]))
    verification = verify_archive(archive, expected=before)
    if verification.get("status") != "ok":
        return {
            "status": "error",
            "stage": "verify",
            "archive": str(archive),
            "problems": verification.get("problems"),
        }
    _write_sidecar(archive, verification)

    weekly = _copy_weekly(archive, out_dir, weekly_keep, verification)
    offsite = sync_offsite(out_dir, remote, timeout)
    orphan_removed = _prune_orphan_sidecars(out_dir)

    return {
        "status": "ok",
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "source": str(source),
        "source_bytes": source.stat().st_size,
        "table_total": verification["table_total"],
        "sha256": verification["sha256"],
        "daily_keep": daily_keep,
        "weekly": weekly,
        "offsite": offsite,
        "orphan_sidecars_removed": orphan_removed,
    }


def restore_drill(
    archive: Path | None = None, *, backup_dir: Path | None = None
) -> dict[str, Any]:
    """Restore snapshot terbaru ke DB sementara dan bandingkan dengan sidecar."""
    ensure_env_loaded()
    out_dir = (backup_dir or _backup_dir()).resolve()
    chosen = archive
    if chosen is None:
        listing = list_db_snapshots(backup_dir=str(out_dir))
        snapshots = listing.get("snapshots") or []
        if not snapshots:
            return {"status": "error", "message": "Tidak ada snapshot untuk drill."}
        chosen = Path(str(snapshots[0]["path"]))
    if not chosen.exists():
        return {"status": "error", "message": f"Snapshot tidak ada: {chosen}"}

    with tempfile.TemporaryDirectory(prefix="alfa_drill_") as tmp_dir:
        target = Path(tmp_dir) / "restored_agent_data.db"
        restored = restore_db_snapshot(str(chosen), target_db_path=str(target))
        if restored.get("status") != "success":
            return {
                "status": "error",
                "stage": "restore",
                "detail": restored,
                "archive": str(chosen),
            }
        try:
            info = inspect_db(target)
        except (sqlite3.Error, OSError) as exc:
            return {"status": "error", "stage": "inspect", "message": str(exc)}

    problems: list[str] = []
    if not info["healthy"]:
        problems.append(f"quick_check: {info['quick_check']}")
    sidecar = _load_sidecar(chosen)
    if sidecar:
        problems.extend(_compare_counts(info, sidecar, exact=True))
    else:
        problems.append("sidecar tidak tersedia (verifikasi terbatas)")

    return {
        "status": "ok" if not problems else "error",
        "archive": str(chosen),
        "table_total": info["table_total"],
        "tables": info["tables"],
        "skipped": info.get("skipped") or [],
        "sidecar": bool(sidecar),
        "problems": problems,
    }


def _print_report(result: dict[str, Any], title: str) -> None:
    print(f"[{title}] status={result.get('status')}", flush=True)
    for key, value in result.items():
        if key in {"status", "tables"}:
            continue
        if isinstance(value, dict):
            inner = ", ".join(f"{k}={v}" for k, v in value.items())
            print(f"  {key}: {inner}", flush=True)
        else:
            print(f"  {key}: {value}", flush=True)
    tables = result.get("tables")
    if isinstance(tables, dict):
        nonzero = {k: v for k, v in tables.items() if v}
        print(f"  tables_total: {len(tables)} (non-zero: {len(nonzero)})", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Buat snapshot terverifikasi + offsite")
    run.add_argument("--backup-dir", default=None)
    run.add_argument("--daily-keep", type=int, default=None)
    run.add_argument("--weekly-keep", type=int, default=None)
    run.add_argument("--offsite-remote", default=None)
    run.add_argument("--timeout", type=int, default=None)

    verify = sub.add_parser("verify", help="Verifikasi satu arsip")
    verify.add_argument("archive")

    drill = sub.add_parser("restore-drill", help="Uji restore snapshot terbaru")
    drill.add_argument("--archive", default=None)
    drill.add_argument("--backup-dir", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = args.command or "run"
    try:
        if command == "run":
            result = run_backup(
                backup_dir=Path(args.backup_dir) if args.backup_dir else None,
                daily_keep=args.daily_keep,
                weekly_keep=args.weekly_keep,
                offsite_remote=args.offsite_remote,
                timeout=args.timeout,
            )
            _print_report(result, "backup")
        elif command == "verify":
            result = verify_archive(Path(args.archive))
            _print_report(result, "verify")
        else:
            result = restore_drill(
                Path(args.archive) if args.archive else None,
                backup_dir=Path(args.backup_dir) if args.backup_dir else None,
            )
            _print_report(result, "restore-drill")
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"[{command}] fatal: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
