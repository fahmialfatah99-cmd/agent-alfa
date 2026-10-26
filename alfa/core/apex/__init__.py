"""
Level 5+ Sovereign Cognitive Apex Engine for ALFA OS.

Unifies the 5 Apex Pillars:
1. Neuro-Symbolic Verification Engine (0% Numerical Hallucination via AST Solver)
2. Offline 'Dreaming Mode' & Deterministic Fast-Path Compiler (Sub-ms 0-token execution)
3. Predictive Operational World-Model (Pre-emptive field anomaly detection)
4. Shadow-Git Canary Self-Evolution (3-Stage verified dynamic tool synthesis & auto-rollback)
5. Adaptive Hardware & Thermal Governor (Host-aware resource & quarantine protection)
"""

from __future__ import annotations

import logging
from typing import Any

from alfa.core.apex.canary_evolution import (
    get_canary_evolution_metrics,
    init_canary_tables,
    synthesize_and_hotload_tool,
    verify_code_via_canary_gate,
)
from alfa.core.apex.dreaming_compiler import (
    compile_fastpath,
    get_dreaming_metrics,
    init_dreaming_tables,
    run_idle_dreaming_cycle,
    seed_compiled_fastpaths,
    try_execute_compiled_fastpath,
)
from alfa.core.apex.hardware_governor import (
    IMMUTABLE_PROTECTED_SERVICES,
    get_hardware_governor_state,
    is_service_quarantined,
    read_cpu_temperature_celsius,
)
from alfa.core.apex.neuro_symbolic import (
    safe_ast_math_eval,
    verify_and_prove_response,
    verify_arithmetic_equations_in_text,
)
from alfa.core.apex.world_model import (
    analyze_field_event_preemptively,
    get_world_model_summary,
    init_world_model_tables,
    record_world_anomaly,
)
from alfa.core.brain.learning_loop import get_learning_loop_metrics

logger = logging.getLogger("ApexEngine")


def _register_tool(category: str = "agent"):
    """Deferred tool registration decorator to prevent circular imports."""
    def decorator(fn):
        try:
            from alfa.tools.registry import register_tool as _rt
            return _rt(category=category)(fn)
        except Exception:
            return fn
    return decorator


def initialize_apex_engine() -> dict[str, Any]:
    """Initialize all Level 5+ Apex tables, seed compiled fast-paths, and run initial consolidation."""
    init_dreaming_tables()
    init_world_model_tables()
    init_canary_tables()
    seeded = seed_compiled_fastpaths()
    return {"status": "initialized", "seeded_fastpaths": seeded}


def get_apex_full_status() -> dict[str, Any]:
    """Aggregate comprehensive telemetry across all 5 Level 5+ Cognitive Apex pillars."""
    initialize_apex_engine()
    gov = get_hardware_governor_state()
    dream = get_dreaming_metrics()
    world = get_world_model_summary()
    canary = get_canary_evolution_metrics()
    learning = get_learning_loop_metrics()

    return {
        "status": "success",
        "autonomy_level": "Level 5+ (Sovereign Cognitive Apex)",
        "governor": gov,
        "dreaming": dream,
        "world_model": world,
        "canary_evolution": canary,
        "learning_loop": learning,
    }


# --- Registered Level 5+ Agent Tools ---

@_register_tool(category="agent")
def apex_synthesize_dynamic_tool(
    tool_name: str,
    description: str,
    python_code: str,
) -> dict[str, Any]:
    """
    SINTESIS TOOL BARU OTONOM (LEVEL 5+ CANARY SELF-EVOLUTION):
    Menulis fungsi tool Python baru secara mandiri, mengujinya melewati 3-Stage Canary Gate
    (AST Security Audit + Isolated Compilation + Smoke Verification), dan melakukan hot-load
    ke runtime ALFA OS dengan proteksi auto-rollback.
    """
    return synthesize_and_hotload_tool(
        tool_name=tool_name,
        description=description,
        code_source=python_code,
    )


@_register_tool(category="agent")
def apex_neuro_symbolic_verify(
    text_or_equation: str,
    context_prompt: str = "",
) -> dict[str, Any]:
    """
    PEMBUKTIAN MATEMATIKA & FAKTA NEURO-SIMBOLIK (0% HALLUCINATION PROVER):
    Mengevaluasi ekspresi matematika menggunakan AST Solver deterministik serta memvalidasi
    klaim angka/stok logistik terhadap invarian database.
    """
    direct_val = safe_ast_math_eval(text_or_equation)
    proof_res = verify_and_prove_response(context_prompt, text_or_equation)
    return {
        "status": "success",
        "direct_ast_result": direct_val,
        "verification": proof_res,
    }


@_register_tool(category="agent")
def apex_run_dreaming_consolidation() -> dict[str, Any]:
    """
    KOMPILASI FAST-PATH & KONSOLIDASI MEMORI (OFFLINE DREAMING COMPILER):
    Menjalankan siklus konsolidasi untuk mengubah aturan berkepercayaan tinggi menjadi
    jalur cepat deterministik (0 token, eksekusi < 2 milidetik).
    """
    return run_idle_dreaming_cycle(force=True)


@_register_tool(category="agent")
def apex_system_telemetry() -> dict[str, Any]:
    """
    TELEMETRI PENUH LEVEL 5+ SOVEREIGN COGNITIVE APEX:
    Melihat status Hardware Thermal Governor, Neuro-Symbolic Prover, Dreaming Fast-Paths,
    Predictive World-Model, dan Canary Self-Evolution.
    """
    return get_apex_full_status()


__all__ = [
    "IMMUTABLE_PROTECTED_SERVICES",
    "analyze_field_event_preemptively",
    "apex_neuro_symbolic_verify",
    "apex_run_dreaming_consolidation",
    "apex_synthesize_dynamic_tool",
    "apex_system_telemetry",
    "compile_fastpath",
    "get_apex_full_status",
    "get_canary_evolution_metrics",
    "get_dreaming_metrics",
    "get_hardware_governor_state",
    "get_world_model_summary",
    "initialize_apex_engine",
    "is_service_quarantined",
    "read_cpu_temperature_celsius",
    "record_world_anomaly",
    "run_idle_dreaming_cycle",
    "safe_ast_math_eval",
    "seed_compiled_fastpaths",
    "synthesize_and_hotload_tool",
    "try_execute_compiled_fastpath",
    "verify_and_prove_response",
    "verify_arithmetic_equations_in_text",
    "verify_code_via_canary_gate",
]
