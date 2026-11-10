"""
Level 5+ Adaptive Hardware & Thermal Governor for ALFA OS.

Monitors physical host metrics (CPU load, RAM, Swap, CPU Thermal sensors on Linux)
and dynamically governs background cognitive tasks (Dreaming, Indexing, Synthesis)
while enforcing strict quarantine protection for critical services (wa-sheets-bot).
"""

from __future__ import annotations

import glob
import logging
import os
from typing import Any

import psutil

try:
    import alfa_accel

    _HAS_RUST_ACCEL = getattr(alfa_accel, "is_rust_accelerated", lambda: False)()
except ImportError:
    _HAS_RUST_ACCEL = False


def is_governor_rust_accelerated() -> bool:
    """Check if Hardware Governor telemetry is running with native Rust acceleration."""
    return bool(_HAS_RUST_ACCEL)


logger = logging.getLogger("ApexGovernor")

# HARD QUARANTINE RULE (AGENTS.md): Never restart, stop, or touch WhatsApp QR session service.
IMMUTABLE_PROTECTED_SERVICES: frozenset[str] = frozenset({
    "wa-sheets-bot.service",
    "wa-sheets-bot",
})


_GOV_ERRORS = (psutil.Error, OSError, RuntimeError, ValueError, AttributeError)


def read_cpu_temperature_celsius() -> float:
    """Read physical CPU temperature from Linux sysfs thermal zones or psutil."""
    if _HAS_RUST_ACCEL:
        try:
            _, _, _, rust_temp = alfa_accel.read_host_hardware_telemetry()
            if 15.0 <= rust_temp <= 115.0:
                return float(rust_temp)
        except _GOV_ERRORS as e:
            logger.debug(f"Rust telemetry temperature fallback: {e}")

    try:
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures() or {}
            for name in ("coretemp", "k10temp", "acpitz", "pch_skylake"):
                if name in temps and temps[name]:
                    vals = [t.current for t in temps[name] if t.current and t.current > 0]
                    if vals:
                        return round(float(max(vals)), 1)
    except _GOV_ERRORS:
        pass

    # Fallback: direct Linux sysfs thermal_zone reading
    max_temp = 0.0
    try:
        for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read().strip()
                if raw.isdigit():
                    val = int(raw) / 1000.0
                    if 15.0 < val < 115.0 and val > max_temp:
                        max_temp = val
            except OSError:
                continue
    except _GOV_ERRORS:
        pass

    return round(max_temp, 1) if max_temp > 0 else 45.0


def get_hardware_governor_state() -> dict[str, Any]:
    """
    Evaluate real-time host hardware telemetry and determine the active Apex Governor Mode:
    - APEX_TURBO: Low load & cool temperature -> full background dreaming & synthesis allowed.
    - BALANCED: Moderate load -> prioritize interactive turns, throttle heavy background jobs.
    - THERMAL_PROTECTION: High CPU/temp or low RAM -> suspend background tasks immediately.
    """
    cpu_pct: float | None = None
    ram_used_pct: float | None = None
    ram_avail_mb: float | None = None
    temp_c: float | None = None

    if _HAS_RUST_ACCEL:
        try:
            cpu_pct, ram_used_pct, ram_avail_mb, temp_c = (
                alfa_accel.read_host_hardware_telemetry()
            )
        except _GOV_ERRORS as e:
            logger.debug(f"Rust hardware telemetry fallback: {e}")
            cpu_pct = None
            ram_used_pct = None
            ram_avail_mb = None
            temp_c = None

    if cpu_pct is None:
        try:
            cpu_pct = psutil.cpu_percent(interval=0.05)
        except _GOV_ERRORS:
            cpu_pct = 10.0

    if ram_used_pct is None or ram_avail_mb is None:
        try:
            vm = psutil.virtual_memory()
            ram_used_pct = vm.percent
            ram_avail_mb = round(vm.available / (1024 * 1024), 1)
        except _GOV_ERRORS:
            ram_used_pct = 50.0
            ram_avail_mb = 2048.0

    try:
        sw = psutil.swap_memory()
        swap_used_pct = sw.percent
    except _GOV_ERRORS:
        swap_used_pct = 0.0

    if temp_c is None:
        temp_c = read_cpu_temperature_celsius()
    # Guard sensor: bila pembacaan temperatur gagal total (None), pakai default
    # 0.0 agar comparison mode-matrix tidak melempar TypeError di runtime.
    if temp_c is None:
        temp_c = 0.0
    load_1m, load_5m, _ = os.getloadavg() if hasattr(os, "getloadavg") else (0.5, 0.5, 0.5)

    # Binding definite mypy 1.8 tidak menarrow melalui tuple-unpack di try/except;
    # setelah titik ini semua telemetri dijamin non-None (Decision Matrix aman).
    cpu_pct_f = cpu_pct if cpu_pct is not None else 10.0
    temp_c_f = float(temp_c)
    ram_used_f = ram_used_pct if ram_used_pct is not None else 50.0
    ram_avail_f = ram_avail_mb if ram_avail_mb is not None else 2048.0

    # Decision Matrix for Level 5+ Governor
    if temp_c_f >= 78.0 or cpu_pct_f >= 80.0 or ram_avail_f < 450:
        mode = "THERMAL_PROTECTION"
        allow_dreaming = False
        allow_heavy_synthesis = False
        recommendation = "Suhu/Beban tinggi: Background Dreaming ditunda, prioritas 100% pada respons interaktif."
    elif temp_c_f >= 65.0 or cpu_pct_f >= 45.0 or ram_avail_f < 900:
        mode = "BALANCED"
        allow_dreaming = True
        allow_heavy_synthesis = True
        recommendation = "Kondisi seimbang: Eksekusi normal dengan pembatasan antrean background."
    else:
        mode = "APEX_TURBO"
        allow_dreaming = True
        allow_heavy_synthesis = True
        recommendation = "Kondisi optimal & dingin: Offline Dreaming Compiler dan Neuro-Symbolic Prover aktif penuh."

    return {
        "status": "success",
        "governor_mode": mode,
        "cpu_percent": round(cpu_pct_f, 1),
        "cpu_temp_celsius": temp_c_f,
        "ram_used_percent": round(ram_used_f, 1),
        "ram_available_mb": ram_avail_f,
        "swap_used_percent": round(swap_used_pct, 1),
        "load_avg_1m": round(load_1m, 2),
        "load_avg_5m": round(load_5m, 2),
        "allow_dreaming": allow_dreaming,
        "allow_heavy_synthesis": allow_heavy_synthesis,
        "protected_services": list(IMMUTABLE_PROTECTED_SERVICES),
        "recommendation": recommendation,
    }


def is_service_quarantined(service_name: str) -> bool:
    """Check if a service is strictly protected from automated restart/stop actions."""
    norm = (service_name or "").strip().lower()
    return any(p in norm for p in IMMUTABLE_PROTECTED_SERVICES)
