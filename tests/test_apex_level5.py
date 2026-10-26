"""
Comprehensive Unit Tests for Level 5+ Sovereign Cognitive Apex Engine (ALFA OS).

Tests all 5 Apex Pillars:
1. Neuro-Symbolic Verification Engine (AST Math Prover & Invariant Solver)
2. Offline 'Dreaming Mode' & Deterministic Fast-Path Compiler
3. Predictive Operational World-Model (Pre-emptive Field Anomaly Detection)
4. Shadow-Git Canary Self-Evolution (3-Stage Gate & Automatic Canary Rollback)
5. Adaptive Hardware & Thermal Governor (Host Telemetry & Quarantine Enforcement)
"""

from alfa.core.apex import (
    analyze_field_event_preemptively,
    apex_neuro_symbolic_verify,
    apex_run_dreaming_consolidation,
    apex_synthesize_dynamic_tool,
    apex_system_telemetry,
    get_apex_full_status,
    get_canary_evolution_metrics,
    get_hardware_governor_state,
    get_world_model_summary,
    is_service_quarantined,
    run_idle_dreaming_cycle,
    safe_ast_math_eval,
    synthesize_and_hotload_tool,
    try_execute_compiled_fastpath,
    verify_and_prove_response,
    verify_arithmetic_equations_in_text,
    verify_code_via_canary_gate,
)


def test_pillar1_neuro_symbolic_ast_prover():
    # Safe AST evaluation
    assert safe_ast_math_eval("68 - 7") == 61
    assert safe_ast_math_eval("63 + 94 + 1 + 2") == 160
    assert safe_ast_math_eval("(68 - 7) + 99") == 160
    # Reject unsafe non-math strings
    assert safe_ast_math_eval("__import__('os').system('ls')") is None

    # Auto-repair miscalculated inline equations
    raw_text = "Mandor Mugi mengambil 68 - 7 = 64 batang dan total 61 + 99 = 170 batang."
    fixed_text, findings = verify_arithmetic_equations_in_text(raw_text)
    assert "68 - 7 = 61" in fixed_text
    assert "61 + 99 = 160" in fixed_text
    assert len(findings) == 2
    assert not findings[0]["is_valid"]
    assert not findings[1]["is_valid"]

    # Domain Invariant Prover for Lahat
    res = verify_and_prove_response(
        user_prompt="Berapa total tiang Lahat?",
        reply_text="Total bersih adalah 145 batang untuk cluster Lahat.",
    )
    assert not res["is_valid"]
    assert "160 batang" in res["corrected_reply"]
    assert len(res["symbolic_proofs"]) >= 1


def test_pillar2_dreaming_fastpath_compiler():
    cycle_res = run_idle_dreaming_cycle(force=True)
    assert cycle_res["status"] == "success"
    assert cycle_res["seeded_fastpaths"] >= 1

    # Sub-millisecond fastpath execution for Lahat pole summary
    fp_hit = try_execute_compiled_fastpath("berapa total tiang bersih lahat?")
    assert fp_hit is not None
    assert "160 Batang" in fp_hit["response"]
    assert fp_hit["saved_tokens"] >= 800

    # Never trigger fastpath when user is issuing a correction
    fp_corr = try_execute_compiled_fastpath("salah, bukan begitu total tiang lahat")
    assert fp_corr is None


def test_pillar3_predictive_world_model():
    # Detect unquantified return risk
    alert1 = analyze_field_event_preemptively("Mandor Mugi ada retur tiang hari ini di Lahat")
    assert alert1["status"] == "alert"
    assert any(a["category"] == "UNQUANTIFIED_RETURN" for a in alert1["anomalies_detected"])

    # Detect large pole dispatch without breakdown specification
    alert2 = analyze_field_event_preemptively("Pengambilan 85 batang tiang untuk cluster Curup")
    assert alert2["status"] == "alert"
    assert any(a["category"] == "MISSING_POLE_SPEC_BREAKDOWN" for a in alert2["anomalies_detected"])

    # Clean dispatch with full specification passes without alert
    clean_ev = analyze_field_event_preemptively("Pengambilan 60 batang tiang T73 7m 3 inch Lahat")
    assert clean_ev["status"] == "clean"

    summary = get_world_model_summary()
    assert summary["status"] == "success"
    assert summary["unresolved_anomalies_count"] >= 2


def test_pillar4_canary_evolution_and_rollback():
    # 1. Reject code touching quarantined service wa-sheets-bot
    bad_code = "def bad_tool():\n    return 'systemctl restart wa-sheets-bot.service'\n"
    gate_bad = verify_code_via_canary_gate("bad_tool", bad_code)
    assert not gate_bad["passed"]
    assert "QUARANTINE" in gate_bad["stage"]

    # 2. Synthesize & hotload valid dynamic tool with smoke test
    valid_code = (
        "def calc_pole_reserve(net_poles: int, buffer_pct: float = 0.1) -> dict:\n"
        "    reserve = int(round(net_poles * buffer_pct))\n"
        "    return {'net': net_poles, 'reserve': reserve, 'total_with_buffer': net_poles + reserve}\n"
    )
    syn_res = synthesize_and_hotload_tool(
        tool_name="calc_pole_reserve",
        description="Calculate pole reserve buffer for FTTH cluster",
        code_source=valid_code,
        smoke_test_args={"net_poles": 160, "buffer_pct": 0.1},
    )
    assert syn_res["status"] == "success"
    assert syn_res["smoke_output"]["total_with_buffer"] == 176

    # 3. Verify Canary Auto-Rollback when a dynamic tool fails at runtime
    faulty_runtime_code = (
        "def unstable_sensor_tool(x: int) -> int:\n"
        "    if x < 0:\n"
        "        raise RuntimeError('Sensor calibration underflow')\n"
        "    return x * 2\n"
    )
    gate_ok = verify_code_via_canary_gate(
        "unstable_sensor_tool",
        faulty_runtime_code,
        smoke_test_args={"x": 5},
    )
    assert gate_ok["passed"]
    synthesize_and_hotload_tool(
        tool_name="unstable_sensor_tool",
        description="Test canary rollback on negative input",
        code_source=faulty_runtime_code,
        smoke_test_args={"x": 5},
    )

    from alfa.core.apex.canary_evolution import _wrap_with_canary_rollback_guard
    guarded = _wrap_with_canary_rollback_guard("unstable_sensor_tool", gate_ok["callable"])
    rb_res = guarded(x=-1)
    assert rb_res["status"] == "canary_rolled_back"
    assert "Sensor calibration underflow" in rb_res["error"]

    metrics = get_canary_evolution_metrics()
    assert metrics["total_canary_rollbacks"] >= 1


def test_pillar5_hardware_governor_and_agent_tools():
    gov = get_hardware_governor_state()
    assert gov["status"] == "success"
    assert gov["governor_mode"] in ("APEX_TURBO", "BALANCED", "THERMAL_PROTECTION")
    assert gov["cpu_temp_celsius"] > 0

    # Verify strict quarantine on wa-sheets-bot.service
    assert is_service_quarantined("wa-sheets-bot.service")
    assert is_service_quarantined("wa-sheets-bot")
    assert not is_service_quarantined("telegram-ai-bot.service")

    # Test registered agent tools
    ns_tool = apex_neuro_symbolic_verify("68 - 7 = 61", "Lahat")
    assert ns_tool["status"] == "success"

    dr_tool = apex_run_dreaming_consolidation()
    assert dr_tool["status"] == "success"

    tel_tool = apex_system_telemetry()
    assert tel_tool["status"] == "success"
    assert "Level 5+" in tel_tool["autonomy_level"]

    syn_tool = apex_synthesize_dynamic_tool(
        tool_name="km_to_drum_estimator",
        description="Estimate cable drums needed for route km",
        python_code="def km_to_drum_estimator(km: float) -> int:\n    return int((km * 1000) // 4000) + 1\n",
    )
    assert syn_tool["status"] == "success"

    full = get_apex_full_status()
    assert full["status"] == "success"
    assert "cloud_rescue_vault" in full
    assert "symbolic_ledgers" in full


def test_perfection_4_phases_vault_ledger_and_maintenance(tmp_path):
    import openpyxl
    from alfa.core.apex import (
        audit_excel_formula_integrity,
        run_autonomous_apex_maintenance,
        stage_file_for_cloud_rescue,
    )

    # Phase 1: Cloud-Local Rescue Vault
    dummy_file = tmp_path / "Master_Laporan_Cluster_Lahat_Test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rekap"
    ws["G6"] = 61
    ws["G7"] = 99
    ws["G8"] = "=SUM(G6:G7)"  # Clean dynamic formula (no circular ref)
    wb.save(str(dummy_file))

    vault_res = stage_file_for_cloud_rescue(
        str(dummy_file),
        cluster_name="LAHAT",
        attempt_cloud_upload=False,
        vault_root=str(tmp_path / "vault"),
    )
    assert vault_res["status"] == "success"
    assert vault_res["sync_status"] == "LOCAL_VAULTED"

    # Phase 2: Symbolic Excel Formula Integrity Auditor (Clean vs Circular)
    audit_ok = audit_excel_formula_integrity(str(dummy_file))
    assert audit_ok["status"] == "valid"
    assert audit_ok["is_clean"] is True
    assert audit_ok["formula_count"] == 1

    # Test Circular Reference Detection
    bad_xlsx = tmp_path / "Bad_Circular.xlsx"
    wb_bad = openpyxl.Workbook()
    ws_bad = wb_bad.active
    ws_bad["G10"] = "=SUM(G6:G10)"  # Circular self-reference!
    wb_bad.save(str(bad_xlsx))

    audit_bad = audit_excel_formula_integrity(str(bad_xlsx))
    assert audit_bad["status"] == "circular_detected"
    assert audit_bad["is_clean"] is False
    assert len(audit_bad["circular_references"]) == 1

    # Phase 3 & 4: Full Autonomous Maintenance Cycle
    maint = run_autonomous_apex_maintenance(force=True)
    assert maint["status"] == "success"
    assert maint["sqlite_wal_checkpoint"] == "ok"

