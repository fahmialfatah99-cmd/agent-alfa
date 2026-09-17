"""
ALFA Sovereign AI Agent Core Package
Unified, Modular AI Agent Architecture

Modules:
    - core: Main reasoning engine, tool RAG, brain routing, permissions, database
    - memory: Vector memory, semantic search, and memory reflection
    - pipelines: Autonomous multi-step execution pipelines
    - tools: Domain-specific tools (filesystem, web, desktop, media, system)
    - swarm: Autonomous multi-agent orchestration
    - bot: Telegram AI agent and interface handlers
    - dashboard: Sovereign Command Center Pro-Max web interface and API
    - security: Vault encryption and security configurations
    - media: TTS and audio/video generation
    - scrapers: Multi-tier stealth web scraping engines
    - integrations: External services (Google Drive, WhatsApp, etc.)
    - cli: Command-line interface for ALFA Agent

Usage:
    from alfa.core import get_brain
    from alfa.cli import main as cli_main

    # Or run CLI directly:
    # python -m alfa.cli
    # python -m alfa --server http://localhost:8080
"""

__version__ = "2.5.0"
__author__ = "Fahmi Alfatah"
__all__ = [
    "core",
    "memory",
    "pipelines",
    "tools",
    "scrapers",
    "swarm",
    "bot",
    "dashboard",
    "security",
    "media",
    "integrations",
    "cli",
]
