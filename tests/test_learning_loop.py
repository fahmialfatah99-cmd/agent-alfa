"""
Unit tests for Hermes-Style Learning Loop in ALFA OS.
"""

from alfa.core.brain.learning_loop import (
    audit_against_learned_skills,
    detect_and_process_user_correction,
    format_learned_skills_prompt,
    get_learning_loop_metrics,
    init_learning_tables,
    is_positive_reinforcement_signal,
    is_user_correction_signal,
    query_learned_skills,
    record_agent_experience,
    record_trajectory,
    reinforce_skill,
    retrieve_relevant_skills,
    seed_initial_critical_skills,
    smart_extract_user_rule,
    synthesize_skill_from_experience,
)


def test_init_and_seed_learning_tables():
    init_learning_tables()
    count = seed_initial_critical_skills()
    assert count >= 4


def test_synthesize_and_retrieve_skills():
    res = synthesize_skill_from_experience(
        topic="CLUSTER_CURUP_FO",
        trigger_pattern="curup cluster material tiang kabel",
        learned_rule="Cluster Curup menggunakan ODP 8 port dan tiang 7 meter 3 inch.",
    )
    assert res["status"] == "success"
    assert res["topic"] == "CLUSTER_CURUP_FO"

    # Query matching skills
    matched = retrieve_relevant_skills("tolong rekap material cluster curup")
    assert len(matched) >= 1
    assert any("CURUP" in m["topic"] for m in matched)

    # Format prompt block
    prompt_str = format_learned_skills_prompt("curup material")
    assert "HERMES LEARNING LOOP" in prompt_str
    assert "CLUSTER_CURUP_FO" in prompt_str


def test_record_trajectory():
    row_id = record_trajectory(
        user_prompt="Berapa tiang lahat?",
        tool_calls=[{"tool": "reconcile_whatsapp_material_group", "args": {}}],
        result_summary="160 tiang",
        success=True,
        feedback="Jawaban akurat",
        category="telecom",
    )
    assert row_id > 0


def test_learning_loop_tools():
    # Test record_agent_experience tool
    res_rec = record_agent_experience(
        topic="AUTONOMY_RULE",
        lesson_learned="Selalu verifikasi formula dinamis sebelum menyimpan spreadsheet.",
        trigger_pattern="formula excel dynamic",
    )
    assert res_rec["status"] == "success"
    assert "AUTONOMY_RULE" in res_rec["topic"]

    # Test query_learned_skills tool
    res_query = query_learned_skills("dynamic excel")
    assert res_query["status"] == "success"
    assert res_query["count"] >= 1


def test_auto_reflexion_correction_detection():
    # 1. Deteksi sinyal koreksi
    assert is_user_correction_signal("salah, total tiang yang benar adalah 160")
    assert is_user_correction_signal("bukan begitu, harusnya mandor mugi")
    assert not is_user_correction_signal("halo apa kabar")

    # 2. Sintesis koreksi otomatis
    res_corr = detect_and_process_user_correction("koreksi: tiang lahat net 160 btg mandor mugi")
    assert res_corr is not None
    assert res_corr["status"] == "success"
    assert "TELECOM_FIELD_LOGISTICS" in res_corr["topic"]


def test_audit_against_learned_skills():
    # Test validasi respon jika menyalahi aturan 160 tiang Lahat
    is_valid, msg, corrected = audit_against_learned_skills(
        user_prompt="Berapa total tiang Lahat?",
        reply_text="Berdasarkan rekap, total bersih 140 batang tiang.",
    )
    assert not is_valid
    assert "160 batang" in corrected
    assert "CLUSTER_LAHAT_MATERIAL" in msg

    # Respon yang sudah benar lolos audit
    is_valid_ok, _, _ = audit_against_learned_skills(
        user_prompt="Berapa total tiang Lahat?",
        reply_text="Total bersih adalah 160 batang tiang.",
    )
    assert is_valid_ok


def test_get_learning_loop_metrics():
    metrics = get_learning_loop_metrics()
    assert metrics["status"] == "success"
    assert metrics["total_active_skills"] >= 4
    assert metrics["total_trajectories"] >= 1
    assert "Hermes" in metrics["learning_engine"]
    assert "avg_confidence" in metrics
    assert "total_hits" in metrics


def test_smart_extract_user_rule():
    topic, rule, trigger = smart_extract_user_rule(
        "salah, harusnya mandor mugi ambil 61 batang bukan 68"
    )
    assert topic == "TELECOM_FIELD_LOGISTICS"
    assert "61 batang" in rule
    assert "mugi" in trigger


def test_positive_reinforcement_and_hebbian_learning():
    assert is_positive_reinforcement_signal("mantap, hasilnya sudah sangat akurat!")
    assert is_positive_reinforcement_signal("sip keren top")
    assert not is_positive_reinforcement_signal("coba hitung lagi")

    # Reinforce skill positive
    res_pos = reinforce_skill("CLUSTER_LAHAT_MATERIAL", success=True, weight_delta=0.05)
    assert res_pos is True

    # Reinforce skill negative
    res_neg = reinforce_skill("CLUSTER_LAHAT_MATERIAL", success=False, weight_delta=0.05)
    assert res_neg is True


