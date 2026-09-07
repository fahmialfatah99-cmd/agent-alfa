# System Resilience & Advanced Feature Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 5 system resilience and user experience upgrades across WhatsApp bot auto-heal, local offline vector memory, Telegram progressive streaming response, frontend ES6 modularization, and Swarm Live Arena visualizer.

**Architecture:** Layered, backward-compatible implementation across 5 tasks, each with independent unit testing and zero disruption to active systemd services.

**Tech Stack:** Python 3.14 (FastAPI, pytest, asyncio), Node.js (Express, whatsapp-web.js, puppeteer), Tailwind CSS, Alpine.js, Chart.js.

**Spec:** [`docs/superpowers/specs/2026-09-07-system-resilience-and-feature-enhancements-design.md`](file:///home/fahmial/telegram-ai-bot/docs/superpowers/specs/2026-09-07-system-resilience-and-feature-enhancements-design.md)

## Global Constraints
- Never break existing systemd service executions: `alfa-dashboard.service`, `telegram-ai-bot.service`, and `wa-sheets-bot.service` must remain runnable.
- SQLite `agent_data.db` and Google Sheets credentials must remain untouched and uncorrupted.
- All existing and new tests in `tests/` must pass cleanly via `./venv/bin/pytest tests/`.
- Root shims must maintain 100% backward compatibility for imports and execution.

---

### Task 1: WhatsApp Bot Watchdog & Auto-Heal Engine

**Files:**
- Modify: `/home/fahmial/wa-sheets-bot/src/whatsapp.js`
- Modify: `/home/fahmial/wa-sheets-bot/src/server.js`
- Test: `/home/fahmial/wa-sheets-bot/test_watchdog.js`

**Interfaces:**
- Consumes: Node.js `whatsapp-web.js` Client, filesystem `fs`, `child_process`.
- Produces: Proactive `cleanStaleLocks()`, background `startWatchdog()`, safe `autoRecover()` triggering on stuck initializations or detached frame errors.

- [ ] **Step 1: Write test script for stale lock cleaning & watchdog logic**
- [ ] **Step 2: Implement `cleanStaleLocks()` in `src/whatsapp.js`**
- [ ] **Step 3: Implement background watchdog timer detecting stuck `INITIALIZING` state (>90s)**
- [ ] **Step 4: Enhance `/api/logout` and `/logout` error handlers in `src/server.js` to catch detached frame errors gracefully**
- [ ] **Step 5: Run watchdog test and verify service reload**
- [ ] **Step 6: Commit changes to `wa-sheets-bot`**

---

### Task 2: Local Vector Embeddings for Second Brain & Memory

**Files:**
- Modify: `vector_memory.py`
- Modify: `alfa/tools/memory_tools.py`
- Test: `tests/test_local_vector_memory.py`

**Interfaces:**
- Consumes: `agent_data.db` vector table, text queries.
- Produces: `get_embedding(text)` with transparent local fallback, `semantic_search(user_id, query, top_k)` operating with 0 API cost and offline resilience.

- [ ] **Step 1: Write failing test in `tests/test_local_vector_memory.py` for offline local embedding generation & search**
- [ ] **Step 2: Run pytest to verify test fails without local fallback**
- [ ] **Step 3: Implement lightweight local embedding engine and fallback in `vector_memory.py`**
- [ ] **Step 4: Update `alfa/tools/memory_tools.py` to seamlessly leverage local embeddings**
- [ ] **Step 5: Run pytest and confirm all vector tests pass**
- [ ] **Step 6: Commit changes**

---

### Task 3: Telegram Bot Progressive Streaming Response Engine

**Files:**
- Modify: `alfa/bot/telegram_bot.py`
- Test: `tests/test_telegram_streamer.py`

**Interfaces:**
- Consumes: `gemini_client.aio.models.generate_content_stream()`, Telegram `context.bot.edit_message_text`.
- Produces: `TelegramStreamer` class with rate-limit dampener (1.2s interval) and progressive draft streaming.

- [ ] **Step 1: Write failing test in `tests/test_telegram_streamer.py` mocking progressive editing & rate-limit backoff**
- [ ] **Step 2: Run pytest to verify test fails**
- [ ] **Step 3: Implement `TelegramStreamer` in `alfa/bot/telegram_bot.py`**
- [ ] **Step 4: Integrate streaming response into `run_agent_turn()` and `handle_text_message()`**
- [ ] **Step 5: Run pytest and confirm all streaming tests pass**
- [ ] **Step 6: Commit changes**

---

### Task 4: Frontend Modularization (`static/js/app.js` -> `static/js/modules/`)

**Files:**
- Create: `static/js/modules/state.js`
- Create: `static/js/modules/audio.js`
- Create: `static/js/modules/hotkeys.js`
- Create: `static/js/modules/telemetry.js`
- Modify: `static/js/app.js`
- Modify: `templates/index.html`
- Test: `tests/test_frontend_modules.py`

**Interfaces:**
- Consumes: Alpine.js global store, browser Web Audio API, Chart.js.
- Produces: Modularized JS architecture under 1,500 lines per module, clean dependency graph.

- [ ] **Step 1: Write failing test in `tests/test_frontend_modules.py` verifying all modules are served and syntactically valid**
- [ ] **Step 2: Extract `state.js` (Alpine reactive store & session variables)**
- [ ] **Step 3: Extract `audio.js` (Visualizer, mic recorder, TTS playback)**
- [ ] **Step 4: Extract `hotkeys.js` (Keyboard navigation & shortcut modal)**
- [ ] **Step 5: Extract `telemetry.js` (Hardware graphs & WebSocket live monitors)**
- [ ] **Step 6: Slim down `static/js/app.js` into clean orchestrator**
- [ ] **Step 7: Update `templates/index.html` script tags and verify test suite passes**
- [ ] **Step 8: Commit changes**

---

### Task 5: Swarm Live Arena Visualizer in Web Command Center

**Files:**
- Modify: `alfa/dashboard/routes/swarm.py`
- Modify: `templates/index.html`
- Modify: `static/js/modules/state.js` (or `app.js`)
- Test: `tests/test_swarm_visualizer.py`

**Interfaces:**
- Consumes: Swarm session events from `alfa/swarm/engine.py`.
- Produces: Interactive visual debate stage in Web Dashboard Swarm tab with agent cards, active speaker glow, and consensus progress bar.

- [ ] **Step 1: Write failing test in `tests/test_swarm_visualizer.py` validating Swarm live event payload formatting**
- [ ] **Step 2: Enhance `alfa/dashboard/routes/swarm.py` to stream structured visual debate events**
- [ ] **Step 3: Add Swarm Live Arena HTML component in `templates/index.html`**
- [ ] **Step 4: Add real-time visualizer state handlers in frontend JS**
- [ ] **Step 5: Run pytest to verify endpoint tests pass**
- [ ] **Step 6: Commit changes**

---

### Task 6: End-to-End System Verification & Service Health Check

**Files:**
- Verify: Full codebase & all running services
- Test: `tests/`

- [ ] **Step 1: Run complete pytest suite: `./venv/bin/pytest tests/ -v`**
- [ ] **Step 2: Restart and verify systemd user services: `alfa-dashboard.service`, `telegram-ai-bot.service`, `wa-sheets-bot.service`**
- [ ] **Step 3: Verify HTTP 200 on `http://127.0.0.1:8080/` and `http://127.0.0.1:3000/health`**
- [ ] **Step 4: Verify SQLite database `agent_data.db` integrity**
- [ ] **Step 5: Final code review & merge preparation**
