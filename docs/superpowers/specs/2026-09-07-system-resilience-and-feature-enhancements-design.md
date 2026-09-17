# Design Specification: ALFA System Resilience & Advanced Feature Enhancements

- **Date:** 2026-09-07
- **Author:** Antigravity AI
- **Status:** Draft (Awaiting Final User Sign-off)
- **Target Systems:**
  1. `wa-sheets-bot` (`/home/fahmial/wa-sheets-bot`)
  2. `telegram-ai-bot` (`alfa/bot/telegram_bot.py`)
  3. `vector_memory.py` / `alfa/tools/memory_tools.py`
  4. `web_dashboard` (`alfa/dashboard/`, `static/js/`, `templates/index.html`)

---

## 1. Executive Summary & Goals

This specification defines the architecture, data models, interface contracts, and implementation blueprints for 5 high-impact enhancements:
1. **WhatsApp Puppeteer Watchdog & Auto-Heal**: Automatic detection of stuck initialization, detached frames, and stale Chromium locks with automatic recovery.
2. **Local Vector Embeddings for Second Brain**: Zero-cost, high-speed, offline-capable embedding generation for vector memory and Auto-RAG.
3. **Telegram Progressive Streaming Responses**: Real-time word-by-word streaming generation in Telegram using rate-limit-dampened message editing.
4. **Frontend ES6 Modularization**: Decomposing monolithic `static/js/app.js` into cohesive modules (`state.js`, `audio.js`, `hotkeys.js`, `telemetry.js`).
5. **Swarm Live Arena Visualizer**: Real-time visual timeline and debate stage visualizer in Web Command Center.

### Non-Goals
- Breaking existing systemd service scripts or unit configurations.
- Changing Telegram command signatures or breaking legacy API endpoints.
- Overwriting existing database schema in `agent_data.db`.

---

## 2. Phase A: Core Stability & Intelligence

### 2.1 WhatsApp Bot Watchdog & Auto-Heal (`wa-sheets-bot`)
- **Problem**: When headless Chromium crashes or experiences abnormal shutdown, `whatsapp-web.js` leaves dangling lock files (`DevToolsActivePort`, `SingletonLock`, and sockets under `/tmp/org.chromium.*`), causing subsequent initializations to hang indefinitely in `INITIALIZING` or throw `Attempted to use detached Frame`.
- **Architecture**:
  - **Watchdog Timer**: Runs every 30 seconds inside `src/whatsapp.js`. If `clientStatus === 'INITIALIZING'` exceeds 90 seconds, the watchdog triggers `autoRecover()`.
  - **Auto-Recovery Routine**:
    1. Force-kills orphaned Chromium processes associated with `wa-sheets-bot`.
    2. Deletes stale lock files (`DevToolsActivePort`, `SingletonLock`, `SingletonCookie`, `SingletonSocket`) and `/tmp/org.chromium.*` temp directories.
    3. Re-instantiates `Client` and restarts initialization.
  - **API Exception Trap**: In `server.js`, wrap `/api/logout` and `/logout` to catch detached frame errors and immediately trigger file-level session cleanup rather than throwing 500.

### 2.2 Local Vector Embeddings for Second Brain (`vector_memory.py`)
- **Problem**: Vector memory currently depends on external Google GenAI embedding endpoints. If API keys are quota-limited or network connectivity drops, semantic search fails.
- **Architecture**:
  - **Dual-Mode Embedding Engine**:
    - Primary: Local fast embedding model (`fastembed` with `BAAI/bge-small-en-v1.5` or ONNX-based lightweight cosine model, producing dense 384-dimensional embeddings).
    - Fallback/Cloud mode: Google GenAI `text-embedding-004` (768-d).
  - **Dimension Compatibility**: Store vectors with model metadata in `agent_data.db` so searches only compare matching dimension sets, preventing dimensional mismatches.
  - **Offline Resilience**: When internet access is disconnected, semantic search and knowledge retrieval continue to work with 0 ms network latency.

---

## 3. Phase B: Telegram Experience & Streaming

### 3.1 Progressive Streaming Response (`alfa/bot/telegram_bot.py`)
- **Problem**: Long reasoning and tool-calling turns make the user wait 10–25 seconds with only a static "typing..." status before receiving the entire output block.
- **Architecture**:
  - **Streaming Generator**: Use `gemini_client.aio.models.generate_content_stream()` (or streaming SSE for OpenAI-compatible providers).
  - **Rate-Limit Dampened Editor (`TelegramStreamer`)**:
    - Sends an initial placeholder message: `💭 Sedang berpikir...` within 300ms.
    - Accumulates tokens in an internal buffer.
    - Edits the message every 1.2–1.5 seconds (respecting Telegram Bot API's limit of ~1 edit/second per chat).
    - When generation completes, executes the final edit with complete markdown formatting.
  - **Fallback Safety**: If Telegram returns `429 Too Many Requests` or `Message Not Modified`, the streamer backs off gracefully and yields the final text at turn conclusion.

---

## 4. Phase C: Frontend Command Center & Swarm Visualization

### 4.1 Frontend ES6 Modularization (`static/js/app.js`)
- **Problem**: `static/js/app.js` is ~5,972 lines. Modifying telemetry or audio code risks regressions in Alpine state.
- **Architecture**:
  - Split `static/js/app.js` into focused modules:
    - [`static/js/modules/state.js`](file:///home/fahmial/telegram-ai-bot/static/js/modules/state.js): Alpine.js reactive store, session persistence, active views.
    - [`static/js/modules/audio.js`](file:///home/fahmial/telegram-ai-bot/static/js/modules/audio.js): Web Audio API context, audio visualizer, mic recording, TTS playback.
    - [`static/js/modules/hotkeys.js`](file:///home/fahmial/telegram-ai-bot/static/js/modules/hotkeys.js): Keyboard shortcuts (`Ctrl+K`, ESC, quick navigation).
    - [`static/js/modules/telemetry.js`](file:///home/fahmial/telegram-ai-bot/static/js/modules/telemetry.js): System charts, WebSocket stats, CPU/RAM/VRAM gauge updates.
  - Maintain [`static/js/app.js`](file:///home/fahmial/telegram-ai-bot/static/js/app.js) as an entrypoint that coordinates module initialization and binds to Alpine globals.

### 4.2 Swarm Live Arena Visualizer (`alfa/dashboard/`)
- **Problem**: Multi-agent Swarm debates (`conduct_ai_meeting`) run primarily in backend logs, giving the user limited visual insight into how personas interact.
- **Architecture**:
  - **Backend SSE / WebSocket Event Stream**: Emit structured Swarm events:
    - `swarm:turn_start` (Active agent, role, avatar)
    - `swarm:thought` (Deliberation stream)
    - `swarm:vote` (Persona voting and critique matrix)
    - `swarm:consensus` (Final agreement and synthesis)
  - **Frontend UI Component**:
    - A dedicated visual stage in the Swarm tab with agent cards (Leader, Researcher, Critic, Executor), active speaker glowing indicator, and consensus progress bar.

---

## 5. Verification & Test Plan

1. **WhatsApp Watchdog Verification**:
   - Inject simulated lock file and kill Chromium; verify watchdog triggers auto-recovery within 90 seconds and re-establishes `QR_READY` or `READY`.
2. **Vector Memory Verification**:
   - Run unit tests on `vector_memory.py` validating offline embedding generation, cosine similarity ranking, and storage retrieval.
3. **Telegram Streaming Verification**:
   - Mock Telegram Bot `edit_message_text` with rate-limiting; verify message updates progressively without triggering 429 exceptions.
4. **Frontend Integrity Verification**:
   - Validate that `/static/js/modules/*` load cleanly, Alpine.js initializes without console errors, and dashboard remains 100% functional.
5. **Full Regression Suite**:
   - Ensure all 181 pytest tests continue to pass (`./venv/bin/pytest tests/`).
