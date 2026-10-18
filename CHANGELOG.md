# Changelog

All notable changes to the ALFA Agent project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed & Hardened — Zero Mypy, Zero Bandit, BLE001 −205 & CI Sentinel (2026-10-18, putaran 3)
- **Fase 1 — `mypy` 7 → 0 error (baseline `.github/mypy-baseline.txt` = `0`):**
  seluruh 238 berkas sumber di `alfa/` kini bersih di bawah `mypy --ignore-missing-imports alfa/`. Perbaikan mencakup guard `if gemini_client is None:` pada `alfa/bot/commands/admin.py`, anotasi `dict[str, Any]` pada `alfa/dashboard/common.py`, konstruktor `types.Part(text=...)` dan guard `prompt_instruction` pada `alfa/swarm/step_executor.py`, perbaikan argumen `execute_with_healing(..., target_fn=None)` serta import `get_active_api_key` dari `alfa.core.db.keys` di `alfa/tools/media/av.py`, penyelesaian atribut shadow `_audit_mod` di `alfa/core/perm/__init__.py`, dan anotasi tipe eksplisit di `alfa/core/brain/agentic.py`, `alfa/bot/handlers/callback_router.py`, `alfa/bot/turn_executor.py`, serta `alfa/swarm/affiliate_engine.py`.
- **Fase 2 — Penyempitan `blind-except` (`BLE001`) 1261 → 1056 (−205 instans, 186 → 175 file):**
  `except Exception` generik disempitkan menjadi tuple pengecualian spesifik (`(ValueError, SyntaxError, TypeError)`, `OSError`, `sqlite3.Error`, `httpx.HTTPError`, `(InvalidTag, TypeError, ValueError)`) di `alfa/core/brain/`, `alfa/bot/turn_executor.py`, `alfa/swarm/`, `alfa/dashboard/routes/`, `alfa/integrations/`, `alfa/core/db/`, dan `alfa/core/perm/`; region budget `pyproject.toml` disinkronkan via `scripts/lint_budget.py --apply`.
- **Fase 3 — Evaluasi Modularisasi SPA & Playwright Gate:**
  instalasi binary browser Chromium Playwright diuji pada lingkungan host (`ubuntu26.04-x64`) dan ditolak upstream oleh Playwright (`ERROR: Playwright does not support chromium on ubuntu26.04-x64`); sesuai kebijakan anti-blind-refactor, monolit `static/index.html` tidak dipecah tanpa baseline snapshot visual yang valid.
- **Fase 4 — Sanitasi Bandit Medium+ 4 → 0 (`bandit -r alfa plugins -ll -q`):**
  kueri SQL cron job di `alfa/core/db/tasks.py` diubah dari f-string menjadi tuple kueri statis berparameter (`?`) sehingga bebas `B608`; pemanggilan `urllib.request.urlopen` di `alfa/mcp/client.py` dan `alfa/tools/system/sites.py` kini divalidasi skemanya (`http`/`https` saja) dan didokumentasikan di `SECURITY.md` beserta `# nosec B310`.
- **Fase 5 — Dependabot & Determinism Sentinel CI:**
  menambahkan `.github/dependabot.yml` (pembaruan mingguan `pip` & `github-actions`) serta langkah sentinel determinisme `pytest tests -p no:cacheprovider -q` 2× berturut-turut pada job `test` di `.github/workflows/ci.yml`.

### Fixed — Determinisme test & gates matang (2026-10-18, putaran 2)
- **Akar flaky GDrive dituntaskan, bukan ditambal:** `alfa/security/vault.py`
  mematok `DB_PATH` saat import — ubah `ALFA_DB_PATH` setelah import tidak
  menggeser koneksi, sehingga baris vault dari test sebelumnya bocor ke test
  berikutnya (`_detect_gdrive_auth_mode` salah "oauth"). Kini `_vault_db_path()`
  mengerjakan resolusi dinamis per koneksi (urut: pakai attr `DB_PATH` di-
  patch eksplisit; env `ALFA_DB_PATH`/`DATABASE_URL` runtime; resolver
  `alfa.core.db.connection`; fallback statis) dan `secret_store.delete_secret`
  mengikutinya. Regresi +3 test `tests/test_vault_dynamic_path.py`.
- **Seed agent default idempoten:** `init_db_sync()` kini `INSERT OR IGNORE`
  — akar error `UNIQUE constraint failed: custom_agents.name` antar-urutan
  test (auto-init saat import `alfa.core.database` bisa bersarang dengan
  init dari fixture; seed dobel kini tak baku kengeri error).
- **Coverage kini berangka & beramart:** threshold CI `--cov-fail-under=44`
  (baseline terukur pertama: **46,67%** total 26.178 statement), plus
  codecov/artifact tetap. Semua alat CI di-sematkan versinya (ruff 0.16.4,
  bandit 1.9.4, mkdocs 1.6.1/material 9.7.7, pytest 9.1.1, pytest-cov 7.1.0,
  pytest-asyncio 1.4.0) supaya gerbang deterministik lintas-tahun.
- **BLE001 1282 → 1261 (perbaikan nyata, bukan kelonggaran):** catch-all
  disempitkan bila aman − parser JSON/AST (`tool_exec`), I/O berkas & HTTP
  helpers (`whatsapp.py`), dekripsi kunci (`keys.py`, `crypto.decrypt_key`
  → `InvalidTag/TypeError/ValueError`). Sisa catch-all adalah guard
  portabilitas yang memang sepatutnya; bud mengikuti anggara.

### Fixed — Swarm scraping gate (2026-10-18)
- **Scraping hanya bila diperlukan:** sebelumnya setiap agent bernama "Research"
  / role "Intel" menjalankan `universal_deep_scraper` di **setiap langkah** —
  termasuk langkah tulis-ringkasan/analisa — dan Prime melakukannya berulang
  per SESTA run. Kini `_step_needs_deep_scrape()` membutuhkan sinyal nyata:
  instruksi langkah menyebut pengambilan data (scrape/CSV/kumpulkan data/
  marketplace, dll.) ATAU intent `is_scrape`; sinyal intent bersifat
  **sekali per (topic, agent)** dengan dedupe, instruksi eksplisit selalu
  diizinkan ulang. Non-riset tak pernah scrape. Skip terlog (PLAN: "⏭️ skip").

### Added — Backlog upgrade (2026-10-18)
- **Passkey/WebAuthn end-to-end:** endpoint register/login passkey dengan verifikasi kriptografis nyata (python-webauthn, ES256/P-256, attestation none), challenge server-side sekali-pakai, `sign_count` anti-klon, penyimpanan kredensial DB, UI `static/webauthn.html`; RP ID wajib hostname (IP ditolak) — SECURITY.md/README masa kini, bukan roadmap
- **MCP ekspansi:** transport HTTP streamable (`alfamcp/http_server.py`, token `ALFA_MCP_HTTP_TOKEN` wajib fail-closed + DNS-rebinding guard) sebagai pelengkap stdio; MCP resources `alfa://status` dan `alfa://tools/catalog`; route admin `/api/mcp/status` + handshake di uji kriptografik; test +5 kelas
- **Lint budget TRY/BLE:** rules `TRY*` & `BLE*` AKTIF penuh di ruff; utang legacy 1282 instans dipatok per-instansi di region budget `pyproject.toml` (regen `scripts/lint_budget.py --apply`; CI gagal bila instans bertambah)
- **mkdocs strict:** site material `mkdocs build --strict` hijau; registry nav 11 halaman + landing `docs/index.md` + salinan sinkron `docs/{about,security,CHANGELOG}.md` (regen `scripts/build_docs.py`); job CI Docs
- **Startup lazy:** `google.genai` (±1.4 s) tidak lagi diimpor saat boot — `alfa/bot/config.gemini_client` inilah None (dibangun saat API dipakai), `alfa/swarm/llm_client._ensure_genai()` on-demand; bootstrap import: `telegram_bot` 2135→604 ms, `dashboard.app` 2444→1174 ms; dijaga test regresi subprocess

### Changed — Arsitektur (P1)
- **Config service tunggal (`alfa/core/config.py`):** `.env` dimuat **satu kali per proses** dengan `override=False` — menggantikan 6 titik `load_dotenv()` tersebar (dashboard/common, app, bot/config, brain/client, input_automation) + helper `env_str/env_int/env_float/env_bool`
- **Anti-siklus impor (`alfa/core/notification.py`):** port notifikasi + adapter; `affiliate_engine` & `management` kini tidak mengimpor `alfa.bot` — bot mendaftarkan diri ke port saat dimuat
- **Refactor `run_agent_turn` (turn_executor):** god-function 752 baris kini pipeline bertahap — `_build_memory_block`, `_build_system_instruction`, `_prepare_tools_and_configs`, `_audit_correction_pass`, `_openai_compat_turn`, `_try_alt_provider_keys`; `run_agent_turn` jadi wrapper telemetri (turn started/finished)
- **Observability (`alfa/core/metrics.py`):** counter tool-calls/errors + latensi p50/p95 per tool + turn naik; hook di `core.brain.tool_exec._execute_tool`; terekspose di `/api/metrics` field `agent` (tanpa dependency baru)
- **Sandbox plugin subprocess (`plugins/runner.py`):** plugin dinamis default dieksekusi di child process ber-resource-limit (RLIMIT_AS/CPU), hasil JSON satu baris via fd terbackup (stdout plugin dialihkan ke stderr); override `ALFA_PLUGIN_SANDBOX=false`, timeout `ALFA_PLUGIN_TIMEOUT`
- Jalur persistence yang terdiam kini terylog (reflection)

### Docs — Ketelitian Klaim
- Klaim passkey/WebAuthn "roadmap" pada putaran ini telah digantikan implementasi nyata (lihat blok Added); klaim kini jujur termasuk batasnya (RP ID hostname, HTTPS produksi)

### Removed — Root shim legacy
- **37 file shim root dihapus** (`database.py`, `tools.py`, `web_dashboard.py`, `bot.py`, dll.) — semuanya fasad back-compat murni yang memetakan ke paket `alfa.*`; konsumen terakhir dimigrasi:
  - 17 berkas uji kini mengimpor modul nyata (mis. `import alfa.core.brain as main_brain`, `import alfa.memory.vector as vector_memory`) + string target-patch diperbaiki (`patch("vector_memory.*")` → `patch("alfa.memory.vector.*")`)
  - 3 titik kode sumber: `alfa/tools/media/av.py`, `alfa/dashboard/routes/swarm/affiliate_routes.py`, `alfa/dashboard/routes/system/workspace_vault.py` → `import alfa.video as video_generator`
  - `evals/run_evals.py` — fallback shim dibuang; memakai `alfa.bot.telegram_bot`
  - `scripts/run.sh`, `scripts/setup.sh`, `deploy/*.service` — start via `python -m alfa.dashboard.app` / `-m alfa.bot.telegram_bot` / `-m alfa.core.cli` (runner uvicorn baru `alfa/dashboard/app.py::_serve`)
- Gotcha Python tercatat: `import alfa.dashboard.app as X` mengikat **instansi FastAPI** (atribut package shadow submodule) — test memakai `importlib.import_module("alfa.dashboard.app")`
- `tests/conftest.py`: `DASHBOARD_HOST` dipaksa `127.0.0.1` (hermetik) — `.env` operator ber-host publik tidak lagi memicu boot-guard fatal saat koleksi test; test yang mengetes guard mengatur env sendiri

### Security
- **Boot guard keamanan (`alfa/core/security_boot_guard.py`):** boot bot Telegram/Discord/dashboard DITOLAK bila `ALFA_UNRESTRICTED=true` + `DASHBOARD_HOST` publik; kombinasi unrestricted+host-exec kini wajib pengakuan eksplisit (`ALFA_UNRESTRICTED_ACK=yes`)
- **WebSocket `/ws/terminal` dikeraskan:** auth wajib saat `DASHBOARD_AUTH_TOKEN` terisi; mode tanpa-token hanya loopback (127.0.0.1); validasi Origin semua channel WS (`/ws/terminal`, `/ws/logs`, `/ws/broadcast`) — menutup RCE cross-site
- **Registrasi dashboard ditutup:** setelah bootstrap, `/api/auth/register` butuh invite token sekali-pakai (`POST /api/auth/invite`, admin-only, hash-only di DB) atau sesi admin; user pertama tetap bootstrap-admin
- **Rate limit login & register** (in-memory sliding window, 429 + Retry-After)
- **`GET /api/settings` kini admin-only** dan seluruh nilai rahasia `system_settings` (OAuth Google, kredensial SA, token) direduksi menjadi flag `_set` — tidak pernah lagi dikirim via HTTP
- **`GET /api/models-for-key` kini admin-only** (proxy keluar berkunci server)
- **Sandbox Docker diputus dari jaringan:** `--network none` default (override `ALFA_SANDBOX_NETWORK`); argumen docker run dikonsolidasi ke `_docker_common_args()` (bash + python)
- `.env` contoh runtime direset ke mode aman (`ALFA_UNRESTRICTED=false`, `ALFA_ALLOW_HOST_EXEC=false`)

### Security
- **RBAC sweep mekanis:** 25+ endpoint sensitif kini `require_admin` (`/api/tools/execute`, `/api/plugins/execute`, `/api/vault/list`, `/api/workspace/{tree,file}`, `/api/artifacts/download`, `/api/security/*`, `/api/keys*`, `/api/stats`, `/api/system/home-dir`, `/api/services*`, `/api/pipelines/{run,save,enable}`, `/api/memory/{add,delete}`, `/api/brain/{export,vector/*}`, `/api/scraper/*`, `/api/chat/{model,history,export}`, passkey toggle) — regresi dikunci oleh test sweep parametrized (anonim 401/member 403)
- **Anti-spoof identitas:** header `X-User-Id`/query `user_id` hanya dipercayai di mode lokal tanpa token; mode token selalu jatuh ke whitelist `ALLOWED_USER_IDS`
- **SSRF guard (`alfa/security/net_guard.py`):** loopback/private/link-local/metadata & DNS-resolve terlarang ditolak di `download_file_from_url` + `fetch_web_page_content`; bypass eksplisit `ALFA_ALLOW_PRIVATE_FETCH`; filename unduhan disanitasi (anti path-traversal write)
- **GDrive kredensial → vault AES-256-GCM:** OAuth token & SA JSON tak lagi plaintext di `system_settings` (migrasi otomatis saat startup, hash/encrypted-only); reader/writer/auth/logout/dirutekan ke `gdrive/secret_store.py`
- **Git history termigrasi:** snapshot `agent_data.db`/`-wal`/`-shm` dipurge dari seluruh sejarah (git-filter-repo) — riwayat sekarang hanya konten live; lift paksa push `git push --force --all` diperlukan oleh owner

### Added
- 34 regression-test hardening (`tests/test_security_hardening.py`): boot guard, WS auth/origin, kebijakan registrasi, invite roundtrip, redaksi settings, argumen sandbox, rate limit
- 48 regression-test tambahan: RBAC sweep parametrized, SSRF guard, identitas anti-spoof, vault roundtrip gdrive

### Added
- Durable swarm mission queue (`alfa/swarm/queue.py`, `/api/swarm/queue/*`, worker retry-backoff)
- Opt-in LLM cache untuk generasi tanpa tool (`ALFA_LLM_CACHE`)
- OTel-lite: propagasi span via contextvars + header W3C `traceparent`
- RBAC `require_admin` pada 15 endpoint sensitif dashboard
- HMAC-SHA256 webhook + GitHub fail-closed; rotasi master key + versioning secret vault
- 20 golden eval tasks + CI offline eval gate

## [Unreleased]

### Security
- Enforce permission gate on dashboard-direct `/api/tools/execute` (403) and MCP `call_tool`
- Remove compromised `deep-translator` dependency; translate via Gemini
- Patch 19 dependency CVEs (anyio, click, mcp 1.30, pypdf 6.19) + multidict to 6.9.1 (CVE-2026-104874)
- Close shell-injection vectors (git tool args, volume, service names, ffmpeg argv)
- SSRF scheme guard on urllib scrapers; TLS verify on by default
- Redact secret-valued args in permission audit trail; bandit medium/high clean

### Added
- 46 critical-path tests (gate, trust math, vault, MCP, localhost audit)
- `ALFA_VERIFY_SSL`, `ALFA_MCP_USER_ID`, permission-gate env options

### Changed
- Split `agent_engine` and `browser` into focused subpackages
- Trust-score speed bonus now decays instead of a constant
- Test suite fully hermetic (isolated DB, no env leakage)

## [3.5.0] - 2026-09-29

### Added
- CLI coding-agent suite: /plan + /approve, /auto, /permit, /todo, /test, /git, /status, /session, /compact
- Agent runner: plan-mode read-only enforcement, tool aliases, truncated tool-call repair, malformed-call self-heal, auto-continue on pending todos, honest execution reports, run-state tracking
- run_command timeout now returns partial output; /undo no longer wipes uncommitted work
- Project memory (ALFA.md), per-tool permission store, workspace todo manager, session persistence
- 40 new tests (agent runner, reply auditor, system monitoring)

### Changed
- Decomposed monoliths: keys_models, slash_commands, direct_ai, interactive_menu, rag, monitoring, swarm engine, runner (parsing/reporting mixins)
- Version aligned to 3.5.0 across package, CLI, and docs

## [2.5.0] - 2024-12-XX

### Added
- Comprehensive test suite with conftest fixtures
- Code quality metrics and reporting
- Enhanced CI/CD with security scanning
- Bandit security scan integration
- Dependency vulnerability checking with Safety
- Black code formatting checks
- Custom pytest markers (slow, integration, security, rag, swarm)
- Test coverage reporting to Codecov
- HTML coverage artifacts

### Changed
- Updated pyproject.toml with complete tool configurations
- Enhanced pytest configuration with better coverage tracking
- Improved GitHub Actions workflows for code quality

### Fixed
- Missing conftest.py for shared test fixtures
- Incomplete test coverage reporting
- Limited security scanning in CI/CD

### Security
- Added automated security scanning with Bandit
- Integrated dependency vulnerability checks
- Enhanced whitelist enforcement testing

## [Unreleased]

### Added
- Initial release of ALFA Agent ecosystem
- 126+ tools for AI agent operations
- Swarm AI engine with multi-agent collaboration
- RAG-powered tool discovery and memory system
- Passkey-based vault engine for secure credential storage
- Web dashboard for real-time monitoring
- CLI interface for headless operations
- Multi-platform setup scripts (Linux, macOS, Windows)
- Security sandbox with whitelist enforcement
- Git sandbox for safe code execution
- LSP-based code intelligence
- Video generation capabilities
- TTS engine for voice output
- Academic researcher agent
- Affiliate marketing engine
- Universal scrapers (web, mobile, large-scale)
- Google Drive integration suite
- Permission gate for operation authorization
- Memory reflection and self-improvement
- Vector memory for semantic search
- Tracing and observability system

### Security
- Whitelist-only tool execution
- Sandboxed git operations
- Encrypted passkey vault
- Permission gates for sensitive operations
- Security auditor with automated scanning

## [0.1.0] - 2024-08-30

### Added
- Initial public release
- Core agent brain (`main_brain.py`)
- Bot framework (`bot.py`)
- Database layer with SQLite (`database.py`)
- Tools registry and execution engine
- Authentication system with passkeys
- Test suite for security and core functionality
- Documentation: README.md, INSTALL.md
- Example environment configuration (.env.example)

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

---

## Version Guidelines

- **Major** (X.0.0): Breaking changes, major feature releases
- **Minor** (0.X.0): New features, backward-compatible improvements
- **Patch** (0.0.X): Bug fixes, security patches, minor improvements

## Release Process

1. Update version in `pyproject.toml`
2. Update this CHANGELOG with release date
3. Create git tag: `git tag -a v0.X.0 -m "Release v0.X.0"`
4. Push tag: `git push origin --tags`
5. Create GitHub release with changelog excerpt
