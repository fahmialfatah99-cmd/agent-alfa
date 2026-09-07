"""Tests for Swarm Live Arena Visualizer backend endpoint, stage parser, agent states, and template rendering."""

import json
import os
import sys
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alfa.dashboard.app import app
from alfa.dashboard.routes.swarm import (
    parse_arena_state,
    parse_swarm_stage,
    detect_active_speaker,
    compute_agent_states,
    compute_consensus_percent,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_swarm_live_response_structure(client, monkeypatch):
    """Test /api/swarm/live response includes structured arena data."""
    # Ensure no residual running state
    from alfa.swarm import engine as se
    monkeypatch.setattr(se, "MEETING_RUNNING", False)

    res = client.get("/api/swarm/live")
    assert res.status_code == 200
    data = res.json()

    assert data.get("status") == "success"
    assert "running" in data
    assert isinstance(data["running"], bool)
    assert "active_speaker" in data
    assert data["active_speaker"] is None or isinstance(data["active_speaker"], str)
    assert "stage" in data
    assert data["stage"] in ("idle", "plan", "debate", "vote", "consensus", "execute")
    assert "consensus_percent" in data
    assert isinstance(data["consensus_percent"], int)
    assert 0 <= data["consensus_percent"] <= 100
    assert "agent_states" in data
    assert isinstance(data["agent_states"], dict)
    for expected_id in ("commander", "researcher", "critic", "executor"):
        assert expected_id in data["agent_states"]
    assert "entries" in data
    assert isinstance(data["entries"], list)


def test_parse_stage_idle():
    """Test idle stage when meeting is not running and no events."""
    assert parse_swarm_stage([], running=False) == "idle"
    # When completed with DONE
    entries = [{"tag": "DONE", "text": "🏁 Eksekusi swarm selesai."}]
    assert parse_swarm_stage(entries, running=False) == "idle"


def test_parse_stage_planning():
    """Test stage parsing detects planning stage."""
    entries = [
        {"tag": "SESSION", "text": "Sesi EXECUTE dimulai — topik: Setup architecture"},
        {"tag": "PLAN", "text": "🗂️ 1: Analisis kebutuhan arsitektur dan dependensi"},
    ]
    assert parse_swarm_stage(entries, running=True) == "plan"


def test_parse_stage_deliberation():
    """Test stage parsing detects debate / deliberation stage."""
    entries = [
        {"tag": "SESSION", "text": "Sesi EXECUTE dimulai"},
        {"tag": "DIALOG", "text": "💬 Researcher Prime: Berdasarkan data benchmark, opsi B lebih stabil."},
    ]
    assert parse_swarm_stage(entries, running=True) == "debate"


def test_parse_stage_voting():
    """Test stage parsing detects voting stage."""
    entries = [
        {"tag": "SESSION", "text": "Sesi EXECUTE dimulai"},
        {"tag": "VOTE", "text": "🗳️ Alpha Lead mengajukan voting konsensus solusi arsitektur"},
    ]
    assert parse_swarm_stage(entries, running=True) == "vote"


def test_parse_stage_consensus():
    """Test stage parsing detects consensus stage."""
    entries = [
        {"tag": "SESSION", "text": "Sesi EXECUTE dimulai"},
        {"tag": "CONSENSUS", "text": "🤝 Konsensus tercapai: Seluruh agen menyepakati strategi hybrid."},
    ]
    assert parse_swarm_stage(entries, running=True) == "consensus"


def test_parse_stage_execution():
    """Test stage parsing detects execution stage."""
    entries = [
        {"tag": "SESSION", "text": "Sesi EXECUTE dimulai"},
        {"tag": "EXEC", "text": "⚙️ Code Crafter mulai eksekusi: Tulis script database migration"},
    ]
    assert parse_swarm_stage(entries, running=True) == "execute"

    # Also tool call triggers execution stage
    entries_tool = [
        {"tag": "SESSION", "text": "Sesi EXECUTE dimulai"},
        {"tag": "TOOL", "text": "⚙️ forced-exec write_file -> success"},
    ]
    assert parse_swarm_stage(entries_tool, running=True) == "execute"


def test_agent_state_detection():
    """Test agent state detection marks current speaker as speaking and others as waiting/idle."""
    entries = [
        {"tag": "SESSION", "text": "Sesi dimulai"},
        {"tag": "DIALOG", "text": "💬 Alpha Lead: Mari kita mulai dekomposisi rencana."},
    ]
    speaker = detect_active_speaker(entries)
    assert speaker in ("Alpha Lead", "Commander")

    states = compute_agent_states(entries, running=True)
    assert states["commander"] == "speaking"
    assert states["researcher"] in ("waiting", "idle", "listening")
    assert states["critic"] in ("waiting", "idle", "listening")
    assert states["executor"] in ("waiting", "idle", "listening")


def test_agent_state_different_personas():
    """Test speaker detection and state mapping for different personas."""
    # Researcher speaking
    res_entries = [{"tag": "DIALOG", "text": "💬 Researcher Prime: Menemukan 3 paper terkait."}]
    res_states = compute_agent_states(res_entries, running=True)
    assert res_states["researcher"] == "speaking"
    assert res_states["commander"] != "speaking"

    # Critic speaking
    crit_entries = [{"tag": "DIALOG", "text": "💬 System Auditor: Perlu audit keamanan port 8080."}]
    crit_states = compute_agent_states(crit_entries, running=True)
    assert crit_states["critic"] == "speaking"
    assert crit_states["executor"] != "speaking"

    # Executor speaking or executing
    exec_entries = [{"tag": "EXEC", "text": "⚙️ Code Crafter mulai eksekusi task..."}]
    exec_states = compute_agent_states(exec_entries, running=True)
    assert exec_states["executor"] == "speaking"
    assert exec_states["researcher"] != "speaking"


def test_consensus_percent_computation():
    """Test consensus percentage scales appropriately with stages and events."""
    assert compute_consensus_percent("idle", []) == 0
    assert compute_consensus_percent("plan", [{"tag": "PLAN", "text": "Plan ready"}]) >= 15
    assert compute_consensus_percent("debate", [{"tag": "DIALOG", "text": "Discussing"}]) >= 35
    assert compute_consensus_percent("vote", [{"tag": "VOTE", "text": "Voting in progress"}]) >= 65
    assert compute_consensus_percent("consensus", [{"tag": "CONSENSUS", "text": "Agreement reached"}]) >= 85
    assert compute_consensus_percent("idle", [{"tag": "DONE", "text": "Finished successfully"}]) == 100


def test_templates_index_renders_swarm_arena():
    """Test that templates/index.html renders #swarm-arena and its child components."""
    templates_path = Path(__file__).resolve().parent.parent / "templates" / "index.html"
    assert templates_path.exists(), "templates/index.html must exist"
    content = templates_path.read_text(encoding="utf-8")

    # Swarm Arena Container
    assert 'id="swarm-arena"' in content or "id='swarm-arena'" in content

    # Stage progress tracker pills (1. Planning, 2. Debate, 3. Voting, 4. Consensus, 5. Execution)
    assert "Planning" in content
    assert "Debate" in content
    assert "Voting" in content
    assert "Consensus" in content
    assert "Execution" in content

    # Agent cards for the 4 core personas
    assert "agent-card-commander" in content
    assert "agent-card-researcher" in content
    assert "agent-card-critic" in content
    assert "agent-card-executor" in content

    # Consensus agreement bar
    assert "swarm-consensus-fill" in content or "swarm-consensus-bar" in content
    assert "swarm-consensus-percent" in content


def test_live_feed_integration_with_temp_file(client, monkeypatch):
    """Test /api/swarm/live endpoint when feed file contains real entries."""
    from alfa.swarm import engine as se

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
        events = [
            {"i": 1, "ts": "18:00:01", "tag": "SESSION", "text": "Sesi EXECUTE dimulai — topik: Refactor Swarm Arena"},
            {"i": 2, "ts": "18:00:03", "tag": "PLAN", "text": "🗂️ 1: Desain visualizer komponen"},
            {"i": 3, "ts": "18:00:06", "tag": "DIALOG", "text": "💬 Alpha Lead: Code Crafter siapkan styling cyber."},
        ]
        for e in events:
            f.write(json.dumps(e) + "\n")
        temp_feed_path = f.name

    try:
        monkeypatch.setattr(se, "LIVE_FEED_FILE", temp_feed_path)
        monkeypatch.setattr(se, "MEETING_RUNNING", True)

        res = client.get("/api/swarm/live")
        assert res.status_code == 200
        data = res.json()

        assert data["running"] is True
        assert len(data["entries"]) >= 3
        assert data["active_speaker"] in ("Alpha Lead", "Commander")
        assert data["agent_states"]["commander"] == "speaking"
        assert data["stage"] in ("plan", "debate")
        assert data["consensus_percent"] > 0
    finally:
        if os.path.exists(temp_feed_path):
            os.remove(temp_feed_path)
