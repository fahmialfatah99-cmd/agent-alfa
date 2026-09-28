"""Unit tests for ALFA Unified Sovereign & Developer CLI."""

from unittest.mock import MagicMock

from alfa.core.cli.app import AlfaCLI
from alfa.core.cli.constants import VERSION
from alfa.core.cli.direct_ai import PRESETS, PROVIDERS_CATALOG, DirectAIClient


def test_constants():
    assert VERSION == "3.5.0"
    assert "google" in PROVIDERS_CATALOG
    assert "openai" in PROVIDERS_CATALOG
    assert "coding" in PRESETS


def test_direct_ai_client_initialization():
    client = DirectAIClient(provider="google", model="gemini-3.6-flash")
    assert client.provider == "google"
    assert client.model == "gemini-3.6-flash"


def test_direct_ai_preset():
    client = DirectAIClient(provider="google")
    assert client.apply_preset("coding") is True
    assert client.temperature == 0.2
    assert client.max_tokens == 8192


def test_scan_file_mentions(tmp_path):
    f1 = tmp_path / "test_file.py"
    f1.write_text("print('hello world')", encoding="utf-8")

    client = DirectAIClient()
    text = f"Tolong cek kode di @{str(f1)} sekarang."
    _, mentions = client.scan_file_mentions(text)

    assert len(mentions) == 1
    assert str(f1) in mentions[0]


def test_build_prompt_with_context(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("x = 42\n", encoding="utf-8")

    client = DirectAIClient()
    prompt = client.build_prompt_with_context("Jelaskan variabel ini", [str(f)])
    assert "KONTEKS FILE PROYEK" in prompt
    assert "x = 42" in prompt
    assert "Jelaskan variabel ini" in prompt


def test_alfa_cli_initialization():
    cli = AlfaCLI(mode="standalone", attached_files=[])
    assert cli.mode == "standalone"
    assert hasattr(cli, "direct_ai")
    assert cli.direct_ai is not None


def test_alfa_cli_slash_mode():
    cli = AlfaCLI(mode="auto")
    cli.do_slash_mode("standalone")
    assert cli.mode == "standalone"

    cli.do_slash_mode("server")
    assert cli.mode == "server"


def test_alfa_cli_file_management(tmp_path):
    sample = tmp_path / "dummy.txt"
    sample.write_text("sample content", encoding="utf-8")

    cli = AlfaCLI()
    cli.do_slash_file(f"add {str(sample)}")
    assert len(cli.attached_files) == 1

    cli.do_slash_file("clear")
    assert len(cli.attached_files) == 0


def test_nvidia_nim_provider():
    assert "nvidia" in PROVIDERS_CATALOG
    catalog = PROVIDERS_CATALOG["nvidia"]
    assert "nvidia/llama-3.1-nemotron-70b-instruct" in catalog["models"]
    assert "deepseek-ai/deepseek-r1" in catalog["models"]
    assert "meta/llama-3.3-70b-instruct" in catalog["models"]
    assert "qwen/qwen2.5-coder-32b-instruct" in catalog["models"]
    assert "NVIDIA_API_KEY" in catalog["env_keys"]
    assert catalog["default_url"] == "https://integrate.api.nvidia.com/v1"

    client = DirectAIClient()
    assert client.set_provider("nim") is True
    assert client.provider == "nvidia"
    assert client.base_url == "https://integrate.api.nvidia.com/v1"


def test_gemini_38_catalog():
    google_models = PROVIDERS_CATALOG["google"]["models"]
    assert "gemini-3.8-flash" in google_models
    assert "gemini-3.8-pro" in google_models
    assert "gemini-3.8-flash-lite" in google_models


def test_file_patcher_extraction():
    from alfa.core.cli.cursor_ui import FilePatcher

    patcher = FilePatcher()
    sample_text = """
Berikut perubahan:
```python:alfa/demo.py
print("halo")
```
"""
    mods = patcher.extract_modifications(sample_text)
    assert len(mods) == 1
    assert mods[0][0] == "alfa/demo.py"
    assert 'print("halo")' in mods[0][1]


def test_interactive_menu_workspace_files():
    from alfa.core.cli.interactive_menu import get_workspace_files

    files = get_workspace_files(max_files=10)
    assert isinstance(files, list)
    assert len(files) > 0


def test_9router_catalog_and_client():
    from alfa.core.cli.direct_ai import PROVIDERS_CATALOG, DirectAIClient

    assert "9router" in PROVIDERS_CATALOG
    cat = PROVIDERS_CATALOG["9router"]
    assert cat["default_url"] == "http://127.0.0.1:20128/v1"
    assert "ag/gemini-3.8-flash" in cat["models"]
    assert "gratisan" in cat["models"]
    assert "antigravity" in cat["models"]

    client = DirectAIClient(provider="9router")
    assert client.provider == "9router"
    assert client.base_url == "http://127.0.0.1:20128/v1"
    key = client.get_api_key()
    assert key != ""


def test_normalize_provider_aliases():
    from alfa.core.cli.direct_ai import normalize_provider

    assert normalize_provider("gemini") == "google"
    assert normalize_provider("nim") == "nvidia"
    assert normalize_provider("kimi") == "moonshot"
    assert normalize_provider("dashscope") == "qwen"
    assert normalize_provider("9r") == "9router"
    assert normalize_provider("router") == "9router"


def test_database_vault_key_resolution():
    from alfa.core.cli.direct_ai import DirectAIClient

    # In agent_data.db, there is an active Gemini key
    client = DirectAIClient(provider="gemini")
    key = client.get_api_key()
    # It should resolve from SQLite DB vault even if GEMINI_API_KEY env is not set
    assert key != ""


def test_sync_providers_catalog_integration():
    from alfa.core.cli.direct_ai import sync_providers_catalog

    cat = sync_providers_catalog()
    assert "9router" in cat
    assert "google" in cat
    assert "nvidia" in cat
    assert "deepseek" in cat
    assert "qwen" in cat
    assert "openrouter" in cat
    # Check that 9router models list has grown from live endpoint or defaults
    assert len(cat["9router"]["models"]) >= 10


def test_slash_keys_display(capsys):
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone")
    cli.do_slash_keys("")
    captured = capsys.readouterr()
    assert "ALFA Vault" in captured.out
    assert "agent_data.db" in captured.out
    assert "9Router AI Gateway" in captured.out


def test_patch_history_manager_and_rollback(tmp_path):
    from alfa.core.cli.agent_engine import PatchHistoryManager

    manager = PatchHistoryManager(workspace_root=tmp_path)
    test_file = tmp_path / "code.py"
    test_file.write_text("def hello():\n    return 'v1'\n", encoding="utf-8")

    # Record patch to v2
    old_c = test_file.read_text(encoding="utf-8")
    new_c = "def hello():\n    return 'v2'\n"
    test_file.write_text(new_c, encoding="utf-8")
    record = manager.record_patch("code.py", old_c, new_c)

    assert record.id == 1
    assert "code.py" in record.filepath
    assert len(manager.list_patches()) == 1

    # Verify rollback
    success, msg = manager.rollback_latest()
    assert success is True
    assert test_file.read_text(encoding="utf-8") == old_c


def test_repomap_generator(tmp_path):
    from alfa.core.cli.agent_engine import RepomapGenerator

    src_file = tmp_path / "module.py"
    src_file.write_text(
        "class OrderService:\n    def process_order(self):\n        pass\n\ndef calculate_tax():\n    pass\n",
        encoding="utf-8",
    )

    gen = RepomapGenerator(root_dir=tmp_path)
    repomap = gen.generate_repomap()

    assert "module.py" in repomap
    assert "class OrderService" in repomap
    assert "process_order" in repomap
    assert "def calculate_tax" in repomap


def test_local_tool_registry(tmp_path):
    from alfa.core.cli.agent_engine import LocalToolRegistry

    registry = LocalToolRegistry(workspace_root=tmp_path)

    # 1. write_file
    res_w = registry.write_file("app.py", "x = 10\ny = 20\n")
    assert "Sukses" in res_w
    assert (tmp_path / "app.py").exists()

    # 2. read_file
    res_r = registry.read_file("app.py", start_line=1, end_line=2)
    assert "x = 10" in res_r
    assert "y = 20" in res_r

    # 3. patch_file
    res_p = registry.patch_file("app.py", "y = 20", "y = 99")
    assert "Sukses" in res_p
    assert "y = 99" in (tmp_path / "app.py").read_text(encoding="utf-8")

    # 4. find_files
    res_f = registry.find_files("*.py")
    assert "app.py" in res_f

    # 5. search_code
    res_s = registry.search_code("y = 99")
    assert "app.py" in res_s

    # 6. run_command safe & dangerous
    res_cmd = registry.run_command("python3 -c \"print('ALFA_TEST_OK')\"")
    assert "ALFA_TEST_OK" in res_cmd

    res_dang = registry.run_command("rm -rf /")
    assert "Ditolak" in res_dang


def test_autonomous_agent_tool_extraction():
    from alfa.core.cli.agent_engine import AutonomousAgentRunner

    runner = AutonomousAgentRunner(direct_ai=MagicMock())

    text_with_block = """
Saya akan membaca file app.py terlebih dahulu.
```tool_call
{"tool": "read_file", "args": {"path": "app.py", "start_line": 1, "end_line": 10}}
```
"""
    calls = runner._extract_tool_calls(text_with_block)
    assert len(calls) == 1
    assert calls[0]["tool"] == "read_file"
    assert calls[0]["args"]["path"] == "app.py"

    text_raw = 'Tindakan: {"tool": "search_code", "args": {"query": "login"}}'
    calls_raw = runner._extract_tool_calls(text_raw)
    assert len(calls_raw) == 1
    assert calls_raw[0]["tool"] == "search_code"

    text_fn = 'Saya memanggil list_directory(".") sekarang'
    calls_fn = runner._extract_tool_calls(text_fn)
    assert len(calls_fn) == 1
    assert calls_fn[0]["tool"] == "list_directory"
    assert calls_fn[0]["args"]["path"] == "."


def test_anti_refusal_and_proactive_folder_check(tmp_path):
    from alfa.core.cli.agent_engine import AutonomousAgentRunner

    dummy_file = tmp_path / "hello.py"
    dummy_file.write_text("print('test')", encoding="utf-8")

    mock_ai = MagicMock()
    # Turn 1: AI hallucinates refusal
    # Turn 2: After auto-intervention, AI answers properly
    mock_ai.generate.side_effect = [
        "Maaf, saya tidak memiliki akses langsung ke sistem file lokal Anda. Silakan jalankan ls -la.",
        "Final Answer: Saya telah memeriksa folder ini dan menemukan file hello.py.",
    ]
    mock_ai.system_prompt = ""
    mock_ai.provider = "google"
    mock_ai.model = "test-model"

    runner = AutonomousAgentRunner(direct_ai=mock_ai, workspace_root=tmp_path)
    result = runner.run("cek folder ini")

    assert "hello.py" in result or "Final Answer" in result
    assert mock_ai.generate.call_count == 2


def test_agent_slash_commands(capsys):
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone")

    # /agent toggle
    cli.do_slash_agent("on")
    assert cli.agent_mode is True

    cli.do_slash_agent("off")
    assert cli.agent_mode is False

    cli.do_slash_agent("status")
    captured = capsys.readouterr()
    assert "Autonomous Agent Mode" in captured.out

    # /tools command
    cli.do_slash_tools("")
    captured2 = capsys.readouterr()
    assert "search_code" in captured2.out
    assert "run_command" in captured2.out

    # /repomap command
    cli.do_slash_repomap("")
    captured3 = capsys.readouterr()
    assert "Repomap" in captured3.out


def test_server_manager_status():
    from alfa.core.cli.server_manager import get_servers_status

    status = get_servers_status()
    assert "dashboard" in status
    assert "9router" in status
    assert "bot" in status
    assert "ok" in status["dashboard"]


def test_swarm_agents_and_persona_switching(capsys):
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone")

    # /agents listing
    cli.do_slash_agents("")
    captured = capsys.readouterr()
    assert (
        "Workforce" in captured.out
        or "Swarm" in captured.out
        or "Custom Agent" in captured.out
    )

    # /persona listing
    cli.do_slash_persona("")
    captured_p = capsys.readouterr()
    assert "Persona Swarm Saat Ini" in captured_p.out

    # Switch to persona (e.g. Code Crafter)
    cli.do_slash_persona("Code Crafter")
    assert cli.active_persona_name == "Code Crafter"
    assert "Code Crafter" in cli.prompt

    # Reset persona
    cli.do_slash_persona("reset")
    assert cli.active_persona_name is None
    assert "Code Crafter" not in cli.prompt


def test_agent_runner_ecosystem_tools(tmp_path):
    from alfa.core.cli.agent_engine import AutonomousAgentRunner

    mock_ai = MagicMock()
    mock_ai.system_prompt = ""
    mock_ai.provider = "google"
    mock_ai.model = "test-model"

    runner = AutonomousAgentRunner(direct_ai=mock_ai, workspace_root=tmp_path)

    # Test executing get_system_stats via _execute_tool
    res = runner._execute_tool("get_system_stats", {})
    assert "cpu" in res.lower() or "ram" in res.lower() or "status" in res.lower()


def test_servers_slash_command(capsys):
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone")
    cli.do_slash_servers("status")
    captured = capsys.readouterr()
    assert "Web Command Center" in captured.out
    assert "9Router" in captured.out


def test_sync_external_api_keys(capsys):
    from alfa.core import database

    # Verify sync function runs cleanly
    synced = database.sync_external_api_keys_sync()
    assert isinstance(synced, list)

    keys = database.list_api_keys_sync(auto_sync=True)
    assert len(keys) > 0
    # 9router should be present in keys
    providers = [k["provider"] for k in keys]
    assert "9router" in providers

    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone")
    cli.do_slash_keys("sync")
    captured = capsys.readouterr()
    assert "ALFA Vault" in captured.out
    assert "9Router" in captured.out


def test_proactive_deep_folder_inspection_and_rich_fallback(tmp_path):
    from unittest.mock import MagicMock

    from alfa.core.cli.agent_engine import AutonomousAgentRunner

    # Create a dummy blueprint file
    bp_file = tmp_path / "chat-Arsitektur.txt"
    bp_file.write_text(
        "Blueprint Sistem Agen Super Cerdas:\n- Layer 1: Core\n- Layer 2: Tools",
        encoding="utf-8",
    )

    mock_ai = MagicMock()
    mock_ai.system_prompt = ""
    mock_ai.provider = "9router"
    mock_ai.model = "antigravity"

    # AI generates text with mention of list_directory in prose, but finishes without Final Answer: prefix
    mock_ai.generate.return_value = (
        "### Laporan Analisis Arsitektur Proyek\n\n"
        "Berdasarkan hasil pemindaian dan pembacaan berkas, direktori ini memuat cetak biru agen cerdas.\n"
        "Arsitektur terdiri atas Core dan Tools."
    )

    runner = AutonomousAgentRunner(direct_ai=mock_ai, workspace_root=tmp_path)
    ans = runner.run("cek folder ini")

    # Assert deep inspection caught the content and outputted rich analysis, NOT lazy 1-line fallback
    assert "Pemeriksaan dan tindakan selesai" not in ans
    assert "Laporan Analisis Arsitektur Proyek" in ans or "Core dan Tools" in ans


def test_single_vs_swarm_mode_and_agent_model_config(capsys):
    from alfa.core import database
    from alfa.core.cli.app import AlfaCLI

    cli = AlfaCLI(mode="standalone")

    # 1. Default execution mode is single
    assert cli.agent_execution_mode == "single"
    assert "single" in cli.prompt

    # 2. Switch to swarm mode
    cli.do_slash_mode("swarm")
    assert cli.agent_execution_mode == "swarm"
    assert "swarm" in cli.prompt
    assert "🐝" in cli.prompt

    # 3. Switch back to single mode via /agent single
    cli.do_slash_agent("single")
    assert cli.agent_execution_mode == "single"
    assert "single" in cli.prompt
    assert "⚡" in cli.prompt

    # 4. Configure per-agent model via /swarm model
    cli.do_slash_swarm('model "Code Crafter" deepseek deepseek-coder')
    captured = capsys.readouterr()
    assert "Code Crafter" in captured.out
    assert "DEEPSEEK" in captured.out

    agent_cc = database.get_custom_agent_sync("Code Crafter")
    assert agent_cc is not None
    assert agent_cc["provider"] == "deepseek"
    assert agent_cc["model"] == "deepseek-coder"

    # 5. Configure agent #1 via /agent model
    cli.do_slash_agent("model 1 9router antigravity")
    captured_1 = capsys.readouterr()
    assert "9ROUTER" in captured_1.out

    agent_1 = database.get_custom_agent_sync(1)
    assert agent_1 is not None
    assert agent_1["provider"] == "9router"
    assert agent_1["model"] == "antigravity"

    # 6. Check /mode display
    cli.do_slash_mode("")
    captured_mode = capsys.readouterr()
    assert "Mode Eksekusi Agen" in captured_mode.out
    assert "Mode Koneksi" in captured_mode.out


def test_resilient_patching_3_layers(tmp_path):
    """Test 3-layer progressive patch matching: exact, whitespace-normalized, fuzzy."""
    from alfa.core.cli.agent_engine import LocalToolRegistry

    registry = LocalToolRegistry(workspace_root=tmp_path)
    test_file = tmp_path / "code.py"
    initial_content = (
        "def calculate_total(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item.price\n"
        "    return total\n"
    )
    test_file.write_text(initial_content, encoding="utf-8")

    # 1. Exact match test
    res1 = registry.patch_file(
        "code.py",
        "        total += item.price",
        "        total += item.price * (1 + item.tax_rate)",
    )
    assert "Sukses" in res1
    assert "exact" in res1
    assert "total += item.price * (1 + item.tax_rate)" in test_file.read_text(
        encoding="utf-8"
    )

    # 2. Whitespace-normalized match test (different trailing whitespace and tab/spaces)
    res2 = registry.patch_file(
        "code.py",
        "def calculate_total(items):   \n    total = 0   ",
        "def calculate_total(items, discount=0.0):\n    total = -discount",
    )
    assert "Sukses" in res2
    assert "whitespace-normalized" in res2
    assert "def calculate_total(items, discount=0.0):" in test_file.read_text(
        encoding="utf-8"
    )

    # 3. Fuzzy similarity match test (minor difference in loop lines)
    res3 = registry.patch_file(
        "code.py",
        "    for item in items:\n"
        "        # process\n"
        "        total += item.price * (1 + item.tax_rate)",
        "    for item in items:\n        total += item.calculate_final_price()",
    )
    assert "Sukses" in res3
    assert "fuzzy-matched" in res3
    assert "calculate_final_price()" in test_file.read_text(encoding="utf-8")


def test_relaxed_json_and_balanced_tool_extraction():
    """Test resilient balanced braces and relaxed JSON repair for tool extraction."""
    from alfa.core.cli.agent_engine import AutonomousAgentRunner

    runner = AutonomousAgentRunner(direct_ai=MagicMock())

    # 1. Single quotes & nested JSON object
    text1 = (
        "Thought: Membaca konfigurasi\n"
        "```tool_call\n"
        "{'tool': 'custom_setup', 'args': {'config': {'theme': 'dark', 'port': 8080}, 'enabled': True}}\n"
        "```"
    )
    calls1 = runner._extract_tool_calls(text1)
    assert len(calls1) == 1
    assert calls1[0]["tool"] == "custom_setup"
    assert calls1[0]["args"]["config"]["theme"] == "dark"
    assert calls1[0]["args"]["config"]["port"] == 8080

    # 2. Trailing comma in JSON
    text2 = '```json\n{"tool": "find_files", "args": {"pattern": "*.py",},}\n```'
    calls2 = runner._extract_tool_calls(text2)
    assert len(calls2) == 1
    assert calls2[0]["tool"] == "find_files"
    assert calls2[0]["args"]["pattern"] == "*.py"

    # 3. Keyword-arg function call syntax
    text3 = 'Mari kita baca file: read_file(path="app.py", start_line=10, end_line=50)'
    calls3 = runner._extract_tool_calls(text3)
    assert len(calls3) == 1
    assert calls3[0]["tool"] == "read_file"
    assert calls3[0]["args"]["path"] == "app.py"
    assert calls3[0]["args"]["start_line"] == 10
    assert calls3[0]["args"]["end_line"] == 50


def test_smart_rolling_context_compression():
    """Test that older heavy observations are compressed while recent turns remain full resolution."""
    from alfa.core.cli.agent_engine import AutonomousAgentRunner

    long_output = "Line 1: data\n" + ("X" * 100 + "\n") * 20 + "Line final: end data\n"
    history = [
        {"role": "user", "content": "User Request: Analisis file ini"},
        {"role": "assistant", "content": "Thought: Membaca file"},
        {"role": "user", "content": f"Observation from read_file:\n{long_output}"},
        {"role": "assistant", "content": "Thought: Menjalankan test"},
        {"role": "user", "content": f"Observation from run_command:\n{long_output}"},
        {"role": "assistant", "content": "Thought: Menerapkan patch"},
        {"role": "user", "content": "Observation from patch_file:\nSukses diterapkan"},
        {"role": "assistant", "content": "Thought: Menjalankan verifikasi akhir"},
        {"role": "user", "content": "Observation from pytest:\n10 passed"},
    ]

    compressed = AutonomousAgentRunner._compress_conversation_history(
        history, keep_recent_messages=4
    )

    # Root prompt always preserved
    assert compressed[0]["content"] == "User Request: Analisis file ini"
    # Older long observation compressed
    assert "diringkas untuk efisiensi token" in compressed[2]["content"]
    assert len(compressed[2]["content"]) < len(long_output)
    # Recent turns preserved at 100% full fidelity
    assert compressed[-1]["content"] == "Observation from pytest:\n10 passed"
    assert (
        compressed[-3]["content"] == "Observation from patch_file:\nSukses diterapkan"
    )


def test_dynamic_shell_timeout_and_noninteractive_env(tmp_path):
    """Test dynamic timeout and non-interactive environment variables in run_command."""
    from alfa.core.cli.agent_engine import LocalToolRegistry

    registry = LocalToolRegistry(workspace_root=tmp_path)

    # Verify non-interactive env flags are passed
    res = registry.run_command(
        "python3 -c \"import os; print(os.environ.get('CI'), os.environ.get('DEBIAN_FRONTEND'))\""
    )
    assert "1 noninteractive" in res


def test_multi_language_repomap_symbol_extraction(tmp_path):
    """Test rich symbol extraction for TypeScript, Go, Rust, and Dart."""
    from alfa.core.cli.agent_engine import RepomapGenerator

    gen = RepomapGenerator(root_dir=tmp_path)

    # 1. TypeScript file
    ts_file = tmp_path / "service.ts"
    ts_file.write_text(
        "export interface UserProfile { id: string; }\n"
        "export type AuthState = 'idle' | 'logged_in';\n"
        "export class AuthService { login() {} }\n"
        "export const authenticateUser = async () => {};\n",
        encoding="utf-8",
    )
    ts_symbols = gen._extract_regex_symbols(ts_file)
    assert any("interface UserProfile" in s for s in ts_symbols)
    assert any("type AuthState" in s for s in ts_symbols)
    assert any("class AuthService" in s for s in ts_symbols)
    assert any("authenticateUser" in s for s in ts_symbols)

    # 2. Go file
    go_file = tmp_path / "server.go"
    go_file.write_text(
        "package main\n"
        "type Config struct { Port int }\n"
        "type Service interface { Run() }\n"
        "func (c *Config) Validate() error { return nil }\n"
        "func NewServer() *Server { return &Server{} }\n",
        encoding="utf-8",
    )
    go_symbols = gen._extract_regex_symbols(go_file)
    assert any("struct Config" in s for s in go_symbols)
    assert any("interface Service" in s for s in go_symbols)
    assert any("(Config).Validate()" in s for s in go_symbols)
    assert any("NewServer()" in s for s in go_symbols)
