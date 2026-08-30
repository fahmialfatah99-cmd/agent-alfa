import sys
from pathlib import Path
import os
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools
import main_brain
import alfa
import alfa.core
import alfa.security
import alfa.swarm
import alfa.scrapers


def test_alfa_modular_package_structure():
    """Verify alfa modular sub-packages load correctly."""
    assert alfa.__version__ == "2.5.0"
    assert hasattr(alfa, "core")
    assert hasattr(alfa, "security")
    assert hasattr(alfa, "swarm")
    assert hasattr(alfa, "scrapers")


def test_ollama_offline_mode_main_brain(monkeypatch):
    """Verify get_main_brain routes to local Ollama Hermes 3 when offline mode is enabled."""
    monkeypatch.setenv("ALFA_OFFLINE_MODE", "true")
    monkeypatch.setenv("OLLAMA_MODEL", "hermes3:latest")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    
    brain = main_brain.get_main_brain()
    assert brain["provider"] == "ollama"
    assert brain["model"] == "hermes3:latest"
    assert brain["base_url"] == "http://localhost:11434/v1"
    assert brain["label"] == "ollama-local"


def test_fetch_web_page_content_structure():
    """Verify fetch_web_page_content returns expected schema and engine info."""
    # Test on a dummy or known local URL / mock
    res = tools.fetch_web_page_content("https://httpbin.org/html")
    assert "status" in res
    if res["status"] == "success":
        assert "content" in res
        assert "engine" in res


def test_browser_open_url_stealth_fallback():
    """Verify browser_open_url gracefully returns interactive elements."""
    res = tools.browser_open_url("https://httpbin.org/html")
    assert "status" in res
    if res["status"] == "success":
        assert "interactive_elements" in res
