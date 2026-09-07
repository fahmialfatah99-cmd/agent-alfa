# Architectural Specification: ALFA Codebase Restructuring & Modularization

- **Date:** 2026-09-07
- **Status:** Approved
- **Scope:** Full Repo Modularization, Monolith Decomposition, and Root Hygiene with Backward-Compatible Shims

---

## 1. Executive Summary & Goals

The ALFA repository currently suffers from significant architectural debt:
1. Massive monoliths: `tools.py` (6,580 lines), `web_dashboard.py` (4,921 lines), and `templates/index.html` (11,450 lines inline).
2. Cluttered root folder with over 75 loose files (multi-OS launcher scripts, untracked databases/backups, test files, and image assets).
3. Split architecture between a partial `alfa/` package and duplicate root-level modules.

**Primary Goal:** Transform the codebase into an enterprise-grade, clean, layered Python package located under `alfa/`, while guaranteeing **zero downtime and 100% backward compatibility** for all existing systemd user services (`alfa-dashboard.service`, `telegram-ai-bot.service`), CLI commands, and test suites via thin compatibility shims in the root directory.

---

## 2. Directory Structure & Layout

### 2.1 Target Directory Layout

```text
telegram-ai-bot/
├── alfa/                            # Unified Core Domain Package
│   ├── __init__.py
│   ├── core/                        # Engine, DB, Memory, Permissions
│   │   ├── __init__.py
│   │   ├── database.py              # SQLite/SQLAlchemy models & migrations
│   │   ├── brain.py                 # LLM client & reasoning pipeline
│   │   ├── permissions.py           # Permission gating & security auditor
│   │   ├── runtime_ctx.py           # Thread-local / async context
│   │   └── cli.py                   # Unified CLI implementation
│   ├── tools/                       # Modularized tools (split from tools.py)
│   │   ├── __init__.py              # Central registry & export interface
│   │   ├── registry.py              # @register_tool decorator & schema generators
│   │   ├── system_tools.py          # Bash, Python sandbox, network scanning, stats
│   │   ├── filesystem_tools.py      # File IO, precise edits, diffs, code search
│   │   ├── web_tools.py             # Web search, web content fetch, browser automation
│   │   ├── desktop_tools.py         # Screenshot (Wayland/X11/Win32), mouse, keyboard
│   │   ├── academic_tools.py        # ArXiv, PubMed, literature research
│   │   ├── media_tools.py           # Image generation, TTS audio, video synthesis
│   │   └── memory_tools.py          # Vector store & persistent knowledge memory
│   ├── dashboard/                   # Modularized dashboard (split from web_dashboard.py)
│   │   ├── __init__.py
│   │   ├── app.py                   # FastAPI factory, middleware, static mounts
│   │   ├── websocket.py             # WebSocket connection manager
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── chat.py              # SSE chat streaming & session endpoints
│   │       ├── tools.py             # Tool execution & catalog endpoints
│   │       ├── swarm.py             # Swarm agent endpoints & persona dispatch
│   │       ├── system.py            # System metrics, logs, telemetry
│   │       └── auth.py              # Token verification & session management
│   ├── bot/                         # Telegram Bot logic (split from bot.py)
│   │   ├── __init__.py
│   │   └── telegram_bot.py          # Handlers, filters, polling/webhook logic
│   ├── swarm/                       # Multi-agent Swarm system
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── personas.py
│   │   └── checkpoint.py
│   ├── scrapers/                    # Scraping subsystem
│   │   ├── __init__.py
│   │   ├── fast.py
│   │   └── universal.py
│   └── integrations/                # External services (GDrive, etc.)
│       ├── __init__.py
│       └── gdrive.py
├── scripts/                         # Multi-platform scripts
│   ├── run.sh                       # Linux runner
│   ├── setup.sh                     # Linux setup
│   ├── run.bat                      # Windows runner
│   ├── setup.bat                    # Windows setup
│   ├── setup.ps1                    # PowerShell setup
│   ├── start_alfa.ps1               # PowerShell launcher
│   ├── alfa_guardian.ps1            # Windows watchdog
│   ├── enable_autostart.bat / .ps1  # Autostart config
│   ├── disable_autostart.bat / .ps1
│   └── launch_guardian_hidden.vbs
├── static/                          # Extracted static frontend assets
│   ├── css/
│   │   └── dashboard.css            # Custom CSS styles extracted from index.html
│   ├── js/
│   │   ├── app.js                   # Alpine.js state store & app init
│   │   ├── chat.js                  # SSE chat & message renderer
│   │   ├── terminal.js              # WebSocket terminal & log streaming
│   │   └── tools.js                 # Tools modal & audio controllers
│   └── img/                         # laptop-1024.png, mobile-390.png
├── templates/
│   └── index.html                   # Clean semantic HTML template (<1,500 lines)
├── storage/                         # Database and persistent files
│   ├── agent_data.db
│   └── backups/
├── tests/                           # Consolidated test suite
│   ├── test_agent.py
│   ├── test_auth_system.py
│   ├── test_security.py
│   ├── test_security_fixes.py
│   └── ...
├── bot.py                           # Root shim (delegates to alfa.bot)
├── web_dashboard.py                 # Root shim (delegates to alfa.dashboard)
├── tools.py                         # Root shim (delegates to alfa.tools)
├── database.py                      # Root shim (delegates to alfa.core.database)
├── main_brain.py                    # Root shim (delegates to alfa.core.brain)
├── swarm_engine.py                  # Root shim (delegates to alfa.swarm.engine)
├── cli.py                           # Root shim (delegates to alfa.core.cli)
└── run.sh                           # Symlink / thin launcher invoking scripts/run.sh
```

---

## 3. Detailed Component Specifications

### 3.1 Root Shims Specification
To ensure all external consumers (systemd units, crons, docker scripts) continue functioning transparently:
- `tools.py`:
  ```python
  """Backward-compatibility shim for alfa.tools."""
  from alfa.tools import *  # noqa: F403
  ```
- `web_dashboard.py`:
  ```python
  """Backward-compatibility shim for alfa.dashboard."""
  import os
  import uvicorn
  from alfa.dashboard.app import app

  if __name__ == "__main__":
      port = int(os.getenv("DASHBOARD_PORT", "8080"))
      host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
      uvicorn.run(app, host=host, port=port, reload=False)
  ```
- `bot.py`:
  ```python
  """Backward-compatibility shim for alfa.bot."""
  from alfa.bot.telegram_bot import main

  if __name__ == "__main__":
      main()
  ```

### 3.2 Modularization of `tools.py`
The ~6,580 lines of `tools.py` are mapped into targeted modules under `alfa/tools/`:
1. `registry.py`: Defines `@register_tool` decorator, `TOOL_REGISTRY` dictionary, and `get_tool_definitions()`.
2. `system_tools.py`: `execute_bash_command`, `execute_python_sandbox`, `get_system_stats`, `scan_local_network`, `schedule_reminder`.
3. `filesystem_tools.py`: `read_local_file`, `write_local_file`, `edit_file_precise`, `apply_unified_diff`, `search_workspace_files`, `grep_workspace`, `index_codebase`, `search_codebase`.
4. `web_tools.py`: `web_search`, `fetch_web_page_content`, `browser_open_url`, `browser_click_element`, `browser_type_text`, `browser_capture_screenshot`, `browser_close_tab`.
5. `desktop_tools.py`: `capture_desktop_screenshot`, `capture_webcam_frame`, `desktop_click_coordinate`, `desktop_type_keys`, `desktop_launch_app`.
6. `academic_tools.py`: Literature searches, arXiv queries, PubMed extraction.
7. `media_tools.py`: TTS audio synthesis, video generation, image generation triggers.
8. `memory_tools.py`: `save_knowledge_memory`, `search_knowledge_memory`, vector index handlers.
9. `alfa/tools/__init__.py`: Imports and re-exports all tools into a single namespace.

### 3.3 Modularization of `web_dashboard.py`
The ~4,921 lines are broken down into FastAPI `APIRouter` instances:
1. `alfa/dashboard/app.py`: Sets up FastAPI instance, CORS, authentication middleware, error handlers, and mounts `/static`.
2. `alfa/dashboard/websocket.py`: Encapsulates WebSocket connections, broadcast queues, and client tracking.
3. `alfa/dashboard/routes/chat.py`: Handles `/api/chat` SSE stream, conversation management, message histories.
4. `alfa/dashboard/routes/tools.py`: Handles `/api/tools`, manual tool invocation, catalog listings.
5. `alfa/dashboard/routes/swarm.py`: Handles `/api/swarm/*`, persona selection, and delegation.
6. `alfa/dashboard/routes/system.py`: Handles `/api/system/*`, `/health`, CPU/RAM statistics, and log feeds.
7. `alfa/dashboard/routes/auth.py`: Handles `/api/auth/*`, token validation, and password checks.

### 3.4 Frontend Extraction (`templates/index.html`)
The 11,450 lines of `templates/index.html` are split cleanly:
1. `static/css/dashboard.css`: Contains custom CSS animations, dark mode overrides, custom scrollbar styling.
2. `static/js/app.js`: Alpine.js reactive state store, theme toggles, notification toast handlers.
3. `static/js/chat.js`: SSE EventSource streaming parser, markdown rendering via marked.js, message auto-scrolling.
4. `static/js/terminal.js`: Terminal rendering, WebSocket log streaming, ANSI color code parser.
5. `static/js/tools.js`: Tool parameter forms, execution trigger handlers, audio recorder/player.
6. `templates/index.html`: Contains only structural semantic HTML referencing the above CSS and JS files via standard `<link>` and `<script>` tags.

---

## 4. Migration & Verification Strategy

### 4.1 Step-by-Step Execution Sequence
1. **Directory Structure Creation**: Create `scripts/`, `static/css/`, `static/js/`, `static/img/`, `storage/backups/`, and `alfa/` subdirectories.
2. **Root File Relocation**:
   - Move OS scripts to `scripts/`.
   - Move `.png` files to `static/img/`.
   - Move root `test_*.py` files to `tests/`.
   - Update `.gitignore` to explicitly ignore credentials and local `.db` backups.
3. **Core & Domain Code Migration**:
   - Extract and populate `alfa/tools/*`.
   - Extract and populate `alfa/dashboard/*`.
   - Extract and populate `alfa/core/*`, `alfa/bot/*`, `alfa/swarm/*`.
4. **Root Shims Deployment**:
   - Write clean shims for `tools.py`, `web_dashboard.py`, `bot.py`, `database.py`, `main_brain.py`, `swarm_engine.py`, `cli.py`.
5. **Frontend Asset Extraction**:
   - Split `templates/index.html` into `dashboard.css`, `app.js`, `chat.js`, `terminal.js`, `tools.js`.
   - Verify template renders properly.

### 4.2 Quality Assurance & Verification
- **Syntax Check:** `python -m py_compile` across all files in `alfa/` and root shims.
- **Import Check:** Verify `python -c "import tools, web_dashboard, bot, database, swarm_engine"` executes with 0 errors.
- **Test Suite:** Execute `pytest tests/` to ensure no regression.
- **Service Verification:** Verify `curl -s http://127.0.0.1:8080/` returns HTTP 200 and loads extracted static assets correctly.
