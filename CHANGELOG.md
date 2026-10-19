# Changelog

All notable changes to the ALFA Agent project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Quality & Hardening (P1 + P2) — XSS, RBAC default-deny, registry SSOT, ES modules (2026-10-20, putaran 6)
Melanjutkan P0 (7 celah keamanan tertutup) dengan perbaikan kualitas &
struktur yang tersisa. Semua gate tetap hijau: ruff, mypy 0/251 file, bandit
0 Medium/0 High, lint budget 782 (turun dari 785), 1.098 uji, coverage 54,20%.

- **P1-8 — Stored XSS di dashboard (Lapis 1: sanitasi):**
  output LLM (rapat, chat, consensus) disimpan ke DB lalu dirender lewat
  `marked.parse()` → `innerHTML` tanpa sanitasi. Sekarang semua pemanggilan
  lewat `safeMarkdown()` (marked → DOMPurify), `escHtml()` lengkap
  (`& < > " '`) menggantikan `escAttr()` yang hanya escape 3 karakter,
  definisi ganda `escAttr` di `app.js` dihapus (versi `app.js` diam-diam
  menimpa versi `state.js` untuk SELURUH halaman), dan ~20 titik interpolasi
  mentah (judul rapat, nama agen, ringkasan eksekusi, produk affiliate,
  secret vault, finding keamanan, hasil scraper, Google Drive, katalog tool)
  kini di-escape.
- **P1-8 — Lapis 2: Content-Security-Policy.** Middleware `CSPNonceMiddleware`
  menambah CSP ketat (`default-src 'self'`, `script-src` dengan nonce untuk
  2 script inline, tanpa `'unsafe-inline'`) plus `X-Content-Type-Options`,
  `Referrer-Policy`, `X-Frame-Options`. DOMPurify dimuat dari CDN versi
  ter-pin.
- **P1-9 — RBAC default-deny pada endpoint sensitif.** 25 endpoint mutating
  yang sebelumnya tanpa gate kini memakai `dependencies=[Depends(require_admin)]`
  (eksekusi agent/swarm, rapat, antrean misi, broadcast affiliate, kredensial
  & upload Google Drive, WhatsApp, situs, resume checkpoint, passkey
  register/delete, eksekusi tool & plugin). Penolakan izin di
  `/api/tools/execute` tidak lagi ditelan `except Exception` → HTTP 200
  dengan status "error" (sekarang 403). `public_paths` memakai pencocokan
  PERSIS — sebelumnya prefix match membuat `/docs` dan seluruh `/api/v1/*`
  publik (openapi.json memetakan permukaan API ke publik).
- **P1-10 — Registry tool jadi sumber kebenaran tunggal.** Daftar manual
  165 tool menimpa decorator `@register_tool`, sehingga 8 tool RAG/vector
  (`search_vector_memory`, `graph_rag_query_multi_doc`, dll) TIDAK PERNAH
  terlihat model. Sekarang `TOOL_REGISTRY` = SSOT: `sync_available_from_registry()`,
  `sync_registry_from_available()`, `sync_domains_from_registry()`. Semua
  173 tool punya metadata + risk tier.
- **P1-11 — Eksekusi tool ganda & timeout yang tidak membatalkan.**
  `except TypeError` tidak bisa membedakan mismatch signature vs `TypeError`
  di dalam body tool → tool dengan efek samping jalan DUA KALI. Sekarang
  signature dicek (`inspect.signature().bind()`) SEBELUM pemanggilan.
  `TOOL_EXEC_TIMEOUT` tidak membatalkan apa pun (blok `with ThreadPoolExecutor`
  menunggu worker selesai → 300s × 24 iterasi). Sekarang pool modul-level
  dipakai ulang + `asyncio.wait_for` di pemanggil.
- **P1-12 — Tipe JSON parameter tool.** `list[str]`/`dict`/`Optional` sebelumnya
  jatuh ke "string" → model mengirim "a,b,c" untuk parameter list →
  TypeError. Sekarang dipetakan via `typing.get_origin/get_args`.
- **P1-13 — Rate limiter yang benar-benar di-enforce.** `allowed` sebelumnya
  dihitung lalu dibuang. Sekarang brain mengembalikan pesan kuota ke user;
  `api_token_usage` dapat kolom `user_id` sehingga budget benar-benar per-user
  (sebelumnya dijumlahkan global). Query budget & usage dipisah agar tabel
  `user_budgets` yang belum ada tidak menihilkan pemakaian.
- **P1-14 — Budget swarm aktif + circuit breaker terpasang.**
  `ALFA_SWARM_TASK_TIMEOUT`/`ALFA_SWARM_MAX_STEPS` default `0` (nonaktif) →
  sekarang 1800s / 40 langkah. `ALFA_SWARM_JUDGE` default `auto` (LLM judge
  per langkah) → `mechanical` (bukti filesystem, hemat kuota). Circuit breaker
  kini dipakai di swarm: model 429/503 diberi cooldown & dilewati.
- **P2-15 — SPA jadi ES module asli.** 13 `<script>` klasik → 1
  `<script type="module">` dengan import/export eksplisit. 74 guard
  `typeof x === 'function'` (yang menyembunyikan dependensi hilang) dihapus;
  graf dependensi kini bisa dianalisis statis & divalidasi test. API global
  untuk handler inline HTML (143 di `index.html` + 49 yang dibangun di JS)
  dipertahankan lewat *global bridge* yang eksplisit di tiap file.
  `scripts/es_modules.py` mendokumentasikan & mereproduksi transformasinya.
- **P2-16 — State swarm per-sesi.** `MEETING_RUNNING` & flag pembatalan
  global → registry per `session_id`. Dua rapat paralel tidak lagi saling
  mematikan flag (cancel untuk sesi yang masih berjalan pernah dijawab
  "tidak ada sesi aktif"), dan cancel satu sesi tidak membatalkan sesi lain.
- **P2-18 — Resolusi path DB tunggal.** Tiga resolver terpisah (core,
  permission store, vault) digabung ke `alfa/core/db/paths.py`. Permission
  store sebelumnya mengabaikan `DATABASE_URL` → bisa mendarat di DB berbeda
  dari data yang dilindunginya.
- **P2-19 — Angka yang melenceng diperbaiki.** README "162 tools" → 173,
  "794 uji" → 1.098, "RBAC admin di 15 endpoint" → default-deny di seluruh
  endpoint mutating sensitif, `app.py` "148 native tools" → 173, judul tab
  "126 Tools Catalog" → diisi dari runtime, `docs/CODE_QUALITY.md` diperbarui
  (coverage 54,20%, 1.098 uji, mypy 0, bandit 0/0).

### Security (P0) — 7 celah keamanan kritis ditutup (2026-10-19, putaran 5)
Audit keamanan menemukan 7 celah yang bisa dieksploitasi. Semuanya kini
ditutup, dengan regression test di `tests/test_p0_security.py` (29 test).

- **P0-1 — Sandbox Docker bisa di-escape jadi akses full host FS.**
  `working_dir="/"` membuat container mendapat mount `-v /:/workspace -v /:/`
  → seluruh host filesystem read-write di dalam "sandbox", berjalan sebagai
  UID host. Kini `working_dir` WAJIB lolos containment check terhadap root
  yang diizinkan (`ALFA_SANDBOX_ROOT`; default: folder kerja ALFA saja).
  Root `/`, `$HOME`, dan nenek moyang `$HOME` selalu ditolak. Mount
  `host:host` ke path di luar root dihapus; root lain di-mount pada path
  sisi-container (`/alfa/rootN`).
- **P0-2 — `execute_python_sandbox` diam-diam jatuh ke host.** Berbeda
  dengan `execute_bash_command` yang menolak, jalur Python hanya mem-log
  warning lalu menjalankan kode AI dengan hak akses penuh mesin. Kini
  **fail-closed**: tanpa Docker, kedua sandbox menolak (kecuali
  `ALFA_ALLOW_HOST_EXEC=true`). Pengecekan dipindah sebelum file script
  ditulis agar tidak ada sisa kode di disk.
- **P0-3 — Trust score self-escalate ke tier CRITICAL dalam 1 panggilan.**
  `base_ratio = safe/total` membuat satu approval tool LOW menghasilkan
  trust 1.0, dan `trust >= 0.9` auto-approve `ssh_execute_command`/
  `clean_system_storage` (CRITICAL). Kini trust dihitung **per
  `(chat_id, tier)`** (tabel `user_tier_trust`), auto-approve **tidak pernah**
  menambah skor, dan tiap tier mensyaratkan jumlah persetujuan eksplisit
  manusia minimum (`PERMISSION_GATE_MIN_APPROVALS_*`).
- **P0-4 — 136/165 tool tak terklasifikasi dan default-nya MEDIUM.**
  `vault_delete_secret` (hapus secret terenkripsi) hanya MEDIUM. Kini
  `DEFAULT_TIER = HIGH` (fail-closed) dan **seluruh 165 tool** punya entri
  eksplisit di `TOOL_CLASSIFICATION`; `vault_delete_secret` = CRITICAL,
  `vault_get_secret`/`vault_store_secret`/`execute_python_sandbox` = HIGH,
  `read_local_file` turun dari LOW ke MEDIUM (bisa membaca `.env`).
- **P0-5 — Permission gate dilewati di 3 jalur produksi.** `approval_gate=None`
  membuat tool berjalan tanpa human-in-the-loop; jalur fallback provider
  Telegram (`try_alt_provider_keys`) memakai **165 tools tanpa gate**,
  `memory/reflection.py` (job background) punya akses ke
  `vault_delete_secret`, dan `swarm/llm_client.py` memakai 14 tools tanpa
  gate. Kini **deny-by-default**: tanpa gate → tool ditolak; gate yang
  melempar error → juga ditolak (fail-closed, sebelumnya fail-open). Gate
  diteruskan ke jalur fallback, `reflection.py` diberi `tools_schema=[]`, dan
  swarm memakai gate headless (`swarm_headless_gate`).
- **P0-6 — Dashboard API terbuka total bila `DASHBOARD_AUTH_TOKEN` kosong.**
  `if DASHBOARD_AUTH_TOKEN and path.startswith("/api/")` membuat seluruh
  `/api/*` terbuka tanpa autentikasi. Kini **fail-closed**: semua `/api/*`
  wajib punya session valid/token. Escape hatch development lokal
  `ALFA_INSECURE_LOCAL=true` (klien lokal saja, tidak berlaku bila token
  diset, boot ditolak saat bind `0.0.0.0/::`). `require_admin` ikut
  fail-closed. Ceremony passkey login (`/api/auth/webauthn/login/*`) kini
  publik agar login tetap bisa dipakai.
- **P0-7 — `alfa/security` mengekspor API keamanan palsu.** `encrypt_api_key`
  mengembalikan plaintext dan `is_command_blocked` selalu `False`, keduanya
  diekspor di `__all__`. Stub diganti implementasi yang meneruskan ke
  modul asli (`alfa.core.db.crypto` AES-256-GCM,
  `alfa.tools.system.constants` blocklist). `encrypt_key` kini **fail-closed**
  (melempar `CryptoUnavailableError`) alih-alih menyimpan API key plaintext
  tanpa error dan tanpa log.
- **Bonus — CI security gate kembali hijau:** 2 temuan Bandit Medium
  (`B310` di `alfa/bot/proactive.py`, `B608` di `alfa/memory/graph_rag.py`)
  diselesaikan → `bandit -r alfa plugins -ll` = 0 Medium/0 High, exit 0.

### Added, Refactored & Hardened — SPA Modularization + Playwright Visual Snapshots, BLE001 < 800 & Coverage Gate 50%+ (2026-10-19, putaran 4)
- **Part A — Modularisasi SPA + Playwright Visual & DOM Snapshot Gate:**
  - Memasang Chromium headless di Playwright (`PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64`) dan membangun suite regresi visual & metrik tata letak DOM di `tests/test_spa_playwright_snapshots.py` pada 4 lebar viewport (`375px`, `768px`, `1024px`, `1440px`) beserta verifikasi interaksi tab dan tombol approve eksekusi.
  - Memecah monolit `static/js/app.js` dari **5.814 baris menjadi 3.679 baris (−2.135 baris / −36,7%)** ke dalam 5 modul domain terfokus di `static/js/modules/`:
    1. `static/js/modules/pipelines_sites.js` (550 baris) — Workflow Pipelines DAG Canvas & Sites Gallery
    2. `static/js/modules/gdrive.js` (429 baris) — Google Drive Cloud Backup & Explorer
    3. `static/js/modules/scraper.js` (364 baris) — Universal Pro Web Scraper & Modern Scraper Lab
    4. `static/js/modules/vault_security.js` (366 baris) — Multi-Provider API Key Vault & Security Passkeys
    5. `static/js/modules/affiliate.js` (426 baris) — Affiliate Video Clipper Studio
- **Part B — Kikis `BLE001` / `TRY` Lint Budget 1056 → 782 (−274 instans tambahan; total −479 dari 1261):**
  - Menyempitkan `except Exception` menjadi tuple exception spesifik (`_MODE_ERR`, `_DC_ERR`, `_TOOL_ERR`, `_SRV_ERR`, `_PDF_ERR`, `_AV_ERR`, `_CAP_ERR`, `_HND_ERR`, `_PRO_ERR`, `_ADV_ERR`, `_EXT_ERR`, `_MGT_ERR`, `_SITE_ERR`, `_PIPE_ERR`, `_MCP_ERR`, `_VEC_ERR`, `_SCR_ERR`) di 17 modul (`alfa/bot/{mode_commands,discord_bot,handlers,proactive,advanced_commands}.py`, `alfa/core/cli/{agent_engine/tool_registry,server_manager}.py`, `alfa/mcp/client.py`, `alfa/memory/vector.py`, `alfa/pipelines/engine.py`, `alfa/tools/desktop/capture.py`, `alfa/tools/filesystem/universal_file_extractor.py`, `alfa/tools/media/{av,pdf_editor}.py`, `alfa/tools/system/{management,sites}.py`, `alfa/tools/web/scrapers.py`).
  - Menyinkronkan region budget otomatis di `pyproject.toml` via `scripts/lint_budget.py --apply` menjadi **782 instans** (di bawah target `< 800`).
- **Part C — Peningkatan Test Coverage 46,37% → 51,62% & Kenaikan Gate CI 44% → 50%:**
  - Menambahkan suite unit test cepat dan hermetik di `tests/test_coverage_boost_phase3.py` yang menguji seluruh alur perintah bot Telegram (`mode_commands`, `basic_commands`, `wa_menu`, `advanced_commands`, `SwarmProgressReporter`) serta rute FastAPI (`observability`, `meetings_routes`, `agents_routes`, `pipelines_memory`, `settings_admin`, `telemetry`, `workspace_vault`, `scrapers`).
  - Menaikkan ambang batas `--cov-fail-under=50` di `.github/workflows/ci.yml` dan `fail_under = 50` di `pyproject.toml`.

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
