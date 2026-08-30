"""
ALFA Sovereign AI Agent Core Package
Unified, Modular AI Agent Architecture

Modules:
    - core: Main reasoning engine, tool RAG, brain routing
    - scrapers: Multi-tier stealth web scraping engines
    - swarm: Autonomous multi-agent orchestration
    - security: Security utilities and configurations
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
__all__ = ["core", "scrapers", "swarm", "security", "cli"]
