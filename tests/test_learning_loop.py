"""
Unit tests for Hermes-Style Learning Loop in ALFA OS.
"""

from alfa.core.brain.learning_loop import (
    format_learned_skills_prompt,
    init_learning_tables,
    query_learned_skills,
    record_agent_experience,
    record_trajectory,
    retrieve_relevant_skills,
    seed_initial_critical_skills,
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
