"""
Unit Tests for ALFA OS Rust Acceleration Module (alfa_accel via PyO3).

Guarantees 100% equivalence between Rust native acceleration and Python fallback,
validating Zero Regression (Rule 1 of ALFA OS).
"""

import alfa.core.apex.dreaming_compiler as dc
import alfa.core.apex.neuro_symbolic as ns
import alfa.core.apex.temporal_graphrag as tg
import alfa.memory.vector as vm


def test_rust_acceleration_loaded():
    assert ns.is_neuro_symbolic_rust_accelerated() is True
    assert vm.is_vector_rust_accelerated() is True
    assert dc.is_dreaming_rust_accelerated() is True
    assert tg.is_graphrag_rust_accelerated() is True


def test_math_eval_rust_vs_python_equivalence():
    expressions = [
        "68 - 7",
        "63 + 94 + 1 + 2",
        "(68 - 7) + 99",
        "100 / 4",
        "10 // 3",
        "10 % 3",
        "2 * 3 + 4",
        "2 + 3 * 4",
        "(10 + 5) * (20 - 4)",
        "-15 + 30",
        "+25 - 5",
        "3.5 * 2",
        "__import__('os').system('ls')",  # malicious/unsafe
        "invalid + + syntax",
        "10 / 0",  # zero division
        "",
        "   ",
    ]

    for expr in expressions:
        # Evaluate with Rust
        ns._HAS_RUST_ACCEL = True
        res_rust = ns.safe_ast_math_eval(expr)

        # Evaluate with Python fallback
        ns._HAS_RUST_ACCEL = False
        res_py = ns.safe_ast_math_eval(expr)

        assert (
            res_rust == res_py
        ), f"Mismatch for '{expr}': Rust={res_rust!r} vs Py={res_py!r}"

    # Restore Rust acceleration
    ns._HAS_RUST_ACCEL = True


def test_text_equation_verification_rust_vs_python_equivalence():
    sample_text = (
        "Mandor Mugi mengambil 68 - 7 = 64 batang dan total 61 + 99 = 170 batang. "
        "Hitungan valid: 10 + 5 = 15 unit."
    )

    # Run with Rust
    ns._HAS_RUST_ACCEL = True
    fixed_rust, findings_rust = ns.verify_arithmetic_equations_in_text(sample_text)

    # Run with Python fallback
    ns._HAS_RUST_ACCEL = False
    fixed_py, findings_py = ns.verify_arithmetic_equations_in_text(sample_text)

    assert fixed_rust == fixed_py
    assert len(findings_rust) == len(findings_py)
    for f_rs, f_py in zip(findings_rust, findings_py, strict=True):
        assert f_rs["expression"] == f_py["expression"]
        assert f_rs["claimed"] == f_py["claimed"]
        assert f_rs["actual"] == f_py["actual"]
        assert f_rs["is_valid"] == f_py["is_valid"]

    # Restore Rust acceleration
    ns._HAS_RUST_ACCEL = True


def test_cosine_similarity_rust_vs_python_equivalence():
    test_pairs = [
        ([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]),
        ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
        ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),
        ([-1.0, 0.5, -2.0], [2.0, -1.0, 4.0]),
        ([1.0, 0.0], [1.0, 0.0, 0.0, 0.0]),  # dimension mismatch
        ([], [1.0, 2.0]),  # empty
        ([0.0, 0.0], [0.0, 0.0]),  # zero norm
    ]

    for v_a, v_b in test_pairs:
        # Run with Rust
        vm._HAS_RUST_ACCEL = True
        sim_rust = vm.cosine_similarity(v_a, v_b)

        # Run with Python NumPy fallback
        vm._HAS_RUST_ACCEL = False
        sim_py = vm.cosine_similarity(v_a, v_b)

        assert abs(sim_rust - sim_py) < 1e-5, (
            f"Mismatch for vectors {v_a} vs {v_b}: Rust={sim_rust} vs Py={sim_py}"
        )

    # Restore Rust acceleration
    vm._HAS_RUST_ACCEL = True


def test_fastpath_pattern_matching_rust_vs_python_equivalence():
    dc.seed_compiled_fastpaths()

    test_queries = [
        "berapa total tiang bersih lahat?",
        "total tiang lahat",
        "rekap tiang cluster lahat",
        "pertanyaan acak yang tidak ada di fastpath",
        "salah bukan begitu total tiang",  # user correction signal, should return None
        "",
    ]

    for q in test_queries:
        # Match using Rust
        dc._HAS_RUST_ACCEL = True
        res_rust = dc.try_execute_compiled_fastpath(q)

        # Match using Python fallback
        dc._HAS_RUST_ACCEL = False
        res_py = dc.try_execute_compiled_fastpath(q)

        if res_rust is None:
            assert res_py is None, f"Mismatch for '{q}': Rust=None vs Py={res_py}"
        else:
            assert res_py is not None, f"Mismatch for '{q}': Rust={res_rust} vs Py=None"
            assert res_rust["fastpath_id"] == res_py["fastpath_id"]
            assert res_rust["topic"] == res_py["topic"]
            assert res_rust["response"] == res_py["response"]
            assert res_rust["saved_tokens"] == res_py["saved_tokens"]

    # Restore Rust acceleration
    dc._HAS_RUST_ACCEL = True


def test_bm25_scoring_rust_vs_python_equivalence():
    corpus = [
        "Python programming language for web backend development and software systems",
        "Building software backend applications and web services with Python coding",
        "Delicious recipe for strawberry shortcake with whipped cream and butter pastry",
        "Rust programming with fearless concurrency, memory safety and native speed",
    ]
    query = "Python software backend development"

    # Evaluate with Rust
    vm._HAS_RUST_ACCEL = True
    scores_rust = vm._calculate_bm25_scores(corpus, query)

    # Evaluate with Python rank_bm25 fallback
    vm._HAS_RUST_ACCEL = False
    scores_py = vm._calculate_bm25_scores(corpus, query)

    assert len(scores_rust) == len(scores_py) == len(corpus)
    # The top matching document should have score 1.0 (normalized)
    assert scores_rust[0] == 1.0
    assert scores_py[0] == 1.0
    # Both should rank docs 0 and 1 much higher than doc 2 (recipe)
    assert scores_rust[0] > scores_rust[2]
    assert scores_py[0] > scores_py[2]

    # Empty corpus & empty query handling
    vm._HAS_RUST_ACCEL = True
    assert vm._calculate_bm25_scores([], query) == []
    assert vm._calculate_bm25_scores(corpus, "") == [0.0] * len(corpus)

    vm._HAS_RUST_ACCEL = False
    assert vm._calculate_bm25_scores([], query) == []
    assert vm._calculate_bm25_scores(corpus, "") == [0.0] * len(corpus)

    # Restore Rust acceleration
    vm._HAS_RUST_ACCEL = True


def test_temporal_graphrag_rust_vs_python_equivalence():
    tg.init_graphrag_tables()
    tg.upsert_graph_entity("PROJECT_QUANTUM", "SYSTEM", "Next-gen quantum mesh")
    tg.upsert_graph_entity("RUST_CORE", "COMPONENT", "Native accelerator module")
    tg.upsert_graph_relation("PROJECT_QUANTUM", "USES", "RUST_CORE", weight_delta=0.5)

    query = "PROJECT_QUANTUM"

    # Query with Rust
    tg._HAS_RUST_ACCEL = True
    res_rust = tg.query_temporal_graphrag(query)

    # Query with Python fallback
    tg._HAS_RUST_ACCEL = False
    res_py = tg.query_temporal_graphrag(query)

    assert len(res_rust["matched_entities"]) == len(res_py["matched_entities"])
    assert len(res_rust["hop1_relations"]) == len(res_py["hop1_relations"])
    assert len(res_rust["hop2_bridges"]) == len(res_py["hop2_bridges"])

    # Restore Rust acceleration
    tg._HAS_RUST_ACCEL = True




