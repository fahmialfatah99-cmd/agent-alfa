# ALFA Codebase Restructuring & Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the monolithic ALFA codebase into a clean, layered Python package (`alfa/`) with modular subpackages for tools, dashboard, bot, and core services, while maintaining 100% backward compatibility for all existing systemd services via thin root shims.

**Architecture:** A domain-driven package architecture under `alfa/` (`alfa.tools`, `alfa.dashboard`, `alfa.core`, `alfa.bot`, `alfa.swarm`). Root-level entrypoints (`tools.py`, `web_dashboard.py`, `bot.py`, etc.) become thin shims delegating to `alfa.*`, ensuring zero breaking changes to existing systemd user services or scripts. Non-code clutter (scripts, assets, databases, tests) is consolidated into dedicated directories.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, SQLite/SQLAlchemy, Tailwind CSS, Alpine.js, Pytest, Systemd.

**Spec:** [`docs/superpowers/specs/2026-09-07-codebase-restructuring-and-modularization-design.md`](file:///home/fahmial/telegram-ai-bot/docs/superpowers/specs/2026-09-07-codebase-restructuring-and-modularization-design.md)

## Global Constraints

- Never break existing systemd service executions: `%h/telegram-ai-bot/venv/bin/python3 %h/telegram-ai-bot/web_dashboard.py` and `bot.py` must remain valid entrypoints.
- All existing imports from `tools` (e.g. `from tools import web_search`) must continue to work via root `tools.py` re-exporting `alfa.tools.*`.
- Active database `agent_data.db` and its WAL files must never be corrupted or overwritten.
- Python files must pass `python -m py_compile` and existing pytest test suites.

---

### Task 1: Project Hygiene & Root Cleanup

**Files:**
- Create: `scripts/` directory
- Create: `static/img/` directory
- Create: `storage/backups/` directory
- Modify: `.gitignore`
- Move: `run.sh`, `setup.sh`, `run.bat`, `setup.bat`, `setup.ps1`, `start_alfa.ps1`, `alfa_guardian.ps1`, `enable_autostart.*`, `disable_autostart.*`, `launch_guardian_hidden.vbs` -> `scripts/`
- Create: Root `run.sh` thin launcher calling `scripts/run.sh`
- Move: `laptop-1024.png`, `mobile-390.png` -> `static/img/`
- Move: `test_agent.py`, `test_auth_system.py`, `test_security.py`, `test_security_fixes.py` -> `tests/`

**Interfaces:**
- Consumes: Existing root loose files
- Produces: Clean root folder, dedicated `scripts/`, `static/img/`, `tests/` directories

- [ ] **Step 1: Create target directory structures**

```bash
mkdir -p scripts static/img static/css static/js storage/backups
```

- [ ] **Step 2: Move scripts and create root run.sh forwarder**

Move launcher scripts to `scripts/`:
```bash
mv setup.sh setup.bat setup.ps1 run.bat start_alfa.ps1 alfa_guardian.ps1 enable_autostart.bat enable_autostart.ps1 disable_autostart.bat disable_autostart.ps1 launch_guardian_hidden.vbs scripts/
cp run.sh scripts/run.sh
```
Create root `run.sh` delegator:
```bash
cat << 'EOF' > run.sh
#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/scripts/run.sh" "$@"
EOF
chmod +x run.sh scripts/run.sh
```

- [ ] **Step 3: Move image assets and test files**

```bash
mv laptop-1024.png mobile-390.png static/img/ 2>/dev/null || true
mv test_agent.py test_auth_system.py test_security.py test_security_fixes.py tests/ 2>/dev/null || true
```

- [ ] **Step 4: Update .gitignore for security & backups**

Ensure `.gitignore` contains:
```gitignore
agent_data.db.bak
agent_data.db.local_backup
gdrive_oauth_client_secret.json
gdrive_oauth_token.json
.venv/
```

- [ ] **Step 5: Run tests to verify relocated test files pass**

Run: `./venv/bin/pytest tests/test_database.py -v`
Expected: PASS

- [ ] **Step 6: Commit Task 1**

```bash
git add scripts/ static/img/ tests/ .gitignore run.sh
git commit -m "refactor(repo): organize root scripts, assets, and tests into dedicated directories"
```

---

### Task 2: Core Subsystems & Utilities Consolidation (`alfa/core/`, `alfa/scrapers/`, `alfa/integrations/`)

**Files:**
- Create: `alfa/core/__init__.py`
- Create: `alfa/core/database.py` (migrated from `database.py`)
- Create: `alfa/core/brain.py` (migrated from `main_brain.py`)
- Create: `alfa/core/permissions.py` (migrated from `permission_gate.py` & `security_auditor.py`)
- Create: `alfa/core/runtime_ctx.py` (migrated from `runtime_ctx.py`)
- Create: `alfa/core/cli.py` (migrated from `cli.py`)
- Create: `alfa/scrapers/__init__.py`, `alfa/scrapers/fast.py`, `alfa/scrapers/universal.py`
- Create: `alfa/integrations/__init__.py`, `alfa/integrations/gdrive.py`
- Modify: `database.py`, `main_brain.py`, `permission_gate.py`, `cli.py`, `fast_scraper.py`, `universal_scraper.py`, `gdrive_suite.py` (become thin compatibility shims)

**Interfaces:**
- Consumes: Existing root logic files
- Produces: `alfa.core.*`, `alfa.scrapers.*`, `alfa.integrations.*` with backward-compatible shims in root

- [ ] **Step 1: Migrate database, brain, permissions, runtime_ctx to `alfa/core/`**

Copy and adjust internal package imports:
- `alfa/core/database.py`: Core database models and operations
- `alfa/core/brain.py`: LLM core engine
- `alfa/core/permissions.py`: Security and gatekeeper logic
- `alfa/core/runtime_ctx.py`: Execution context
- `alfa/core/cli.py`: Interactive CLI

- [ ] **Step 2: Create root shims for core modules**

In `database.py`:
```python
"""Backward-compatibility shim for alfa.core.database."""
from alfa.core.database import *  # noqa: F403
```
In `main_brain.py`:
```python
"""Backward-compatibility shim for alfa.core.brain."""
from alfa.core.brain import *  # noqa: F403
```
In `permission_gate.py`:
```python
"""Backward-compatibility shim for alfa.core.permissions."""
from alfa.core.permissions import *  # noqa: F403
```
In `cli.py`:
```python
"""Backward-compatibility shim for alfa.core.cli."""
from alfa.core.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Migrate scrapers and integrations**

- Populate `alfa/scrapers/fast.py` (from `fast_scraper.py`) and `alfa/scrapers/universal.py` (from `universal_scraper.py`)
- Populate `alfa/integrations/gdrive.py` (from `gdrive_suite.py`)
- Replace root `fast_scraper.py`, `universal_scraper.py`, and `gdrive_suite.py` with thin shims.

- [ ] **Step 4: Verify syntax and import compatibility**

Run:
```bash
./venv/bin/python3 -c "import database; import main_brain; import permission_gate; import cli; import fast_scraper; import universal_scraper; print('Core shims imported successfully')"
```
Expected: `Core shims imported successfully`

- [ ] **Step 5: Run database and brain tests**

Run: `./venv/bin/pytest tests/test_database.py tests/test_main_brain.py -v`
Expected: PASS

- [ ] **Step 6: Commit Task 2**

```bash
git add alfa/core/ alfa/scrapers/ alfa/integrations/ database.py main_brain.py permission_gate.py cli.py fast_scraper.py universal_scraper.py gdrive_suite.py
git commit -m "refactor(core): consolidate database, brain, permissions, scrapers into alfa package with shims"
```

---

### Task 3: Modularize `tools.py` into Domain Submodules (`alfa/tools/`)

**Files:**
- Create: `alfa/tools/__init__.py`
- Create: `alfa/tools/registry.py`
- Create: `alfa/tools/system_tools.py`
- Create: `alfa/tools/filesystem_tools.py`
- Create: `alfa/tools/web_tools.py`
- Create: `alfa/tools/desktop_tools.py`
- Create: `alfa/tools/academic_tools.py`
- Create: `alfa/tools/media_tools.py`
- Create: `alfa/tools/memory_tools.py`
- Modify: `tools.py` (becomes compatibility shim re-exporting `alfa.tools.*`)

**Interfaces:**
- Consumes: ~6,580 lines of functions in `tools.py`
- Produces: `alfa.tools` package where every tool is registered and re-exported under `tools.*`

- [ ] **Step 1: Implement `alfa/tools/registry.py`**

Create the tool registry decorator, catalog container, and schema inspection helpers.

- [ ] **Step 2: Extract tool categories from `tools.py` into dedicated submodules**

- `alfa/tools/system_tools.py`: Bash execution, Python sandbox, network scan, stats, reminders.
- `alfa/tools/filesystem_tools.py`: File read/write, patch/diff, grep, codebase indexer.
- `alfa/tools/web_tools.py`: Web search, content fetch, Camofox browser automation.
- `alfa/tools/desktop_tools.py`: Screenshot capture, mouse coordinate clicking, keyboard typing.
- `alfa/tools/academic_tools.py`: arXiv, PubMed, research paper tools.
- `alfa/tools/media_tools.py`: Video generation, TTS, image generation.
- `alfa/tools/memory_tools.py`: Knowledge memory, vector embeddings.

- [ ] **Step 3: Assemble `alfa/tools/__init__.py`**

Import all functions from the submodules and export via `__all__`.

- [ ] **Step 4: Update root `tools.py` as thin shim**

```python
"""Backward-compatibility shim for alfa.tools.

All tools are now organized in the modular package `alfa.tools`.
"""
from alfa.tools import *  # noqa: F401, F403
```

- [ ] **Step 5: Verify all tools import cleanly**

Run:
```bash
./venv/bin/python3 -c "import tools; print(f'Loaded {len(dir(tools))} symbols from tools shim')"
```
Expected: Prints loaded symbol count without any AttributeError or ImportError.

- [ ] **Step 6: Run existing tools unit tests**

Run: `./venv/bin/pytest tests/test_tools_unit.py -v`
Expected: PASS

- [ ] **Step 7: Commit Task 3**

```bash
git add alfa/tools/ tools.py
git commit -m "refactor(tools): decompose monolithic tools.py into modular alfa.tools subpackage"
```

---

### Task 4: Modularize Swarm & Bot Subsystems (`alfa/swarm/`, `alfa/bot/`)

**Files:**
- Create: `alfa/swarm/__init__.py`
- Create: `alfa/swarm/engine.py` (migrated from `swarm_engine.py`)
- Create: `alfa/swarm/personas.py` (migrated from `swarm_personas.py`)
- Create: `alfa/swarm/checkpoint.py` (migrated from `swarm_checkpoint.py`)
- Create: `alfa/bot/__init__.py`
- Create: `alfa/bot/telegram_bot.py` (migrated from `bot.py`)
- Modify: `swarm_engine.py`, `swarm_personas.py`, `swarm_checkpoint.py` (compatibility shims)
- Modify: `bot.py` (compatibility shim)

**Interfaces:**
- Consumes: Swarm logic and Telegram bot logic
- Produces: `alfa.swarm`, `alfa.bot`, and root shims ensuring `telegram-ai-bot.service` runs seamlessly

- [ ] **Step 1: Modularize Swarm into `alfa/swarm/`**

- Move and adapt `swarm_engine.py` to `alfa/swarm/engine.py`
- Move and adapt `swarm_personas.py` to `alfa/swarm/personas.py`
- Move and adapt `swarm_checkpoint.py` to `alfa/swarm/checkpoint.py`
- Replace root `swarm_engine.py` with compatibility shim:
  ```python
  """Backward-compatibility shim for alfa.swarm.engine."""
  from alfa.swarm.engine import *  # noqa: F403
  ```

- [ ] **Step 2: Modularize Telegram Bot into `alfa/bot/`**

- Move `bot.py` logic to `alfa/bot/telegram_bot.py`
- Replace root `bot.py` with compatibility shim:
  ```python
  """Backward-compatibility shim for alfa.bot."""
  from alfa.bot.telegram_bot import *  # noqa: F403

  if __name__ == "__main__":
      from alfa.bot.telegram_bot import main
      main()
  ```

- [ ] **Step 3: Run syntax validation and swarm tests**

Run:
```bash
./venv/bin/python3 -m py_compile bot.py swarm_engine.py alfa/bot/telegram_bot.py alfa/swarm/engine.py
./venv/bin/pytest tests/test_swarm_logic.py -v
```
Expected: Compiles with code 0 and pytest passes.

- [ ] **Step 4: Commit Task 4**

```bash
git add alfa/swarm/ alfa/bot/ swarm_engine.py swarm_personas.py swarm_checkpoint.py bot.py
git commit -m "refactor(swarm,bot): modularize swarm engine and telegram bot into alfa subpackages"
```

---

### Task 5: Modularize Dashboard Backend (`alfa/dashboard/`)

**Files:**
- Create: `alfa/dashboard/__init__.py`
- Create: `alfa/dashboard/app.py` (FastAPI app setup, middleware, static mounts)
- Create: `alfa/dashboard/websocket.py` (WebSocket connection manager)
- Create: `alfa/dashboard/routes/__init__.py`
- Create: `alfa/dashboard/routes/chat.py` (SSE chat streaming)
- Create: `alfa/dashboard/routes/tools.py` (Tool execution & discovery)
- Create: `alfa/dashboard/routes/swarm.py` (Swarm operations)
- Create: `alfa/dashboard/routes/system.py` (Health, telemetry, logs)
- Create: `alfa/dashboard/routes/auth.py` (Session & auth verification)
- Modify: `web_dashboard.py` (shim delegating to `alfa.dashboard.app:app`)

**Interfaces:**
- Consumes: ~4,921 lines in `web_dashboard.py`
- Produces: Clean FastAPI `APIRouter` structure under `alfa/dashboard/`

- [ ] **Step 1: Create `alfa/dashboard/app.py` and routers**

- Setup FastAPI app instance, CORS middleware, token auth middleware.
- Mount `/static` directory to `static/`.
- Break route handlers into `routes/chat.py`, `routes/tools.py`, `routes/swarm.py`, `routes/system.py`, `routes/auth.py`.
- Break websocket handlers into `websocket.py`.

- [ ] **Step 2: Update `web_dashboard.py` as root entrypoint shim**

```python
"""Backward-compatibility shim for alfa.dashboard.

Used directly by systemd service alfa-dashboard.service.
"""
import os
import uvicorn
from alfa.dashboard.app import app

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    uvicorn.run("alfa.dashboard.app:app", host=host, port=port, reload=False)
```

- [ ] **Step 3: Verify dashboard syntax and import**

Run:
```bash
./venv/bin/python3 -c "from web_dashboard import app; print('web_dashboard app loaded:', app.title)"
```
Expected: Successfully prints app title without errors.

- [ ] **Step 4: Run dashboard tests**

Run: `./venv/bin/pytest tests/test_dashboard_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 5**

```bash
git add alfa/dashboard/ web_dashboard.py
git commit -m "refactor(dashboard): decompose monolithic web_dashboard.py into FastAPI APIRouters"
```

---

### Task 6: Decompose Frontend (`templates/index.html` -> `static/css/`, `static/js/`)

**Files:**
- Create: `static/css/dashboard.css`
- Create: `static/js/app.js`
- Create: `static/js/chat.js`
- Create: `static/js/terminal.js`
- Create: `static/js/tools.js`
- Modify: `templates/index.html`

**Interfaces:**
- Consumes: 11,450 lines in `templates/index.html`
- Produces: Lightweight, clean HTML template referencing external CSS and JS modules

- [ ] **Step 1: Extract custom CSS into `static/css/dashboard.css`**

Extract custom scrollbars, animations, syntax styling, and theme variables from `<style>` tags in `templates/index.html`.

- [ ] **Step 2: Extract JavaScript logic into `static/js/`**

- `static/js/app.js`: Alpine.js root initialization, store, sidebar toggles, audio playback.
- `static/js/chat.js`: SSE EventSource streaming handler, message bubble builder, markdown renderer.
- `static/js/terminal.js`: Terminal WebSocket client, log tailer, ANSI parser.
- `static/js/tools.js`: Tool parameter modal forms and action runners.

- [ ] **Step 3: Update `templates/index.html` to reference external static assets**

Add `<link rel="stylesheet" href="/static/css/dashboard.css">` and `<script src="/static/js/..."></script>` tags. Remove the ~10,000 lines of inline scripts and styles from the template.

- [ ] **Step 4: Verify template rendering via GET request**

Test with curl to verify HTTP 200 and presence of script/css links:
```bash
curl -s http://127.0.0.1:8080/ | grep -E "dashboard.css|chat.js|app.js"
```
Expected: Links to extracted static files appear in output.

- [ ] **Step 5: Commit Task 6**

```bash
git add static/css/ static/js/ templates/index.html
git commit -m "refactor(frontend): extract inline styles and scripts from index.html into static assets"
```

---

### Task 7: Full System Verification & Service Health Check

**Files:**
- Touch: all touched files for final lint / formatting audit

**Interfaces:**
- Full system integration test

- [ ] **Step 1: Run comprehensive pytest suite**

Run: `./venv/bin/pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 2: Run ruff check on refactored codebase**

Run: `./venv/bin/ruff check alfa/ --statistics`
Expected: 0 syntax errors or critical issues.

- [ ] **Step 3: Restart and check systemd services**

Run:
```bash
systemctl --user restart alfa-dashboard.service telegram-ai-bot.service
systemctl --user status alfa-dashboard.service --no-pager
systemctl --user status telegram-ai-bot.service --no-pager
```
Expected: Both services show `active (running)`.

- [ ] **Step 4: Test HTTP live endpoint**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/`
Expected: `200`

- [ ] **Step 5: Final Commit & Tag**

```bash
git commit --allow-empty -m "chore: complete codebase restructuring and modularization"
```
