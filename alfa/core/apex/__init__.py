"""
Level 5+ Sovereign Cognitive Apex & General-Purpose Frontier Engine for ALFA OS.

Unifies all Core & Universal General-Purpose Pillars:
1. Neuro-Symbolic Verification Engine (0% Numerical Hallucination via AST Solver & Excel Auditor)
2. Offline 'Dreaming Mode' & Deterministic Fast-Path Compiler (Sub-ms 0-token execution)
3. Predictive Operational World-Model (Pre-emptive anomaly detection)
4. Shadow-Git Canary Self-Evolution (3-Stage verified dynamic tool synthesis & auto-rollback)
5. Adaptive Hardware & Thermal Governor (Host-aware resource & quarantine protection)
6. Universal Vision Computer-Use Engine (`computer_use.py` — Coordinate Grid Vision & GUI Operator)
7. Episodic Temporal GraphRAG Second Brain (`temporal_graphrag.py` — Multi-Hop Knowledge Graph)
8. Autonomous Full-Stack Software Factory (`software_factory.py` — Devin-Grade E2E Verifier & Auto-Healer)
9. Resilient Cloud-Local Media & Ledger Vault (`cloud_rescue.py`)
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
from alfa.core.apex.cloud_rescue import (
    get_cloud_rescue_metrics,
    init_cloud_rescue_tables,
    run_cloud_rescue_sweep,
    stage_file_for_cloud_rescue,
)
from alfa.core.apex.computer_use import (
    apply_coordinate_grid_overlay,
    capture_desktop_for_vision,
    execute_gui_action,
    inspect_desktop_environment,
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
from alfa.core.apex.maintenance_daemon import run_autonomous_apex_maintenance
from alfa.core.apex.neuro_symbolic import (
    audit_excel_formula_integrity,
    safe_ast_math_eval,
    sync_symbolic_constraints_from_master_ledgers,
    verify_and_prove_response,
    verify_arithmetic_equations_in_text,
)
from alfa.core.apex.software_factory import (
    build_and_verify_fullstack_app,
    get_software_factory_metrics,
    init_software_factory_tables,
    verify_fullstack_project_e2e,
)
from alfa.core.apex.temporal_graphrag import (
    format_temporal_graphrag_prompt,
    get_temporal_graphrag_metrics,
    ingest_text_to_temporal_graph,
    init_graphrag_tables,
    query_temporal_graphrag,
    upsert_graph_entity,
    upsert_graph_relation,
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
    """Initialize all Level 5+ Apex & General-Purpose tables."""
    init_dreaming_tables()
    init_world_model_tables()
    init_canary_tables()
    init_cloud_rescue_tables()
    init_graphrag_tables()
    init_software_factory_tables()
    seeded = seed_compiled_fastpaths()
    return {"status": "initialized", "seeded_fastpaths": seeded}


def get_apex_full_status() -> dict[str, Any]:
    """Aggregate comprehensive telemetry across all Level 5+ Cognitive Apex & General Frontier pillars."""
    initialize_apex_engine()
    gov = get_hardware_governor_state()
    dream = get_dreaming_metrics()
    world = get_world_model_summary()
    canary = get_canary_evolution_metrics()
    learning = get_learning_loop_metrics()
    vault = get_cloud_rescue_metrics()
    ledgers = sync_symbolic_constraints_from_master_ledgers()
    graphrag = get_temporal_graphrag_metrics()
    factory = get_software_factory_metrics()
    desktop = inspect_desktop_environment()

    return {
        "status": "success",
        "autonomy_level": "Level 5+ (Universal Sovereign Cognitive Apex)",
        "governor": gov,
        "dreaming": dream,
        "world_model": world,
        "canary_evolution": canary,
        "learning_loop": learning,
        "cloud_rescue_vault": vault,
        "symbolic_ledgers": ledgers,
        "temporal_graphrag": graphrag,
        "software_factory": factory,
        "computer_use": {
            "display": desktop.get("display"),
            "resolution": desktop.get("screen_resolution"),
            "capabilities": desktop.get("capabilities"),
        },
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
    klaim angka terhadap invarian database.
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
    KOMPILASI FAST-PATH & KONSOLIDASI MEMORI & PEMELIHARAAN OTONOM (APEX MAINTENANCE):
    Menjalankan siklus konsolidasi penuh: mengkompilasi aturan menjadi Fast-Path (0 token),
    mengaudit formula Excel, dan mengamankan berkas ke brankas lokal/cloud.
    """
    return run_autonomous_apex_maintenance(force=True)


@_register_tool(category="agent")
def apex_system_telemetry() -> dict[str, Any]:
    """
    TELEMETRI PENUH LEVEL 5+ SOVEREIGN COGNITIVE APEX:
    Melihat status seluruh pilar otonom (Thermal Governor, Neuro-Symbolic Prover, Dreaming,
    Temporal GraphRAG, Software Factory, dan Vision Computer-Use).
    """
    return get_apex_full_status()


@_register_tool(category="agent")
def apex_computer_use_action(
    action: str = "capture_grid",
    x: int = 0,
    y: int = 0,
    text: str = "",
    key_combo: str = "",
) -> dict[str, Any]:
    """
    UNIVERSAL VISION COMPUTER-USE (OPERASI LAYAR GUI DESKTOP LAYAKNYA MANUSIA):
    Mengambil tangkapan layar dengan Coordinate Grid (`capture_grid`), menginspeksi environment
    desktop (`inspect`), atau mengeksekusi klik kursor/ketik keyboard (`click`, `double_click`,
    `right_click`, `move`, `type`, `key`).
    """
    act = (action or "capture_grid").strip().lower()
    if act == "capture_grid":
        return capture_desktop_for_vision(with_grid=True)
    if act == "inspect":
        return inspect_desktop_environment()
    return execute_gui_action(action=act, x=x, y=y, text=text, key_combo=key_combo)


@_register_tool(category="agent")
def apex_temporal_graphrag_query(
    query_or_text: str,
    mode: str = "query",
    relation_source: str = "",
    relation_type: str = "",
    relation_target: str = "",
) -> dict[str, Any]:
    """
    EPISODIC TEMPORAL GRAPHRAG SECOND BRAIN (OTAK KEDUA UNIVERSAL LINTAS WAKTU):
    - mode='query': Mencari koneksi pengetahuan Multi-Hop (1-Hop & 2-Hop Bridge Discovery).
    - mode='ingest': Mengekstrak entitas dan hubungan dari teks ke dalam Knowledge Graph.
    - mode='link': Menghubungkan `relation_source` --[`relation_type`]--> `relation_target`.
    """
    m = (mode or "query").strip().lower()
    if m == "ingest":
        return ingest_text_to_temporal_graph(query_or_text)
    if m == "link":
        return upsert_graph_relation(relation_source, relation_type, relation_target, context_snippet=query_or_text)
    return query_temporal_graphrag(query_or_text, max_hops=2)


@_register_tool(category="agent")
def apex_software_factory_build(
    app_slug: str,
    title: str,
    frontend_html: str,
    backend_py: str = "",
) -> dict[str, Any]:
    """
    AUTONOMOUS FULL-STACK SOFTWARE FACTORY (DEVIN-GRADE APP BUILDER & E2E VERIFIER):
    Membangun aplikasi web full-stack (`index.html` + `app.py` + `site.json`), melakukan
    Self-Healing perbaikan struktur DOM/AST otomatis, dan memverifikasi kesiapan produksi
    melalui 4-Stage E2E Quality Gate (termasuk Live HTTP 200 Smoke Test) serta mendaftarkannya ke `/sites`.
    """
    return build_and_verify_fullstack_app(
        app_slug=app_slug,
        title=title,
        frontend_html=frontend_html,
        backend_py=backend_py,
        auto_heal=True,
    )


@_register_tool(category="agent")
def rea_clone_and_build_app(
    target_file_path: str,
    app_slug: str,
    app_title: str = "",
    custom_frontend_html: str = "",
    custom_backend_py: str = "",
) -> dict[str, Any]:
    """
    1-CLICK REA REVERSE-ENGINEER & CLONE APPLICATION PIPELINE:
    Membongkar file target (.apk, .js, .py, .asar, .db, atau binary) menggunakan mesin REA,
    menyimpan pola arsitekturnya ke Learning Loop & Temporal GraphRAG, lalu langsung membangun
    aplikasi full-stack baru yang terverifikasi Live HTTP 200 dan terdaftar di `/sites`.
    """
    from alfa.tools.system.reverse_engineering import rea_synthesize_skill_from_code

    eff_title = app_title.strip() or f"ALFA Clone: {app_slug}"
    rea_res = rea_synthesize_skill_from_code(
        target_path=target_file_path,
        skill_topic=f"REA_APP_{app_slug.upper()}",
    )

    upsert_graph_relation(
        source_entity=app_slug.upper(),
        relation_type="CLONED_VIA_REA_FROM",
        target_entity=target_file_path,
        context_snippet=str(rea_res.get("synthesized_rule", ""))[:200],
    )

    rule_summary = rea_res.get("synthesized_rule", "Extracted via REA Engine")
    if not custom_frontend_html.strip():
        custom_frontend_html = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="utf-8">
    <title>{eff_title}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; max-width: 800px; margin: 0 auto; border: 1px solid #334155; }}
        pre {{ background: #020617; padding: 1rem; border-radius: 8px; overflow-x: auto; color: #38bdf8; }}
        button {{ background: #0ea5e9; color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; cursor: pointer; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>⚡ {eff_title}</h1>
        <p>Dibangun otomatis oleh <strong>ALFA OS REA + Software Factory</strong> dari target: <code>{target_file_path}</code></p>
        <h3>📐 Arsitektur Hasil Bedah REA:</h3>
        <pre>{rule_summary}</pre>
        <form id="action-form" onsubmit="event.preventDefault(); alert('Eksekusi modul aktif!');">
            <input type="text" placeholder="Input parameter..." style="padding:0.5rem;border-radius:6px;border:1px solid #475569;background:#0f172a;color:white;" />
            <button type="submit">Jalankan Modul</button>
        </form>
    </div>
</body>
</html>"""

    build_res = build_and_verify_fullstack_app(
        app_slug=app_slug,
        title=eff_title,
        frontend_html=custom_frontend_html,
        backend_py=custom_backend_py,
        auto_heal=True,
    )
    return {
        "status": build_res["status"],
        "rea_analysis": rea_res,
        "build_result": build_res,
        "serve_command": f"/serve {build_res['app_slug']}",
    }


__all__ = [
    "IMMUTABLE_PROTECTED_SERVICES",
    "analyze_field_event_preemptively",
    "apex_computer_use_action",
    "apex_neuro_symbolic_verify",
    "apex_run_dreaming_consolidation",
    "apex_software_factory_build",
    "apex_synthesize_dynamic_tool",
    "apex_system_telemetry",
    "apex_temporal_graphrag_query",
    "apply_coordinate_grid_overlay",
    "audit_excel_formula_integrity",
    "build_and_verify_fullstack_app",
    "capture_desktop_for_vision",
    "compile_fastpath",
    "execute_gui_action",
    "format_temporal_graphrag_prompt",
    "get_apex_full_status",
    "get_canary_evolution_metrics",
    "get_cloud_rescue_metrics",
    "get_dreaming_metrics",
    "get_hardware_governor_state",
    "get_software_factory_metrics",
    "get_temporal_graphrag_metrics",
    "get_world_model_summary",
    "ingest_text_to_temporal_graph",
    "initialize_apex_engine",
    "inspect_desktop_environment",
    "is_service_quarantined",
    "query_temporal_graphrag",
    "rea_clone_and_build_app",
    "read_cpu_temperature_celsius",
    "record_world_anomaly",
    "run_autonomous_apex_maintenance",
    "run_cloud_rescue_sweep",
    "run_idle_dreaming_cycle",
    "safe_ast_math_eval",
    "seed_compiled_fastpaths",
    "stage_file_for_cloud_rescue",
    "sync_symbolic_constraints_from_master_ledgers",
    "synthesize_and_hotload_tool",
    "try_execute_compiled_fastpath",
    "upsert_graph_entity",
    "upsert_graph_relation",
    "verify_and_prove_response",
    "verify_arithmetic_equations_in_text",
    "verify_code_via_canary_gate",
    "verify_fullstack_project_e2e",
]
