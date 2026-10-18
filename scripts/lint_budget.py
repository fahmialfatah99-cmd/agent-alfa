#!/usr/bin/env python3
"""Lint budget TRY/BLE — pola mypy-baseline, granularitas per-instans.

Budget disimpan di ``pyproject.toml``, dua sumber:

1. Region otomatis di bawah ``[tool.ruff.lint.per-file-ignores]``:

       "alfa/bot/advanced_commands.py" = ["BLE001", "TRY300"]  # n=BLE001:18,TRY300:2

   daftar kode ditekan ruff (utang lama); komentar ``n=`` menyimpan JUMLAH
   instans per kode saat budget dibuat.

2. Entri manual pre-existing di luar region (file yang sudah di-ignore untuk
   kode lain). ``--apply`` menambahkan/memperbarui komentar ``# n=...`` pada
   baris entri itu agar jumlah TRY/BLE-nya juga terkunci.

``--check`` membandingkan jumlah raw (``ruff --isolated``, tanpa suppression)
terhadap anggaran: bertambah = exit 1; menyusut = aman (jalankan ``--apply``
untuk mengecilkan budget). Pelanggaran di file baru juga merah via
``ruff check .`` biasa karena file itu tidak tercantum di budget.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SELECT = ("TRY", "BLE")
CODE_PREFIXES = ("TRY", "BLE")

BEGIN = (
    "# ==== lint budget TRY/BLE (dibuat otomatis: scripts/lint_budget.py) ====\n"
)
END = "# ==== akhir lint budget ====\n"

RE_COUNTS = re.compile(r"#\s*n=([\w]+:\d+(?:,[\w]+:\d+)*)")


def _ruff_stdout(select: str, *, isolated: bool) -> str:
    """Jalankan ruff dgn seleksi tertentu; kembalikan stdout format concise."""
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        select,
        "--output-format",
        "concise",
    ]
    if isolated:
        cmd.append("--isolated")
    cmd.append(".")
    proc = subprocess.run(  # noqa: S603 — argumen statis, tanpa input eksternal
        cmd, cwd=ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode not in (0, 1):
        # exit 2 = error konfigurasi/parse — JANGAN dianggap "0 pelanggaran"
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise SystemExit(f"ruff gagal (exit {proc.returncode}):\n{msg[:2000]}")
    return proc.stdout


def _violations_counts(*, raw: bool = False) -> dict[str, dict[str, int]]:
    """{file: {kode: jumlah_instans}} dari ruff --select TRY,BLE."""
    stdout = _ruff_stdout(",".join(SELECT), isolated=raw)
    out: dict[str, dict[str, int]] = {}
    for line in stdout.splitlines():
        tokens = line.split(":", 3)  # path, line, col, " CODE message"
        if len(tokens) < 4:
            continue
        message = tokens[3].strip()
        code = message.split(" ", 1)[0]
        if not code.startswith(CODE_PREFIXES):
            continue
        per_file = out.setdefault(tokens[0], {})
        per_file[code] = per_file.get(code, 0) + 1
    return out


def _counts_from_line(line: str) -> dict[str, int] | None:
    m = RE_COUNTS.search(line)
    if not m:
        return None
    counts: dict[str, int] = {}
    for pair in m.group(1).split(","):
        code, num = pair.split(":")
        counts[code] = int(num)
    return counts


def _budget_map(text: str) -> tuple[dict[str, dict[str, int]], bool]:
    """Parse region budget → ({file: {kode: count}}, region_ada)."""
    budget: dict[str, dict[str, int]] = {}
    in_region = False
    region_present = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped == BEGIN.strip():
            in_region = True
            region_present = True
            continue
        if stripped == END.strip():
            in_region = False
            continue
        if not in_region or not stripped.startswith('"'):
            continue
        head, _, tail = stripped.partition('" = [')
        path = head.strip().strip('"')
        codes_part = tail.partition("]")[0]
        codes = {c.strip().strip('"') for c in codes_part.split(",") if c}
        counts = _counts_from_line(raw_line) or {}
        entry = dict.fromkeys(sorted(codes), 0)
        entry.update(counts)
        budget[path] = entry
    return budget, region_present


def _manual_entries(text: str, region_keys: set[str]) -> dict[str, str]:
    """Baris entri per-file-ignores di luar region (pola → baris aslinya)."""
    manual: dict[str, str] = {}
    in_region = False
    data = tomllib.loads(text)
    table_keys = {
        k for k, v in (
            data.get("tool", {}).get("ruff", {}).get("lint", {})
            .get("per-file-ignores", {})
        ).items()
    }
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped == BEGIN.strip():
            in_region = True
            continue
        if stripped == END.strip():
            in_region = False
            continue
        if in_region or not (stripped.startswith('"') and '" = [' in stripped):
            continue
        key = stripped.split('" = [', 1)[0].strip().strip('"')
        if key not in region_keys and key in table_keys:
            manual[key] = raw_line
    return manual


def check() -> int:
    text = PYPROJECT.read_text(encoding="utf-8")
    budget, region_present = _budget_map(text)
    manual = _manual_entries(text, set(budget))
    manual_counts = {path: _counts_from_line(line) for path, line in manual.items()}
    if not budget or not region_present:
        print(
            "Region budget kosong/tidak ada — jalankan: "
            "python scripts/lint_budget.py --apply",
            file=sys.stderr,
        )
        return 2
    now = _violations_counts(raw=True)
    langgar: list[tuple[str, str, int, int]] = []
    for path, counts in now.items():
        region_counts = budget.get(path)
        manual_for_path = manual_counts.get(path)
        for code, jumlah in sorted(counts.items()):
            anggaran = (
                (region_counts or {}).get(code)
                if region_counts is not None
                else (manual_for_path or {}).get(code)
                if manual_for_path is not None
                else None
            )
            if anggaran is None:
                langgar.append((path, code, jumlah, 0))
            elif jumlah > anggaran:
                langgar.append((path, code, jumlah, anggaran))
    if langgar:
        print(f"LANGGAR BUDGET — {len(langgar)} pasang (file,kode) bertambah:")
        for path, code, jumlah, anggaran in sorted(langgar)[:30]:
            print(f"  {path}: {code} {jumlah}/{anggaran}")
        return 1
    total = sum(sum(c.values()) for c in now.values())
    print(f"Budget sesuai: {total} instans di {len(now)} file (dalam anggaran)")
    return 0


def _upsert_manual_counts(text: str, manual: dict[str, str],
                          counts: dict[str, dict[str, int]]) -> str:
    """Tambahkan/perbarui komentar ``# n=...`` pada baris entri manual."""
    for path, line in sorted(manual.items(), key=lambda kv: text.find(kv[1])):
        if path not in counts:
            continue
        counts_str = ",".join(
            f"{c}:{n}" for c, n in sorted(counts[path].items())
        )
        counts_comment = f"  # n={counts_str}"
        new_line = re.sub(r"\s*#\s*n=([\w]+:\d+(?:,[\w]+:\d+)*)", "", line)
        new_line = new_line.rstrip() + counts_comment + "\n"
        text = text.replace(line, new_line, 1)
    return text


def apply() -> int:
    now = _violations_counts(raw=True)
    text_lama = PYPROJECT.read_text(encoding="utf-8")
    budget_lama, _ = _budget_map(text_lama)
    manual = _manual_entries(text_lama, set(budget_lama))

    entries = []
    for path in sorted(set(now) - set(manual)):
        counts = now[path]
        codes = ", ".join(f'"{c}"' for c in sorted(counts))
        counts_str = ",".join(f"{c}:{n}" for c, n in sorted(counts.items()))
        entries.append(f'"{path}" = [{codes}]  # n={counts_str}')
    block = (
        BEGIN + "\n".join(entries) + "\n" + END if entries else BEGIN + "\n" + END
    )

    start = text_lama.find(BEGIN)
    stop = text_lama.find(END)
    if start != -1 and stop != -1:
        stop += len(END)
        text = text_lama[:start] + block + text_lama[stop:]
    else:
        anchor = "[tool.ruff.lint.per-file-ignores]\n"
        assert anchor in text_lama, "per-file-ignores tidak ketemu"
        text = text_lama.replace(anchor, anchor + block + "\n", 1)
    text = _upsert_manual_counts(text, manual, now)
    tomllib.loads(text)  # validasi hasil parse sebelum menulis
    PYPROJECT.write_text(text, encoding="utf-8")
    total = sum(sum(c.values()) for c in now.values())
    print(f"Budget pyproject diperbarui: {len(entries)} file di region, "
          f"{len(manual)} file manual, {total} instans")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--apply" in argv:
        return apply()
    return check()


if __name__ == "__main__":
    sys.exit(main())
