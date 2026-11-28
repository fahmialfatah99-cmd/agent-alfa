#!/usr/bin/env python3
"""Benchmark reproducible: Rust ``alfa_accel`` vs fallback Python/NumPy.

Jalankan dari root repo:

    venv/bin/python scripts/bench_rust_accel.py
    venv/bin/python scripts/bench_rust_accel.py --json

Angka yang dicetak adalah median dari beberapa pengulangan pada mesin ini.
Hasil bisa berbeda antar-CPU; jangan jadikan klaim universal.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

REPEATS = 3
MATH_EXPRESSIONS = 20_000
COSINE_PAIRS = 20_000
BATCH_VECTORS = 5_000
BM25_DOCS = 300
BM25_RUNS = 30
FASTPATH_PROMPTS = 5_000


def _median_time(fn: Callable[[], Any], repeats: int = REPEATS) -> float:
    fn()  # warm-up
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples)


@contextmanager
def _rust_flag(module: Any, enabled: bool):
    previous = module._HAS_RUST_ACCEL
    module._HAS_RUST_ACCEL = enabled
    try:
        yield
    finally:
        module._HAS_RUST_ACCEL = previous


def _speedup(rust: float, python: float) -> float:
    return python / rust if rust > 0 else 0.0


def _row(name: str, rust: float, python: float, unit: str) -> dict[str, Any]:
    return {
        "operation": name,
        "rust_seconds": round(rust, 6),
        "python_seconds": round(python, 6),
        "speedup": round(_speedup(rust, python), 2),
        "unit": unit,
    }


def _bench_math() -> dict[str, Any]:
    import alfa.core.apex.neuro_symbolic as ns

    expressions = [
        "68 - 7",
        "63 + 94 + 1 + 2",
        "(68 - 7) + 99",
        "10 / 4",
        "2 * 3 + 4",
    ] * (MATH_EXPRESSIONS // 5)

    with _rust_flag(ns, True):
        rust = _median_time(lambda: [ns.safe_ast_math_eval(e) for e in expressions])
    with _rust_flag(ns, False):
        python = _median_time(lambda: [ns.safe_ast_math_eval(e) for e in expressions])
    return _row(f"math ({MATH_EXPRESSIONS:,} expr)", rust, python, "expr")


def _bench_cosine_single(rng: random.Random) -> dict[str, Any]:
    import numpy as np

    import alfa.memory.vector as vm

    vec_a = [rng.random() for _ in range(768)]
    vec_b = [rng.random() for _ in range(768)]

    def _numpy() -> None:
        a = np.asarray(vec_a, dtype=np.float32)
        b = np.asarray(vec_b, dtype=np.float32)
        _ = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def _rust() -> None:
        with _rust_flag(vm, True):
            _ = vm.cosine_similarity(vec_a, vec_b)

    rust = _median_time(lambda: [_rust() for _ in range(COSINE_PAIRS)])
    python = _median_time(lambda: [_numpy() for _ in range(COSINE_PAIRS)])
    return _row(f"cosine 1-pair 768d ({COSINE_PAIRS:,}x)", rust, python, "pair")


def _bench_batch_json(rng: random.Random) -> dict[str, Any]:
    import json as jsonlib

    import alfa_accel
    import numpy as np

    query = [rng.random() for _ in range(768)]
    vectors = [[rng.random() for _ in range(768)] for _ in range(BATCH_VECTORS)]
    raw = [jsonlib.dumps(v) for v in vectors]

    def _rust() -> None:
        _ = alfa_accel.batch_cosine_from_json_strings(query, raw)

    def _numpy() -> None:
        matrix = np.asarray([jsonlib.loads(item) for item in raw], dtype=np.float32)
        q = np.asarray(query, dtype=np.float32)
        _ = (matrix @ q) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q))

    rust = _median_time(_rust)
    python = _median_time(_numpy)
    return _row(
        f"batch cosine dari JSON ({BATCH_VECTORS:,}x768)",
        rust,
        python,
        "batch",
    )


def _bench_bm25(rng: random.Random) -> dict[str, Any]:
    import alfa.memory.vector as vm

    words = [f"w{i}" for i in range(300)]
    corpus = [" ".join(rng.choices(words, k=120)) for _ in range(BM25_DOCS)]
    query = " ".join(rng.choices(words, k=5))

    with _rust_flag(vm, True):
        rust = _median_time(
            lambda: [vm._calculate_bm25_scores(corpus, query) for _ in range(BM25_RUNS)]
        )
    with _rust_flag(vm, False):
        python = _median_time(
            lambda: [vm._calculate_bm25_scores(corpus, query) for _ in range(BM25_RUNS)]
        )
    return _row(f"BM25 ({BM25_RUNS}x{BM25_DOCS} dok)", rust, python, "run")


def _bench_fastpath() -> dict[str, Any]:
    import alfa_accel

    patterns = [
        r"^\s*(?:berapa|cek|info|total|rekap)?\s*(?:jumlah\s+|total\s+)?"
        r"tiang\s+(?:bersih\s+|net\s+)?(?:cluster\s+)?lahat\s*\??\s*$"
    ]
    patterns += [rf"^\s*pertanyaan\s+nomor\s+{i}\s*\??\s*$" for i in range(49)]
    prompts = [f"pertanyaan nomor {i % 50}" for i in range(FASTPATH_PROMPTS)]

    engine = alfa_accel.FastPathEngine()
    engine.set_patterns(list(enumerate(patterns)))
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def _rust() -> None:
        for prompt in prompts:
            engine.find_match(prompt)

    def _python() -> None:
        for prompt in prompts:
            for regex in compiled:
                if regex.match(prompt):
                    break

    rust = _median_time(_rust)
    python = _median_time(_python)
    return _row(
        f"FastPath ({FASTPATH_PROMPTS:,} prompt x {len(patterns)} pola)",
        rust,
        python,
        "batch",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="cetak hasil sebagai JSON")
    args = parser.parse_args()

    try:
        import alfa_accel
    except ImportError:
        print(
            "alfa_accel belum dibangun. Jalankan build Rust sesuai docs/INSTALL.md "
            "(bagian 'Akselerasi Rust')."
        )
        return 0

    if not alfa_accel.is_rust_accelerated():
        print("alfa_accel terpasang tetapi tidak melaporkan akselerasi Rust.")
        return 1

    rng = random.Random(42)
    rows = [
        _bench_math(),
        _bench_cosine_single(rng),
        _bench_batch_json(rng),
        _bench_bm25(rng),
        _bench_fastpath(),
    ]

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"Rust alfa_accel: {alfa_accel.__file__}")
    print(f"{'Operasi':<44} {'Rust':>10} {'Python':>10} {'Speedup':>9}")
    print("-" * 78)
    for row in rows:
        print(
            f"{row['operation']:<44} "
            f"{row['rust_seconds']:>9.3f}s "
            f"{row['python_seconds']:>9.3f}s "
            f"{row['speedup']:>8.2f}x"
        )
    print(
        "\nCatatan: speedup bergantung pada CPU, ukuran data, dan versi dependensi; "
        "angka ini bukan jaminan universal."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
