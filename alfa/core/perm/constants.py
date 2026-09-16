"""Permission gate constants, risk tiers, and classification registry."""

import logging
import os
from enum import Enum
from typing import Dict, Set, Tuple

logger = logging.getLogger("PermissionGate")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

PROJECT_DIR = REPO_ROOT
DB_PATH = os.getenv("ALFA_DB_PATH", os.path.join(PROJECT_DIR, "agent_data.db"))

PERMISSION_GATE_ENABLED = os.getenv("PERMISSION_GATE", "on").strip().lower() != "off"
APPROVAL_TIMEOUT = int(os.getenv("PERMISSION_GATE_TIMEOUT", "300"))
TRUST_THRESHOLD = float(os.getenv("PERMISSION_GATE_TRUST_THRESHOLD", "0.7"))
FAIL_MODE = os.getenv("PERMISSION_GATE_FAIL_MODE", "deny").strip().lower()


# ── Klasifikasi Tool dengan Risk Tiers ─────────────────────────────────────────
class RiskTier(Enum):
    LOW = "low"  # Read-only, reversible
    MEDIUM = "medium"  # Write operations, moderate impact
    HIGH = "high"  # System changes, potentially destructive
    CRITICAL = "critical"  # Irreversible, security-sensitive


# Tool classification dengan risk tier dan deskripsi
TOOL_CLASSIFICATION = {
    # CRITICAL - irreversible, security-critical
    "ssh_execute_command": (RiskTier.CRITICAL, "Akses SSH remote - risiko keamanan tinggi"),
    "manage_crontab_jobs": (RiskTier.CRITICAL, "Modifikasi scheduled tasks - dampak sistem luas"),
    "clean_system_storage": (RiskTier.CRITICAL, "Penghapusan massal file - irreversible"),
    "control_linux_hardware": (RiskTier.CRITICAL, "Kontrol hardware langsung - risiko damage"),
    "kill_process": (RiskTier.HIGH, "Terminasi process - bisa crash sistem"),
    
    # HIGH - system changes, potentially destructive
    "execute_bash_command": (RiskTier.HIGH, "Eksekusi command shell - dampak bervariasi"),
    "write_local_file": (RiskTier.HIGH, "Write file arbitrary - bisa overwrite penting"),
    "edit_file_precise": (RiskTier.HIGH, "Edit file presisi - risiko corrupt data"),
    "apply_unified_diff": (RiskTier.HIGH, "Patch file - bisa break code"),
    "manage_system_services": (RiskTier.HIGH, "Start/stop services - downtime risk"),
    "query_database": (RiskTier.HIGH, "Query SQL - bisa DROP/DELETE"),
    "git_operations": (RiskTier.HIGH, "Git ops - bisa lose commits"),
    "download_file_from_url": (RiskTier.HIGH, "Download external - malware risk"),
    
    # MEDIUM - desktop automation, moderate impact
    "desktop_click_coordinate": (RiskTier.MEDIUM, "Automasi klik - unintended actions"),
    "desktop_type_keys": (RiskTier.MEDIUM, "Automasi keyboard - unintended input"),
    "desktop_launch_app": (RiskTier.MEDIUM, "Launch aplikasi - resource usage"),
    "vision_click_target": (RiskTier.MEDIUM, "Visual automation - misclick risk"),
    "record_desktop_screen": (RiskTier.MEDIUM, "Screen recording - privacy concern"),
    "capture_webcam_frame": (RiskTier.MEDIUM, "Webcam capture - privacy sensitive"),
    "scan_local_network": (RiskTier.MEDIUM, "Network scan - firewall trigger"),
    
    # LOW - read-only, safe operations
    "auto_diagnose_and_heal_system": (RiskTier.LOW, "Diagnostic read-only - safe"),
}

# Default tier untuk tool yang tidak terklasifikasi
DEFAULT_TIER = RiskTier.MEDIUM

# Safe tools yang selalu otomatis lolos (tier LOW implicit)
SAFE_TOOLS = {
    "web_search", "fetch_web_page_content", "deep_research_topic",
    "read_local_file", "search_workspace_files", "grep_workspace",
    "find_user_files",
    "index_codebase", "search_codebase",
    "save_knowledge_memory", "search_knowledge_memory",
    "get_system_stats", "get_current_user_id", "get_current_chat_id",
    "capture_desktop_screenshot", "list_running_processes",
    "generate_secure_password", "translate_text", "token_usage_query",
}

# Timeout per tier (detik)
TIER_TIMEOUTS = {
    RiskTier.LOW: 60,
    RiskTier.MEDIUM: 180,
    RiskTier.HIGH: 300,
    RiskTier.CRITICAL: 600,
}

_LABELS = {
    "once": "✅ Diizinkan (sekali ini)",
    "always": "🔁 Diizinkan SELALY untuk sesi mendatang",
    "always_session": "⏳ Izinkan sampai sesi berakhir",
    "deny": "❌ Ditolak oleh pengguna",
    "timeout": "⏰ Auto-ditolak (tidak ada respons)",
    "auto_approved": "✨ Auto-approved (trust score tinggi)",
}


# ── Penyimpanan aturan 'selalu izinkan' ──────────────────────────────────────
